"""Safe, previewable repository file discovery."""

from __future__ import annotations

import os
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import pathspec

from .ids import content_hash, normalize_relative_path

DEFAULT_MAX_FILE_BYTES = 1_000_000
_CONTROL_FILES = {".gitignore", ".hydraignore"}
_ALWAYS_IGNORED_DIRECTORIES = {".git", ".hg", ".svn", "node_modules", "__pycache__"}
_SECRET_NAMES = {
    ".env",
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "credentials.json",
    "service-account.json",
}
_SECRET_SUFFIXES = {".pem", ".key", ".p12", ".pfx"}
_SECRET_PATTERNS = (
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    re.compile(rb"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(rb"\bgh[opusr]_[A-Za-z0-9]{30,255}\b"),
    re.compile(rb"\bgithub_pat_[A-Za-z0-9_]{30,255}\b"),
    re.compile(
        rb"(?im)^\s*(?:api[_-]?key|secret[_-]?key|access[_-]?token|auth[_-]?token)\s*[:=]\s*['\"]?[A-Za-z0-9_./+=-]{20,}"
    ),
)

_LANGUAGES = {
    ".py": "python",
    ".pyi": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".cs": "csharp",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".c": "c",
    ".h": "c",
    ".hpp": "cpp",
    ".rb": "ruby",
    ".php": "php",
    ".sql": "sql",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".toml": "toml",
    ".md": "markdown",
}


@dataclass(frozen=True, slots=True)
class DiscoveredFile:
    path: str
    absolute_path: Path
    size_bytes: int
    content_hash: str
    language: str | None
    is_test: bool
    is_generated: bool


@dataclass(frozen=True, slots=True)
class IgnoredPath:
    path: str
    reason: str


@dataclass(frozen=True, slots=True)
class DiscoveryReport:
    root: Path
    files: tuple[DiscoveredFile, ...]
    ignored: tuple[IgnoredPath, ...]

    @property
    def ignored_counts(self) -> dict[str, int]:
        return dict(sorted(Counter(item.reason for item in self.ignored).items()))


def _read_ignore_lines(root: Path, names: Iterable[str]) -> list[str]:
    lines: list[str] = []
    for name in names:
        ignore_file = root / name
        if ignore_file.is_file():
            lines.extend(ignore_file.read_text(encoding="utf-8", errors="replace").splitlines())
    return lines


def _is_secret_name(path: Path) -> bool:
    lowered = path.name.lower()
    return (
        lowered in _SECRET_NAMES
        or lowered.startswith(".env.")
        or path.suffix.lower() in _SECRET_SUFFIXES
    )


def _contains_secret(content: bytes) -> bool:
    return any(pattern.search(content) for pattern in _SECRET_PATTERNS)


def _is_binary(content: bytes) -> bool:
    if b"\x00" in content:
        return True
    if not content:
        return False
    sample = content[:8192]
    suspicious = sum(byte < 9 or 13 < byte < 32 for byte in sample)
    return suspicious / len(sample) > 0.10


def discover_files(
    root: str | Path,
    *,
    deny_globs: Iterable[str] = (),
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
) -> DiscoveryReport:
    """Discover safe source files without following symlinks.

    `.gitignore`, `.hydraignore`, explicit deny globs, common secret filenames,
    secret content signatures, binaries, and oversized files are enforced before
    a file becomes eligible for analysis or ingestion.
    """

    repository_root = Path(root).resolve()
    if not repository_root.is_dir():
        raise ValueError(f"repository root is not a directory: {repository_root}")
    if max_file_bytes < 1:
        raise ValueError("max_file_bytes must be positive")

    ignore_lines = _read_ignore_lines(repository_root, (".gitignore", ".hydraignore"))
    ignore_lines.extend(str(pattern) for pattern in deny_globs)
    spec = pathspec.PathSpec.from_lines("gitwildmatch", ignore_lines)

    found: list[DiscoveredFile] = []
    ignored: list[IgnoredPath] = []
    for current_root, directory_names, file_names in os.walk(repository_root, followlinks=False):
        current = Path(current_root)
        kept_directories: list[str] = []
        for name in sorted(directory_names):
            directory = current / name
            relative = normalize_relative_path(directory.relative_to(repository_root))
            if directory.is_symlink():
                ignored.append(IgnoredPath(relative, "symlink"))
            elif name in _ALWAYS_IGNORED_DIRECTORIES:
                ignored.append(IgnoredPath(relative, "default-ignore"))
            elif spec.match_file(f"{relative}/"):
                ignored.append(IgnoredPath(relative, "ignore-rule"))
            else:
                kept_directories.append(name)
        directory_names[:] = kept_directories

        for name in sorted(file_names):
            candidate = current / name
            relative = normalize_relative_path(candidate.relative_to(repository_root))
            if candidate.is_symlink():
                ignored.append(IgnoredPath(relative, "symlink"))
                continue
            if name in _CONTROL_FILES:
                ignored.append(IgnoredPath(relative, "control-file"))
                continue
            if spec.match_file(relative):
                ignored.append(IgnoredPath(relative, "ignore-rule"))
                continue
            if _is_secret_name(candidate):
                ignored.append(IgnoredPath(relative, "secret-name"))
                continue
            try:
                size = candidate.stat().st_size
            except OSError:
                ignored.append(IgnoredPath(relative, "unreadable"))
                continue
            if size > max_file_bytes:
                ignored.append(IgnoredPath(relative, "oversized"))
                continue
            try:
                raw = candidate.read_bytes()
            except OSError:
                ignored.append(IgnoredPath(relative, "unreadable"))
                continue
            if _is_binary(raw):
                ignored.append(IgnoredPath(relative, "binary"))
                continue
            if _contains_secret(raw):
                ignored.append(IgnoredPath(relative, "secret-content"))
                continue

            lowered_parts = {part.lower() for part in Path(relative).parts}
            is_test = (
                "tests" in lowered_parts or name.startswith("test_") or name.endswith("_test.py")
            )
            is_generated = (
                any(part in {"generated", "dist", "build", "vendor"} for part in lowered_parts)
                or ".generated." in name.lower()
            )
            found.append(
                DiscoveredFile(
                    path=relative,
                    absolute_path=candidate,
                    size_bytes=size,
                    content_hash=content_hash(raw),
                    language=_LANGUAGES.get(candidate.suffix.lower()),
                    is_test=is_test,
                    is_generated=is_generated,
                )
            )

    return DiscoveryReport(
        root=repository_root,
        files=tuple(sorted(found, key=lambda item: item.path)),
        ignored=tuple(sorted(ignored, key=lambda item: (item.path, item.reason))),
    )
