"""Deterministic TF-IDF used only for evaluation condition A.

Nothing in the product service imports this module. It is intentionally a
small, inspectable comparison baseline, not a HydraDB failure fallback.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from hydra_graph.ids import content_hash
from hydra_graph.models import Evidence

if TYPE_CHECKING:
    from .gold import ResolvedGold

TOKEN_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


@dataclass(frozen=True, slots=True)
class BaselineEvidence:
    evidence_id: str
    path: str
    start_line: int
    start_column: int
    end_line: int
    end_column: int
    excerpt_hash: str


@dataclass(frozen=True, slots=True)
class BaselineDocument:
    document_id: str
    node_id: str
    content: str
    evidence: tuple[BaselineEvidence, ...] = ()


@dataclass(frozen=True, slots=True)
class RankedDocument:
    document: BaselineDocument
    score: float


def _tokens(text: str) -> tuple[str, ...]:
    tokens: list[str] = []
    for match in TOKEN_PATTERN.finditer(text):
        identifier = match.group(0).lower()
        tokens.append(identifier)
        tokens.extend(part for part in identifier.split("_") if part and part != identifier)
    return tuple(tokens)


class DeterministicTfidf:
    """Rank a fixed corpus without network calls, embeddings, or hidden state."""

    def __init__(self, documents: tuple[BaselineDocument, ...]) -> None:
        if not documents:
            raise ValueError("the baseline corpus cannot be empty")
        identifiers = [document.document_id for document in documents]
        if any(not identifier.strip() for identifier in identifiers):
            raise ValueError("baseline document IDs must be concrete")
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("baseline document IDs must be unique")
        self._documents = tuple(sorted(documents, key=lambda item: item.document_id))
        self._document_tokens = {
            document.document_id: _tokens(document.content) for document in self._documents
        }
        document_frequency: Counter[str] = Counter()
        for tokens in self._document_tokens.values():
            document_frequency.update(set(tokens))
        size = len(self._documents)
        self._idf = {
            token: math.log((size + 1) / (frequency + 1)) + 1
            for token, frequency in document_frequency.items()
        }

    def search(self, query: str, *, limit: int = 10) -> tuple[RankedDocument, ...]:
        if not query.strip():
            raise ValueError("baseline query cannot be blank")
        if limit < 1 or limit > 100:
            raise ValueError("baseline limit must be between 1 and 100")
        query_tokens = _tokens(query)
        query_vector = self._vector(query_tokens)
        ranked = [
            RankedDocument(
                document=document,
                score=self._cosine(
                    query_vector, self._vector(self._document_tokens[document.document_id])
                ),
            )
            for document in self._documents
        ]
        ranked.sort(key=lambda item: (-item.score, item.document.document_id))
        return tuple(item for item in ranked[:limit] if item.score > 0)

    def _vector(self, tokens: tuple[str, ...]) -> dict[str, float]:
        counts = Counter(tokens)
        total = sum(counts.values())
        if total == 0:
            return {}
        return {
            token: (count / total) * self._idf.get(token, 0.0)
            for token, count in counts.items()
            if token in self._idf
        }

    @staticmethod
    def _cosine(left: dict[str, float], right: dict[str, float]) -> float:
        if not left or not right:
            return 0.0
        dot = sum(value * right.get(token, 0.0) for token, value in left.items())
        left_norm = math.sqrt(sum(value * value for value in left.values()))
        right_norm = math.sqrt(sum(value * value for value in right.values()))
        return dot / (left_norm * right_norm) if left_norm and right_norm else 0.0


def baseline_corpus_digest(documents: tuple[BaselineDocument, ...]) -> str:
    payload = [
        {
            "document_id": document.document_id,
            "node_id": document.node_id,
            "content": document.content,
            "evidence": [
                {
                    "evidence_id": item.evidence_id,
                    "path": item.path,
                    "start_line": item.start_line,
                    "start_column": item.start_column,
                    "end_line": item.end_line,
                    "end_column": item.end_column,
                    "excerpt_hash": item.excerpt_hash,
                }
                for item in sorted(document.evidence, key=lambda evidence: evidence.evidence_id)
            ],
        }
        for document in sorted(documents, key=lambda item: item.document_id)
    ]
    canonical = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_baseline_documents(path: str | Path) -> tuple[BaselineDocument, ...]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read baseline corpus: {path}") from error
    if not isinstance(payload, list) or not payload:
        raise ValueError("baseline corpus must be a non-empty JSON array")
    documents: list[BaselineDocument] = []
    for item in payload:
        if not isinstance(item, dict) or set(item) != {
            "document_id",
            "node_id",
            "content",
            "evidence",
        }:
            raise ValueError("baseline corpus entries use an unknown or incomplete shape")
        raw_evidence = item["evidence"]
        if not isinstance(raw_evidence, list):
            raise ValueError("baseline evidence must be an array")
        evidence = tuple(_load_evidence(value) for value in raw_evidence)
        if not all(isinstance(item[key], str) for key in ("document_id", "node_id", "content")):
            raise ValueError("baseline document fields must be strings")
        documents.append(
            BaselineDocument(
                document_id=item["document_id"],
                node_id=item["node_id"],
                content=item["content"],
                evidence=evidence,
            )
        )
    return tuple(documents)


def validate_baseline_documents(
    documents: tuple[BaselineDocument, ...], gold: ResolvedGold
) -> None:
    nodes = gold.graph.node_map()
    evidence: dict[str, tuple[Evidence, frozenset[str]]] = {}
    outgoing_evidence: dict[str, set[str]] = {}
    for edge in gold.graph.edges:
        for item in edge.evidence:
            evidence[item.id] = (item, frozenset((edge.source_id, edge.target_id)))
            outgoing_evidence.setdefault(edge.source_id, set()).add(item.id)
    document_node_ids = [document.node_id for document in documents]
    if len(document_node_ids) != len(set(document_node_ids)):
        raise ValueError("baseline corpus must cover every Graph IR node exactly once")
    for document in documents:
        node = nodes.get(document.node_id)
        if node is None:
            raise ValueError(f"baseline document {document.document_id} references an unknown node")
        if document.document_id != document.node_id:
            raise ValueError("baseline document IDs must equal their stable Graph IR node IDs")
        if node.span is None:
            raise ValueError(f"baseline node {document.node_id} has no source span")
        node_source = _safe_fixture_source(gold.fixture_root, node.path).read_text(encoding="utf-8")
        expected_content = _source_span(
            node_source,
            start_line=node.span.start_line,
            start_column=node.span.start_column,
            end_line=node.span.end_line,
            end_column=node.span.end_column,
        )
        if document.content != expected_content:
            raise ValueError(f"baseline content for {document.document_id} is not source-derived")
        for item in document.evidence:
            matched = evidence.get(item.evidence_id)
            if matched is None:
                raise ValueError(
                    f"baseline document {document.document_id} references unknown evidence"
                )
            actual, endpoints = matched
            if document.node_id not in endpoints:
                raise ValueError(
                    f"baseline evidence is not connected to document {document.document_id}"
                )
            expected = (
                item.path,
                item.start_line,
                item.start_column,
                item.end_line,
                item.end_column,
                item.excerpt_hash,
            )
            observed = (
                actual.path,
                actual.start_line,
                actual.start_column,
                actual.end_line,
                actual.end_column,
                actual.excerpt_hash,
            )
            if expected != observed:
                raise ValueError(
                    f"baseline evidence for {document.document_id} differs from Graph IR"
                )
            source = _safe_fixture_source(gold.fixture_root, item.path).read_text(encoding="utf-8")
            excerpt = _source_span(
                source,
                start_line=item.start_line,
                start_column=item.start_column,
                end_line=item.end_line,
                end_column=item.end_column,
            )
            if content_hash(excerpt) != item.excerpt_hash:
                raise ValueError(
                    f"baseline evidence for {document.document_id} is stale relative to source"
                )
        if {item.evidence_id for item in document.evidence} != outgoing_evidence.get(
            document.node_id, set()
        ):
            raise ValueError(
                f"baseline evidence for {document.document_id} is not the complete outgoing set"
            )
    if set(document_node_ids) != set(nodes):
        raise ValueError("baseline corpus must cover every Graph IR node exactly once")


def _load_evidence(value: object) -> BaselineEvidence:
    fields = {
        "evidence_id",
        "path",
        "start_line",
        "start_column",
        "end_line",
        "end_column",
        "excerpt_hash",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError("baseline evidence uses an unknown or incomplete shape")
    string_fields = ("evidence_id", "path", "excerpt_hash")
    integer_fields = ("start_line", "start_column", "end_line", "end_column")
    if not all(isinstance(value[name], str) and value[name] for name in string_fields):
        raise ValueError("baseline evidence identifiers must be concrete strings")
    if not all(isinstance(value[name], int) for name in integer_fields):
        raise ValueError("baseline evidence span coordinates must be integers")
    evidence = BaselineEvidence(**value)
    if evidence.start_line < 1 or evidence.end_line < 1:
        raise ValueError("baseline evidence lines must be positive")
    if evidence.start_column < 0 or evidence.end_column < 0:
        raise ValueError("baseline evidence columns cannot be negative")
    if (evidence.end_line, evidence.end_column) < (
        evidence.start_line,
        evidence.start_column,
    ):
        raise ValueError("baseline evidence ends before it starts")
    if not re.fullmatch(r"[0-9a-f]{64}", evidence.excerpt_hash):
        raise ValueError("baseline evidence excerpt hash must be lowercase sha256")
    return evidence


def _safe_fixture_source(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as error:
        raise ValueError(f"baseline source path escapes the fixture root: {relative}") from error
    if not candidate.is_file():
        raise ValueError(f"baseline source is not a file: {relative}")
    return candidate


def _source_span(
    source: str,
    *,
    start_line: int,
    start_column: int,
    end_line: int,
    end_column: int,
) -> str:
    lines = source.splitlines()
    if not 1 <= start_line <= end_line <= len(lines):
        raise ValueError("baseline evidence line span is outside its source file")

    def byte_slice(line: str, start: int, end: int | None = None) -> str:
        encoded = line.encode("utf-8")
        try:
            return encoded[start:end].decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValueError("baseline evidence columns split a UTF-8 code point") from error

    if start_line == end_line:
        return byte_slice(lines[start_line - 1], start_column, end_column)
    segments = [byte_slice(lines[start_line - 1], start_column)]
    segments.extend(lines[start_line : end_line - 1])
    segments.append(byte_slice(lines[end_line - 1], 0, end_column))
    return "\n".join(segments)
