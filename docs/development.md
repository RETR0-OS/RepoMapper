# Development guide

[Documentation home](README.md) · [Architecture](architecture.md) · [Project layout](project-layout.md) · [Trust and safety](trust-and-safety.md)

This page is for contributors changing the analyzer, service, extension, schemas, or evaluation harness.

## Set up a development environment

From PowerShell in the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"

Push-Location .\extension
npm install
Pop-Location
```

Python 3.11 or newer, Node.js 20 or newer, and VS Code 1.96 or newer are required.

## Run the full check

```powershell
.\scripts\check.ps1
```

The script is fail-fast and runs:

- Ruff lint;
- Ruff formatting verification;
- the full Python test suite;
- TypeScript type checking;
- extension unit and DOM interaction tests;
- the production extension build;
- `npm audit` at high severity;
- an extension package dry run.

Run focused checks while iterating, then run the complete script before committing.

```powershell
python -m pytest tests/test_query.py -q
python -m ruff check service tests

Push-Location .\extension
npm run check
npm test
npm run build
Pop-Location
```

## Run the UI preview

The standalone preview uses checked, clearly labeled interaction data. It is useful for visual development but is not repository truth.

```powershell
Push-Location .\extension
npm run preview
Pop-Location
```

Open the local URL printed by the preview process. Check all six modes, keyboard focus, graph selection, filters, dragging, pan and zoom, narrow layouts, and the textual path view.

For a real extension host:

```powershell
Push-Location .\extension
npm run build
Pop-Location
code --extensionDevelopmentPath="$PWD\extension"
```

## Python boundaries

The Python package owns:

- safe repository discovery;
- deterministic Python AST extraction;
- stable identifiers and Graph IR validation;
- source cards and BYOG payloads;
- HydraDB transport and synchronization;
- normalized query and product-view contracts;
- checkpoints, diffs, change records, and System Lenses;
- loopback HTTP and MCP interfaces;
- explicit Observe events.

Keep HydraDB calls behind `HydraDBClient`. Do not introduce a second retrieval path in views, MCP tools, or the extension.

## TypeScript boundaries

The extension host owns trusted VS Code operations:

- reading the active editor and workspace roots;
- validating service URLs;
- opening source locations;
- executing confirmed write workflows;
- polling and validating Observe events;
- reporting visible workspace changes.

The webview owns presentation state:

- layout, pan, zoom, and filters;
- selected item and inspector state;
- graph and textual-path rendering;
- mode controls and accessible interaction.

The webview must not receive HydraDB credentials or arbitrary filesystem authority.

## Schemas and models

Shared JSON schemas live in `schemas/`. Pydantic models contain additional invariants that are difficult to express in JSON Schema, such as ordered source spans and reference integrity.

When changing a contract:

1. update the Python model;
2. update the JSON schema when it is a shared serialized contract;
3. update normalization and TypeScript adapters;
4. add a valid golden example;
5. add invalid examples for missing, extra, mixed-revision, or fabricated fields;
6. run both Python and extension tests.

Do not make a schema more permissive just to accept an unstable transport response. Normalize the response at the adapter boundary.

## Testing against gaming

Happy-path fixtures are not enough. Tests should prove that the implementation rejects or downgrades:

- missing credentials;
- mixed repositories or revisions;
- non-BYOG paths presented as exact;
- exact edges without complete evidence;
- partial ingest or delete acknowledgements;
- ignored metadata filters;
- cursor gaps and wrong Observe revisions;
- paths outside the selected repository root;
- fabricated evaluation metrics or stale artifacts;
- B/C evaluation requests that differ by more than `graph_context`.

Prefer mutating a known-good fixture in the test. That demonstrates which invariant causes the failure.

## Adding language support

The current analyzer parses Python. New language support should plug into the deterministic analysis boundary and produce the same Graph IR contract.

Before claiming support, add fixtures that measure:

- symbol discovery;
- containment and import edges;
- calls and test relationships where the language permits exact resolution;
- source spans and evidence hashes;
- stable IDs across unchanged revisions;
- honest omission of unresolved dynamic behavior.

Do not create semantic concept nodes to hide missing parser coverage.

## Adding a view or interaction

Every visible control needs one of three outcomes:

- a working result;
- a clear disabled state;
- an honest error.

For graph changes, verify both the canvas and textual representation. For source actions, validate the workspace-relative path and source range in the extension host. For write actions, add preview and confirmation unless the operation is already safely reversible.

## Recording decisions

Human product documentation belongs in `docs/`. Internal design history remains in `.agents/`.

- Add material architecture decisions to `.agents/decisions.md`.
- Add newly verified HydraDB behavior to `.agents/research/sources.md` with a verification date.
- Keep provisional live behavior labeled as provisional.
