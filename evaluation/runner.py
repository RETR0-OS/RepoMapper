"""Three-condition retrieval runner with an explicit live/offline boundary."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from hydra_graph.config import HydraDBConfig
from hydra_graph.hydradb import HydraDBClient
from hydra_graph.query import normalize_query_response

from .baseline import BaselineDocument, BaselineEvidence, DeterministicTfidf
from .gold import ResolvedGold, ResolvedQuestion
from .metrics import score_observation
from .models import (
    AblationCondition,
    EvaluationRecord,
    EvidenceObservation,
    RelationObservation,
    RetrievalObservation,
    RunMode,
)


@dataclass(frozen=True, slots=True)
class HydraQueryResult:
    payload: Mapping[str, Any]
    latency_ms: float


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
        body = dict(request_body)
        graph_context = body.get("graph_context")
        if not isinstance(graph_context, bool):
            raise ValueError("evaluation HydraDB requests require a boolean graph_context")
        self.calls.append(body)
        return HydraQueryResult(self._responses[graph_context], self._latency_ms)


class LiveHydraTransport:
    """Credential-backed direct HydraDB v2 transport for conditions B and C."""

    fixture_backed = False
    collection = "current"

    def __init__(
        self,
        *,
        config: HydraDBConfig,
        repository_id: str,
        revision_id: str,
        client: HydraDBClient | None = None,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        if not config.configured:
            raise ValueError("live evaluation requires HydraDB API key and database")
        if not repository_id.strip() or not revision_id.strip() or revision_id == "current":
            raise ValueError("live evaluation requires concrete repository and revision IDs")
        self.config = config
        self.repository_id = repository_id
        self.revision_id = revision_id
        self._client = client or HydraDBClient(config)
        self._clock = clock

    @classmethod
    def from_environment(
        cls,
        *,
        repository_id: str,
        revision_id: str,
    ) -> LiveHydraTransport:
        return cls(
            config=HydraDBConfig.from_env(),
            repository_id=repository_id,
            revision_id=revision_id,
        )

    def query(self, request_body: Mapping[str, Any]) -> HydraQueryResult:
        body = dict(request_body)
        self._validate_body(body)
        started = self._clock()
        raw = self._client.query(
            query=body["query"],
            collection=self.collection,
            query_by=body["query_by"],
            mode=body["mode"],
            graph_context=body["graph_context"],
            max_results=body["max_results"],
            metadata_filters=body["metadata_filters"],
        )
        elapsed_ms = max(0.0, (self._clock() - started) * 1_000)
        request_digest = hashlib.sha256(
            json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8")
        ).hexdigest()[:20]
        normalized = normalize_query_response(
            raw,
            session_id=f"evaluation-{request_digest}",
            view_id=f"evaluation-{request_digest}",
            revision=self.revision_id,
            database=self.config.database,
            collections=(self.collection,),
            query_by=body["query_by"],
            mode=body["mode"],
            graph_context=body["graph_context"],
            max_context_chars=12_000,
            max_paths=10,
            max_relations=50,
            max_hops_per_path=10,
            expected_revision=self.revision_id,
        )
        normalized_chunks = _records(normalized.get("chunks"))
        if normalized.get("status") == "ready" and any(
            chunk.get("repository_id") != self.repository_id
            or chunk.get("revision") != self.revision_id
            for chunk in normalized_chunks
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
        return HydraQueryResult(normalized, elapsed_ms)

    def _validate_body(self, body: dict[str, Any]) -> None:
        expected = {
            "query",
            "query_by",
            "mode",
            "graph_context",
            "max_results",
            "collection",
            "metadata_filters",
        }
        if set(body) != expected:
            raise ValueError("live evaluation request body has an unexpected shape")
        if (
            not isinstance(body["query"], str)
            or not body["query"].strip()
            or body["query_by"] != "hybrid"
            or body["mode"] != "thinking"
            or not isinstance(body["graph_context"], bool)
            or not isinstance(body["max_results"], int)
            or not 1 <= body["max_results"] <= 50
        ):
            raise ValueError("live evaluation request does not match the fixed ablation contract")
        if body["collection"] != self.collection:
            raise ValueError("live evaluation must query only the explicit current collection")
        filters = body["metadata_filters"]
        if filters != {
            "repository_id": self.repository_id,
            "revision_id": self.revision_id,
        }:
            raise ValueError("live evaluation request is not bound to the gold repository revision")


class AblationRunner:
    def __init__(
        self,
        *,
        mode: RunMode,
        hydra_transport: HydraEvaluationTransport,
        repository_id: str = "evaluation-fixture",
        revision_id: str = "eval-rev-1",
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        if mode is RunMode.LIVE and hydra_transport.fixture_backed:
            raise ValueError("live evaluation refuses fixture-backed HydraDB responses")
        self.mode = mode
        self.hydra_transport = hydra_transport
        self.repository_id = repository_id
        self.revision_id = revision_id
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
        bodies = [
            self._hydra_request(question.question.prompt, graph_context=False, limit=limit),
            self._hydra_request(question.question.prompt, graph_context=True, limit=limit),
        ]
        _assert_only_graph_context_differs(*bodies)
        for condition, body in zip(
            (AblationCondition.HYDRA_NO_GRAPH, AblationCondition.HYDRA_GRAPH),
            bodies,
            strict=True,
        ):
            result = self.hydra_transport.query(body)
            observations.append(
                _normalize_hydra_observation(
                    run_id=run_id,
                    question_id=question.question.id,
                    condition=condition,
                    mode=self.mode,
                    request_body=body,
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
            returned_node_ids=tuple(item.document.node_id for item in ranked),
            returned_evidence=tuple(_unique_evidence(evidence)),
            context_chars=len(content),
            context_tokens=_token_count(content),
            latency_ms=elapsed_ms,
        )

    def _hydra_request(self, prompt: str, *, graph_context: bool, limit: int) -> dict[str, Any]:
        return {
            "query": prompt,
            "query_by": "hybrid",
            "mode": "thinking",
            "graph_context": graph_context,
            "max_results": limit,
            "collection": "current",
            "metadata_filters": {
                "repository_id": self.repository_id,
                "revision_id": self.revision_id,
            },
        }


def _assert_only_graph_context_differs(
    without_graph: Mapping[str, Any], with_graph: Mapping[str, Any]
) -> None:
    left = dict(without_graph)
    right = dict(with_graph)
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
    request_body: dict[str, Any],
    result: HydraQueryResult,
) -> RetrievalObservation:
    payload = result.payload
    if payload.get("response_schema") != "hack-hydra.query-response.v1":
        return RetrievalObservation(
            run_id=run_id,
            question_id=question_id,
            condition=condition,
            mode=mode,
            status="error",
            request_body=request_body,
            context_chars=0,
            context_tokens=0,
            latency_ms=result.latency_ms,
            warnings=("HydraDB result did not use the stable product response schema.",),
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
            target = _record(hop.get("target"))
            relation = _record(hop.get("relation"))
            source_id = _concrete_string(source.get("id"))
            target_id = _concrete_string(target.get("id"))
            if source_id:
                node_ids.add(source_id)
            if target_id:
                node_ids.add(target_id)
            normalized = _relation_observation(relation, source_id, target_id)
            if normalized is not None:
                relations.append(normalized)
                evidence.extend(normalized.evidence)
    content = "\n".join(str(chunk.get("content") or "") for chunk in chunks)
    warnings = tuple(str(item) for item in payload.get("warnings", []) if isinstance(item, str))
    status = str(payload.get("status") or "error")
    if status not in {"ready", "degraded", "unavailable", "error"}:
        status = "error"
        warnings = (*warnings, "HydraDB response used an unknown status.")
    return RetrievalObservation(
        run_id=run_id,
        question_id=question_id,
        condition=condition,
        mode=mode,
        status=status,
        request_body=request_body,
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
    if isinstance(raw_evidence, Mapping):
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
        evidence=tuple(evidence),
    )


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
