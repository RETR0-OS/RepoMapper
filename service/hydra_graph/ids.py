"""Stable identifiers and hashes for Graph IR.

Identifiers are derived only from normalized, semantic identity inputs. Source
locations and file contents intentionally do not participate in node identity,
so an unchanged declaration keeps its ID when nearby lines move.
"""

from __future__ import annotations

import hashlib
import posixpath
import re
from pathlib import Path, PurePosixPath


_SAFE_REPOSITORY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def normalize_repository_id(repository_id: str) -> str:
    """Validate a caller-provided repository identity."""

    value = repository_id.strip()
    if not _SAFE_REPOSITORY_ID.fullmatch(value):
        raise ValueError(
            "repository_id must be 1-128 characters using letters, numbers, '.', '_', ':', or '-'"
        )
    return value


def normalize_relative_path(path: str | Path) -> str:
    """Return a canonical workspace-relative POSIX path.

    Absolute paths and parent traversal are rejected because Graph IR paths are
    navigation locators inside one repository, never host filesystem paths.
    """

    raw = str(path).replace("\\", "/").strip()
    if raw in {"", ".", "./"}:
        return "."
    if raw.startswith("/") or re.match(r"^[A-Za-z]:/", raw):
        raise ValueError(f"path must be repository-relative: {path!s}")
    normalized = posixpath.normpath(raw)
    if normalized == ".." or normalized.startswith("../"):
        raise ValueError(f"path escapes repository: {path!s}")
    return PurePosixPath(normalized).as_posix()


def content_hash(content: str | bytes) -> str:
    """Hash source content without lossy normalization."""

    data = content.encode("utf-8") if isinstance(content, str) else content
    return hashlib.sha256(data).hexdigest()


def _compact_id(prefix: str, logical_id: str) -> str:
    digest = hashlib.sha256(logical_id.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}_{digest}"


def node_logical_id(
    *,
    repository_id: str,
    path: str | Path,
    language: str | None,
    kind: str,
    qualified_name: str,
    signature_discriminator: str | None = None,
) -> str:
    """Build the readable identity retained beside each compact node ID."""

    repository = normalize_repository_id(repository_id)
    relative_path = normalize_relative_path(path)
    parts = [
        "repo",
        repository,
        (language or "none").strip().lower(),
        relative_path,
        str(kind).strip().lower(),
        qualified_name.strip(),
    ]
    if signature_discriminator:
        parts.append(signature_discriminator.strip())
    return ":".join(parts)


def node_id(**identity: str | Path | None) -> tuple[str, str]:
    """Return ``(compact_id, readable_logical_id)`` for a node."""

    logical = node_logical_id(**identity)  # type: ignore[arg-type]
    return _compact_id("node", logical), logical


def edge_logical_id(
    *,
    repository_id: str,
    source_id: str,
    predicate: str,
    target_id: str,
    quality: str,
) -> str:
    repository = normalize_repository_id(repository_id)
    return ":".join(
        ["repo", repository, source_id, predicate.strip().upper(), target_id, quality.strip().lower()]
    )


def edge_id(**identity: str) -> tuple[str, str]:
    """Return ``(compact_id, readable_logical_id)`` for a relation."""

    logical = edge_logical_id(**identity)
    return _compact_id("edge", logical), logical


def evidence_id(
    *,
    path: str | Path,
    start_line: int | None,
    start_column: int | None,
    end_line: int | None,
    end_column: int | None,
    excerpt_hash: str,
) -> str:
    relative_path = normalize_relative_path(path)
    location = f"{start_line}:{start_column}:{end_line}:{end_column}"
    return _compact_id("evidence", f"{relative_path}:{location}:{excerpt_hash}")


def source_id(node_identifier: str) -> str:
    """Derive the stable HydraDB source ID owned by a graph node."""

    return _compact_id("source", node_identifier)

