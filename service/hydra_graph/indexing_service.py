"""Automatic revisions and expiring, revalidated indexing previews."""

from __future__ import annotations

import hashlib
import json
import secrets
import subprocess
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from threading import RLock

from .analyzer import analyze_repository
from .cards import SourceCard, build_source_cards
from .discovery import DiscoveryReport, discover_files

PREVIEW_TOKEN_TTL_SECONDS = 600
MAX_ACTIVE_PREVIEWS = 32


class IndexPreviewConflict(ValueError):
    """Raised when a preview expired, was reused, or no longer matches disk."""


@dataclass(frozen=True, slots=True)
class PreparedIndex:
    discovery: DiscoveryReport
    cards: tuple[SourceCard, ...]
    revision_id: str
    revision_source: str
    snapshot_hash: str
    node_count: int
    edge_count: int
    diagnostics: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class IndexPreviewRef:
    token: str
    repository_id: str
    repository_root: str
    revision_id: str
    snapshot_hash: str
    expires_at: int


class IndexPreviewStore:
    def __init__(self, repository_root: Path, repository_id: str) -> None:
        self._root = repository_root.resolve()
        self._repository_id = repository_id
        self._records: OrderedDict[str, IndexPreviewRef] = OrderedDict()
        self._lock = RLock()

    def issue(self, prepared: PreparedIndex) -> IndexPreviewRef:
        now = int(time.time())
        token = secrets.token_urlsafe(32)
        record = IndexPreviewRef(
            token=token,
            repository_id=self._repository_id,
            repository_root=str(self._root),
            revision_id=prepared.revision_id,
            snapshot_hash=prepared.snapshot_hash,
            expires_at=now + PREVIEW_TOKEN_TTL_SECONDS,
        )
        with self._lock:
            self._prune(now)
            self._records[token] = record
            while len(self._records) > MAX_ACTIVE_PREVIEWS:
                self._records.popitem(last=False)
        return record

    def consume(self, token: str, prepared: PreparedIndex) -> IndexPreviewRef:
        now = int(time.time())
        with self._lock:
            self._prune(now)
            record = self._records.pop(token, None)
        if record is None:
            raise IndexPreviewConflict("Index preview token is invalid, expired, or already used")
        if (
            record.repository_id != self._repository_id
            or record.repository_root != str(self._root)
            or record.revision_id != prepared.revision_id
            or record.snapshot_hash != prepared.snapshot_hash
        ):
            raise IndexPreviewConflict("Project files changed after the indexing preview")
        return record

    def _prune(self, now: int) -> None:
        for token, record in tuple(self._records.items()):
            if record.expires_at <= now:
                self._records.pop(token, None)


def prepare_automatic_index(repository_root: Path, repository_id: str) -> PreparedIndex:
    root = repository_root.resolve()
    discovery = discover_files(root)
    revision_id, revision_source = automatic_revision(root, discovery)
    graph = analyze_repository(
        root,
        repository_id=repository_id,
        revision_id=revision_id,
        discovery=discovery,
    )
    cards = build_source_cards(graph, root)
    digest = hashlib.sha256()
    for card in cards:
        encoded = json.dumps(
            card.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return PreparedIndex(
        discovery=discovery,
        cards=cards,
        revision_id=revision_id,
        revision_source=revision_source,
        snapshot_hash=digest.hexdigest(),
        node_count=len(graph.nodes),
        edge_count=len(graph.edges),
        diagnostics=graph.diagnostics,
    )


def automatic_revision(root: Path, discovery: DiscoveryReport) -> tuple[str, str]:
    commit = _clean_git_commit(root)
    if commit is not None:
        return commit, "git-clean"
    digest = hashlib.sha256()
    for item in discovery.files:
        encoded_path = item.path.encode()
        digest.update(len(encoded_path).to_bytes(4, "big"))
        digest.update(encoded_path)
        digest.update(bytes.fromhex(item.content_hash))
    return f"content:{digest.hexdigest()}", "content-digest"


def _clean_git_commit(root: Path) -> str | None:
    try:
        status = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
                "--",
                ".",
                ":(exclude).hydra-graph",
                ":(exclude).hydra-graph/**",
            ],
            capture_output=True,
            check=False,
            shell=False,
            timeout=5,
        )
        if status.returncode != 0 or status.stdout.strip():
            return None
        head = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--verify", "HEAD"],
            capture_output=True,
            check=False,
            shell=False,
            timeout=5,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return None
    commit = head.stdout.decode("ascii", errors="ignore").strip()
    return commit if head.returncode == 0 and 40 <= len(commit) <= 64 and commit.isalnum() else None
