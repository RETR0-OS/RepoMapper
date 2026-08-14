"""HydraDB-backed publication and retrieval for deltas and shared lenses."""

from __future__ import annotations

import json
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from threading import Lock, RLock
from typing import Any

from pydantic import ValidationError

from .analyzer import analyze_repository
from .cards import SourceCard, build_app_knowledge, build_graph_payload, build_source_cards
from .checkpoints import CheckpointSlot, CheckpointStore
from .diff import compare_graphs
from .discovery import discover_files
from .events import EventBus
from .hydradb import HydraDBClient, HydraDBError, response_data
from .models import GraphEdge, GraphNode
from .query import QUERY_RESPONSE_SCHEMA, QueryRequest, QueryService, normalize_query_response
from .views import ViewDepth, ViewMode, ViewStore, build_product_view


class EvolutionStatus(StrEnum):
    IDLE = "idle"
    CAPTURING = "capturing"
    PUBLISHING = "publishing"
    READY = "ready"
    UNAVAILABLE = "unavailable"
    INDETERMINATE = "indeterminate"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class EvolutionState:
    status: EvolutionStatus = EvolutionStatus.IDLE
    operation: str | None = None
    detail: str | None = None


class EvolutionService:
    """Coordinates local deterministic artifacts with one HydraDB collection.

    Checkpoints are accepted only as inputs to publication. Compare and lens
    retrieval always call HydraDB and never read checkpoint files.
    """

    def __init__(
        self,
        client: HydraDBClient,
        *,
        repository_id: str,
        repository_root: Any,
        checkpoints: CheckpointStore,
        views: ViewStore,
        current_queries: QueryService,
        events: EventBus | None = None,
        verified_revision: Callable[[], str | None] | None = None,
        current_state_unsafe: Callable[[], bool] | None = None,
        snapshot_verifier: Callable[..., bool] | None = None,
        batch_size: int = 25,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        if client.config.collection == client.config.evolution_collection:
            raise ValueError("Evolution collection must be separate from current")
        self.client = client
        self.repository_id = repository_id
        self.repository_root = repository_root
        self.checkpoints = checkpoints
        self.views = views
        self.current_queries = current_queries
        self.events = events or EventBus()
        self._verified_revision = verified_revision or (lambda: None)
        self._current_state_unsafe = current_state_unsafe or (lambda: False)
        self._snapshot_verifier = snapshot_verifier or (lambda _cards, **_kwargs: False)
        self.batch_size = batch_size
        self._sleep = sleep
        self._monotonic = monotonic
        self._operation_lock = Lock()
        self._state_lock = RLock()
        self._state = EvolutionState()
        self._refresh_views: OrderedDict[str, str] = OrderedDict()

    @property
    def status(self) -> dict[str, Any]:
        with self._state_lock:
            state = self._state
        return {
            "status": state.status.value,
            "operation": state.operation,
            "detail": state.detail,
            "hydradb_available": self.client.configured,
            "collection": self.client.config.evolution_collection,
        }

    def capture_checkpoint(
        self,
        slot: CheckpointSlot | str,
        *,
        revision_id: str,
    ) -> dict[str, Any]:
        selected = CheckpointSlot(slot)
        if not revision_id.strip():
            raise ValueError("revision_id must not be blank")
        ready_revision = self._verified_revision()
        if self._current_state_unsafe() or ready_revision != revision_id:
            raise ValueError(
                "Checkpoint revision must equal the currently verified HydraDB revision"
            )
        with self._operation_lock:
            self._set_state(EvolutionStatus.CAPTURING, "capture_checkpoint")
            try:
                discovery = discover_files(self.repository_root)
                graph = analyze_repository(
                    self.repository_root,
                    repository_id=self.repository_id,
                    revision_id=revision_id,
                    discovery=discovery,
                )
                cards = build_source_cards(graph, self.repository_root)
                if not self._snapshot_verifier(cards, revision_id=revision_id):
                    raise ValueError(
                        "Workspace analysis does not match the verified HydraDB snapshot"
                    )
                reference = self.checkpoints.capture(selected, graph)
            except (OSError, ValueError) as exc:
                self._set_state(EvolutionStatus.FAILED, "capture_checkpoint", str(exc))
                raise
            self._set_state(EvolutionStatus.READY, "capture_checkpoint")
        return {
            "status": "captured",
            "operation": "capture_checkpoint",
            "slot": selected.value,
            "repository_id": self.repository_id,
            "revision_id": revision_id,
            "checkpoint_id": f"checkpoint_{selected.value}_{reference.graph_hash[:24]}",
            "node_count": len(graph.nodes),
            "edge_count": len(graph.edges),
            "writes_performed": True,
            "local_writes_performed": True,
            "hydradb_writes_performed": False,
            "warnings": [],
        }

    def publish_delta(
        self,
        *,
        before_revision_id: str,
        after_revision_id: str,
        confirm: bool = False,
    ) -> dict[str, Any]:
        before, after = self.checkpoints.load_pair(
            before_revision_id=before_revision_id,
            after_revision_id=after_revision_id,
        )
        delta = compare_graphs(before, after)
        from .evolution import build_change_event_cards

        cards = build_change_event_cards(delta, before, after)
        response = self._write_cards(
            cards,
            operation="publish_delta",
            confirm=confirm,
        )
        checkpoints_cleared = False
        if response["status"] == "ready":
            try:
                self.checkpoints.clear()
                checkpoints_cleared = True
            except (OSError, ValueError) as exc:
                response["warnings"].append(
                    f"Delta is ready in HydraDB, but local checkpoints were not cleared: {exc}"
                )
        return {
            **response,
            "repository_id": self.repository_id,
            "before_revision_id": before_revision_id,
            "after_revision_id": after_revision_id,
            "change_counts": _change_counts(delta.model_dump(mode="json")),
            "checkpoints_cleared": checkpoints_cleared,
        }

    def save_lens(
        self,
        *,
        name: str,
        purpose: str,
        view_id: str,
        notes: str | None = None,
        confirm: bool = False,
    ) -> dict[str, Any]:
        stored = self._grounded_view(view_id)
        view = stored["view"]
        from .evolution import build_system_lens, build_system_lens_card

        anchor_node_ids, edge_ids = _lens_selection(view, stored["query"])
        lens = build_system_lens(
            repository_id=self.repository_id,
            name=name,
            purpose=purpose,
            view=view,
            anchor_node_ids=anchor_node_ids,
            edge_ids=edge_ids,
            notes=notes,
        )
        card = build_system_lens_card(lens)
        response = self._write_cards((card,), operation="save_lens", confirm=confirm)
        return {
            **response,
            "lens_id": str(lens.lens_id),
            "source_id": card.source_id,
            "name": lens.name,
            "saved_revision_id": lens.saved_revision_id,
            "anchor_node_ids": list(lens.anchor_node_ids),
            "edge_ids": [str(item.edge_id) for item in lens.baseline_hops],
            "ownership": "shared",
        }

    def accept_lens(
        self,
        *,
        lens_id: str,
        view_id: str,
        confirm: bool = False,
    ) -> dict[str, Any]:
        with self._state_lock:
            bound_lens_id = self._refresh_views.get(view_id)
        if bound_lens_id != lens_id:
            return _invalid_operation(
                self.client,
                operation="accept_lens",
                warning=(
                    "Accept drift requires the opaque current refresh view returned for this "
                    "shared lens."
                ),
            )
        opened = self._query(
            question=f"Open the shared system lens identified by {lens_id}.",
            entity_kind="SYSTEM_LENS",
            revision="current",
            metadata_filters={},
            max_results=12,
            max_relations=50,
            session_id=None,
            record_lookup=lens_id,
        )
        if opened["status"] != "ready" or len(opened.get("records", [])) != 1:
            return {
                "status": opened["status"],
                "operation": "accept_lens",
                "lens_id": lens_id,
                "source_ids": [],
                "source_count": 0,
                "writes_performed": False,
                "hydradb": opened["hydradb"],
                "warnings": opened["warnings"],
            }
        from .evolution import SystemLensRecord, build_system_lens, build_system_lens_card

        prior = SystemLensRecord.model_validate(opened["records"][0])
        if prior.lens_id != lens_id:
            return _invalid_operation(
                self.client,
                operation="accept_lens",
                warning="HydraDB returned a different shared lens; no baseline was updated.",
            )
        stored = self._grounded_view(view_id)
        view = stored["view"]
        anchor_node_ids, edge_ids = _lens_selection(view, stored["query"])
        updated = build_system_lens(
            repository_id=self.repository_id,
            name=prior.name,
            purpose=prior.purpose,
            view=view,
            anchor_node_ids=anchor_node_ids,
            edge_ids=edge_ids,
            notes=prior.notes,
        )
        if updated.lens_id != prior.lens_id:
            raise ValueError("Updated shared lens identity changed unexpectedly")
        card = build_system_lens_card(updated)
        response = self._write_cards((card,), operation="accept_lens", confirm=confirm)
        if response["status"] == "ready":
            with self._state_lock:
                self._refresh_views.pop(view_id, None)
        return {
            **response,
            "lens_id": updated.lens_id,
            "source_id": card.source_id,
            "name": updated.name,
            "previous_revision_id": prior.saved_revision_id,
            "saved_revision_id": updated.saved_revision_id,
            "anchor_node_ids": list(updated.anchor_node_ids),
            "edge_ids": [item.edge_id for item in updated.baseline_hops],
            "ownership": "shared",
        }

    def compare(
        self,
        *,
        before_revision_id: str,
        after_revision_id: str,
        focus: str | None = None,
        max_changes: int = 50,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        focus_text = f" Focus on {focus}." if focus else ""
        return self._query(
            question=(
                f"Retrieve stored graph change events from revision {before_revision_id} "
                f"to {after_revision_id}.{focus_text}"
            ),
            entity_kind="CHANGE_EVENT",
            revision=after_revision_id,
            metadata_filters={
                "before_revision_id": before_revision_id,
                "after_revision_id": after_revision_id,
            },
            max_results=min(50, max(1, max_changes)),
            max_relations=max_changes,
            session_id=session_id,
            record_lookup=None,
        )

    def open_lens(
        self,
        *,
        lens: str,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        saved = self._query(
            question=f"Open the shared system lens named or identified by {lens}.",
            entity_kind="SYSTEM_LENS",
            revision="current",
            metadata_filters={},
            max_results=12,
            max_relations=50,
            session_id=session_id,
            record_lookup=lens,
        )
        if saved["status"] != "ready" or len(saved.get("records", [])) != 1:
            return saved
        from .evolution import SystemLensRecord, build_system_lens, classify_lens_drift

        record = SystemLensRecord.model_validate(saved["records"][0])
        anchor_names = {
            item.node_id: item.qualified_name
            for item in record.entities
            if item.node_id in record.anchor_node_ids
        }
        question = (
            f"Retrieve the current exact repository path for: {record.purpose}. "
            f"Required saved anchors: {', '.join(anchor_names.values())}."
        )
        current = self.current_queries.repository_query(
            QueryRequest(
                question=question,
                revision="current",
                max_results=25,
                max_context_chars=15_000,
                max_paths=3,
                max_relations=24,
                max_hops_per_path=24,
            )
        )
        current["evolution_hydradb"] = saved["hydradb"]
        current["evolution_chunks"] = saved["chunks"]
        current["lens"] = record.model_dump(mode="json")
        current["warnings"] = [*saved["warnings"], *current["warnings"]]
        if current["status"] != "ready":
            current["drift"] = {
                "kind": "unresolved",
                "explanation": "Current HydraDB repository retrieval was unavailable or degraded.",
            }
            return current
        view = build_product_view(
            current,
            mode=ViewMode.PRESERVE,
            depth=ViewDepth.SYMBOL,
            max_nodes=25,
            max_edges=24,
        )
        try:
            anchor_node_ids, edge_ids = _lens_selection(view, current)
            candidate = build_system_lens(
                repository_id=self.repository_id,
                name=record.name,
                purpose=record.purpose,
                view=view,
                anchor_node_ids=anchor_node_ids,
                edge_ids=edge_ids,
                notes=record.notes,
            )
            drift = classify_lens_drift(record, candidate)
        except (ValidationError, ValueError) as exc:
            current["drift"] = {
                "kind": "unresolved",
                "explanation": f"Current exact path could not be grounded: {exc}",
            }
            return current
        current["drift"] = drift.model_dump(mode="json")
        self.views.put(view, current)
        with self._state_lock:
            self._refresh_views[str(current["view_id"])] = record.lens_id
            self._refresh_views.move_to_end(str(current["view_id"]))
            while len(self._refresh_views) > 50:
                self._refresh_views.popitem(last=False)
        return current

    def _query(
        self,
        *,
        question: str,
        entity_kind: str,
        revision: str,
        metadata_filters: Mapping[str, Any],
        max_results: int,
        max_relations: int,
        session_id: str | None,
        record_lookup: str | None,
    ) -> dict[str, Any]:
        session = session_id or f"session_{uuid.uuid4().hex}"
        view_id = f"view_{uuid.uuid4().hex}"
        filters = {
            "repository_id": self.repository_id,
            "entity_kind": entity_kind,
            **dict(metadata_filters),
        }
        metadata = {
            "collections": [self.client.config.evolution_collection],
            "query_by": "hybrid",
            "mode": "thinking",
            "graph_context": True,
            "max_results": max_results,
        }
        self.events.emit(
            "query_started",
            session_id=session,
            revision_id=revision,
            view_id=view_id,
            hydradb_query_metadata=metadata,
        )
        try:
            raw = self.client.query_evolution(
                query=question,
                query_by="hybrid",
                mode="thinking",
                graph_context=True,
                max_results=max_results,
                metadata_filters=filters,
            )
        except HydraDBError as exc:
            return _empty_query(
                session_id=session,
                view_id=view_id,
                revision=revision,
                client=self.client,
                status="unavailable",
                warning=str(exc),
                max_results=max_results,
                max_relations=max_relations,
            )
        result = normalize_query_response(
            raw,
            session_id=session,
            view_id=view_id,
            revision=revision,
            collections=[self.client.config.evolution_collection],
            query_by="hybrid",
            mode="thinking",
            graph_context=True,
            max_context_chars=15_000,
            max_paths=min(10, max_results),
            max_relations=max_relations,
            expected_revision=revision if revision != "current" else None,
            expected_entity_kind=entity_kind,
        )
        result["response_schema"] = QUERY_RESPONSE_SCHEMA
        result.setdefault("records", [])
        result["hydradb"]["cross_collection_traversal"] = False
        result["hydradb"]["memory_used"] = False
        if result["status"] == "ready":
            try:
                records = _validated_records(
                    raw,
                    entity_kind=entity_kind,
                    repository_id=self.repository_id,
                    revision=revision,
                    lookup=record_lookup,
                    before_revision_id=metadata_filters.get("before_revision_id"),
                    after_revision_id=metadata_filters.get("after_revision_id"),
                )
            except (ValidationError, ValueError, json.JSONDecodeError) as exc:
                result = _degrade_record_result(
                    result,
                    f"HydraDB evolution records were incomplete or invalid: {exc}",
                )
            else:
                result["records"] = records
            result["warnings"].append(
                "Result is limited to the evolution collection; no cross-collection "
                "repository traversal was performed."
            )
        return result

    def _grounded_view(self, view_id: str) -> dict[str, Any]:
        stored = self.views.get(view_id)
        if stored is None:
            raise ValueError("The bounded HydraDB view is no longer available")
        view = stored.get("view")
        query = stored.get("query")
        if not isinstance(view, Mapping) or not isinstance(query, Mapping):
            raise ValueError("Stored view is invalid")
        hydradb = view.get("hydradb")
        if (
            query.get("status") != "ready"
            or not isinstance(hydradb, Mapping)
            or not hydradb.get("available")
        ):
            raise ValueError("A shared lens requires an available HydraDB-backed view")
        revision = str(view.get("revision_id") or "")
        if not revision or revision == "current" or query.get("revision") != revision:
            raise ValueError("A shared lens requires one verified revision")
        nodes = view.get("nodes")
        edges = view.get("edges")
        if not isinstance(nodes, Sequence) or not nodes or not isinstance(edges, Sequence):
            raise ValueError("A shared lens requires grounded nodes")
        validated_nodes = []
        for item in nodes:
            try:
                node = GraphNode.model_validate(item)
            except ValidationError as exc:
                raise ValueError("Stored lens view contains an invalid node") from exc
            if node.kind.value != "SYSTEM_LENS" and node.revision_id != revision:
                raise ValueError("Stored lens view mixes revisions")
            validated_nodes.append(node)
        node_ids = {node.id for node in validated_nodes}
        for item in edges:
            try:
                edge = GraphEdge.model_validate(item)
            except ValidationError as exc:
                raise ValueError("Stored lens view contains an invalid edge") from exc
            if (
                edge.revision_id != revision
                or edge.source_id not in node_ids
                or edge.target_id not in node_ids
            ):
                raise ValueError("Stored lens view contains an ungrounded or mixed edge")
            if edge.quality.value == "exact" and not edge.evidence:
                raise ValueError("Stored lens view contains an exact edge without evidence")
        return {"view": dict(view), "query": dict(query)}

    def _write_cards(
        self,
        cards: Sequence[SourceCard],
        *,
        operation: str,
        confirm: bool,
    ) -> dict[str, Any]:
        source_ids = [card.source_id for card in cards]
        if not source_ids:
            raise ValueError("Evolution publication requires at least one source card")
        base = {
            "operation": operation,
            "source_ids": source_ids,
            "source_count": len(source_ids),
            "writes_performed": False,
            "hydradb": self._hydradb_status(False),
            "warnings": [],
        }
        if not confirm:
            return {**base, "status": "preview"}
        if not self.client.configured:
            return {
                **base,
                "status": "unavailable",
                "warnings": [
                    "HydraDB credentials are unavailable; no evolution records were written."
                ],
            }
        with self._operation_lock:
            self._set_state(EvolutionStatus.PUBLISHING, operation)
            attempted = False
            try:
                for batch in _batches(cards, self.batch_size):
                    attempted = True
                    response = response_data(
                        self.client.ingest_evolution(
                            app_knowledge=build_app_knowledge(batch),
                            graph_payload=build_graph_payload(batch),
                            upsert=True,
                        )
                    )
                    returned = {str(item) for item in response.get("ids", [])}
                    expected = {card.source_id for card in batch}
                    if returned != expected:
                        raise _IndeterminateWrite("HydraDB did not confirm every source ID")
                failed = self._wait_until_completed(source_ids)
                if failed:
                    raise _IndeterminateWrite(
                        "HydraDB did not complete every evolution source: "
                        + ", ".join(sorted(failed))
                    )
            except _IndeterminateWrite as exc:
                self._set_state(EvolutionStatus.INDETERMINATE, operation, str(exc))
                return {
                    **base,
                    "status": "indeterminate",
                    "writes_performed": attempted,
                    "hydradb": self._hydradb_status(True),
                    "warnings": [str(exc)],
                }
            except HydraDBError as exc:
                status = "indeterminate" if attempted else "unavailable"
                self._set_state(
                    EvolutionStatus.INDETERMINATE if attempted else EvolutionStatus.UNAVAILABLE,
                    operation,
                    str(exc),
                )
                return {
                    **base,
                    "status": status,
                    "writes_performed": attempted,
                    "hydradb": self._hydradb_status(attempted),
                    "warnings": [str(exc)],
                }
            self._set_state(EvolutionStatus.READY, operation)
        return {
            **base,
            "status": "ready",
            "writes_performed": True,
            "hydradb": self._hydradb_status(True),
        }

    def _wait_until_completed(self, source_ids: Sequence[str]) -> dict[str, str]:
        deadline = self._monotonic() + self.client.config.poll_timeout_seconds
        while True:
            statuses: dict[str, Mapping[str, Any]] = {}
            for index in range(0, len(source_ids), self.batch_size):
                data = response_data(
                    self.client.status(source_ids[index : index + self.batch_size])
                )
                statuses.update(
                    {
                        str(item.get("id")): item
                        for item in data.get("statuses", [])
                        if isinstance(item, Mapping)
                    }
                )
            missing = set(source_ids).difference(statuses)
            if missing:
                return {item: "status missing" for item in missing}
            failed = {
                source_id: str(item.get("error_code") or "indexing failed")
                for source_id, item in statuses.items()
                if item.get("indexing_status") == "errored" or item.get("success") is False
            }
            if failed:
                return failed
            if all(item.get("indexing_status") == "completed" for item in statuses.values()):
                return {}
            if self._monotonic() >= deadline:
                return {
                    source_id: "indexing timed out"
                    for source_id, item in statuses.items()
                    if item.get("indexing_status") != "completed"
                }
            self._sleep(self.client.config.poll_interval_seconds)

    def _hydradb_status(self, write_attempted: bool) -> dict[str, Any]:
        return {
            "available": self.client.configured,
            "collections": [self.client.config.evolution_collection],
            "write_attempted": write_attempted,
            "cross_collection_traversal": False,
            "memory_used": False,
        }

    def _set_state(
        self,
        status: EvolutionStatus,
        operation: str,
        detail: str | None = None,
    ) -> None:
        with self._state_lock:
            self._state = EvolutionState(status=status, operation=operation, detail=detail)


class _IndeterminateWrite(RuntimeError):
    pass


def _empty_query(
    *,
    session_id: str,
    view_id: str,
    revision: str,
    client: HydraDBClient,
    status: str,
    warning: str,
    max_results: int,
    max_relations: int,
) -> dict[str, Any]:
    return {
        "response_schema": QUERY_RESPONSE_SCHEMA,
        "session_id": session_id,
        "view_id": view_id,
        "status": status,
        "hydradb": {
            "available": False,
            "collections": [client.config.evolution_collection],
            "query_by": "hybrid",
            "mode": "thinking",
            "graph_context": True,
            "path_ids": [],
            "origin": None,
            "request_id": None,
            "cross_collection_traversal": False,
            "memory_used": False,
        },
        "revision": revision,
        "paths": [],
        "relations": [],
        "chunk_id_to_group_ids": {},
        "chunks": [],
        "sources": [],
        "additional_context": [],
        "warnings": [warning],
        "budget": {
            "max_context_chars": 15_000,
            "returned_context_chars": 0,
            "max_paths": min(10, max_results),
            "returned_paths": 0,
            "max_relations": max_relations,
            "returned_relations": 0,
            "truncated": False,
        },
    }


def _batches(items: Sequence[SourceCard], size: int) -> list[list[SourceCard]]:
    return [list(items[index : index + size]) for index in range(0, len(items), size)]


def _change_counts(delta: Mapping[str, Any]) -> dict[str, int]:
    fields = (
        "added_node_ids",
        "removed_node_ids",
        "modified_nodes",
        "renamed_nodes",
        "added_edge_ids",
        "removed_edge_ids",
        "evidence_moves",
        "relation_quality_changes",
        "structural_warnings",
    )
    return {field: len(delta.get(field, [])) for field in fields}


def _lens_selection(
    view: Mapping[str, Any], query: Mapping[str, Any]
) -> tuple[list[str], list[str]]:
    exact_edges = {
        str(item["id"]): item
        for item in view.get("edges", [])
        if isinstance(item, Mapping) and item.get("quality") == "exact" and item.get("id")
    }
    by_hydra_id = {
        str(attributes["hydradb_relationship_id"]): edge
        for edge in exact_edges.values()
        for attributes in (
            edge.get("attributes") if isinstance(edge.get("attributes"), Mapping) else {},
        )
        if attributes.get("hydradb_relationship_id")
    }
    for path in query.get("paths", []):
        if not isinstance(path, Mapping):
            continue
        selected: list[Mapping[str, Any]] = []
        endpoints: list[tuple[str, str]] = []
        for hop in path.get("hops", [])[:24]:
            if not isinstance(hop, Mapping):
                selected = []
                break
            relation = hop.get("relation")
            if not isinstance(relation, Mapping):
                selected = []
                break
            returned_id = str(relation.get("id") or "")
            edge = exact_edges.get(returned_id) or by_hydra_id.get(returned_id)
            if edge is None:
                selected = []
                break
            selected.append(edge)
            endpoints.append((str(edge["source_id"]), str(edge["target_id"])))
        if not selected:
            continue
        if any(
            endpoints[index][1] != endpoints[index + 1][0] for index in range(len(endpoints) - 1)
        ):
            continue
        anchors = list(dict.fromkeys((endpoints[0][0], endpoints[-1][1])))
        return anchors, [str(edge["id"]) for edge in selected]
    raise ValueError("A shared lens requires one connected exact HydraDB path")


def _validated_records(
    response: Mapping[str, Any],
    *,
    entity_kind: str,
    repository_id: str,
    revision: str,
    lookup: str | None,
    before_revision_id: Any,
    after_revision_id: Any,
) -> list[dict[str, Any]]:
    from .evolution import (
        CHANGE_EVENT_PAGE_SCHEMA,
        CHANGE_EVENT_SCHEMA,
        SYSTEM_LENS_SCHEMA,
        ChangeEventPage,
        ChangeEventRecord,
        ChangeEventSummary,
        SystemLensRecord,
    )

    chunks = response_data(response).get("chunks", [])
    if not isinstance(chunks, Sequence) or isinstance(chunks, (str, bytes)):
        raise ValueError("chunks are not a sequence")
    parsed: list[tuple[Mapping[str, Any], Mapping[str, Any], Any]] = []
    for chunk in chunks:
        if not isinstance(chunk, Mapping):
            raise ValueError("chunk is not an object")
        metadata = chunk.get("metadata")
        additional = chunk.get("additional_metadata")
        if not isinstance(metadata, Mapping) or not isinstance(additional, Mapping):
            raise ValueError("evolution chunk metadata is missing")
        if (
            metadata.get("repository_id") != repository_id
            or metadata.get("entity_kind") != entity_kind
        ):
            raise ValueError("evolution chunk does not match the requested record kind")
        record_json = additional.get("record_json")
        if not isinstance(record_json, str):
            raise ValueError("evolution chunk has no machine-readable record")
        parsed.append((metadata, additional, json.loads(record_json)))
    if not parsed:
        return []
    if entity_kind == "SYSTEM_LENS":
        lenses = []
        for metadata, additional, payload in parsed:
            if (
                metadata.get("record_schema") != SYSTEM_LENS_SCHEMA
                or additional.get("record_schema") != SYSTEM_LENS_SCHEMA
                or additional.get("record_kind") != "system_lens"
            ):
                raise ValueError("system lens schema metadata is invalid")
            lens = SystemLensRecord.model_validate(payload)
            if lens.repository_id != repository_id:
                raise ValueError("system lens belongs to another repository")
            lenses.append(lens)
        matching = [
            lens
            for lens in lenses
            if lookup is None or lens.lens_id == lookup or lens.name.casefold() == lookup.casefold()
        ]
        if len(matching) != 1:
            raise ValueError("HydraDB did not return exactly one matching shared lens")
        return [matching[0].model_dump(mode="json")]

    summaries = []
    pages = []
    for metadata, additional, payload in parsed:
        record_kind = additional.get("record_kind")
        if record_kind == "change_event_summary":
            if (
                metadata.get("record_schema") != CHANGE_EVENT_SCHEMA
                or additional.get("record_schema") != CHANGE_EVENT_SCHEMA
            ):
                raise ValueError("change summary schema metadata is invalid")
            summaries.append(ChangeEventSummary.model_validate(payload))
        elif record_kind == "change_event_page":
            if (
                metadata.get("record_schema") != CHANGE_EVENT_PAGE_SCHEMA
                or additional.get("record_schema") != CHANGE_EVENT_PAGE_SCHEMA
            ):
                raise ValueError("change page schema metadata is invalid")
            pages.append(ChangeEventPage.model_validate(payload))
        else:
            raise ValueError("unknown change-event record kind")
    if len(summaries) != 1:
        raise ValueError("HydraDB did not return exactly one change-event summary")
    summary = summaries[0]
    ordered = sorted(pages, key=lambda item: item.page_index)
    expected_indices = list(range(1, summary.page_count + 1))
    if (
        [item.page_index for item in ordered] != expected_indices
        or summary.fact_count != len(ordered)
        or any(
            item.event_id != summary.event_id
            or item.repository_id != summary.repository_id
            or item.before_revision_id != summary.before_revision_id
            or item.after_revision_id != summary.after_revision_id
            or item.page_count != summary.page_count
            for item in ordered
        )
    ):
        raise ValueError("change-event pages are incomplete or inconsistent")
    if (
        summary.repository_id != repository_id
        or summary.before_revision_id != before_revision_id
        or summary.after_revision_id != after_revision_id
        or (revision != "current" and summary.after_revision_id != revision)
    ):
        raise ValueError("change event does not match the requested revisions")
    event = ChangeEventRecord(
        event_id=summary.event_id,
        repository_id=summary.repository_id,
        before_revision_id=summary.before_revision_id,
        after_revision_id=summary.after_revision_id,
        facts=tuple(item.fact for item in ordered),
        structural_warnings=summary.structural_warnings,
        lens_impact_status=summary.lens_impact_status,
        affected_lens_ids=summary.affected_lens_ids,
    )
    return [event.model_dump(mode="json")]


def _degrade_record_result(result: dict[str, Any], warning: str) -> dict[str, Any]:
    result["status"] = "degraded"
    for key in (
        "paths",
        "relations",
        "chunks",
        "sources",
        "additional_context",
    ):
        result[key] = []
    result["chunk_id_to_group_ids"] = {}
    result["records"] = []
    result["warnings"].append(warning)
    result["budget"]["returned_context_chars"] = 0
    result["budget"]["returned_paths"] = 0
    result["budget"]["returned_relations"] = 0
    result["budget"]["truncated"] = True
    return result


def _invalid_operation(
    client: HydraDBClient,
    *,
    operation: str,
    warning: str,
) -> dict[str, Any]:
    return {
        "status": "degraded",
        "operation": operation,
        "source_ids": [],
        "source_count": 0,
        "writes_performed": False,
        "hydradb": {
            "available": client.configured,
            "collections": [client.config.evolution_collection],
            "write_attempted": False,
            "cross_collection_traversal": False,
            "memory_used": False,
        },
        "warnings": [warning],
    }
