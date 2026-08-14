"""Three-condition retrieval runner with an explicit live/offline boundary."""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from hydra_graph.config import HydraDBConfig
from hydra_graph.hydradb import HydraDBClient
from hydra_graph.query import normalize_query_response

from .baseline import (
    BaselineDocument,
    BaselineEvidence,
    DeterministicTfidf,
    baseline_corpus_digest,
    validate_baseline_documents,
)
from .gold import ResolvedGold, ResolvedQuestion
from .metrics import score_observation
from .models import (
    AblationCondition,
    EvaluationRecord,
    EvaluationTarget,
    EvidenceObservation,
    HydraDBRequestBody,
    HydraQueryPlan,
    RelationObservation,
    RetrievalObservation,
    RunMode,
)


@dataclass(frozen=True, slots=True)
class HydraQueryResult:
    payload: Mapping[str, Any]
    latency_ms: float
    actual_request_body: HydraDBRequestBody | None = None


class HydraEvaluationTransport(Protocol):
    fixture_backed: bool

    def query(self, request_body: Mapping[str, Any]) -> HydraQueryResult: ...


class FixtureHydraTransport:
    """Offline response transport. Live mode rejects this class unconditionally."""

    fixture_backed = True

    def __init__(
        self,
        *,
        without_graph: Mapping[str, Any],
        with_graph: Mapping[str, Any],
        latency_ms: float = 0.0,
    ) -> None:
        self._responses = {False: without_graph, True: with_graph}
        self._latency_ms = latency_ms
        self.calls: list[dict[str, Any]] = []

    def query(self, request_body: Mapping[str, Any]) -> HydraQueryResult:
        plan = HydraQueryPlan.model_validate(request_body)
        body = plan.model_dump(mode="json")
        self.calls.append(body)
        return HydraQueryResult(self._responses[plan.graph_context], self._latency_ms)


class LiveHydraTransport:
    """Credential-backed direct HydraDB v2 transport for conditions B and C."""

    fixture_backed = False
    collection = "current"

    def __init__(
        self,
        *,
        config: HydraDBConfig,
        target: EvaluationTarget,
        client: HydraDBClient | None = None,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        if not config.configured:
            raise ValueError("live evaluation requires HydraDB API key and database")
        if config.database != target.database:
            raise ValueError("live evaluation database does not match the evaluation target")
        if config.collection != target.collection:
            raise ValueError("live evaluation requires the configured current collection")
        if target.revision_id == "current":
            raise ValueError("live evaluation requires a concrete revision ID")
        self.config = config
        self.target = target
        self._client = client or HydraDBClient(config)
        self._clock = clock

    @classmethod
    def from_environment(
        cls,
        *,
        target: EvaluationTarget,
    ) -> LiveHydraTransport:
        return cls(
            config=HydraDBConfig.from_env(),
            target=target,
        )

    def query(self, request_body: Mapping[str, Any]) -> HydraQueryResult:
        plan = HydraQueryPlan.model_validate(request_body)
        self._validate_plan(plan)
        actual_body = HydraDBRequestBody(
            **plan.model_dump(mode="json"),
            database=self.config.database,
            type="knowledge",
            query_forceful_relations=True,
        )
        started = self._clock()
        raw = self._client.query(
            query=actual_body.query,
            collection=actual_body.collection,
            query_type=actual_body.type,
            query_by=actual_body.query_by,
            mode=actual_body.mode,
            graph_context=actual_body.graph_context,
            max_results=actual_body.max_results,
            metadata_filters=actual_body.metadata_filters.model_dump(mode="json"),
            query_forceful_relations=actual_body.query_forceful_relations,
        )
        elapsed_ms = max(0.0, (self._clock() - started) * 1_000)
        request_digest = hashlib.sha256(
            json.dumps(
                actual_body.model_dump(mode="json"), separators=(",", ":"), sort_keys=True
            ).encode("utf-8")
        ).hexdigest()[:20]
        normalized = normalize_query_response(
            raw,
            session_id=f"evaluation-{request_digest}",
            view_id=f"evaluation-{request_digest}",
            revision=self.target.revision_id,
            collections=(self.collection,),
            query_by=actual_body.query_by,
            mode=actual_body.mode,
            graph_context=actual_body.graph_context,
            max_context_chars=12_000,
            max_paths=10,
            max_relations=50,
            max_hops_per_path=10,
            expected_revision=self.target.revision_id,
        )
        if normalized.get("status") == "ready" and not _live_result_is_grounded(
            normalized,
            self.target,
            graph_context=actual_body.graph_context,
        ):
            normalized = {
                **normalized,
                "status": "degraded",
                "chunks": [],
                "paths": [],
                "relations": [],
                "additional_context": [],
                "warnings": [
                    *normalized.get("warnings", []),
                    "Live result was not bound to the exact gold repository revision.",
                ],
            }
        return HydraQueryResult(normalized, elapsed_ms, actual_body)

    def _validate_plan(self, plan: HydraQueryPlan) -> None:
        if plan.collection != self.collection:
            raise ValueError("live evaluation must query only the explicit current collection")
        if (
            plan.metadata_filters.repository_id != self.target.repository_id
            or plan.metadata_filters.revision_id != self.target.revision_id
        ):
            raise ValueError("live evaluation request is not bound to the gold repository revision")


class AblationRunner:
    def __init__(
        self,
        *,
        mode: RunMode,
        hydra_transport: HydraEvaluationTransport,
        target: EvaluationTarget,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        if mode is RunMode.LIVE and hydra_transport.fixture_backed:
            raise ValueError("live evaluation refuses fixture-backed HydraDB responses")
        self.mode = mode
        self.hydra_transport = hydra_transport
        self.target = target
        if mode is RunMode.LIVE and (
            not isinstance(hydra_transport, LiveHydraTransport) or hydra_transport.target != target
        ):
            raise ValueError("live transport and runner evaluation targets differ")
        self._clock = clock

    def run_question(
        self,
        *,
        run_id: str,
        question: ResolvedQuestion,
        baseline_documents: tuple[BaselineDocument, ...],
        limit: int = 10,
    ) -> tuple[RetrievalObservation, ...]:
        if limit < 1 or limit > 50:
            raise ValueError("evaluation result limit must be between 1 and 50")
        observations = [
            self._run_baseline(
                run_id=run_id,
                question=question,
                documents=baseline_documents,
                limit=limit,
            )
        ]
        plans = [
            self._hydra_request(question.question.prompt, graph_context=False, limit=limit),
            self._hydra_request(question.question.prompt, graph_context=True, limit=limit),
        ]
        _assert_only_graph_context_differs(*plans)
        for condition, plan in zip(
            (AblationCondition.HYDRA_NO_GRAPH, AblationCondition.HYDRA_GRAPH),
            plans,
            strict=True,
        ):
            result = self.hydra_transport.query(plan.model_dump(mode="json"))
            observations.append(
                _normalize_hydra_observation(
                    run_id=run_id,
                    question_id=question.question.id,
                    condition=condition,
                    mode=self.mode,
                    target=self.target,
                    request_plan=plan,
                    result=result,
                )
            )
        return tuple(observations)

    def run_suite(
        self,
        *,
        run_id: str,
        gold: ResolvedGold,
        baseline_documents: tuple[BaselineDocument, ...],
        limit: int = 10,
    ) -> tuple[EvaluationRecord, ...]:
        validate_baseline_documents(baseline_documents, gold)
        if (
            self.target.repository_id != gold.manifest.repository_id
            or self.target.revision_id != gold.manifest.revision_id
            or self.target.repository_root_fingerprint
            != repository_root_fingerprint(gold.fixture_root)
        ):
            raise ValueError("evaluation runner target does not match the resolved gold fixture")
        corpus_digest = baseline_corpus_digest(baseline_documents)
        records: list[EvaluationRecord] = []
        for question in gold.questions:
            observations = self.run_question(
                run_id=run_id,
                question=question,
                baseline_documents=baseline_documents,
                limit=limit,
            )
            records.extend(
                EvaluationRecord(
                    gold_digest=gold.digest,
                    baseline_corpus_digest=corpus_digest,
                    observation=observation,
                    metrics=score_observation(question, observation),
                )
                for observation in observations
            )
        return tuple(records)

    def _run_baseline(
        self,
        *,
        run_id: str,
        question: ResolvedQuestion,
        documents: tuple[BaselineDocument, ...],
        limit: int,
    ) -> RetrievalObservation:
        started = self._clock()
        ranked = DeterministicTfidf(documents).search(question.question.prompt, limit=limit)
        elapsed_ms = max(0.0, (self._clock() - started) * 1_000)
        evidence = []
        for item in ranked:
            evidence.extend(
                EvidenceObservation(**_baseline_evidence_payload(source))
                for source in item.document.evidence
            )
        content = "\n".join(item.document.content for item in ranked)
        return RetrievalObservation(
            run_id=run_id,
            question_id=question.question.id,
            condition=AblationCondition.BASELINE,
            mode=self.mode,
            status="ready",
            target=self.target,
            returned_node_ids=tuple(item.document.node_id for item in ranked),
            returned_evidence=tuple(_unique_evidence(evidence)),
            context_chars=len(content),
            context_tokens=_token_count(content),
            latency_ms=elapsed_ms,
        )

    def _hydra_request(self, prompt: str, *, graph_context: bool, limit: int) -> HydraQueryPlan:
        return HydraQueryPlan(
            query=prompt,
            graph_context=graph_context,
            max_results=limit,
            metadata_filters={
                "repository_id": self.target.repository_id,
                "revision_id": self.target.revision_id,
            },
        )


def _assert_only_graph_context_differs(
    without_graph: HydraQueryPlan, with_graph: HydraQueryPlan
) -> None:
    left = without_graph.model_dump(mode="json")
    right = with_graph.model_dump(mode="json")
    if left.pop("graph_context", None) is not False:
        raise ValueError("condition B must disable graph_context")
    if right.pop("graph_context", None) is not True:
        raise ValueError("condition C must enable graph_context")
    if left != right:
        raise ValueError("conditions B and C may differ only by graph_context")


def _normalize_hydra_observation(
    *,
    run_id: str,
    question_id: str,
    condition: AblationCondition,
    mode: RunMode,
    target: EvaluationTarget,
    request_plan: HydraQueryPlan,
    result: HydraQueryResult,
) -> RetrievalObservation:
    payload = result.payload
    if payload.get("response_schema") != "hack-hydra.query-response.v2":
        return RetrievalObservation(
            run_id=run_id,
            question_id=question_id,
            condition=condition,
            mode=mode,
            status="error",
            target=target,
            request_plan=request_plan,
            hydradb_request_body=result.actual_request_body,
            context_chars=0,
            context_tokens=0,
            latency_ms=result.latency_ms,
            warnings=("HydraDB result did not use the stable product response schema.",),
        )
    status = str(payload.get("status") or "error")
    warnings = tuple(str(item) for item in payload.get("warnings", []) if isinstance(item, str))
    if status not in {"ready", "degraded", "unavailable", "error"}:
        status = "error"
        warnings = (*warnings, "HydraDB response used an unknown status.")
    if (
        mode is RunMode.LIVE
        and condition is AblationCondition.HYDRA_NO_GRAPH
        and (_records(payload.get("paths")) or _records(payload.get("relations")))
    ):
        status = "degraded"
        warnings = (*warnings, "Condition B returned graph paths despite graph_context=false.")
    if mode is RunMode.LIVE and status != "ready":
        return RetrievalObservation(
            run_id=run_id,
            question_id=question_id,
            condition=condition,
            mode=mode,
            status=status,
            target=target,
            request_plan=request_plan,
            hydradb_request_body=result.actual_request_body,
            context_chars=0,
            context_tokens=0,
            latency_ms=result.latency_ms,
            warnings=warnings,
        )
    try:
        content = _context_content(payload)
    except ValueError as error:
        return RetrievalObservation(
            run_id=run_id,
            question_id=question_id,
            condition=condition,
            mode=mode,
            status="error",
            target=target,
            request_plan=request_plan,
            hydradb_request_body=result.actual_request_body,
            context_chars=0,
            context_tokens=0,
            latency_ms=result.latency_ms,
            warnings=(*warnings, str(error)),
        )
    chunks = _records(payload.get("chunks"))
    paths = _records(payload.get("paths"))
    node_ids = {
        str(chunk["node_id"])
        for chunk in chunks
        if isinstance(chunk.get("node_id"), str) and chunk["node_id"]
    }
    relations: list[RelationObservation] = []
    evidence: list[EvidenceObservation] = []
    for path in paths:
        for hop in _records(path.get("hops")):
            source = _record(hop.get("source"))
            target_entity = _record(hop.get("target"))
            relation = _record(hop.get("relation"))
            source_id = _concrete_string(source.get("id"))
            target_id = _concrete_string(target_entity.get("id"))
            if source_id:
                node_ids.add(source_id)
            if target_id:
                node_ids.add(target_id)
            normalized = _relation_observation(relation, source_id, target_id)
            if normalized is not None:
                relations.append(normalized)
                evidence.extend(normalized.evidence)
    return RetrievalObservation(
        run_id=run_id,
        question_id=question_id,
        condition=condition,
        mode=mode,
        status=status,
        target=target,
        request_plan=request_plan,
        hydradb_request_body=result.actual_request_body,
        returned_node_ids=tuple(sorted(node_ids)),
        returned_relations=tuple(sorted(relations, key=lambda item: item.edge_id)),
        returned_evidence=tuple(_unique_evidence(evidence)),
        context_chars=len(content),
        context_tokens=_token_count(content),
        latency_ms=result.latency_ms,
        warnings=warnings,
    )


def _relation_observation(
    relation: Mapping[str, Any], source_id: str | None, target_id: str | None
) -> RelationObservation | None:
    origin = relation.get("origin")
    context = relation.get("context")
    envelope: Mapping[str, Any] = {}
    if isinstance(context, str):
        try:
            parsed = json.loads(context)
        except json.JSONDecodeError:
            parsed = None
        if (
            isinstance(parsed, Mapping)
            and parsed.get("schema") == "hack-hydra.relation-evidence.v1"
        ):
            envelope = parsed
    edge_id = _concrete_string(envelope.get("edge_id") or relation.get("id"))
    predicate = _concrete_string(relation.get("predicate") or relation.get("raw_predicate"))
    quality = _concrete_string(envelope.get("quality")) or "unknown"
    if not edge_id or not source_id or not target_id or not predicate:
        return None
    raw_evidence = envelope.get("evidence")
    evidence = []
    if origin != "byog":
        quality = "unknown"
    elif isinstance(raw_evidence, Mapping):
        try:
            evidence.append(
                EvidenceObservation.model_validate(
                    {
                        "evidence_id": raw_evidence.get("evidence_id") or raw_evidence.get("id"),
                        "path": raw_evidence.get("path"),
                        "start_line": raw_evidence.get("start_line"),
                        "start_column": raw_evidence.get("start_column"),
                        "end_line": raw_evidence.get("end_line"),
                        "end_column": raw_evidence.get("end_column"),
                        "excerpt_hash": raw_evidence.get("excerpt_hash"),
                    }
                )
            )
        except ValueError:
            evidence = []
            quality = "unknown"
    elif quality == "exact":
        quality = "unknown"
    if quality not in {"exact", "inferred", "semantic", "unknown"}:
        quality = "unknown"
    return RelationObservation(
        edge_id=edge_id,
        source_id=source_id,
        predicate=predicate,
        target_id=target_id,
        quality=quality,
        origin=_concrete_string(origin) or "unknown",
        evidence=tuple(evidence),
    )


def repository_root_fingerprint(root: str | Path) -> str:
    canonical = str(Path(root).resolve()).replace("\\", "/")
    if os.name == "nt":
        canonical = canonical.lower()
    canonical = canonical.rstrip("/") or "/"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def fixture_evaluation_target(gold: ResolvedGold) -> EvaluationTarget:
    return EvaluationTarget(
        database="offline-fixture",
        repository_id=gold.manifest.repository_id,
        revision_id=gold.manifest.revision_id,
        repository_root_fingerprint=repository_root_fingerprint(gold.fixture_root),
    )


def configured_evaluation_target(
    gold: ResolvedGold, environment: Mapping[str, str]
) -> EvaluationTarget:
    database = environment.get("HYDRA_DB_DATABASE", "").strip()
    repository_id = environment.get("HYDRA_REPOSITORY_ID", "").strip()
    root_value = environment.get("HYDRA_REPOSITORY_ROOT", "").strip()
    collection = environment.get("HYDRA_DB_COLLECTION", "current").strip() or "current"
    if not database:
        raise ValueError("live evaluation requires HYDRA_DB_DATABASE")
    if repository_id != gold.manifest.repository_id:
        raise ValueError("HYDRA_REPOSITORY_ID must equal the gold repository ID")
    if collection != "current":
        raise ValueError("live evaluation requires HYDRA_DB_COLLECTION=current")
    if not root_value:
        raise ValueError("live evaluation requires HYDRA_REPOSITORY_ROOT")
    configured_root = Path(root_value).resolve()
    if not configured_root.is_dir():
        raise ValueError("HYDRA_REPOSITORY_ROOT must be an existing directory")
    configured_fingerprint = repository_root_fingerprint(configured_root)
    expected_fingerprint = repository_root_fingerprint(gold.fixture_root)
    if configured_fingerprint != expected_fingerprint:
        raise ValueError("HYDRA_REPOSITORY_ROOT must equal the gold fixture repository root")
    return EvaluationTarget(
        database=database,
        collection="current",
        repository_id=repository_id,
        revision_id=gold.manifest.revision_id,
        repository_root_fingerprint=configured_fingerprint,
    )


def _live_result_is_grounded(
    normalized: Mapping[str, Any],
    target: EvaluationTarget,
    *,
    graph_context: bool,
) -> bool:
    hydradb = _record(normalized.get("hydradb"))
    if normalized.get("revision") != target.revision_id or hydradb.get("collections") != [
        target.collection
    ]:
        return False
    chunks = _records(normalized.get("chunks"))
    if not chunks or any(
        chunk.get("repository_id") != target.repository_id
        or chunk.get("revision") != target.revision_id
        for chunk in chunks
    ):
        return False
    grounded_nodes = {
        str(chunk["node_id"])
        for chunk in chunks
        if isinstance(chunk.get("node_id"), str) and chunk["node_id"]
    }
    grounded_chunks = {
        str(chunk["chunk_id"])
        for chunk in chunks
        if isinstance(chunk.get("chunk_id"), str) and chunk["chunk_id"]
    }
    groups = (*_records(normalized.get("paths")), *_records(normalized.get("relations")))
    if graph_context != bool(groups):
        return False
    grounded_hop = False
    for group in groups:
        linked_chunks = {
            str(item) for item in group.get("chunk_ids", []) if isinstance(item, str) and item
        }
        if not linked_chunks or not linked_chunks.issubset(grounded_chunks):
            return False
        for hop in _records(group.get("hops")):
            grounded_hop = True
            source_id = _concrete_string(_record(hop.get("source")).get("id"))
            target_id = _concrete_string(_record(hop.get("target")).get("id"))
            relation = _record(hop.get("relation"))
            relation_chunk = _concrete_string(relation.get("chunk_id"))
            if (
                not source_id
                or not target_id
                or not {source_id, target_id}.issubset(grounded_nodes)
                or relation_chunk not in grounded_chunks
                or relation.get("origin") != "byog"
            ):
                return False
    return grounded_hop if graph_context else True


def _baseline_evidence_payload(evidence: BaselineEvidence) -> dict[str, Any]:
    return {
        "evidence_id": evidence.evidence_id,
        "path": evidence.path,
        "start_line": evidence.start_line,
        "start_column": evidence.start_column,
        "end_line": evidence.end_line,
        "end_column": evidence.end_column,
        "excerpt_hash": evidence.excerpt_hash,
    }


def _context_content(payload: Mapping[str, Any]) -> str:
    identities: dict[str, str] = {}

    def add(identifier: object, value: object) -> None:
        if not isinstance(value, str) or not value:
            return
        key_id = (
            identifier
            if isinstance(identifier, str) and identifier
            else hashlib.sha256(value.encode("utf-8")).hexdigest()
        )
        existing = identities.get(key_id)
        if existing is not None and existing != value:
            raise ValueError(f"HydraDB returned conflicting context for ID {key_id}.")
        identities[key_id] = value

    for chunk in _records(payload.get("chunks")):
        add(
            chunk.get("chunk_id") or chunk.get("source_id") or chunk.get("node_id"),
            chunk.get("content"),
        )
    for chunk in _records(payload.get("additional_context")):
        add(
            chunk.get("chunk_id") or chunk.get("source_id") or chunk.get("node_id"),
            chunk.get("content"),
        )
    for group in (*_records(payload.get("paths")), *_records(payload.get("relations"))):
        add(group.get("path_id"), group.get("summary"))
        for hop in _records(group.get("hops")):
            relation = _record(hop.get("relation"))
            predicate = _concrete_string(relation.get("predicate") or relation.get("raw_predicate"))
            context = _concrete_string(relation.get("context"))
            relation_text = " ".join(item for item in (predicate, context) if item)
            add(relation.get("id"), relation_text)
    return "\n".join(identities.values())


def _unique_evidence(items: Sequence[EvidenceObservation]) -> list[EvidenceObservation]:
    by_id = {item.evidence_id: item for item in items}
    return sorted(by_id.values(), key=lambda item: item.evidence_id)


def _token_count(content: str) -> int:
    return len(content.split())


def _concrete_string(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _record(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _records(value: object) -> list[Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [item for item in value if isinstance(item, Mapping)]
