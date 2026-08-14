"""Deterministic TF-IDF used only for evaluation condition A.

Nothing in the product service imports this module. It is intentionally a
small, inspectable comparison baseline, not a HydraDB failure fallback.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

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
    return tuple(match.group(0).lower() for match in TOKEN_PATTERN.finditer(text))


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
