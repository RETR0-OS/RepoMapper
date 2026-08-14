"""Bounded local Graph IR checkpoints used only for deterministic diffing.

These files are analysis inputs, never a repository retrieval source. The store
owns exactly two named slots and exposes no search or graph-query operation.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from enum import StrEnum
from pathlib import Path
from threading import RLock
from typing import Literal

from pydantic import Field, model_validator

from .ids import normalize_repository_id
from .models import FrozenModel, GraphIR

CHECKPOINT_SCHEMA = "hack-hydra.graph-checkpoint.v1"
DEFAULT_MAX_CHECKPOINT_BYTES = 25_000_000


class CheckpointSlot(StrEnum):
    BEFORE = "before"
    AFTER = "after"


class CheckpointArtifact(FrozenModel):
    checkpoint_schema: Literal["hack-hydra.graph-checkpoint.v1"] = CHECKPOINT_SCHEMA
    slot: CheckpointSlot
    graph_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    graph: GraphIR

    @model_validator(mode="after")
    def validate_hash(self) -> CheckpointArtifact:
        if self.graph_hash != _graph_hash(self.graph):
            raise ValueError("checkpoint graph hash does not match its Graph IR")
        return self


class CheckpointRef(FrozenModel):
    checkpoint_schema: Literal["hack-hydra.graph-checkpoint.v1"] = CHECKPOINT_SCHEMA
    slot: CheckpointSlot
    repository_id: str
    revision_id: str
    graph_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_size: int = Field(ge=1)


class CheckpointStore:
    """Atomic two-slot checkpoint storage beneath one repository root."""

    def __init__(
        self,
        workspace_root: str | Path,
        *,
        repository_id: str,
        max_checkpoint_bytes: int = DEFAULT_MAX_CHECKPOINT_BYTES,
    ) -> None:
        if max_checkpoint_bytes < 1:
            raise ValueError("max_checkpoint_bytes must be positive")
        root = Path(workspace_root).resolve()
        if not root.is_dir():
            raise ValueError(f"workspace root does not exist: {root}")
        self.workspace_root = root
        self.repository_id = normalize_repository_id(repository_id)
        self.max_checkpoint_bytes = max_checkpoint_bytes
        self._lock = RLock()

    def capture(self, slot: CheckpointSlot | str, graph: GraphIR) -> CheckpointRef:
        """Atomically replace one slot with a complete validated Graph IR."""

        selected = CheckpointSlot(slot)
        if graph.repository_id != self.repository_id:
            raise ValueError("checkpoint Graph IR belongs to another repository")
        artifact = CheckpointArtifact(
            slot=selected,
            graph_hash=_graph_hash(graph),
            graph=graph,
        )
        encoded = _canonical_json(artifact.model_dump(mode="json"))
        if len(encoded) > self.max_checkpoint_bytes:
            raise ValueError(
                f"checkpoint exceeds the {self.max_checkpoint_bytes}-byte local analysis limit"
            )

        with self._lock:
            directory, target = self._paths(selected)
            directory.mkdir(parents=True, exist_ok=True)
            directory, target = self._paths(selected)
            if target.is_symlink():
                raise ValueError("checkpoint slot must not be a symbolic link")
            temporary = directory / f".{selected.value}.{uuid.uuid4().hex}.tmp"
            try:
                with temporary.open("xb") as output:
                    output.write(encoded)
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(temporary, target)
            finally:
                if temporary.exists():
                    temporary.unlink()

        return CheckpointRef(
            slot=selected,
            repository_id=graph.repository_id,
            revision_id=graph.revision_id,
            graph_hash=artifact.graph_hash,
            byte_size=len(encoded),
        )

    def load_pair(
        self,
        *,
        before_revision_id: str,
        after_revision_id: str,
    ) -> tuple[GraphIR, GraphIR]:
        """Load only the explicit before/after pair requested for a diff."""

        if not before_revision_id.strip() or not after_revision_id.strip():
            raise ValueError("checkpoint revision IDs must not be blank")
        with self._lock:
            before = self._load(CheckpointSlot.BEFORE, before_revision_id)
            after = self._load(CheckpointSlot.AFTER, after_revision_id)
        return before, after

    def clear(self) -> None:
        """Remove the two owned checkpoint files without deleting the directory."""

        with self._lock:
            for slot in CheckpointSlot:
                _, target = self._paths(slot)
                if target.is_symlink():
                    raise ValueError("checkpoint slot must not be a symbolic link")
                if target.exists():
                    target.unlink()

    def _load(self, slot: CheckpointSlot, expected_revision_id: str) -> GraphIR:
        _, target = self._paths(slot)
        if target.is_symlink():
            raise ValueError("checkpoint slot must not be a symbolic link")
        try:
            encoded = target.read_bytes()
        except FileNotFoundError as exc:
            raise ValueError(f"{slot.value} checkpoint is missing") from exc
        if not encoded or len(encoded) > self.max_checkpoint_bytes:
            raise ValueError(f"{slot.value} checkpoint violates the local analysis size limit")
        try:
            payload = json.loads(encoded)
            artifact = CheckpointArtifact.model_validate(payload)
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
            raise ValueError(f"{slot.value} checkpoint is invalid") from exc
        if artifact.slot is not slot:
            raise ValueError(f"{slot.value} checkpoint contains the wrong slot")
        if artifact.graph.repository_id != self.repository_id:
            raise ValueError(f"{slot.value} checkpoint belongs to another repository")
        if artifact.graph.revision_id != expected_revision_id:
            raise ValueError(f"{slot.value} checkpoint belongs to another revision")
        return artifact.graph

    def _paths(self, slot: CheckpointSlot) -> tuple[Path, Path]:
        directory = (self.workspace_root / ".hydra-graph" / "checkpoints").resolve()
        try:
            directory.relative_to(self.workspace_root)
        except ValueError as exc:
            raise ValueError("checkpoint directory escapes the workspace root") from exc
        # Do not resolve the final component: resolving it would dereference an
        # existing slot symlink before the caller can reject that symlink.
        target = directory / f"{slot.value}.json"
        if target.parent != directory:
            raise ValueError("checkpoint slot escapes the checkpoint directory")
        return directory, target


def _graph_hash(graph: GraphIR) -> str:
    return hashlib.sha256(_canonical_json(graph.model_dump(mode="json"))).hexdigest()


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
