"""HydraDB-backed query planning, normalization, and response budgeting."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from itertools import zip_longest
from typing import Any

from .diagnostics import Timings, log_query
from .events import EventBus
from .flow import assemble_flow_paths
from .hydradb import (
    HydraDBAPIError,
    HydraDBClient,
    HydraDBError,
    HydraDBTimeout,
    HydraDBUnavailable,
    hydradb_reason,
    response_data,
)
from .relations import (
    FetchedRelations,
    RelationCache,
    fetch_repository_relations,
    has_byog_envelope_marker,
    result_window,
)

QUERY_RESPONSE_SCHEMA = "hack-hydra.query-response.v2"

# The order of the funnel a HydraDB answer passes through. A graph becomes empty at
# exactly one of these stages, and the counts name which one.
FUNNEL_STAGES = (
    "raw_chunks",
    "raw_test_chunks",
    "completion_candidates",
    "completion_chunks",
    "completion_dropped_revision",
    "raw_paths",
    "raw_relations",
    "dropped_paths",
    "dropped_relations",
    "kept_paths",
    "kept_relations",
    "assembled_paths",
    "hops",
    "sources",
)

# How a question treats test code. Test sources repeat feature words and carry whole
# code excerpts, so an unranked answer fills with them and never shows the flow.
TEST_POLICIES = ("last", "mixed", "only")

# How many times an answer may reach one step further out for the code that joins it.
COMPLETION_ROUNDS = 2


@dataclass(frozen=True, slots=True)
class _CompletionResult:
    """What one window-completion read added, and what it refused."""

    response: Mapping[str, Any] = field(default_factory=dict)
    candidates: int = 0
    chunks_added: int = 0
    dropped_revision: int = 0


@dataclass(frozen=True, slots=True)
class QueryRequest:
    question: str
    revision: str = "current"
    max_results: int = 8
    max_context_chars: int = 100_000
    max_paths: int = 3
    max_relations: int = 30
    max_hops_per_path: int | None = None
    relation_quality: tuple[str, ...] = ("exact", "inferred")
    entity_kinds: tuple[str, ...] = ()
    strict_entity_kinds: bool = False
    query_by: str = "hybrid"
    mode: str = "thinking"
    graph_context: bool = True
    tests: str = "last"
    entry_points_only: bool = False
    session_id: str | None = None

    def __post_init__(self) -> None:
        if not self.question.strip():
            raise ValueError("question must not be blank")
        if not 1 <= self.max_results <= 50:
            raise ValueError("max_results must be between 1 and 50")
        if self.max_context_chars < 1:
            raise ValueError("max_context_chars must be positive")
        if self.max_paths < 0 or self.max_relations < 0:
            raise ValueError("path and relation budgets cannot be negative")
        if self.max_hops_per_path is not None and self.max_hops_per_path < 1:
            raise ValueError("max_hops_per_path must be positive")
        if self.tests not in TEST_POLICIES:
            raise ValueError(f"tests must be one of {', '.join(TEST_POLICIES)}")


class QueryService:
    def __init__(
        self,
        client: HydraDBClient,
        *,
        repository_id: str,
        events: EventBus | None = None,
        verified_revision: Callable[[], str | None] | None = None,
        byog_source_ids: Callable[[], Sequence[str]] | None = None,
        current_state_indeterminate: Callable[[], bool] | None = None,
    ) -> None:
        self.client = client
        self.repository_id = repository_id
        self.events = events or EventBus()
        self._verified_revision = verified_revision or (lambda: None)
        self._byog_source_ids = byog_source_ids or (lambda: ())
        self._current_state_indeterminate = current_state_indeterminate or (lambda: False)
        # A source cannot change inside one revision, and the revision is part of the
        # key, so a repeated view pays for the stored graph only once.
        self._relation_cache = RelationCache()

    def repository_query(self, request: QueryRequest) -> dict[str, Any]:
        # Every stage is measured, because a query that is slow, a query that fails,
        # and a query that returns an empty graph all look the same from the panel.
        timings = Timings()
        session_id = request.session_id or f"session_{uuid.uuid4().hex}"
        view_id = f"view_{uuid.uuid4().hex}"
        metadata_filters: dict[str, Any] = {"repository_id": self.repository_id}
        with timings.stage("verified_revision"):
            current_verified_revision = self._verified_revision()
        verified_revision = current_verified_revision if request.revision == "current" else None
        requested_revision = verified_revision or request.revision
        if requested_revision != "current":
            metadata_filters["revision_id"] = requested_revision
        if request.relation_quality:
            metadata_filters["relation_quality"] = list(request.relation_quality)
        if request.entity_kinds:
            metadata_filters["entity_kind"] = list(request.entity_kinds)
        if request.entry_points_only:
            metadata_filters["is_entry_point"] = True
        query_metadata = {
            "collections": [self.client.config.collection],
            "query_by": request.query_by,
            "mode": request.mode,
            "graph_context": request.graph_context,
            "max_results": request.max_results,
        }
        self.events.emit(
            "query_started",
            session_id=session_id,
            revision_id=requested_revision,
            view_id=view_id,
            hydradb_query_metadata=query_metadata,
        )
        if request.revision == "current":
            with timings.stage("sync_state"):
                indeterminate = self._current_state_indeterminate()
            if indeterminate:
                result = self._degraded(
                    request=request,
                    session_id=session_id,
                    view_id=view_id,
                    warning=(
                        "The current HydraDB collection is indeterminate after a failed sync; "
                        "no repository context was exposed."
                    ),
                    query_metadata=query_metadata,
                    reason="sync state is indeterminate",
                )
                log_query(
                    timings=timings,
                    session=session_id,
                    view=view_id,
                    status="degraded",
                    outcome="sync_indeterminate",
                )
                return result
        composition_warnings: list[str] = []
        try:
            with timings.stage("hydradb_query"):
                raw, test_chunks = self._retrieve(
                    request,
                    metadata_filters=metadata_filters,
                    warnings=composition_warnings,
                )
        except HydraDBError as exc:
            # A read timeout, a refusal, and a lost credential each need a different
            # correction. One shared sentence hid all three.
            reason = self._failure_reason(exc)
            result = self._unavailable(
                request=request,
                session_id=session_id,
                view_id=view_id,
                warning=f"HydraDB could not serve this repository query. {reason}",
                query_metadata=query_metadata,
                reason=reason,
            )
            log_query(
                timings=timings,
                session=session_id,
                view=view_id,
                status="unavailable",
                outcome=type(exc).__name__,
                reason=reason,
            )
            return result
        expected_revision = requested_revision if requested_revision != "current" else None
        # The query decides which sources are relevant. It must not decide the graph,
        # because it returns only a few relation groups and ranks HydraDB's own
        # concept relations beside this repository's. The stored graph is read here.
        #
        # The read is one request per source, so it runs only once the answer is known
        # to hold one revision. A revision conflict then costs no request at all.
        fetched = FetchedRelations()
        candidates = 0
        chunks_added = 0
        dropped_revision = 0
        if not _revision_conflict(response_data(raw), expected_revision):
            fetched = self._read_relations(raw, revision=requested_revision, timings=timings)
            # An entry point is usually several calls above the code that matched, so
            # one round reaches the caller and stops one step short of where execution
            # starts. Each further round is one fast read, and the loop ends as soon as
            # a round adds nothing.
            for _ in range(COMPLETION_ROUNDS):
                completion = self._complete_window(
                    raw,
                    fetched,
                    revision=requested_revision,
                    metadata_filters=metadata_filters,
                    tests=request.tests,
                    timings=timings,
                    warnings=composition_warnings,
                )
                candidates += completion.candidates
                dropped_revision += completion.dropped_revision
                if not completion.chunks_added:
                    break
                chunks_added += completion.chunks_added
                raw = completion.response
                # The window is larger, so relations that cited a chunk outside it can
                # now be proven. The cache absorbs the sources already read.
                fetched = self._read_relations(raw, revision=requested_revision, timings=timings)

        groups = fetched.groups

        with timings.stage("normalize"):
            result = normalize_query_response(
                raw,
                repository_relations=lambda _window: groups,
                session_id=session_id,
                view_id=view_id,
                revision=request.revision,
                collections=[self.client.config.collection],
                query_by=request.query_by,
                mode=request.mode,
                graph_context=request.graph_context,
                max_context_chars=request.max_context_chars,
                max_paths=request.max_paths,
                max_relations=request.max_relations,
                max_hops_per_path=request.max_hops_per_path,
                expected_revision=expected_revision,
                expected_entity_kinds=(
                    request.entity_kinds if request.strict_entity_kinds else ()
                ),
                byog_source_ids=(
                    self._byog_source_ids()
                    if current_verified_revision and requested_revision == current_verified_revision
                    else ()
                ),
            )
        result["warnings"] = [*composition_warnings, *result.get("warnings", [])]
        diagnostics = dict(result.get("diagnostics") or {})
        diagnostics["stage_ms"] = timings.as_dict()
        diagnostics["funnel"] = {
            **dict(diagnostics.get("funnel") or {}),
            "raw_test_chunks": test_chunks,
            "completion_candidates": candidates,
            "completion_chunks": chunks_added,
            "completion_dropped_revision": dropped_revision,
            "relation_sources": fetched.requested_sources,
            "relation_cached": fetched.cached_sources,
            "relation_pairs": fetched.returned_pairs,
            "relation_outside_window": fetched.outside_window,
            "relation_failures": fetched.failures,
        }
        result["diagnostics"] = diagnostics
        log_query(
            timings=timings,
            funnel=diagnostics.get("funnel"),
            session=session_id,
            view=view_id,
            status=result["status"],
            outcome=diagnostics.get("outcome", result["status"]),
            reason=diagnostics.get("reason"),
        )
        relationship_ids = tuple(
            dict.fromkeys(
                str(hop.get("relation", {}).get("id"))
                for path in result["paths"]
                for hop in path.get("hops", [])
                if hop.get("relation", {}).get("id")
            )
        )[:100]
        entity_ids = tuple(
            dict.fromkeys(
                str(entity.get("id"))
                for path in result["paths"]
                for hop in path.get("hops", [])
                for entity in (hop.get("source", {}), hop.get("target", {}))
                if entity.get("id")
            )
        )[:100]
        self.events.emit(
            "hydradb_result_returned",
            session_id=session_id,
            revision_id=result["revision"],
            view_id=view_id,
            entity_ids=entity_ids,
            relationship_ids=relationship_ids,
            hydradb_query_metadata=query_metadata,
        )
        for path in result["paths"]:
            self.events.emit(
                "path_replay_started",
                session_id=session_id,
                revision_id=result["revision"],
                view_id=view_id,
                hydradb_query_metadata={"path_id": path["path_id"]},
            )
            for hop in path.get("hops", []):
                relation_id = hop.get("relation", {}).get("id")
                self.events.emit(
                    "path_hop_replayed",
                    session_id=session_id,
                    revision_id=result["revision"],
                    view_id=view_id,
                    relationship_ids=(str(relation_id),) if relation_id else (),
                )
        return result

    def _retrieve(
        self,
        request: QueryRequest,
        *,
        metadata_filters: Mapping[str, Any],
        warnings: list[str],
    ) -> tuple[Mapping[str, Any], int]:
        """Answer the question with test code ordered behind implementation code.

        HydraDB ranks one query; it cannot be told to rank a metadata value last. So a
        ``last`` policy asks twice with opposite ``is_test`` filters and concatenates.
        Each half is still ranked entirely by HydraDB, and the order between the halves
        is a fixed rule rather than a local relevance score.
        """

        if request.tests == "mixed":
            return self._query_once(request, metadata_filters, request.max_results), 0
        if request.tests == "only":
            filters = {**dict(metadata_filters), "is_test": True}
            raw = self._query_once(request, filters, request.max_results)
            return raw, len(_mapping_list(response_data(raw).get("chunks")))

        primary = self._query_once(
            request,
            {**dict(metadata_filters), "is_test": False},
            request.max_results,
        )
        try:
            # The tail is a small, fast read. A thinking-mode query is the slowest call
            # this service makes, and paying for it twice to order the tail would cost
            # more than the ordering is worth.
            secondary = self._query_once(
                request,
                {**dict(metadata_filters), "is_test": True},
                max(1, request.max_results // 4),
                mode="fast",
            )
        except HydraDBError as exc:
            # Implementation code is the answer. Losing the test tail must not lose it.
            warnings.append(
                "Test-code results were omitted because a second HydraDB query failed: "
                f"{self._failure_reason(exc)}"
            )
            return primary, 0
        merged = _merge_responses(primary, secondary)
        test_chunks = len(_mapping_list(response_data(merged).get("chunks"))) - len(
            _mapping_list(response_data(primary).get("chunks"))
        )
        return merged, max(0, test_chunks)

    def _query_once(
        self,
        request: QueryRequest,
        metadata_filters: Mapping[str, Any],
        max_results: int,
        mode: str | None = None,
    ) -> Mapping[str, Any]:
        return self.client.query(
            query=request.question,
            query_by=request.query_by,
            mode=mode or request.mode,
            graph_context=request.graph_context,
            max_results=max(1, min(50, max_results)),
            metadata_filters=dict(metadata_filters),
            # Forceful relations make HydraDB extract fresh relations at query
            # time. Those carry concept entity ids and prose context instead of
            # this repository's node ids and evidence envelopes, and they hide
            # the uploaded BYOG graph, so every hop is dropped as ungrounded.
            query_forceful_relations=False,
        )

    def _read_relations(
        self, raw: Mapping[str, Any], *, revision: str, timings: Timings
    ) -> FetchedRelations:
        chunk_window, source_ids = result_window(raw)
        with timings.stage("repository_relations"):
            return fetch_repository_relations(
                self.client,
                source_ids=source_ids,
                chunk_window=chunk_window,
                revision=revision,
                max_sources=self.client.config.relation_sources,
                workers=self.client.config.relation_workers,
                cache=self._relation_cache,
            )

    def _complete_window(
        self,
        raw: Mapping[str, Any],
        fetched: FetchedRelations,
        *,
        revision: str,
        metadata_filters: Mapping[str, Any],
        tests: str,
        timings: Timings,
        warnings: list[str],
    ) -> _CompletionResult:
        """Fetch the cards that join the matched cards, then widen the answer.

        A relation survives only when every chunk it cites came back in the same
        answer. The code that connects two matched symbols is rarely a word match for
        the question, so it stays outside the window and every relation through it is
        dropped as ungrounded. That is why the graph arrives as disconnected pairs.

        The endpoints are named by the stored graph, so this asks HydraDB for those
        exact records instead of guessing. A returned card that does not carry the
        requested revision is discarded rather than mixed in.
        """

        budget = self.client.config.completion_sources
        if not budget:
            return _CompletionResult(response=raw)
        # Two directions are missing, and they need different seeds. A relation this
        # answer already holds names the code it reaches, so its endpoints find the
        # callees. Nothing here names the callers, because a card's stored graph holds
        # only the relations it owns. Every card does list its incoming relations by
        # name, so searching for the matched names finds the code that calls them.
        names = _dedupe_names(
            _qualified_names(fetched.outside_endpoints),
            _matched_names(response_data(raw)),
        )[:budget]
        if not names:
            return _CompletionResult(response=raw)
        filters = dict(metadata_filters)
        if tests != "only":
            # This read exists to join implementation code. A test that calls the same
            # symbol matches these names just as well and would spend the budget
            # without connecting anything.
            filters["is_test"] = False
        try:
            with timings.stage("window_completion"):
                extra = self.client.query(
                    query=" ".join(names),
                    query_by="text",
                    mode="fast",
                    graph_context=False,
                    max_results=max(1, min(50, len(names))),
                    metadata_filters=filters,
                    query_forceful_relations=False,
                )
        except HydraDBError as exc:
            warnings.append(
                "Connecting repository records could not be fetched, so the graph may "
                f"show unlinked pairs: {self._failure_reason(exc)}"
            )
            return _CompletionResult(response=raw, candidates=len(names))
        kept, dropped = _revision_matched_chunks(extra, revision)
        if not kept:
            return _CompletionResult(response=raw, candidates=len(names), dropped_revision=dropped)
        merged = _merge_responses(raw, _with_chunks(extra, kept))
        added = len(_mapping_list(response_data(merged).get("chunks"))) - len(
            _mapping_list(response_data(raw).get("chunks"))
        )
        return _CompletionResult(
            response=merged,
            candidates=len(names),
            chunks_added=max(0, added),
            dropped_revision=dropped,
        )

    def _failure_reason(self, failure: HydraDBError) -> str:
        """Return a reason that is safe to show, by the same rule as the setup test.

        Only ``HydraDBAPIError`` carries text that HydraDB itself wrote. A locally
        raised failure wraps a socket error, and that text can name the host, the
        database, or a URL that holds a key. So the class of the failure chooses the
        sentence, and no local exception message is ever exposed.
        """

        if isinstance(failure, HydraDBAPIError):
            return hydradb_reason(failure)
        if isinstance(failure, HydraDBTimeout):
            budget = self.client.config.request_timeout_seconds
            return f"HydraDB did not answer inside the {budget:g} s service budget."
        if isinstance(failure, HydraDBUnavailable):
            return "HydraDB is unreachable, or no credential is available for this project."
        return "HydraDB refused the request."

    def _unavailable(
        self,
        *,
        request: QueryRequest,
        session_id: str,
        view_id: str,
        warning: str,
        query_metadata: Mapping[str, Any],
        reason: str | None = None,
    ) -> dict[str, Any]:
        return {
            "response_schema": QUERY_RESPONSE_SCHEMA,
            "session_id": session_id,
            "view_id": view_id,
            "status": "unavailable",
            "diagnostics": {
                "outcome": "hydradb_unavailable",
                **({"reason": reason} if reason else {}),
                "funnel": dict.fromkeys(FUNNEL_STAGES, 0),
            },
            "hydradb": {
                **dict(query_metadata),
                "available": False,
            },
            "revision": request.revision,
            "paths": [],
            "relations": [],
            "chunk_id_to_group_ids": {},
            "chunks": [],
            "sources": [],
            "additional_context": [],
            "warnings": [warning],
            "budget": {
                "max_context_chars": request.max_context_chars,
                "returned_context_chars": 0,
                "max_paths": request.max_paths,
                "returned_paths": 0,
                "max_relations": request.max_relations,
                "returned_relations": 0,
                "truncated": False,
            },
        }

    def _degraded(
        self,
        *,
        request: QueryRequest,
        session_id: str,
        view_id: str,
        warning: str,
        query_metadata: Mapping[str, Any],
        reason: str | None = None,
    ) -> dict[str, Any]:
        result = self._unavailable(
            request=request,
            session_id=session_id,
            view_id=view_id,
            warning=warning,
            query_metadata=query_metadata,
            reason=reason,
        )
        result["status"] = "degraded"
        result["hydradb"]["available"] = True
        result["budget"]["truncated"] = True
        result["diagnostics"]["outcome"] = "sync_indeterminate"
        return result


def normalize_query_response(
    response: Mapping[str, Any],
    *,
    session_id: str,
    view_id: str,
    revision: str,
    collections: Sequence[str],
    query_by: str,
    mode: str,
    graph_context: bool,
    max_context_chars: int,
    max_paths: int,
    max_relations: int,
    max_hops_per_path: int | None = None,
    expected_revision: str | None = None,
    expected_entity_kinds: Sequence[str] = (),
    byog_source_ids: Sequence[str] = (),
    repository_relations: Callable[[set[str]], Sequence[Mapping[str, Any]]] | None = None,
) -> dict[str, Any]:
    data = response_data(response)
    raw_chunks = _mapping_list(data.get("chunks"))
    returned_revisions, target_revision = _returned_revisions(data, expected_revision)
    if _revision_conflict(data, expected_revision):
        return _revision_conflict_response(
            session_id=session_id,
            view_id=view_id,
            revision=expected_revision or revision,
            collections=collections,
            query_by=query_by,
            mode=mode,
            graph_context=graph_context,
            max_context_chars=max_context_chars,
            max_paths=max_paths,
            max_relations=max_relations,
            returned_revisions=returned_revisions,
            outcome="revision_conflict",
            raw_chunks=len(raw_chunks),
        )
    if expected_entity_kinds and any(
        _mapping(chunk.get("metadata")).get("entity_kind") not in set(expected_entity_kinds)
        for chunk in raw_chunks
    ):
        return _revision_conflict_response(
            session_id=session_id,
            view_id=view_id,
            revision=target_revision or revision,
            collections=collections,
            query_by=query_by,
            mode=mode,
            graph_context=graph_context,
            max_context_chars=max_context_chars,
            max_paths=max_paths,
            max_relations=max_relations,
            returned_revisions=returned_revisions,
            warning=(
                "HydraDB did not return the requested "
                f"{', '.join(expected_entity_kinds)} records; no generic repository "
                "chunks were presented as specialized results."
            ),
            outcome="entity_kind_mismatch",
            raw_chunks=len(raw_chunks),
        )
    graph = _mapping(data.get("graph_context"))
    chunk_window = _chunk_window_ids(raw_chunks)
    all_paths = _mapping_list(graph.get("query_paths"))
    # The stored graph goes first, so the relation budget is spent on relations this
    # repository can prove before any concept relation the query ranked above them.
    stored = repository_relations(chunk_window) if repository_relations else ()
    all_relations = [*_mapping_list(stored), *_mapping_list(graph.get("chunk_relations"))]
    raw_paths, omitted_paths = _grounded_groups(all_paths, chunk_window)
    raw_relations, omitted_relations = _grounded_groups(all_relations, chunk_window)
    # Ordered flow goes in front of HydraDB's own path ranking, so the path budget is
    # spent on the steps that answer "how does this work" before anything else. Every
    # hop is a relation already returned and already proven here; only the order and
    # the choice of start are added.
    assembled = assemble_flow_paths(
        raw_chunks,
        [*raw_paths, *raw_relations],
        max_paths=max(1, max_paths),
        max_hops=max_hops_per_path or max(1, max_relations),
    )
    # An assembled path is built from these same groups, so keeping both would show one
    # chain twice and spend the budget on it twice. The ordered form replaces the group
    # it was built from; a group holding anything extra stays.
    raw_paths = [*assembled, *_without_covered_groups(raw_paths, assembled)]
    warnings: list[str] = []
    omitted_groups = omitted_paths + omitted_relations
    if omitted_groups:
        warnings.append(
            f"Omitted {omitted_groups} HydraDB relation group(s) that cite chunks outside "
            "this result; their revision could not be proven here."
        )
    raw_budgeted_chunks, raw_additional, returned_chars, context_truncated = _budget_context(
        raw_chunks,
        _additional_context(data.get("additional_context")),
        max_context_chars,
    )
    if context_truncated:
        warnings.append("Context character budget truncated HydraDB content.")
    chunk_groups = _mapping(graph.get("chunk_id_to_group_ids"))
    chunks = [
        _normalize_chunk(chunk, rank=index + 1, group_ids=chunk_groups)
        for index, chunk in enumerate(raw_budgeted_chunks)
    ]
    additional = [
        _normalize_chunk(item, rank=index + 1, group_ids={})
        for index, item in enumerate(raw_additional)
    ]
    entity_ids = _entity_id_lookup(raw_chunks)
    verified_byog_sources = {str(item) for item in byog_source_ids}
    byog_chunk_ids = {
        str(chunk.get("chunk_uuid"))
        for chunk in raw_chunks
        if chunk.get("chunk_uuid") and str(chunk.get("id")) in verified_byog_sources
    }
    paths, path_hops, path_truncated = _normalize_groups(
        raw_paths,
        group_limit=max_paths,
        hop_limit=max_relations,
        per_group_hop_limit=max_hops_per_path,
        entity_ids=entity_ids,
        byog_chunk_ids=byog_chunk_ids,
    )
    remaining_hops = max(0, max_relations - path_hops)
    relations, relation_hops, relation_truncated = _normalize_groups(
        raw_relations,
        group_limit=len(raw_relations),
        hop_limit=remaining_hops,
        per_group_hop_limit=max_hops_per_path,
        entity_ids=entity_ids,
        byog_chunk_ids=byog_chunk_ids,
    )
    if path_truncated:
        warnings.append("Path or hop budget truncated HydraDB returned paths.")
    if relation_truncated:
        warnings.append("Relation budget truncated HydraDB relation groups or hops.")
    revision_id = _revision_from_chunks(chunks) or target_revision or revision
    path_ids = [str(path["path_id"]) for path in paths]
    has_byog = any(
        hop.get("relation", {}).get("origin") == "byog"
        for path in (*paths, *relations)
        for hop in path.get("hops", [])
    )
    funnel = {
        "raw_chunks": len(raw_chunks),
        "assembled_paths": len(assembled),
        "raw_paths": len(all_paths),
        "raw_relations": len(all_relations),
        "dropped_paths": omitted_paths,
        "dropped_relations": omitted_relations,
        "kept_paths": len(paths),
        "kept_relations": len(relations),
        "hops": path_hops + relation_hops,
        "sources": len(_mapping_list(data.get("sources"))),
    }
    return {
        "response_schema": QUERY_RESPONSE_SCHEMA,
        "session_id": session_id,
        "view_id": view_id,
        "status": "ready",
        "diagnostics": {"outcome": _ready_outcome(funnel), "funnel": funnel},
        "hydradb": {
            "available": True,
            "collections": list(collections),
            "query_by": query_by,
            "mode": mode,
            "graph_context": graph_context,
            "path_ids": path_ids,
            "origin": "byog" if has_byog else None,
            "request_id": _mapping(response.get("meta")).get("request_id"),
        },
        "revision": revision_id,
        "paths": paths,
        "relations": relations,
        "chunk_id_to_group_ids": {
            str(chunk_id): [str(group_id) for group_id in group_ids]
            for chunk_id, group_ids in chunk_groups.items()
            if isinstance(group_ids, Sequence) and not isinstance(group_ids, (str, bytes))
        },
        # Order is exactly the order returned by HydraDB. Budgeting only removes
        # the tail or trims the final included chunk.
        "chunks": chunks,
        # Source records carry graph-grounding metadata but no chunk content, so
        # they remain available when the text context budget removes chunk tails.
        "sources": _normalize_sources(
            _mapping_list(data.get("sources")),
            raw_chunks,
        ),
        "additional_context": additional,
        "warnings": warnings,
        "budget": {
            "max_context_chars": max_context_chars,
            "returned_context_chars": returned_chars,
            "max_paths": max_paths,
            "returned_paths": len(paths),
            "max_relations": max_relations,
            "returned_relations": path_hops + relation_hops,
            "truncated": bool(warnings),
        },
    }


def _merge_responses(primary: Mapping[str, Any], secondary: Mapping[str, Any]) -> dict[str, Any]:
    """Concatenate two HydraDB answers, keeping the first answer's order in front.

    Ranking inside each answer stays HydraDB's. Only the join order is this service's,
    and it is a fixed rule rather than a score, so the result is reproducible.
    """

    first = response_data(primary)
    second = response_data(secondary)
    merged = dict(first)
    merged["chunks"] = _dedupe(
        [*_mapping_list(first.get("chunks")), *_mapping_list(second.get("chunks"))],
        key="chunk_uuid",
    )
    merged["sources"] = _dedupe(
        [*_mapping_list(first.get("sources")), *_mapping_list(second.get("sources"))],
        key="id",
    )
    first_graph = _mapping(first.get("graph_context"))
    second_graph = _mapping(second.get("graph_context"))
    graph = dict(first_graph)
    graph["query_paths"] = _dedupe_groups(
        [
            *_mapping_list(first_graph.get("query_paths")),
            *_mapping_list(second_graph.get("query_paths")),
        ]
    )
    graph["chunk_relations"] = _dedupe_groups(
        [
            *_mapping_list(first_graph.get("chunk_relations")),
            *_mapping_list(second_graph.get("chunk_relations")),
        ]
    )
    graph["chunk_id_to_group_ids"] = {
        **_mapping(first_graph.get("chunk_id_to_group_ids")),
        **_mapping(second_graph.get("chunk_id_to_group_ids")),
    }
    if graph["query_paths"] or graph["chunk_relations"] or graph["chunk_id_to_group_ids"]:
        merged["graph_context"] = graph
    merged["additional_context"] = [
        *_additional_context(first.get("additional_context")),
        *_additional_context(second.get("additional_context")),
    ]
    return {"data": merged, "meta": primary.get("meta") or secondary.get("meta")}


def _with_chunks(
    response: Mapping[str, Any], chunks: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    data = dict(response_data(response))
    data["chunks"] = [dict(chunk) for chunk in chunks]
    keep = {str(chunk.get("id")) for chunk in chunks if chunk.get("id")}
    data["sources"] = [
        source for source in _mapping_list(data.get("sources")) if str(source.get("id")) in keep
    ]
    return {"data": data, "meta": response.get("meta")}


def _revision_matched_chunks(
    response: Mapping[str, Any], revision: str
) -> tuple[list[dict[str, Any]], int]:
    """Keep only chunks that carry the requested revision.

    A completion read widens the window, so it can also widen it with another
    revision's cards. Those are discarded here; mixing them would defeat the check
    that keeps one answer inside one revision.
    """

    if revision == "current":
        return [], 0
    kept: list[dict[str, Any]] = []
    dropped = 0
    for chunk in _mapping_list(response_data(response).get("chunks")):
        if str(_mapping(chunk.get("metadata")).get("revision_id")) == revision:
            kept.append(chunk)
        else:
            dropped += 1
    return kept, dropped


def _qualified_names(logical_ids: Sequence[str]) -> list[str]:
    """Read the readable name out of each logical id, in first-seen order.

    ``node_logical_id`` builds ``repo:<id>:<language>:<path>:<kind>:<qualified name>``.
    Only a value in that exact shape is used, so a HydraDB concept identifier cannot
    become a search term.
    """

    names: list[str] = []
    seen: set[str] = set()
    for value in logical_ids:
        parts = str(value).split(":", 5)
        if len(parts) != 6 or parts[0] != "repo":
            continue
        name = parts[5].strip()
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    return names


def _matched_names(data: Mapping[str, Any]) -> list[str]:
    """Return the qualified names this answer matched, best rank first, tests last."""

    ranked: list[tuple[bool, int, str]] = []
    for index, chunk in enumerate(_mapping_list(data.get("chunks"))):
        name = _mapping(chunk.get("additional_metadata")).get("qualified_name")
        if not name:
            continue
        is_test = str(_mapping(chunk.get("metadata")).get("is_test")).lower() in {"true", "1"}
        ranked.append((is_test, index, str(name)))
    return [name for _, _, name in sorted(ranked)]


def _dedupe_names(*groups: Sequence[str]) -> list[str]:
    """Interleave name sources so neither direction is starved by the other."""

    ordered: list[str] = []
    seen: set[str] = set()
    for row in zip_longest(*groups):
        for name in row:
            if name and name not in seen:
                seen.add(name)
                ordered.append(name)
    return ordered


def _dedupe_groups(groups: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Drop relation groups both answers returned, so a hop is never counted twice."""

    seen: set[str] = set()
    kept: list[dict[str, Any]] = []
    for group in groups:
        identity = (
            str(group.get("group_id") or "")
            or hashlib.sha256(
                json.dumps(group, separators=(",", ":"), sort_keys=True, default=str).encode(
                    "utf-8"
                )
            ).hexdigest()
        )
        if identity in seen:
            continue
        seen.add(identity)
        kept.append(dict(group))
    return kept


def _dedupe(items: Sequence[Mapping[str, Any]], *, key: str) -> list[dict[str, Any]]:
    seen: set[str] = set()
    kept: list[dict[str, Any]] = []
    for item in items:
        identity = str(item.get(key) or "")
        if identity and identity in seen:
            continue
        if identity:
            seen.add(identity)
        kept.append(dict(item))
    return kept


def _revision_conflict_response(
    *,
    session_id: str,
    view_id: str,
    revision: str,
    collections: Sequence[str],
    query_by: str,
    mode: str,
    graph_context: bool,
    max_context_chars: int,
    max_paths: int,
    max_relations: int,
    returned_revisions: set[str],
    warning: str | None = None,
    outcome: str = "revision_conflict",
    raw_chunks: int = 0,
) -> dict[str, Any]:
    revisions = ", ".join(sorted(returned_revisions)) or "missing revision metadata"
    return {
        "response_schema": QUERY_RESPONSE_SCHEMA,
        "session_id": session_id,
        "view_id": view_id,
        "status": "degraded",
        "diagnostics": {
            "outcome": outcome,
            "reason": f"returned revisions: {revisions}",
            "funnel": {**dict.fromkeys(FUNNEL_STAGES, 0), "raw_chunks": raw_chunks},
        },
        "hydradb": {
            "available": True,
            "collections": list(collections),
            "query_by": query_by,
            "mode": mode,
            "graph_context": graph_context,
            "path_ids": [],
            "origin": None,
            "request_id": None,
        },
        "revision": revision,
        "paths": [],
        "relations": [],
        "chunk_id_to_group_ids": {},
        "chunks": [],
        "sources": [],
        "additional_context": [],
        "warnings": [
            warning
            or (
                "HydraDB returned an inconsistent revision slice "
                f"({revisions}); no mixed repository context was exposed."
            )
        ],
        "budget": {
            "max_context_chars": max_context_chars,
            "returned_context_chars": 0,
            "max_paths": max_paths,
            "returned_paths": 0,
            "max_relations": max_relations,
            "returned_relations": 0,
            "truncated": True,
        },
    }


def _ready_outcome(funnel: Mapping[str, int]) -> str:
    """Name the funnel stage that emptied the graph, or report ``ok``.

    A successful HydraDB answer can still produce no graph. Each cause needs a
    different correction, so the panel and the log must not share one sentence.
    """

    if funnel["hops"]:
        return "ok"
    if not funnel["raw_chunks"]:
        return "no_chunks"
    if not funnel["raw_paths"] and not funnel["raw_relations"]:
        return "no_graph_context"
    if not funnel["kept_paths"] and not funnel["kept_relations"]:
        return "all_groups_ungrounded"
    return "no_hops"


def _returned_revisions(
    data: Mapping[str, Any], expected_revision: str | None
) -> tuple[set[str], str | None]:
    raw_chunks = _mapping_list(data.get("chunks"))
    revisions = [
        str(_mapping(chunk.get("metadata")).get("revision_id"))
        for chunk in raw_chunks
        if _mapping(chunk.get("metadata")).get("revision_id")
    ]
    returned = set(revisions)
    target = expected_revision or (next(iter(returned)) if len(returned) == 1 else None)
    return returned, target


def _revision_conflict(data: Mapping[str, Any], expected_revision: str | None) -> bool:
    """Answer whether this response mixes revisions or fails to prove one.

    The service asks before it spends a request on the stored graph, and
    normalization asks again before it exposes anything. Both must apply the same
    rule, so the rule lives here.
    """

    raw_chunks = _mapping_list(data.get("chunks"))
    if not raw_chunks:
        return False
    returned, target = _returned_revisions(data, expected_revision)
    revisions = [
        chunk for chunk in raw_chunks if _mapping(chunk.get("metadata")).get("revision_id")
    ]
    return bool(
        len(revisions) != len(raw_chunks)
        or target is None
        or returned != {target}
        or not _related_data_matches_revision(data, target)
    )


def _related_data_matches_revision(data: Mapping[str, Any], target_revision: str) -> bool:
    """Every card returned beside the chunks must name the same revision."""

    for source in _mapping_list(data.get("sources")):
        if _mapping(source.get("metadata")).get("revision_id") != target_revision:
            return False
    for item in _additional_context(data.get("additional_context")):
        if _mapping(item.get("metadata")).get("revision_id") != target_revision:
            return False
    return True


def _chunk_window_ids(chunks: Sequence[Mapping[str, Any]]) -> set[str]:
    return {str(chunk.get("chunk_uuid")) for chunk in chunks if chunk.get("chunk_uuid")}


def _group_is_grounded(group: Mapping[str, Any], chunk_ids: set[str]) -> bool:
    """Answer whether every chunk this group cites came back in the same response.

    HydraDB graph context reaches neighbors of the retrieved chunks, so a relation
    may cite a chunk outside the returned window. That chunk carries no revision
    proof here, so the group is dropped. It is not evidence of a mixed revision:
    the returned chunks and sources are checked for that separately.
    """

    linked = {str(item) for item in (group.get("source_chunk_ids") or [])}
    if not linked.issubset(chunk_ids):
        return False
    for triplet in (group.get("triplets") or []):
        relation_chunk = _mapping(_mapping(triplet).get("relation")).get("chunk_id")
        if relation_chunk and str(relation_chunk) not in chunk_ids:
            return False
    return True


def _group_relation_ids(group: Mapping[str, Any]) -> set[str]:
    identifiers: set[str] = set()
    for triplet in _mapping_list(group.get("triplets")):
        relation = _mapping(triplet.get("relation"))
        identifier = relation.get("relationship_id") or relation.get("relation_id")
        if identifier:
            identifiers.add(str(identifier))
    return identifiers


def _without_covered_groups(
    groups: Sequence[Mapping[str, Any]], assembled: Sequence[Mapping[str, Any]]
) -> list[Mapping[str, Any]]:
    """Drop groups whose every relation already appears in an assembled path."""

    if not assembled:
        return list(groups)
    covered = [_group_relation_ids(group) for group in assembled]
    kept: list[Mapping[str, Any]] = []
    for group in groups:
        identifiers = _group_relation_ids(group)
        if identifiers and any(identifiers <= item for item in covered):
            continue
        kept.append(group)
    return kept


def _grounded_groups(
    groups: Sequence[Mapping[str, Any]], chunk_ids: set[str]
) -> tuple[list[Mapping[str, Any]], int]:
    kept = [group for group in groups if _group_is_grounded(group, chunk_ids)]
    return kept, len(groups) - len(kept)


def _budget_context(
    chunks: list[dict[str, Any]], additional: list[dict[str, Any]], limit: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int, bool]:
    remaining = limit
    returned_chunks: list[dict[str, Any]] = []
    returned_additional: list[dict[str, Any]] = []
    truncated = False
    for source, destination in ((chunks, returned_chunks), (additional, returned_additional)):
        for item in source:
            content = str(item.get("chunk_content", ""))
            if len(content) <= remaining:
                destination.append(dict(item))
                remaining -= len(content)
                continue
            # The budget bounds exposed text, not grounding. A dropped card also drops
            # the node id, path, and span that anchor a node or an edge, and the view
            # would then show nothing even though HydraDB proved every card. So the
            # card stays and only its content is clipped.
            clipped = dict(item)
            clipped["chunk_content"] = content[:remaining]
            clipped["content_truncated"] = True
            destination.append(clipped)
            remaining = 0
            truncated = True
    return returned_chunks, returned_additional, limit - remaining, truncated


def _additional_context(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, Mapping):
        return [
            {"context_id": str(key), **dict(item)}
            for key, item in value.items()
            if isinstance(item, Mapping)
        ]
    return _mapping_list(value)


def _normalize_chunk(
    chunk: Mapping[str, Any], *, rank: int, group_ids: Mapping[str, Any]
) -> dict[str, Any]:
    metadata = _mapping(chunk.get("metadata"))
    additional = _mapping(chunk.get("additional_metadata"))
    chunk_id = str(chunk.get("chunk_uuid") or chunk.get("context_id") or "")
    span = _source_span(additional)
    return {
        "rank": rank,
        "chunk_id": chunk_id,
        "source_id": str(chunk.get("id") or ""),
        "content": str(chunk.get("chunk_content") or ""),
        "content_truncated": bool(chunk.get("content_truncated", False)),
        "title": str(chunk.get("source_title") or ""),
        "source_type": str(chunk.get("source_type") or ""),
        "score": chunk.get("relevancy_score"),
        "path": additional.get("path"),
        "span": span,
        "revision": metadata.get("revision_id"),
        "repository_id": metadata.get("repository_id"),
        "entity_kind": metadata.get("entity_kind"),
        "language": metadata.get("language"),
        "relation_quality": metadata.get("relation_quality"),
        "node_id": additional.get("node_id"),
        "logical_id": additional.get("logical_id"),
        "qualified_name": additional.get("qualified_name"),
        "signature": additional.get("signature"),
        "content_hash": additional.get("content_hash"),
        "parser": additional.get("parser"),
        "parser_version": additional.get("parser_version"),
        "is_generated": bool(metadata.get("is_generated", False)),
        "group_ids": [str(item) for item in group_ids.get(chunk_id, [])],
    }


def _normalize_source(source: Mapping[str, Any]) -> dict[str, Any]:
    metadata = _mapping(source.get("metadata"))
    additional = _mapping(source.get("additional_metadata"))
    return {
        "source_id": str(source.get("id") or ""),
        "title": str(source.get("title") or ""),
        "source_type": str(source.get("type") or ""),
        "chunk_ids": [str(item) for item in source.get("chunk_ids", [])],
        "path": additional.get("path"),
        "span": _source_span(additional),
        "revision": metadata.get("revision_id"),
        "repository_id": metadata.get("repository_id"),
        "entity_kind": metadata.get("entity_kind"),
        "language": metadata.get("language"),
        "relation_quality": metadata.get("relation_quality"),
        "node_id": additional.get("node_id"),
        "logical_id": additional.get("logical_id"),
        "qualified_name": additional.get("qualified_name"),
        "signature": additional.get("signature"),
        "content_hash": additional.get("content_hash"),
        "parser": additional.get("parser"),
        "parser_version": additional.get("parser_version"),
        "is_generated": bool(metadata.get("is_generated", False)),
    }


def _normalize_sources(
    sources: Sequence[Mapping[str, Any]], chunks: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    chunks_by_source: dict[str, list[Mapping[str, Any]]] = {}
    for chunk in chunks:
        source_id = str(chunk.get("id") or "")
        if source_id:
            chunks_by_source.setdefault(source_id, []).append(chunk)

    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_source in sources:
        source_id = str(raw_source.get("id") or "")
        source_chunks = chunks_by_source.get(source_id, [])
        first_chunk = source_chunks[0] if source_chunks else {}
        metadata = {
            **dict(_mapping(first_chunk.get("metadata"))),
            **dict(_mapping(raw_source.get("metadata"))),
        }
        additional = {
            **dict(_mapping(first_chunk.get("additional_metadata"))),
            **dict(_mapping(raw_source.get("additional_metadata"))),
        }
        enriched = {
            **dict(raw_source),
            "title": raw_source.get("title") or first_chunk.get("source_title"),
            "type": raw_source.get("type") or first_chunk.get("source_type"),
            "metadata": metadata,
            "additional_metadata": additional,
            "chunk_ids": [
                str(chunk.get("chunk_uuid")) for chunk in source_chunks if chunk.get("chunk_uuid")
            ],
        }
        normalized.append(_normalize_source(enriched))
        seen.add(source_id)

    # HydraDB normally returns one source record per chunk source. Preserve
    # grounding if a response omits that summary record but still returns chunks.
    for source_id, source_chunks in chunks_by_source.items():
        if source_id in seen:
            continue
        first_chunk = source_chunks[0]
        normalized.append(
            _normalize_source(
                {
                    "id": source_id,
                    "title": first_chunk.get("source_title"),
                    "type": first_chunk.get("source_type"),
                    "metadata": first_chunk.get("metadata"),
                    "additional_metadata": first_chunk.get("additional_metadata"),
                    "chunk_ids": [
                        str(chunk.get("chunk_uuid"))
                        for chunk in source_chunks
                        if chunk.get("chunk_uuid")
                    ],
                }
            )
        )
    return normalized


def _normalize_groups(
    groups: Sequence[Mapping[str, Any]],
    *,
    group_limit: int,
    hop_limit: int,
    per_group_hop_limit: int | None,
    entity_ids: Mapping[str, str],
    byog_chunk_ids: set[str],
) -> tuple[list[dict[str, Any]], int, bool]:
    normalized: list[dict[str, Any]] = []
    used_hops = 0
    truncated = len(groups) > group_limit
    for rank, group in enumerate(groups[:group_limit], start=1):
        raw_hops = _mapping_list(group.get("triplets"))
        available = max(0, hop_limit - used_hops)
        group_available = (
            min(available, per_group_hop_limit) if per_group_hop_limit is not None else available
        )
        selected = raw_hops[:group_available]
        if len(selected) < len(raw_hops):
            truncated = True
        if not selected:
            if raw_hops:
                break
            continue
        hops = [
            _normalize_hop(
                item,
                index=index,
                entity_ids=entity_ids,
                byog_chunk_ids=byog_chunk_ids,
            )
            for index, item in enumerate(selected, start=1)
        ]
        normalized.append(
            {
                "path_id": _stable_path_id(group, hops),
                "rank": rank,
                "score": group.get("relevancy_score"),
                "summary": str(group.get("combined_context") or ""),
                "chunk_ids": [str(item) for item in group.get("source_chunk_ids", [])],
                "hops": hops,
                **({"origin": group["origin"]} if group.get("origin") else {}),
            }
        )
        used_hops += len(hops)
        if used_hops >= hop_limit:
            if rank < min(len(groups), group_limit):
                truncated = True
            break
    return normalized, used_hops, truncated


def _normalize_hop(
    triplet: Mapping[str, Any],
    *,
    index: int,
    entity_ids: Mapping[str, str],
    byog_chunk_ids: set[str] | None = None,
) -> dict[str, Any]:
    relation = _mapping(triplet.get("relation"))
    chunk_id = relation.get("chunk_id")
    origin = relation.get("origin")
    if (
        origin is None
        and chunk_id is not None
        and str(chunk_id) in (byog_chunk_ids or set())
        and has_byog_envelope_marker(relation.get("context"))
    ):
        # HydraDB v2 currently omits relation origin from live query results.
        # The verified sync manifest proves that this source carried BYOG; the
        # ProductView layer still fully validates the evidence envelope.
        origin = "byog"
    return {
        "hop": index,
        "source": _normalize_entity(_mapping(triplet.get("source")), entity_ids),
        "relation": {
            "id": relation.get("relationship_id"),
            "predicate": relation.get("canonical_predicate") or relation.get("raw_predicate"),
            "raw_predicate": relation.get("raw_predicate"),
            "context": relation.get("context"),
            "confidence": relation.get("confidence"),
            "origin": origin,
            "chunk_id": chunk_id,
        },
        "target": _normalize_entity(_mapping(triplet.get("target")), entity_ids),
    }


def _normalize_entity(entity: Mapping[str, Any], entity_ids: Mapping[str, str]) -> dict[str, Any]:
    identifier = str(entity.get("identifier") or "")
    hydradb_id = str(entity.get("entity_id") or "")
    normalized = {
        "id": entity_ids.get(identifier) or identifier or hydradb_id,
        "logical_id": identifier or None,
        "hydradb_entity_id": hydradb_id or None,
        "name": str(entity.get("name") or ""),
        "kind": str(entity.get("type") or "UNKNOWN"),
        "namespace": entity.get("namespace"),
    }
    role = entity.get("role")
    if role in {"entry", "step", "target"}:
        normalized["role"] = role
    return normalized


def _entity_id_lookup(chunks: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for chunk in chunks:
        additional = _mapping(chunk.get("additional_metadata"))
        node_id = additional.get("node_id")
        if not node_id:
            continue
        node_id = str(node_id)
        lookup[node_id] = node_id
        logical_id = additional.get("logical_id")
        if logical_id:
            lookup[str(logical_id)] = node_id
    return lookup


def _stable_path_id(group: Mapping[str, Any], hops: Sequence[Mapping[str, Any]]) -> str:
    group_id = group.get("group_id")
    if group_id:
        return str(group_id)
    relation_ids = [str(hop["relation"].get("id") or "") for hop in hops]
    joined = "-".join(item for item in relation_ids if item)
    if joined:
        return joined
    encoded = json.dumps(hops, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return f"path_{hashlib.sha256(encoded).hexdigest()[:24]}"


def _source_span(additional: Mapping[str, Any]) -> dict[str, int] | None:
    keys = ("start_line", "start_column", "end_line", "end_column")
    if not all(additional.get(key) is not None for key in keys):
        return None
    try:
        return {key: int(additional[key]) for key in keys}
    except (TypeError, ValueError):
        return None


def _revision_from_chunks(chunks: Sequence[Mapping[str, Any]]) -> str | None:
    for chunk in chunks:
        revision = chunk.get("revision")
        if revision:
            return str(revision)
    return None


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _mapping_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]
