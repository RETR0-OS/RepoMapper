#!/usr/bin/env python
"""Ask HydraDB what it stored for sources that were uploaded with a BYOG graph.

A repository query can return HydraDB's own extracted concept graph instead of the
uploaded graph. That looks the same from the panel: relations come back, and none of
them can be grounded. This asks HydraDB directly, for one source at a time, so the
two cases separate.

Read-only. It sends status and relation reads and writes nothing. It prints ids,
types, predicates, and paths. It never prints a code excerpt, an API key, or a
database name.

Usage:
  python scripts/diagnose_byog.py --root <project> [--count 5] [--env .env]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "service"))

from hydra_graph.config import HydraDBConfig  # noqa: E402
from hydra_graph.hydradb import HydraDBClient, HydraDBError, response_data  # noqa: E402

EVIDENCE_SCHEMA = "hack-hydra.relation-evidence.v1"


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


def find_relations(data: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return the relation list from whichever key this API version used."""

    for key in ("relations", "results", "edges", "triplets"):
        value = data.get(key)
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            return [dict(item) for item in value if isinstance(item, Mapping)]
    return []


def describe_envelope(context: Any) -> str:
    """Report whether a relation carries this repository's evidence envelope.

    Only the schema, the quality, and the file path are read. The excerpt inside an
    envelope is repository source text, so it is never printed.
    """

    if not isinstance(context, str):
        return "no context"
    try:
        envelope = json.loads(context)
    except json.JSONDecodeError:
        return "prose context (not an evidence envelope)"
    if not isinstance(envelope, Mapping):
        return "context is not an object"
    if envelope.get("schema") != EVIDENCE_SCHEMA:
        return f"envelope schema {str(envelope.get('schema'))[:40]!r}"
    evidence = envelope.get("evidence")
    path = evidence.get("path") if isinstance(evidence, Mapping) else None
    return f"evidence envelope, quality={envelope.get('quality')}, path={path}"


def entity_label(entity: Any) -> str:
    entity = entity if isinstance(entity, Mapping) else {}
    return f"{entity.get('identifier') or entity.get('name')!r} [{entity.get('type')}]"


def compare_with_query(client: HydraDBClient, stored: Sequence[Mapping[str, Any]]) -> None:
    """Ask the query path about the same entity the stored graph names.

    This is the A/B that separates two very different faults. If the query returns
    the same pairs under other identifiers, HydraDB is re-typing this repository's
    graph. If it returns different pairs, the query is reading another graph.
    """

    source = stored[0].get("source")
    handle = (source or {}).get("identifier") or (source or {}).get("name") if source else None
    if not handle:
        print("  compare: the stored relation names no source entity\n")
        return
    question = str(handle).rsplit(":", 1)[-1]
    print(f"  compare: querying for {question!r}")
    try:
        response = client.query(
            query=question,
            graph_context=True,
            max_results=10,
            query_forceful_relations=False,
        )
    except HydraDBError as exc:
        print(f"  compare: query failed: {type(exc).__name__}: {exc}\n")
        return
    graph = response_data(response).get("graph_context")
    graph = graph if isinstance(graph, Mapping) else {}
    for name in ("query_paths", "chunk_relations"):
        groups = graph.get(name)
        groups = groups if isinstance(groups, Sequence) else []
        print(f"  compare: {name} groups={len(groups)}")
        for group in list(groups)[:2]:
            if not isinstance(group, Mapping):
                continue
            for triplet in list(group.get("triplets", []))[:4]:
                if not isinstance(triplet, Mapping):
                    continue
                relation = triplet.get("relation")
                relation = relation if isinstance(relation, Mapping) else {}
                print(
                    f"    {entity_label(triplet.get('source'))}"
                    f" -{relation.get('canonical_predicate') or relation.get('raw_predicate')}->"
                    f" {entity_label(triplet.get('target'))}"
                    f" origin={relation.get('origin')}"
                )
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", type=Path)
    parser.add_argument("--env", default=None, type=Path)
    parser.add_argument("--count", default=5, type=int, help="How many BYOG sources to inspect")
    parser.add_argument("--limit", default=20, type=int, help="Relations to request per source")
    parser.add_argument(
        "--compare",
        action="store_true",
        help="Also query for each inspected source and show the entities the query returns",
    )
    args = parser.parse_args()

    root = args.root.resolve()
    identity = read_json(root / ".hydra-graph" / "identity.json")
    manifest = read_json(root / ".hydra-graph" / "manifest.json")
    repository_id = identity.get("repository_id") or manifest.get("repository_id")
    byog_sources = list(manifest.get("byog_sources", []))
    if not repository_id or not byog_sources:
        print(f"No repository id or no BYOG source in {root}/.hydra-graph/manifest.json")
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

    sample = byog_sources[: args.count]
    print(f"repository id {repository_id}")
    print(f"collection    {manifest.get('collection') or 'current'}")
    print(f"byog sources  {len(byog_sources)} recorded, inspecting {len(sample)}\n")

    try:
        status = response_data(client.status(sample))
    except HydraDBError as exc:
        print(f"status read failed: {type(exc).__name__}: {exc}")
        status = {}
    if status:
        print(f"status keys: {sorted(status)[:8]}")
        records = find_relations(status) or status.get("statuses") or []
        if isinstance(records, Sequence):
            for record in list(records)[: args.count]:
                if isinstance(record, Mapping):
                    print(f"  {record.get('id')}: {record.get('status') or record.get('state')}")
        print()

    total = Counter()
    shape_printed = False
    for source_id in sample:
        try:
            data = response_data(client.relations(source_id, limit=args.limit))
        except HydraDBError as exc:
            print(f"{source_id}\n  relations read failed: {type(exc).__name__}: {exc}\n")
            continue
        relations = find_relations(data)
        print(f"{source_id}")
        if not relations:
            print(f"  no relation returned. payload keys: {sorted(data)[:8]}\n")
            total["no relations stored"] += 1
            continue
        if not shape_printed:
            # The field names decide where the predicate, the origin, and the evidence
            # envelope live. Print them once instead of guessing.
            shape_printed = True
            record = relations[0]
            print(f"  stored relation fields: {sorted(record)}")
            for key in ("source", "target"):
                if isinstance(record.get(key), Mapping):
                    print(f"  stored {key} fields: {sorted(record[key])}")
        if args.compare:
            compare_with_query(client, relations)
        detail_shape_printed = False
        for record in relations[:5]:
            source = record.get("source") or record.get("source_entity") or {}
            target = record.get("target") or record.get("target_entity") or {}
            source = source if isinstance(source, Mapping) else {}
            target = target if isinstance(target, Mapping) else {}
            # An entity pair carries its own nested list of predicates, so the
            # predicate, the origin, and the evidence envelope live one level down.
            details = record.get("relations")
            if not isinstance(details, Sequence) or isinstance(details, (str, bytes)):
                details = [record]
            print(
                f"  {source.get('identifier') or source.get('name')!r}"
                f" [{source.get('type')}] -> "
                f"{target.get('identifier') or target.get('name')!r}"
                f" [{target.get('type')}]"
            )
            for detail in list(details)[:3]:
                if not isinstance(detail, Mapping):
                    continue
                if not detail_shape_printed:
                    detail_shape_printed = True
                    print(f"    predicate record fields: {sorted(detail)}")
                predicate = (
                    detail.get("canonical_predicate")
                    or detail.get("raw_predicate")
                    or detail.get("predicate")
                )
                origin = detail.get("origin")
                print(f"    -{predicate}-> origin={origin}")
                print(f"    {describe_envelope(detail.get('context'))}")
                total[f"origin={origin}"] += 1
        print(f"  {len(relations)} entity pair(s) returned\n")

    print("Summary:")
    for label, count in total.most_common():
        print(f"  {count:4d}  {label}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
