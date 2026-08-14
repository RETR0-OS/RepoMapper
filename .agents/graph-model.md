# Graph Model

## Goal

Represent enough repository structure to answer “what is this?”, “what is related?”, “how does this flow?”, “what did the agent see?”, and “what changed?” without pretending static analysis knows every runtime behavior.

The analyzer emits Graph IR. HydraDB receives source cards plus deterministic BYOG relations derived from that IR.

## Graph levels

### Repository structure

```text
repository → package/module → file → symbol
```

Used for overview, semantic zoom, and navigation.

### Repository behavior

```text
entrypoint → handler → service → adapter → datastore/event/external API
```

Used for cross-file and cross-language traces.

### Function-local control flow

```text
entry block → condition → branch/loop/call → return/throw
```

Generated on demand for a selected function. It is not stored for every function in the MVP.

## Node kinds

Core:

- `REPOSITORY`
- `PACKAGE`
- `MODULE`
- `FILE`
- `CLASS`
- `INTERFACE`
- `TYPE`
- `FUNCTION`
- `METHOD`
- `VARIABLE`
- `CONSTANT`
- `TEST`
- `ENTRYPOINT`
- `CONFIG_BLOCK`
- `INFRA_BLOCK`
- `BUILD_TARGET`
- `ROUTE`
- `EVENT`
- `DATASTORE`
- `EXTERNAL_SERVICE`
- `SYSTEM_LENS`
- `CHANGE_EVENT`

Parsers may emit language-specific kinds, but the normalized kind must also be present.

## Relation predicates

### Structural

- `CONTAINS`
- `DEFINES`
- `DECLARES`
- `IMPORTS`
- `EXPORTS`
- `REFERENCES`

### Type and implementation

- `EXTENDS`
- `IMPLEMENTS`
- `OVERRIDES`
- `RETURNS`
- `ACCEPTS`
- `INSTANTIATES`

### Behavioral

- `CALLS`
- `MAY_CALL`
- `DISPATCHES_TO`
- `HANDLES`
- `EMITS`
- `SUBSCRIBES_TO`
- `READS_FROM`
- `WRITES_TO`
- `THROWS`

### Validation

- `TESTS`
- `MOCKS`
- `ASSERTS_BEHAVIOR_OF`
- `USES_FIXTURE`

### Configuration and runtime wiring

- `CONFIGURES`
- `RESOLVES_TO`
- `LOADS`
- `PROVIDES`
- `DEPLOYS`
- `INVOKES`

### Evolution

- `ADDED_IN`
- `REMOVED_IN`
- `CHANGED_IN`
- `RENAMED_TO`
- `REPLACES`
- `DRIFTS_FROM`

Keep the predicate vocabulary small and documented. Do not create synonyms for the same relation merely because different parsers use different wording.

## Stable identifiers

Graph IR needs a deterministic identifier independent of HydraDB's request-local entity key.

Recommended identity inputs:

- Repository identity.
- Normalized relative path.
- Normalized language.
- Symbol kind.
- Qualified name.
- Signature discriminator where overloading exists.

Example logical ID:

```text
repo:<repo-id>:python:src/payments/auth.py:function:payments.auth.authorize_user
```

Hash this logical ID for compact storage but retain the readable form for debugging.

Renames break name-based identity. Revision comparison should attempt deterministic rename matching using syntax kind, signature, body fingerprint, and surrounding ownership. Record a rename only above an explicit threshold and retain evidence.

## Node record

Every node should contain:

```text
id
kind
display_name
qualified_name
language
path
span
signature
revision_id
content_hash
parser
parser_version
is_generated
attributes
```

Not every field applies to every kind. Avoid fake values.

## Edge record

Every edge should contain:

```text
id
source_id
predicate
target_id
quality
confidence
evidence[]
revision_id
extractor
extractor_version
attributes
```

`quality` is one of:

- `exact` — syntax, compiler/language-service resolution, or explicit configuration proves the relation.
- `inferred` — a deterministic heuristic suggests the relation but cannot prove it.
- `semantic` — derived from a semantic process rather than code resolution.
- `unknown` — retained only for diagnostics; not shown as a normal edge.

Use confidence only where it has a defined meaning. Exact relations do not need a decorative probability.

## Evidence

An evidence record should include:

```text
path
start_line
start_column
end_line
end_column
excerpt_hash
explanation
```

The relation context sent to HydraDB should state the relationship and evidence plainly, for example:

```text
payments.api.create_order calls payments.service.submit_order at src/payments/api.py:48.
```

Keep this context below HydraDB's 2,000-character relation limit. Usually one sentence is enough.

## Source ownership of relations

Each relation must have one canonical owning source to avoid duplicate BYOG triplets.

Recommended rules:

- A call or reference relation belongs to the source symbol containing the call/reference.
- A `DEFINES` relation belongs to the file/module summary source.
- A type relation belongs to the declaring symbol.
- A `TESTS` relation belongs to the test source.
- A configuration/runtime relation belongs to the configuration source that declares the link.
- A change relation belongs to the change-event source.

The target entity may be defined by another source. Its globally unambiguous HydraDB name must be consistent in both payloads.

## Symbol knowledge card

A generated source card should be readable by both HydraDB retrieval and humans:

```text
Entity: authorize_user
Qualified name: payments.auth.authorize_user
Kind: function
Language: Python
Path: src/payments/auth.py
Lines: 31-67
Signature: authorize_user(session, action, resource) -> Decision
Summary: Evaluates a session against the configured policy store.

Code:
<exact bounded source excerpt>

Known exact relations:
- Called by payments.api.handle_request.
- Reads from payments.auth.PolicyStore.
- Tested by tests.auth.test_authorize_user.
```

Do not generate an LLM summary during deterministic ingestion unless clearly labeled and separately stored. A docstring or syntax-derived summary is acceptable.

## Control-flow honesty

Repository-level flow is mostly an interprocedural relation graph, not a perfect runtime trace.

The UI must distinguish:

- `CALLS`: statically resolved call.
- `MAY_CALL`: possible dynamic target.
- `DISPATCHES_TO`: framework or routing configuration links an entry to a handler.
- Observed runtime edges, if added later, with a separate provenance class.

Dynamic dispatch, reflection, dependency injection, generated code, native boundaries, and external services can make paths incomplete. Show gaps explicitly rather than inventing continuity.

## Semantic zoom

The same data should support different resolutions:

1. Repository view: packages and major modules.
2. Module view: files and public symbols.
3. Symbol view: callers, callees, tests, and types.
4. Function view: optional local control-flow graph.

Collapsing nodes is a presentation operation. It must not alter HydraDB facts.

## Graph deltas

A graph delta compares two verified revisions and contains:

- Added, removed, modified, and renamed nodes.
- Added and removed edges.
- Evidence-span changes.
- Saved System Lenses that no longer resolve to the same path.
- Structural warnings such as a new cycle or lost test relation.

Every delta item records both revision IDs and its deterministic comparison evidence.

Do not call a structural warning a defect unless a test or rule proves it.
