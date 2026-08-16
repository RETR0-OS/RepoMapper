#!/usr/bin/env python
"""Find which query parameter makes HydraDB return concepts instead of BYOG.

An exact symbol name returns this repository's uploaded graph. A natural-language
question returns HydraDB's own concept graph, which can never be grounded. The two
calls differ in more than the question, so this runs a small matrix and counts the
shape of the entities that come back.

An entity is "byog" when its identifier is one of this repository's logical ids,
which always begin with "repo:". Anything else is HydraDB's own entity.

Read-only. It sends one query for each row and writes nothing. It prints counts and
identifiers only, never chunk content or a credential.

Usage:
  python scripts/diagnose_query_shape.py --root <project> --question "..." --symbol "a.b.C"
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "service"))

from hydra_graph.config import HydraDBConfig  # noqa: E402
from hydra_graph.hydradb import HydraDBClient, HydraDBError, response_data  # noqa: E402

LOGICAL_ID_PREFIX = "repo:"


def read_env_file(target: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not target.is_file():
        return values
    for line in target.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        values[name.strip()] = value.strip().strip("\"'")
    return values


def read_json(target: Path) -> dict[str, Any]:
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def groups_of(graph: Mapping[str, Any], name: str) -> list[Mapping[str, Any]]:
    value = graph.get(name)
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def count_shapes(response: Mapping[str, Any]) -> dict[str, int]:
    """Count triplets whose endpoints are this repository's entities."""

    data = response_data(response)
    graph = data.get("graph_context")
    graph = graph if isinstance(graph, Mapping) else {}
    counts = {"paths": 0, "relations": 0, "byog": 0, "other": 0, "chunks": 0}
    chunks = data.get("chunks")
    counts["chunks"] = len(chunks) if isinstance(chunks, Sequence) else 0
    counts["paths"] = len(groups_of(graph, "query_paths"))
    counts["relations"] = len(groups_of(graph, "chunk_relations"))
    for name in ("query_paths", "chunk_relations"):
        for group in groups_of(graph, name):
            triplets = group.get("triplets")
            if not isinstance(triplets, Sequence):
                continue
            for triplet in triplets:
                if not isinstance(triplet, Mapping):
                    continue
                ends = []
                for key in ("source", "target"):
                    entity = triplet.get(key)
                    entity = entity if isinstance(entity, Mapping) else {}
                    ends.append(str(entity.get("identifier") or ""))
                if all(end.startswith(LOGICAL_ID_PREFIX) for end in ends):
                    counts["byog"] += 1
                else:
                    counts["other"] += 1
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", type=Path)
    parser.add_argument("--env", default=None, type=Path)
    parser.add_argument("--question", default="how do tools work?")
    parser.add_argument("--symbol", default=None, help="An exact qualified name that is indexed")
    args = parser.parse_args()

    root = args.root.resolve()
    identity = read_json(root / ".hydra-graph" / "identity.json")
    manifest = read_json(root / ".hydra-graph" / "manifest.json")
    repository_id = identity.get("repository_id") or manifest.get("repository_id")
    revision_id = manifest.get("revision_id")
    if not repository_id:
        print(f"No .hydra-graph/identity.json under {root}")
        return 2

    environment = read_env_file(args.env or root / ".env")
    api_key = environment.get("HYDRA_DB_API_KEY")
    database = environment.get("HYDRA_DB_DATABASE")
    if not api_key or not database:
        print("Set HYDRA_DB_API_KEY and HYDRA_DB_DATABASE in the env file, or pass --env.")
        return 2

    client = HydraDBClient(
        HydraDBConfig(
            api_key=api_key,
            database=database,
            collection=manifest.get("collection") or "current",
        ),
        repository_id=repository_id,
    )

    # These are the filters QueryService sends for a current-revision query.
    service_filters: dict[str, Any] = {"repository_id": repository_id}
    if revision_id:
        service_filters["revision_id"] = revision_id
    service_filters["relation_quality"] = ["exact", "inferred"]

    rows: list[tuple[str, dict[str, Any]]] = [
        ("question, no filters, 10", {"query": args.question, "max_results": 10}),
        ("question, no filters, 50", {"query": args.question, "max_results": 50}),
        (
            "question, service filters, 50",
            {"query": args.question, "max_results": 50, "metadata_filters": service_filters},
        ),
        (
            "question, repo filter only, 50",
            {
                "query": args.question,
                "max_results": 50,
                "metadata_filters": {"repository_id": repository_id},
            },
        ),
        (
            "question, no relation_quality, 50",
            {
                "query": args.question,
                "max_results": 50,
                "metadata_filters": {
                    key: value
                    for key, value in service_filters.items()
                    if key != "relation_quality"
                },
            },
        ),
        ("question, forceful relations, 50", {"query": args.question, "max_results": 50}),
    ]
    if args.symbol:
        rows.insert(0, ("symbol, no filters, 10", {"query": args.symbol, "max_results": 10}))
        rows.append(
            (
                "symbol, service filters, 50",
                {"query": args.symbol, "max_results": 50, "metadata_filters": service_filters},
            )
        )

    print(f"repository id {repository_id}")
    print(f"revision      {revision_id or 'none'}\n")
    print(f"{'row':34} {'chunks':>7} {'paths':>6} {'rels':>5} {'byog':>5} {'other':>6}")
    print("-" * 68)
    for label, call in rows:
        forceful = "forceful" in label
        try:
            response = client.query(
                graph_context=True,
                query_forceful_relations=forceful,
                **call,
            )
        except HydraDBError as exc:
            print(f"{label:34} failed: {type(exc).__name__}: {str(exc)[:40]}")
            continue
        counts = count_shapes(response)
        print(
            f"{label:34} {counts['chunks']:>7} {counts['paths']:>6} "
            f"{counts['relations']:>5} {counts['byog']:>5} {counts['other']:>6}"
        )

    print("\nbyog  = both endpoints are this repository's entities (identifier begins 'repo:')")
    print("other = at least one endpoint is a HydraDB entity, so the hop can never ground")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
