# Core concepts

[Documentation index](README.md) · [Architecture](architecture.md) ·
[Graph and evidence](graph-and-evidence.md) ·
[Compare and Preserve](compare-and-preserve.md)

Hydra Repository Map helps a developer understand a changing codebase without
pretending that static analysis can see everything that happens at runtime. It
combines deterministic repository facts with HydraDB retrieval, then presents a
small, inspectable graph to a person or coding agent.

## The mental model

Think of the product as three layers:

1. **Repository truth** — a local analyzer reads source code and emits concrete
   nodes, relations, and evidence as Graph IR.
2. **Queryable knowledge** — source cards and exact relations are synchronized
   to HydraDB Knowledge. HydraDB filters, ranks, and returns relevant chunks and
   graph paths.
3. **Bounded views** — the VS Code extension and repository MCP tools show the
   returned slice. They do not query a hidden local graph.

The analyzer decides what is structurally proven. HydraDB decides what stored
knowledge is relevant to a query. The UI decides how to lay out the returned
items. These responsibilities do not overlap.

## Concrete entities, not concept nodes

A repository node represents something with a deterministic repository
identity: for example a package, file, class, function, method, or test. A
line-addressable entity also has an exact source range.

Names such as “authentication” or “checkout flow” can be questions, lens names,
or labels around a path. They are not repository structure nodes. The graph
model has no generic `CONCEPT` kind, and the normal repository projection
excludes product records such as change events and System Lenses.

## Facts, retrieval, and presentation

These are separate kinds of information:

- **Graph facts** are nodes and relations in versioned Graph IR.
- **Retrieval results** are chunks and paths returned by HydraDB for a specific
  query and revision.
- **Presentation state** includes node positions, pan, zoom, filters, and the
  selected item.

Moving two nodes closer together does not make them more related. Hiding an edge
does not delete the fact. A semantic match does not become an exact code
relation because it ranked highly.

## Exact and inferred relations

An **exact** relation is supported by a deterministic mechanism such as syntax,
resolved names, or explicit filesystem ownership. Exact relations carry named
extractor provenance and evidence. They do not carry a decorative confidence
score.

An **inferred** relation is a deterministic hypothesis that cannot be proved by
the same standard. It requires evidence, an extractor, and a confidence value.
Inferred relations are excluded from exact BYOG payloads and hidden by default
in repository projections.

The model also reserves `semantic` and `unknown` qualities. Semantic relations
are retrieval aids, not normal repository structure. Unknown quality means the
product did not validate deterministic provenance; it must never be presented
as exact.

See [Graph and evidence](graph-and-evidence.md) for the exact record rules.

## Revisions and ready state

Every node and edge belongs to one concrete revision. A stable view should use
one verified revision unless it is explicitly comparing two revisions.

HydraDB ingestion is asynchronous and current-collection replacement is not
transactional. The service therefore distinguishes a candidate revision from a
verified revision. If an upload or deletion is only partly confirmed, the
current collection is marked indeterminate and repository queries return an
empty degraded result instead of exposing a possibly mixed graph.

The last verified revision is a bookkeeping marker. It is not a promise that a
failed replacement left every old HydraDB source untouched.

## The six product modes

- **Repository** shows bounded package, file, or symbol structure.
- **Explore** focuses on a concrete entity and its returned neighborhood.
- **Trace** asks HydraDB for a graph-backed path through the repository.
- **Observe** shows query, returned-path, selected-context, opened-evidence, and
  workspace-change events that the system can actually observe.
- **Compare** retrieves a stored structural change event between two revisions.
- **Preserve** saves one important exact path and reports how its grounded path
  changes later.

Observe does not expose private model reasoning or HydraDB's private internal
traversal. It shows product events and returned data only.

## Current implementation scope

The repository analyzer currently emits Graph IR for Python source using
Python's AST. It produces repository, package, file, class, function, method,
and test nodes, plus exact `CONTAINS`, `DEFINES`, `IMPORTS`, `EXTENDS`, `CALLS`,
`INSTANTIATES`, and `TESTS` relations when their targets resolve inside the
discovered repository.

Discovery recognizes many file extensions so it can report repository scope,
but that does not mean those languages have implemented graph analyzers. The
TypeScript code in this repository implements the VS Code extension; it is not
evidence of TypeScript repository-analysis coverage.

## Guarantees and limits

The implementation is designed to guarantee that:

- visible structure has a concrete repository identity;
- exact and inferred qualities remain separate;
- complete source ranges are ordered and repository-relative;
- Graph IR does not contain duplicate IDs or dangling edge endpoints;
- production retrieval goes through HydraDB; and
- HydraDB failure is visible rather than replaced by a local search fallback.

It does not guarantee perfect knowledge of dynamic dispatch, reflection,
dependency injection, generated behavior, native boundaries, runtime state, or
external services. An absent relation means “not proven by the current
analyzer,” not necessarily “impossible at runtime.”

For the component boundaries behind these rules, continue to
[Architecture](architecture.md).
