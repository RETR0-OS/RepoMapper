"""Deterministic Python AST analysis with exact, source-backed relations."""

from __future__ import annotations

import ast
import tokenize
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .discovery import DiscoveredFile, DiscoveryReport, discover_files
from .entrypoints import EntryPoint, detect_entry_points
from .ids import content_hash, edge_id, evidence_id, node_id
from .models import (
    Evidence,
    GraphEdge,
    GraphIR,
    GraphNode,
    NodeKind,
    RelationPredicate,
    RelationQuality,
    SourceSpan,
)

PARSER_NAME = "python-ast"
PARSER_VERSION = "1"
FILESYSTEM_PARSER = "filesystem-scanner"
FILESYSTEM_VERSION = "1"


@dataclass(frozen=True, slots=True)
class _ParsedFile:
    discovered: DiscoveredFile
    source: str
    tree: ast.Module
    module_name: str


@dataclass(frozen=True, slots=True)
class _Symbol:
    node: GraphNode
    ast_node: ast.AST
    parent_id: str
    module_name: str
    class_qualified_name: str | None


def _module_name(path: str) -> str:
    pure = PurePosixPath(path)
    parts = list(pure.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts) or pure.stem


def _node_span(node: ast.AST) -> SourceSpan:
    return SourceSpan(
        start_line=node.lineno,  # type: ignore[attr-defined]
        start_column=node.col_offset,  # type: ignore[attr-defined]
        end_line=node.end_lineno,  # type: ignore[attr-defined]
        end_column=node.end_col_offset,  # type: ignore[attr-defined]
    )


def _source_segment(source: str, node: ast.AST) -> str:
    return ast.get_source_segment(source, node) or ""


def _function_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    prefix = "async " if isinstance(node, ast.AsyncFunctionDef) else ""
    arguments = ast.unparse(node.args)
    returns = f" -> {ast.unparse(node.returns)}" if node.returns is not None else ""
    return f"{prefix}{node.name}({arguments}){returns}"


def _body_fingerprint(node: ast.AST) -> str:
    """Hash structure while excluding declaration names and line positions.

    The normalized source text is hashed instead of `ast.dump`, because the dump
    format changes between CPython releases and would give one structure a
    different fingerprint on every interpreter that analyzes the repository.
    """

    clone = ast.parse(ast.unparse(node)).body[0]
    if isinstance(clone, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        clone.name = "__symbol__"
    return content_hash(ast.unparse(clone))


def _qualified_expression(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _qualified_expression(node.value)
        return f"{parent}.{node.attr}" if parent else None
    return None


def _relative_module(current_module: str, module: str | None, level: int) -> str:
    if level == 0:
        return module or ""
    package_parts = current_module.split(".")[:-1]
    keep = max(0, len(package_parts) - (level - 1))
    base = package_parts[:keep]
    if module:
        base.extend(module.split("."))
    return ".".join(base)


def _entry_reasons_by(
    entry_points: Iterable[EntryPoint],
    *,
    key: Callable[[EntryPoint], str | None],
    named: bool,
) -> dict[str, list[str]]:
    """Group entry-point reasons by one identity.

    A record that names a symbol marks that symbol; a record that names none marks the
    file. Without the split, the file holding a marked function would inherit the
    function's reason and report a start that its own text does not show.
    """

    grouped: dict[str, set[str]] = {}
    for item in entry_points:
        identity = key(item)
        if not identity or (item.qualified_name is not None) != named:
            continue
        grouped.setdefault(identity, set()).add(item.reason)
    return {identity: sorted(reasons) for identity, reasons in grouped.items()}


class PythonAnalyzer:
    """Build a Graph IR from Python's concrete syntax tree.

    The resolver emits only targets proven by declarations in the discovered
    repository. Dynamic or external calls remain absent rather than becoming
    guessed exact edges.
    """

    def __init__(self, repository_id: str, revision_id: str) -> None:
        self.repository_id = repository_id
        self.revision_id = revision_id

    def analyze(
        self,
        root: str | Path,
        *,
        discovery: DiscoveryReport | None = None,
    ) -> GraphIR:
        report = discovery or discover_files(root)
        parsed_files, diagnostics = self._parse_files(report.files)
        entry_points = detect_entry_points(
            report,
            python_modules={item.discovered.path: item.tree for item in parsed_files},
        )
        entry_paths = _entry_reasons_by(entry_points, key=lambda item: item.path, named=False)
        entry_symbols = _entry_reasons_by(
            entry_points, key=lambda item: item.qualified_name, named=True
        )
        nodes: dict[str, GraphNode] = {}
        edges_by_key: dict[
            tuple[str, RelationPredicate, str, RelationQuality, str], list[Evidence]
        ] = defaultdict(list)

        repository = self._repository_node(report)
        nodes[repository.id] = repository
        file_nodes, package_nodes = self._structure_nodes(report, entry_paths)
        nodes.update({node.id: node for node in (*package_nodes, *file_nodes)})

        for package in package_nodes:
            parent_path = str(PurePosixPath(package.path).parent)
            parent = (
                repository if parent_path == "." else self._node_at_path(package_nodes, parent_path)
            )
            self._collect_edge(
                edges_by_key,
                parent,
                RelationPredicate.CONTAINS,
                package,
                parent.id,
                self._filesystem_evidence(
                    package, f"{parent.display_name} contains {package.display_name}."
                ),
            )
        for file_node in file_nodes:
            parent_path = str(PurePosixPath(file_node.path).parent)
            parent = (
                repository if parent_path == "." else self._node_at_path(package_nodes, parent_path)
            )
            self._collect_edge(
                edges_by_key,
                parent,
                RelationPredicate.CONTAINS,
                file_node,
                parent.id,
                self._filesystem_evidence(
                    file_node, f"{parent.display_name} contains {file_node.display_name}."
                ),
            )

        # Import resolution must never reach a non-Python file: `import web.index`
        # would otherwise resolve onto `web/index.js` and claim an exact edge that no
        # parser proved.
        file_by_path = {node.path: node for node in file_nodes if node.language == "python"}
        symbols = self._extract_symbols(
            parsed_files, file_by_path, nodes, edges_by_key, entry_symbols
        )
        self._resolve_relations(parsed_files, file_by_path, symbols, edges_by_key)
        edges = self._materialize_edges(edges_by_key)
        return GraphIR(
            repository_id=self.repository_id,
            revision_id=self.revision_id,
            nodes=tuple(sorted(nodes.values(), key=lambda item: item.id)),
            edges=tuple(sorted(edges, key=lambda item: item.id)),
            diagnostics=tuple(sorted(diagnostics)),
        )

    def _parse_files(self, files: Iterable[DiscoveredFile]) -> tuple[list[_ParsedFile], list[str]]:
        parsed: list[_ParsedFile] = []
        diagnostics: list[str] = []
        for discovered in files:
            if discovered.language != "python":
                continue
            try:
                with tokenize.open(discovered.absolute_path) as source_file:
                    source = source_file.read()
            except (OSError, UnicodeDecodeError) as error:
                diagnostics.append(
                    f"{discovered.path}: unreadable Python source ({error.__class__.__name__})"
                )
                continue
            try:
                tree = ast.parse(source, filename=discovered.path, type_comments=True)
            except SyntaxError as error:
                diagnostics.append(f"{discovered.path}:{error.lineno or 1}: syntax error")
                continue
            parsed.append(
                _ParsedFile(
                    discovered=discovered,
                    source=source,
                    tree=tree,
                    module_name=_module_name(discovered.path),
                )
            )
        return parsed, diagnostics

    def _repository_node(self, report: DiscoveryReport) -> GraphNode:
        compact, logical = node_id(
            repository_id=self.repository_id,
            path=".",
            language=None,
            kind=NodeKind.REPOSITORY.value,
            qualified_name=self.repository_id,
            signature_discriminator=None,
        )
        manifest = "\n".join(
            f"{item.path}:{item.content_hash}" for item in report.files if item.language == "python"
        )
        return GraphNode(
            id=compact,
            logical_id=logical,
            kind=NodeKind.REPOSITORY,
            display_name=report.root.name,
            qualified_name=self.repository_id,
            path=".",
            revision_id=self.revision_id,
            content_hash=content_hash(manifest),
            parser=FILESYSTEM_PARSER,
            parser_version=FILESYSTEM_VERSION,
        )

    def _structure_nodes(
        self, report: DiscoveryReport, entry_paths: Mapping[str, list[str]]
    ) -> tuple[list[GraphNode], list[GraphNode]]:
        packages: set[str] = set()
        files: list[GraphNode] = []
        for discovered in report.files:
            is_python = discovered.language == "python"
            reasons = entry_paths.get(discovered.path)
            # A non-Python file becomes a node only when a manifest proves it starts the
            # system. Indexing every other file would add nodes nothing can explain.
            if not is_python and not reasons:
                continue
            parent = PurePosixPath(discovered.path).parent
            while str(parent) != ".":
                packages.add(str(parent))
                parent = parent.parent
            # A Python file is named by its module. Any other file keeps its path,
            # because 'web/index.js' and 'web/index.py' would otherwise share one name.
            qualified = _module_name(discovered.path) if is_python else discovered.path
            compact, logical = node_id(
                repository_id=self.repository_id,
                path=discovered.path,
                language=discovered.language,
                kind=NodeKind.FILE.value,
                qualified_name=qualified,
                signature_discriminator=None,
            )
            attributes: dict[str, object] = {"is_test": discovered.is_test}
            if reasons:
                attributes["is_entry_point"] = True
                attributes["entry_reasons"] = reasons
            files.append(
                GraphNode(
                    id=compact,
                    logical_id=logical,
                    kind=NodeKind.FILE,
                    display_name=PurePosixPath(discovered.path).name,
                    qualified_name=qualified,
                    language=discovered.language,
                    path=discovered.path,
                    revision_id=self.revision_id,
                    content_hash=discovered.content_hash,
                    parser=FILESYSTEM_PARSER,
                    parser_version=FILESYSTEM_VERSION,
                    is_generated=discovered.is_generated,
                    attributes=attributes,
                )
            )
        package_nodes: list[GraphNode] = []
        for package in sorted(packages):
            compact, logical = node_id(
                repository_id=self.repository_id,
                path=package,
                language=None,
                kind=NodeKind.PACKAGE.value,
                qualified_name=package.replace("/", "."),
                signature_discriminator=None,
            )
            package_nodes.append(
                GraphNode(
                    id=compact,
                    logical_id=logical,
                    kind=NodeKind.PACKAGE,
                    display_name=PurePosixPath(package).name,
                    qualified_name=package.replace("/", "."),
                    path=package,
                    revision_id=self.revision_id,
                    content_hash=content_hash(package),
                    parser=FILESYSTEM_PARSER,
                    parser_version=FILESYSTEM_VERSION,
                )
            )
        return files, package_nodes

    @staticmethod
    def _node_at_path(nodes: Iterable[GraphNode], path: str) -> GraphNode:
        return next(node for node in nodes if node.path == path)

    def _extract_symbols(
        self,
        parsed_files: list[_ParsedFile],
        file_by_path: dict[str, GraphNode],
        nodes: dict[str, GraphNode],
        edges_by_key: dict[
            tuple[str, RelationPredicate, str, RelationQuality, str], list[Evidence]
        ],
        entry_symbols: Mapping[str, list[str]],
    ) -> list[_Symbol]:
        symbols: list[_Symbol] = []
        for parsed in parsed_files:
            file_node = file_by_path[parsed.discovered.path]

            def visit_body(
                body: list[ast.stmt],
                scope_parts: list[str],
                parent_id: str,
                class_qualified_name: str | None,
                parsed_file: _ParsedFile = parsed,
                owner_file: GraphNode = file_node,
            ) -> None:
                for syntax in body:
                    if not isinstance(
                        syntax, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
                    ):
                        continue
                    qualified = ".".join([parsed_file.module_name, *scope_parts, syntax.name])
                    if isinstance(syntax, ast.ClassDef):
                        kind = NodeKind.CLASS
                        signature = f"class {syntax.name}"
                        next_class = qualified
                    elif syntax.name.startswith("test_") or parsed_file.discovered.is_test:
                        kind = NodeKind.TEST
                        signature = _function_signature(syntax)
                        next_class = class_qualified_name
                    elif nodes[parent_id].kind is NodeKind.CLASS:
                        kind = NodeKind.METHOD
                        signature = _function_signature(syntax)
                        next_class = class_qualified_name
                    else:
                        kind = NodeKind.FUNCTION
                        signature = _function_signature(syntax)
                        next_class = class_qualified_name
                    compact, logical = node_id(
                        repository_id=self.repository_id,
                        path=parsed_file.discovered.path,
                        language="python",
                        kind=kind.value,
                        qualified_name=qualified,
                        signature_discriminator=None,
                    )
                    excerpt = _source_segment(parsed_file.source, syntax)
                    docstring = ast.get_docstring(syntax, clean=True)
                    attributes: dict[str, object] = {
                        "body_fingerprint": _body_fingerprint(syntax),
                        "docstring": docstring,
                        "is_test": kind is NodeKind.TEST,
                    }
                    entry_reasons = entry_symbols.get(qualified)
                    if entry_reasons:
                        attributes["is_entry_point"] = True
                        attributes["entry_reasons"] = entry_reasons
                    graph_node = GraphNode(
                        id=compact,
                        logical_id=logical,
                        kind=kind,
                        display_name=syntax.name,
                        qualified_name=qualified,
                        language="python",
                        path=parsed_file.discovered.path,
                        span=_node_span(syntax),
                        signature=signature,
                        revision_id=self.revision_id,
                        content_hash=content_hash(excerpt),
                        parser=PARSER_NAME,
                        parser_version=PARSER_VERSION,
                        is_generated=parsed_file.discovered.is_generated,
                        attributes=attributes,
                    )
                    nodes[compact] = graph_node
                    symbol = _Symbol(
                        node=graph_node,
                        ast_node=syntax,
                        parent_id=parent_id,
                        module_name=parsed_file.module_name,
                        class_qualified_name=next_class,
                    )
                    symbols.append(symbol)
                    parent_node = nodes[parent_id]
                    evidence = self._ast_evidence(
                        parsed_file,
                        syntax,
                        f"{parent_node.display_name} defines {graph_node.display_name}.",
                    )
                    self._collect_edge(
                        edges_by_key,
                        parent_node,
                        RelationPredicate.DEFINES,
                        graph_node,
                        owner_file.id,
                        evidence,
                    )
                    visit_body(
                        syntax.body,
                        [*scope_parts, syntax.name],
                        graph_node.id,
                        next_class,
                    )

            visit_body(parsed.tree.body, [], file_node.id, None)
        return symbols

    def _resolve_relations(
        self,
        parsed_files: list[_ParsedFile],
        file_by_path: dict[str, GraphNode],
        symbols: list[_Symbol],
        edges_by_key: dict[
            tuple[str, RelationPredicate, str, RelationQuality, str], list[Evidence]
        ],
    ) -> None:
        file_by_module = {_module_name(path): node for path, node in file_by_path.items()}
        symbol_by_qualified = {symbol.node.qualified_name: symbol for symbol in symbols}
        symbol_by_ast = {id(symbol.ast_node): symbol for symbol in symbols}

        for parsed in parsed_files:
            file_node = file_by_path[parsed.discovered.path]
            aliases: dict[str, str] = {}
            # Only module-level bindings participate in this resolver. A local
            # import has function scope; treating it as global could fabricate a
            # call from another function. A later scoped resolver may add those
            # facts without weakening today's exactness.
            for syntax in parsed.tree.body:
                if isinstance(syntax, ast.Import):
                    for alias in syntax.names:
                        bound = alias.asname or alias.name.split(".")[0]
                        aliases[bound] = alias.name if alias.asname else alias.name.split(".")[0]
                        target_file = file_by_module.get(alias.name)
                        if target_file:
                            explanation = (
                                f"{file_node.display_name} imports {target_file.qualified_name}."
                            )
                            self._collect_edge(
                                edges_by_key,
                                file_node,
                                RelationPredicate.IMPORTS,
                                target_file,
                                file_node.id,
                                self._ast_evidence(
                                    parsed,
                                    syntax,
                                    explanation,
                                ),
                            )
                elif isinstance(syntax, ast.ImportFrom):
                    module = _relative_module(parsed.module_name, syntax.module, syntax.level)
                    import_targets: dict[str, GraphNode] = {}
                    for alias in syntax.names:
                        if alias.name == "*":
                            continue
                        bound = alias.asname or alias.name
                        candidate = f"{module}.{alias.name}" if module else alias.name
                        aliases[bound] = candidate
                        target_file = file_by_module.get(candidate) or file_by_module.get(module)
                        if target_file:
                            import_targets[target_file.id] = target_file
                    # A star import can still prove a file-to-file import even
                    # though it cannot safely bind individual target symbols.
                    if any(alias.name == "*" for alias in syntax.names):
                        target_file = file_by_module.get(module)
                        if target_file:
                            import_targets[target_file.id] = target_file
                    for target_file in sorted(import_targets.values(), key=lambda item: item.id):
                        explanation = (
                            f"{file_node.display_name} imports {target_file.qualified_name}."
                        )
                        self._collect_edge(
                            edges_by_key,
                            file_node,
                            RelationPredicate.IMPORTS,
                            target_file,
                            file_node.id,
                            self._ast_evidence(
                                parsed,
                                syntax,
                                explanation,
                            ),
                        )

            class Resolver(ast.NodeVisitor):
                def __init__(
                    resolver_self,
                    parsed_file: _ParsedFile,
                    alias_map: dict[str, str],
                ) -> None:
                    resolver_self.scope: list[_Symbol] = []
                    resolver_self.parsed_file = parsed_file
                    resolver_self.alias_map = alias_map

                def visit_ClassDef(resolver_self, syntax: ast.ClassDef) -> None:
                    symbol = symbol_by_ast.get(id(syntax))
                    if symbol:
                        for base in syntax.bases:
                            target = self._resolve_expression(
                                base,
                                symbol,
                                resolver_self.alias_map,
                                symbol_by_qualified,
                            )
                            if target and target.node.kind is NodeKind.CLASS:
                                explanation = (
                                    f"{symbol.node.qualified_name} extends "
                                    f"{target.node.qualified_name}."
                                )
                                self._collect_edge(
                                    edges_by_key,
                                    symbol.node,
                                    RelationPredicate.EXTENDS,
                                    target.node,
                                    symbol.node.id,
                                    self._ast_evidence(
                                        resolver_self.parsed_file,
                                        base,
                                        explanation,
                                    ),
                                )
                        resolver_self.scope.append(symbol)
                    for child in syntax.body:
                        resolver_self.visit(child)
                    if symbol:
                        resolver_self.scope.pop()

                def visit_FunctionDef(resolver_self, syntax: ast.FunctionDef) -> None:
                    resolver_self._visit_function(syntax)

                def visit_AsyncFunctionDef(resolver_self, syntax: ast.AsyncFunctionDef) -> None:
                    resolver_self._visit_function(syntax)

                def _visit_function(
                    resolver_self, syntax: ast.FunctionDef | ast.AsyncFunctionDef
                ) -> None:
                    symbol = symbol_by_ast.get(id(syntax))
                    if symbol:
                        resolver_self.scope.append(symbol)
                    for child in syntax.body:
                        resolver_self.visit(child)
                    if symbol:
                        resolver_self.scope.pop()

                def visit_Call(resolver_self, syntax: ast.Call) -> None:
                    if resolver_self.scope:
                        source_symbol = resolver_self.scope[-1]
                        target_symbol = self._resolve_expression(
                            syntax.func,
                            source_symbol,
                            resolver_self.alias_map,
                            symbol_by_qualified,
                        )
                        if target_symbol and target_symbol.node.id != source_symbol.node.id:
                            predicate = (
                                RelationPredicate.INSTANTIATES
                                if target_symbol.node.kind is NodeKind.CLASS
                                else RelationPredicate.CALLS
                            )
                            evidence = self._ast_evidence(
                                resolver_self.parsed_file,
                                syntax,
                                f"{source_symbol.node.qualified_name} {predicate.value.lower()} "
                                f"{target_symbol.node.qualified_name}.",
                            )
                            self._collect_edge(
                                edges_by_key,
                                source_symbol.node,
                                predicate,
                                target_symbol.node,
                                source_symbol.node.id,
                                evidence,
                            )
                            if (
                                source_symbol.node.kind is NodeKind.TEST
                                and target_symbol.node.kind is not NodeKind.TEST
                            ):
                                test_explanation = (
                                    f"{source_symbol.node.qualified_name} tests "
                                    f"{target_symbol.node.qualified_name} through a resolved call."
                                )
                                test_evidence = evidence.model_copy(
                                    update={"explanation": test_explanation}
                                )
                                self._collect_edge(
                                    edges_by_key,
                                    source_symbol.node,
                                    RelationPredicate.TESTS,
                                    target_symbol.node,
                                    source_symbol.node.id,
                                    test_evidence,
                                )
                    resolver_self.generic_visit(syntax)

            Resolver(parsed, aliases).visit(parsed.tree)

    @staticmethod
    def _resolve_expression(
        expression: ast.AST,
        source: _Symbol,
        aliases: dict[str, str],
        symbols: dict[str, _Symbol],
    ) -> _Symbol | None:
        dotted = _qualified_expression(expression)
        if not dotted:
            return None
        if dotted.startswith("self.") and source.class_qualified_name:
            return symbols.get(f"{source.class_qualified_name}.{dotted.removeprefix('self.')}")
        first, separator, rest = dotted.partition(".")
        if first in aliases:
            dotted = aliases[first] + (f".{rest}" if separator else "")
            if dotted in symbols:
                return symbols[dotted]
        scope_parts = source.node.qualified_name.split(".")[:-1]
        while scope_parts:
            candidate = ".".join([*scope_parts, dotted])
            if candidate in symbols:
                return symbols[candidate]
            scope_parts.pop()
        return symbols.get(f"{source.module_name}.{dotted}") or symbols.get(dotted)

    def _collect_edge(
        self,
        edges: dict[tuple[str, RelationPredicate, str, RelationQuality, str], list[Evidence]],
        source: GraphNode,
        predicate: RelationPredicate,
        target: GraphNode,
        owner_id: str,
        evidence: Evidence,
    ) -> None:
        # A recursive call, or any other self-reference, is not a repository graph
        # edge: GraphEdge rejects one. Drop it here so analysis never builds an
        # invalid edge and fails the whole revision.
        if source.id == target.id:
            return
        key = (source.id, predicate, target.id, RelationQuality.EXACT, owner_id)
        if all(existing.id != evidence.id for existing in edges[key]):
            edges[key].append(evidence)

    def _materialize_edges(
        self,
        edge_evidence: dict[
            tuple[str, RelationPredicate, str, RelationQuality, str], list[Evidence]
        ],
    ) -> list[GraphEdge]:
        output: list[GraphEdge] = []
        for (source, predicate, target, quality, owner), evidence in sorted(
            edge_evidence.items(), key=lambda item: tuple(str(part) for part in item[0])
        ):
            compact, logical = edge_id(
                repository_id=self.repository_id,
                source_id=source,
                predicate=predicate.value,
                target_id=target,
                quality=quality.value,
            )
            output.append(
                GraphEdge(
                    id=compact,
                    logical_id=logical,
                    source_id=source,
                    predicate=predicate,
                    target_id=target,
                    quality=quality,
                    evidence=tuple(sorted(evidence, key=lambda item: item.id)),
                    revision_id=self.revision_id,
                    extractor=PARSER_NAME
                    if predicate is not RelationPredicate.CONTAINS
                    else FILESYSTEM_PARSER,
                    extractor_version=PARSER_VERSION,
                    owner_source_id=owner,
                )
            )
        return output

    @staticmethod
    def _ast_evidence(parsed: _ParsedFile, syntax: ast.AST, explanation: str) -> Evidence:
        segment = _source_segment(parsed.source, syntax)
        span = _node_span(syntax)
        excerpt = content_hash(segment)
        identifier = evidence_id(
            path=parsed.discovered.path,
            start_line=span.start_line,
            start_column=span.start_column,
            end_line=span.end_line,
            end_column=span.end_column,
            excerpt_hash=excerpt,
        )
        return Evidence(
            id=identifier,
            path=parsed.discovered.path,
            start_line=span.start_line,
            start_column=span.start_column,
            end_line=span.end_line,
            end_column=span.end_column,
            excerpt_hash=excerpt,
            explanation=explanation,
        )

    @staticmethod
    def _filesystem_evidence(node: GraphNode, explanation: str) -> Evidence:
        identifier = evidence_id(
            path=node.path,
            start_line=None,
            start_column=None,
            end_line=None,
            end_column=None,
            excerpt_hash=node.content_hash,
        )
        return Evidence(
            id=identifier,
            path=node.path,
            excerpt_hash=node.content_hash,
            explanation=explanation,
        )


def analyze_repository(
    root: str | Path,
    *,
    repository_id: str,
    revision_id: str,
    discovery: DiscoveryReport | None = None,
) -> GraphIR:
    return PythonAnalyzer(repository_id, revision_id).analyze(root, discovery=discovery)
