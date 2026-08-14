# Glossary

[Documentation home](README.md) · [Concepts](concepts.md) · [Graph and evidence](graph-and-evidence.md)

## Aggregate edge

A package- or file-level presentation edge derived from one or more lower-level exact relations. It retains the contributing edge and evidence IDs. It is compression, not a new repository fact.

## BYOG

“Bring your own graph.” The application sends deterministic repository relations alongside source Knowledge. A returned relation with `origin: byog` came from that supplied graph rather than automatic relation extraction.

## Checkpoint

One validated Graph IR snapshot stored locally in the bounded `before` or `after` slot. Checkpoints exist only to compute a deterministic change event; they are not queried for repository answers.

## Current collection

The configured HydraDB Knowledge collection containing the most recently indexed repository source cards. Its default name is `current`.

## Degraded

The service responded but could not provide a fully verified result. Examples include unavailable credentials, an ignored filter, mixed revision data, or an incomplete evolution record. Degraded results do not silently fall back to local search.

## Edge

A directed relation between two concrete graph nodes, such as `CONTAINS`, `IMPORTS`, `CALLS`, or `TESTS`.

## Evidence

The source location and explanation proving why a node or edge exists. Exact edge evidence includes a normalized repository-relative path, complete line and column range, excerpt hash, and derivation explanation.

## Evolution collection

The HydraDB Knowledge collection containing published change-event records and shared System Lens records. Its default name is `evolution`.

## Exact relation

A relation produced by deterministic analysis and backed by complete evidence. Exact relations never carry a confidence score because their status comes from their derivation contract.

## Graph IR

The versioned, validated intermediate representation of a repository revision. It contains concrete nodes, relations, evidence, provenance, stable IDs, repository identity, and revision identity.

## Inferred relation

A non-deterministic or heuristic relation with explicit confidence and evidence. It is visually distinct from exact relations and hidden by default.

## Indeterminate

A synchronization state used when HydraDB may have accepted only part of a write or delete operation. The service cannot honestly claim either the old or candidate remote state is complete.

## Knowledge

HydraDB’s persistent source type used by this MVP for repository cards, graph relations, change events, and the shared System Lens.

## Lens drift

The deterministic comparison between a saved System Lens path and the current grounded path. Examples include unchanged, anchor removed, relation changed, path extended, path shortened, test-coverage relation changed, or unresolved.

## Node

A concrete repository entity: repository, package, file, class, function, method, test, configuration item, or other source-owned object allowed by the Graph IR schema.

## Observe event

A bounded, explicit record of something the application can prove happened, such as a tool query, returned context, a selection, opened evidence, or a visible workspace edit.

## Product view

The bounded, normalized graph response sent to the extension. It includes nodes, edges, aggregates, HydraDB status, warnings, budgets, mode, depth, revision, and an opaque view ID.

## Provenance

How a fact was produced. Important examples are exact deterministic extraction, inferred analysis, semantic retrieval, and HydraDB BYOG origin.

## Revision

The explicit identifier supplied during indexing. It binds source cards, graph facts, queries, views, Observe sessions, checkpoints, and evaluation artifacts to one repository state.

## Source card

A stable HydraDB Knowledge source describing one concrete graph entity and its navigation metadata, summary, revision, repository identity, and owned relations.

## Stable ID

A deterministic identifier derived from logical repository identity rather than a transient database row. Stable IDs allow nodes and edges to be compared across revisions.

## System Lens

A shared, named, grounded view of an important repository path. It stores purpose, anchors, exact relations, evidence, and a reviewed baseline for later drift classification.

## View ID

An opaque identifier for one bounded product view. Observe uses it to validate selections and evidence events without exposing or trusting arbitrary entity IDs.

