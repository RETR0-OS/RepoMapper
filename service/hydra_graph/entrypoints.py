"""Deterministic, language-agnostic entry-point detection from proven manifests.

A detector emits a fact only when the referenced target resolves to a file that
discovery already accepted, or to a symbol declared in the same module. A
reference that cannot be proven is left absent rather than guessed, so the graph
never claims an execution start that the repository does not contain.
"""

from __future__ import annotations

import ast
import json
import posixpath
import shlex
import tokenize
import tomllib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath

from .discovery import DiscoveredFile, DiscoveryReport
from .ids import normalize_relative_path

MAX_MANIFEST_BYTES = 1_000_000

_SCRIPT_SUFFIXES = frozenset({".cjs", ".js", ".jsx", ".mjs", ".py", ".sh", ".ts", ".tsx"})
_CONTAINER_REASONS = {"ENTRYPOINT": "container-entrypoint", "CMD": "container-cmd"}


@dataclass(frozen=True, slots=True)
class EntryPoint:
    path: str
    qualified_name: str | None
    reason: str
    manifest_path: str
    manifest_line: int | None


def _module_name(path: str) -> str:
    pure = PurePosixPath(path)
    parts = list(pure.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts) or pure.stem


def _read_text(discovered: DiscoveredFile) -> str | None:
    if discovered.size_bytes > MAX_MANIFEST_BYTES:
        return None
    try:
        return discovered.absolute_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError, ValueError):
        return None


def _line_of(text: str, needle: str) -> int | None:
    """Locate the line that carries a reference in a format without line numbers.

    TOML and JSON parsers discard positions, so the proving line is recovered by
    an exact substring scan. A reference that cannot be located keeps a null line
    instead of an invented one.
    """

    if not needle:
        return None
    for index, line in enumerate(text.splitlines(), start=1):
        if needle in line:
            return index
    return None


def _resolve_reference(
    reference: str, directory: str, discovered_paths: frozenset[str]
) -> str | None:
    candidate = reference.strip().strip("\"'")
    if not candidate or candidate.startswith("-"):
        return None
    joined = candidate if directory == "." else posixpath.join(directory, candidate)
    try:
        normalized = normalize_relative_path(joined)
    except ValueError:
        return None
    return normalized if normalized in discovered_paths else None


def _resolve_repository_token(
    token: str, directory: str, discovered_paths: frozenset[str]
) -> str | None:
    for base in (directory, "."):
        resolved = _resolve_reference(token, base, discovered_paths)
        if resolved is not None:
            return resolved
    return None


def _command_tokens(argument: str) -> list[str]:
    text = argument.strip()
    if text.startswith("["):
        try:
            parsed = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return []
        if not isinstance(parsed, list):
            return []
        return [item for item in parsed if isinstance(item, str)]
    try:
        return shlex.split(text)
    except ValueError:
        return []


def _is_dunder_name(node: ast.expr) -> bool:
    return isinstance(node, ast.Name) and node.id == "__name__"


def _is_main_constant(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and node.value == "__main__"


def _is_main_guard(test: ast.expr) -> bool:
    if not isinstance(test, ast.Compare) or len(test.ops) != 1 or len(test.comparators) != 1:
        return False
    if not isinstance(test.ops[0], ast.Eq):
        return False
    left = test.left
    right = test.comparators[0]
    if _is_dunder_name(left) and _is_main_constant(right):
        return True
    return _is_main_constant(left) and _is_dunder_name(right)


def _module_declarations(
    tree: ast.Module,
) -> tuple[frozenset[str], dict[str, ast.ClassDef]]:
    callables: set[str] = set()
    classes: dict[str, ast.ClassDef] = {}
    for statement in tree.body:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            callables.add(statement.name)
        elif isinstance(statement, ast.ClassDef):
            callables.add(statement.name)
            classes[statement.name] = statement
    return frozenset(callables), classes


def _resolve_local_callee(
    func: ast.expr,
    module: str,
    callables: frozenset[str],
    classes: Mapping[str, ast.ClassDef],
) -> str | None:
    """Resolve a callee only against declarations in the same module.

    Chasing an imported name would need the resolver's alias table and could bind
    the wrong module, so an imported or dynamic callee emits nothing.
    """

    if isinstance(func, ast.Name):
        return f"{module}.{func.id}" if func.id in callables else None
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        owner = classes.get(func.value.id)
        if owner is None:
            return None
        for statement in owner.body:
            if (
                isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
                and statement.name == func.attr
            ):
                return f"{module}.{func.value.id}.{func.attr}"
    return None


def _python_entry_points(discovered: DiscoveredFile, tree: ast.Module | None) -> list[EntryPoint]:
    path = discovered.path
    results: list[EntryPoint] = []
    if PurePosixPath(path).name == "__main__.py":
        results.append(
            EntryPoint(
                path=path,
                qualified_name=None,
                reason="python-main-module",
                manifest_path=path,
                manifest_line=None,
            )
        )
    if tree is None:
        return results
    module = _module_name(path)
    callables, classes = _module_declarations(tree)
    for statement in tree.body:
        if not isinstance(statement, ast.If) or not _is_main_guard(statement.test):
            continue
        results.append(
            EntryPoint(
                path=path,
                qualified_name=None,
                reason="python-main-guard",
                manifest_path=path,
                manifest_line=statement.lineno,
            )
        )
        for guarded in statement.body:
            for node in ast.walk(guarded):
                if not isinstance(node, ast.Call):
                    continue
                qualified = _resolve_local_callee(node.func, module, callables, classes)
                if qualified is None:
                    continue
                results.append(
                    EntryPoint(
                        path=path,
                        qualified_name=qualified,
                        reason="python-main-guard-call",
                        manifest_path=path,
                        manifest_line=node.lineno,
                    )
                )
    return results


def _python_file_by_module(report: DiscoveryReport) -> dict[str, str]:
    modules: dict[str, str] = {}
    for discovered in report.files:
        if discovered.language == "python":
            modules.setdefault(_module_name(discovered.path), discovered.path)
    return modules


def _console_script_entry_points(
    discovered: DiscoveredFile, report: DiscoveryReport
) -> list[EntryPoint]:
    text = _read_text(discovered)
    if text is None:
        return []
    try:
        document = tomllib.loads(text)
    except (tomllib.TOMLDecodeError, ValueError):
        return []
    project = document.get("project")
    if not isinstance(project, dict):
        return []
    file_by_module = _python_file_by_module(report)
    results: list[EntryPoint] = []
    for table_name in ("gui-scripts", "scripts"):
        table = project.get(table_name)
        if not isinstance(table, dict):
            continue
        for _, value in sorted(table.items()):
            if not isinstance(value, str):
                continue
            tokens = value.strip().split()
            if not tokens:
                continue
            reference = tokens[0]
            module, separator, attribute = reference.partition(":")
            if not separator or not module or not attribute:
                continue
            path = file_by_module.get(module)
            if path is None:
                continue
            results.append(
                EntryPoint(
                    path=path,
                    qualified_name=f"{module}.{attribute}",
                    reason="python-console-script",
                    manifest_path=discovered.path,
                    manifest_line=_line_of(text, reference),
                )
            )
    return results


def _script_tokens(command: str) -> list[str]:
    try:
        tokens = shlex.split(command)
    except ValueError:
        return []
    return [
        token
        for token in tokens
        if not token.startswith("-") and PurePosixPath(token).suffix.lower() in _SCRIPT_SUFFIXES
    ]


def _node_entry_points(
    discovered: DiscoveredFile, discovered_paths: frozenset[str]
) -> list[EntryPoint]:
    text = _read_text(discovered)
    if text is None:
        return []
    try:
        document = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return []
    if not isinstance(document, dict):
        return []
    references: list[tuple[str, str]] = []
    binaries = document.get("bin")
    if isinstance(binaries, str):
        references.append(("node-package-bin", binaries))
    elif isinstance(binaries, dict):
        for _, value in sorted(binaries.items()):
            if isinstance(value, str):
                references.append(("node-package-bin", value))
    main = document.get("main")
    if isinstance(main, str):
        references.append(("node-package-main", main))
    scripts = document.get("scripts")
    if isinstance(scripts, dict):
        start = scripts.get("start")
        if isinstance(start, str):
            references.extend(("node-package-start", token) for token in _script_tokens(start))

    directory = str(PurePosixPath(discovered.path).parent)
    results: list[EntryPoint] = []
    for reason, reference in references:
        resolved = _resolve_reference(reference, directory, discovered_paths)
        if resolved is None:
            continue
        results.append(
            EntryPoint(
                path=resolved,
                qualified_name=None,
                reason=reason,
                manifest_path=discovered.path,
                manifest_line=_line_of(text, reference),
            )
        )
    return results


def _dockerfile_instructions(text: str) -> list[tuple[int, str, str]]:
    instructions: list[tuple[int, str, str]] = []
    buffer = ""
    start = 1
    for index, raw in enumerate(text.splitlines(), start=1):
        line = raw.rstrip()
        if not buffer:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            start = index
        if line.endswith("\\"):
            buffer += line[:-1]
            continue
        buffer += line
        parts = buffer.strip().split(None, 1)
        if len(parts) == 2:
            instructions.append((start, parts[0].upper(), parts[1].strip()))
        buffer = ""
    parts = buffer.strip().split(None, 1)
    if len(parts) == 2:
        instructions.append((start, parts[0].upper(), parts[1].strip()))
    return instructions


def _container_entry_points(
    discovered: DiscoveredFile, discovered_paths: frozenset[str]
) -> list[EntryPoint]:
    text = _read_text(discovered)
    if text is None:
        return []
    directory = str(PurePosixPath(discovered.path).parent)
    results: list[EntryPoint] = []
    for lineno, instruction, argument in _dockerfile_instructions(text):
        reason = _CONTAINER_REASONS.get(instruction)
        if reason is None:
            continue
        for token in _command_tokens(argument):
            resolved = _resolve_repository_token(token, directory, discovered_paths)
            if resolved is None:
                continue
            results.append(
                EntryPoint(
                    path=resolved,
                    qualified_name=None,
                    reason=reason,
                    manifest_path=discovered.path,
                    manifest_line=lineno,
                )
            )
    return results


def _procfile_entry_points(
    discovered: DiscoveredFile, discovered_paths: frozenset[str]
) -> list[EntryPoint]:
    text = _read_text(discovered)
    if text is None:
        return []
    directory = str(PurePosixPath(discovered.path).parent)
    results: list[EntryPoint] = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        name, separator, command = line.partition(":")
        if not separator or not name.strip():
            continue
        for token in _command_tokens(command):
            resolved = _resolve_repository_token(token, directory, discovered_paths)
            if resolved is None:
                continue
            results.append(
                EntryPoint(
                    path=resolved,
                    qualified_name=None,
                    reason="procfile-process",
                    manifest_path=discovered.path,
                    manifest_line=lineno,
                )
            )
    return results


def _parsed_modules(
    report: DiscoveryReport, provided: Mapping[str, ast.Module] | None
) -> Mapping[str, ast.Module]:
    if provided is not None:
        return provided
    modules: dict[str, ast.Module] = {}
    for discovered in report.files:
        if discovered.language != "python" or discovered.size_bytes > MAX_MANIFEST_BYTES:
            continue
        try:
            with tokenize.open(discovered.absolute_path) as handle:
                source = handle.read()
            modules[discovered.path] = ast.parse(source, filename=discovered.path)
        except (OSError, UnicodeDecodeError, SyntaxError, ValueError):
            continue
    return modules


def _sorted_entry_points(found: Iterable[EntryPoint]) -> tuple[EntryPoint, ...]:
    return tuple(
        sorted(
            set(found),
            key=lambda item: (
                item.path,
                item.reason,
                item.qualified_name or "",
                item.manifest_path,
                item.manifest_line or 0,
            ),
        )
    )


def detect_entry_points(
    report: DiscoveryReport,
    *,
    python_modules: Mapping[str, ast.Module] | None = None,
) -> tuple[EntryPoint, ...]:
    """Detect proven execution starts across every discovered manifest.

    ``python_modules`` maps a repository-relative POSIX path to its parsed tree.
    A module name cannot be inverted back to a path, and ``pkg/__init__.py`` and
    ``pkg.py`` share one module name, so the path is the key. Callers that
    already parsed the repository pass their trees to avoid a second parse;
    omitting them makes this module read and parse the Python files itself.
    """

    modules = _parsed_modules(report, python_modules)
    discovered_paths = frozenset(item.path for item in report.files)
    found: list[EntryPoint] = []
    for discovered in report.files:
        name = PurePosixPath(discovered.path).name
        if discovered.language == "python":
            found.extend(_python_entry_points(discovered, modules.get(discovered.path)))
        if name == "pyproject.toml":
            found.extend(_console_script_entry_points(discovered, report))
        elif name == "package.json":
            found.extend(_node_entry_points(discovered, discovered_paths))
        elif name == "Dockerfile" or name.startswith("Dockerfile."):
            found.extend(_container_entry_points(discovered, discovered_paths))
        elif name == "Procfile":
            found.extend(_procfile_entry_points(discovered, discovered_paths))
    return _sorted_entry_points(found)
