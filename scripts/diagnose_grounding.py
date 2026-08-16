#!/usr/bin/env python
"""Name the exact rule that dropped every hop from a repository view.

The panel can only say that no source card proved the entities. This runs the same
query the service runs, then checks each hop endpoint against the same rules and
reports which rule refused it, and how often.

Read-only. It sends one HydraDB query and writes nothing. It prints ids, paths, and
counts. It never prints chunk content, an API key, or a database name.

Usage:
  python scripts/diagnose_grounding.py --root <project> [--question "..."] [--env .env]

--root must be the project the extension indexed, because the repository id and the
verified revision are read from <root>/.hydra-graph/.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "service"))

from hydra_graph.config import HydraDBConfig  # noqa: E402
from hydra_graph.hydradb import HydraDBClient  # noqa: E402
from hydra_graph.query import QueryRequest, QueryService  # noqa: E402
from hydra_graph.views import (  # noqa: E402
    ViewDepth,
    ViewMode,
    _entity_id,
    _entity_node,
    build_product_view,
)

GROUNDING_FIELDS = ("node_id", "path", "content_hash", "parser", "parser_version", "revision")
CONTAINER_KINDS = {"REPOSITORY", "PACKAGE", "MODULE", "FILE"}


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


def why_no_node(entity: Mapping[str, Any], chunk: Mapping[str, Any] | None) -> str:
    """Return the first rule that refused this entity.

    This mirrors ``_entity_node`` in service/hydra_graph/views.py. Keep the two in
    step: the point of this script is to say which of those lines rejected the hop.
    """

    if not chunk:
        return "no source card for this entity came back in this result"
    entity_id = _entity_id(entity)
    if not entity_id:
        return "the hop entity carries no identifier"
    missing = [field for field in GROUNDING_FIELDS if not chunk.get(field)]
    if missing:
        return f"the card is missing {', '.join(missing)}"
    if entity_id != str(chunk["node_id"]):
        return f"entity id {entity_id!r} is not the card node_id {str(chunk['node_id'])!r}"
    kind = str(chunk.get("entity_kind") or entity.get("kind") or "").upper()
    span = chunk.get("span") if isinstance(chunk.get("span"), Mapping) else None
    if kind not in CONTAINER_KINDS and span is None:
        return f"kind {kind or 'UNKNOWN'} needs a line span and the card has none"
    return "the node failed its own schema validation"


def chunk_lookups(
    result: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Rebuild the three lookups that _symbol_graph uses to find a card."""

    by_id: dict[str, Any] = {}
    by_node: dict[str, Any] = {}
    by_logical: dict[str, Any] = {}
    for item in [*result.get("chunks", []), *result.get("sources", [])]:
        if not isinstance(item, Mapping):
            continue
        if item.get("chunk_id"):
            by_id.setdefault(str(item["chunk_id"]), item)
        for chunk_id in item.get("chunk_ids", []):
            by_id.setdefault(str(chunk_id), item)
        if item.get("node_id"):
            by_node.setdefault(str(item["node_id"]), item)
        if item.get("logical_id"):
            by_logical.setdefault(str(item["logical_id"]), item)
    return by_id, by_node, by_logical


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", type=Path)
    parser.add_argument(
        "--question", default="How does this repository handle its main request flow?"
    )
    parser.add_argument("--env", default=None, type=Path)
    parser.add_argument("--max-nodes", default=50, type=int)
    parser.add_argument("--max-edges", default=80, type=int)
    parser.add_argument("--show", default=8, type=int, help="How many failing hops to list")
    args = parser.parse_args()

    root = args.root.resolve()
    identity = read_json(root / ".hydra-graph" / "identity.json")
    manifest = read_json(root / ".hydra-graph" / "manifest.json")
    repository_id = identity.get("repository_id") or manifest.get("repository_id")
    revision_id = manifest.get("revision_id")
    if not repository_id:
        print(f"No .hydra-graph/identity.json under {root}. Open that project in VS Code once.")
        return 2

    environment = read_env_file(args.env or root / ".env")
    api_key = environment.get("HYDRA_DB_API_KEY")
    database = environment.get("HYDRA_DB_DATABASE")
    if not api_key or not database:
        print("Set HYDRA_DB_API_KEY and HYDRA_DB_DATABASE in the env file, or pass --env.")
        return 2

    print(f"root          {root}")
    print(f"repository id {repository_id}")
    print(f"revision      {revision_id or 'none recorded'}")
    print(f"sources       {len(manifest.get('sources', {}))}")
    print(f"byog sources  {len(manifest.get('byog_sources', []))}\n")

    client = HydraDBClient(
        HydraDBConfig(
            api_key=api_key,
            database=database,
            collection=manifest.get("collection") or "current",
        ),
        repository_id=repository_id,
    )
    service = QueryService(
        client,
        repository_id=repository_id,
        verified_revision=lambda: revision_id,
        byog_source_ids=lambda: tuple(manifest.get("byog_sources", [])),
    )
    result = service.repository_query(
        QueryRequest(
            question=args.question,
            max_results=min(50, max(4, args.max_nodes)),
            max_paths=max(1, min(10, args.max_edges)),
            max_relations=args.max_edges,
        )
    )
    view = build_product_view(
        result,
        mode=ViewMode.TRACE,
        depth=ViewDepth.SYMBOL,
        max_nodes=args.max_nodes,
        max_edges=args.max_edges,
    )
    diagnostics = view.get("diagnostics", {})
    print(f"status   {result['status']}")
    print(f"outcome  {diagnostics.get('outcome')}")
    print(f"funnel   {json.dumps(diagnostics.get('funnel', {}))}")
    for warning in result.get("warnings", []):
        print(f"warning  {warning}")
    print()

    chunks = [item for item in result.get("chunks", []) if isinstance(item, Mapping)]
    if chunks:
        complete = sum(1 for item in chunks if all(item.get(key) for key in GROUNDING_FIELDS))
        print(f"{complete} of {len(chunks)} returned cards carry every grounding field.")
        for field in GROUNDING_FIELDS:
            absent = sum(1 for item in chunks if not item.get(field))
            if absent:
                print(f"  {absent} card(s) have no {field}")
        with_span = sum(1 for item in chunks if isinstance(item.get("span"), Mapping))
        print(f"  {with_span} of {len(chunks)} cards carry a line span\n")

    by_id, by_node, by_logical = chunk_lookups(result)
    reasons: Counter[str] = Counter()
    examples: list[str] = []
    hops = 0
    grounded = 0
    for group in [*result.get("paths", []), *result.get("relations", [])]:
        for hop in group.get("hops", []):
            hops += 1
            relation = hop.get("relation", {})
            source, target = hop.get("source", {}), hop.get("target", {})
            source_id, target_id = _entity_id(source), _entity_id(target)
            source_chunk = (
                by_id.get(str(relation.get("chunk_id")))
                or by_node.get(source_id)
                or by_logical.get(str(source.get("logical_id")))
            )
            target_chunk = by_node.get(target_id) or by_logical.get(str(target.get("logical_id")))
            source_node = _entity_node(source, source_chunk)
            target_node = _entity_node(target, target_chunk)
            if source_node and target_node:
                grounded += 1
                continue
            for label, entity, chunk, node in (
                ("source", source, source_chunk, source_node),
                ("target", target, target_chunk, target_node),
            ):
                if node is not None:
                    continue
                reason = why_no_node(entity, chunk)
                reasons[f"{label}: {reason.split(chr(39))[0].strip()}"] += 1
                if len(examples) < args.show:
                    examples.append(
                        f"  hop {label} {_entity_id(entity)!r} "
                        f"({entity.get('kind') or 'UNKNOWN'}) -> {reason}"
                    )

    print(f"{grounded} of {hops} hop(s) had both ends grounded.")
    if reasons:
        print("\nWhy the other ends were refused, most common first:")
        for reason, count in reasons.most_common():
            print(f"  {count:4d}  {reason}")
    if examples:
        print("\nExamples:")
        for line in examples:
            print(line)
    return 0 if grounded else 1


if __name__ == "__main__":
    raise SystemExit(main())
