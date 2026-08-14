# Graph IR and source evidence

[Documentation index](README.md) · [Core concepts](concepts.md) ·
[Architecture](architecture.md) ·
[Compare and Preserve](compare-and-preserve.md)

Graph IR is the deterministic handoff between repository analysis and HydraDB
ingestion. It records what the analyzer found, how each fact was produced, and
which revision and source evidence support it.

## A versioned graph

The current Graph IR version is `1.0`. A graph contains:

- one repository ID;
- one concrete revision ID;
- node records;
- edge records; and
- parser diagnostics.

Validation rejects unsupported versions, duplicate node or edge IDs, dangling
edge endpoints, missing canonical owners, and nodes or edges from another
revision.

Graph IR records are treated as immutable snapshots. A new analysis produces a
new graph rather than updating an earlier revision in place.

## Nodes

A node stores both a compact ID and a readable logical ID. It also records its
kind, display and qualified names, repository-relative path, optional language,
source span where required, signature, revision, content hash, parser name and
version, generated flag, and parser attributes.

Line-addressable kinds such as functions, methods, classes, tests, routes, and
configuration blocks require an exact source span. Repository, package, and file
structure can be path-addressable without a line span.

Product records use `SYSTEM_LENS` and `CHANGE_EVENT` kinds, but repository
projections explicitly exclude them from normal source structure.

## Stable identifiers

Node identity is derived from normalized semantic inputs:

```text
repository + language + relative path + kind + qualified name
```

An optional signature discriminator is available where an analyzer needs it.
Revision, line number, and source contents are not part of node identity, so an
unchanged declaration keeps its ID when nearby lines move or a new revision is
created. A path or qualified-name change normally creates a new ID.

Edge identity is derived from repository, source node ID, predicate, target node
ID, and relation quality. Evidence identity is derived from path, complete
range, and excerpt hash.

Compact IDs are SHA-256-derived prefixes. The readable logical ID remains in the
record for debugging and integrity checks.

## Edges and canonical ownership

An edge records:

- source, predicate, and target;
- exact, inferred, semantic, or unknown quality;
- confidence when that quality requires it;
- one or more evidence records where required;
- revision, extractor, and extractor version; and
- one canonical owner source.

Self-relations are rejected. Exact and inferred edges require evidence. Exact
edges reject confidence; inferred and semantic edges require it.

Canonical ownership prevents duplicate BYOG triplets. For example, a call is
owned by the source containing the call, while a `TESTS` relation is owned by
the test source. The target can be defined by another source.

## What “exact” means

Exact means the named deterministic extractor proved the relation represented
by the edge. It does not mean the analyzer has a complete model of every runtime
path.

The current Python analyzer emits exact:

- repository/package/file `CONTAINS` edges;
- file or nested declaration `DEFINES` edges;
- repository-resolved `IMPORTS` edges;
- resolved class `EXTENDS` edges;
- resolved constructor `INSTANTIATES` edges;
- resolved `CALLS` edges; and
- `TESTS` edges for resolved production references from tests.

Module-level imports participate in name resolution. Unresolved, external,
dynamic, or ambiguously scoped targets are omitted rather than promoted to
exact.

The graph model supports inferred relations, but the current Python analyzer
does not manufacture inferred call targets. When an inferred edge is supplied
by another deterministic adapter, it remains opt-in and does not enter the exact
BYOG payload.

## Evidence

Evidence records contain:

```text
id
path
start_line / start_column
end_line / end_column
excerpt_hash
explanation
```

Lines are one-based. Columns are zero-based UTF-8 byte offsets. The end position
is exclusive. A range must be complete and ordered; partial ranges are rejected.
Filesystem structure evidence may be path-level with no range.

For line-addressable AST evidence, the excerpt hash is SHA-256 over the exact
source represented by the evidence. Before building a source card,
line-addressable node content is read again and checked against the stored node
hash. A stale or fabricated span fails instead of silently uploading different
code.

Clicking a line-addressable node should open its declaration span. Clicking an
exact edge should open its proving evidence when the returned relation contains
a validated line-addressable evidence envelope. An aggregate edge opens its
contributing relations; it does not claim that one arbitrary line proves the
whole aggregate.

## From Graph IR to HydraDB

Each concrete entity becomes a readable source card. The card includes identity,
path, signature, documentation when present, a bounded source excerpt, and a
list of incident exact relations.

The canonical owner's exact edges become a HydraDB BYOG graph. The relation
context is versioned JSON containing a readable summary, stable edge ID,
quality, extractor, extractor version, and the original evidence record. The
context must fit HydraDB's 2,000-character limit. Only the duplicate human
summary may be shortened; evidence is never truncated to make it fit. If the
envelope cannot fit, card construction fails.

Graph IR can retain multiple evidence records on an edge. The current ordinary
repository BYOG relation envelope transports the first canonical evidence
record. Evolution records preserve the complete before/after relation evidence
inside their structured Knowledge records.

HydraDB-returned relations are not trusted only because they have an exact-looking
predicate. Product views require BYOG origin and a valid evidence envelope before
rendering exact source evidence. Malformed or automatic relations are omitted or
downgraded rather than upgraded.

## Repository projections

Symbol projections show concrete nodes and exact edges by default. A caller can
explicitly include inferred edges.

Package and file projections aggregate exact lower-level relations by source
group, predicate, and target group. Each aggregate retains:

- the exact contributing edge IDs;
- all contributing evidence IDs;
- the exact relation count; and
- the revision.

Aggregation changes presentation scale, not graph truth. Node and edge budgets
are deterministic, and a truncated projection says so.

## Guarantees

- IDs are deterministic for the same normalized identity inputs.
- Paths cannot be absolute or escape the repository.
- Line-addressable nodes cannot omit spans.
- Exact and inferred relations cannot share the same validation rules by
  accident.
- Exact BYOG payloads exclude inferred edges.
- Relation endpoints and canonical owners must exist in the same Graph IR.
- Source-card construction detects source changes after analysis.
- Empty graphs stay empty; no fake self-edge is created.

## Limits

- A stable ID identifies a declared repository entity, not a runtime object.
- File moves and renames usually change node identity. Rename handling during a
  comparison is an inferred hypothesis, not exact continuity.
- Static analysis can miss reflection, dynamic imports, framework wiring, and
  runtime-only behavior.
- Source-card code excerpts are bounded to 12,000 characters.
- HydraDB BYOG limits are enforced per source: 5,000 entities, 10,000 relations,
  degree 500, 256-character entity names and predicates, and 2,000-character
  relation context.
- Discovery's language classification is broader than implemented parser
  coverage. Only Python currently produces repository Graph IR.

To see how two validated graphs become reviewable change knowledge, continue to
[Compare and Preserve](compare-and-preserve.md).
