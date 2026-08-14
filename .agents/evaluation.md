# Evaluation and Hackathon Proof

## Goal

Prove that **HydraDB graph-backed retrieval gives coding agents more useful repository context than similarity-only retrieval**, while the VS Code experience gives programmers a clearer understanding of the same context and its evolution.

The evaluation must make HydraDB's unique contribution visible. A polished graph animation without retrieval evidence is not enough.

## Core hypotheses

### H1: Graph context improves relevance

For repository questions that require calls, types, tests, imports, or configuration, HydraDB with deterministic BYOG relations returns more required evidence than similarity-only retrieval.

### H2: Graph context reduces waste

For the same answer quality, HydraDB graph-backed context uses fewer irrelevant source tokens.

### H3: Shared visualization improves comprehension

A programmer can identify what context the agent received and why each source was relevant.

### H4: Graph diff improves change understanding

A programmer can identify important structural effects of an agent edit faster than by reading a file list or diff alone.

## Required ablation

Run the same questions through three conditions:

| Condition | Retrieval |
|---|---|
| A. Naive baseline | Conventional embedding/chunk similarity or the simplest available vector baseline |
| B. HydraDB without graph | HydraDB ranked chunks with graph context disabled |
| C. **HydraDB with deterministic BYOG graph** | HydraDB hybrid query, thinking mode, graph context enabled |

This separates “HydraDB is a good retriever” from “HydraDB's graph capability matters.”

If time permits, add literal repository search as a diagnostic baseline, not as a fake semantic competitor.

## Question set

Use concrete repository questions with known evidence. Examples:

### Flow

- How does an incoming request reach the database write?
- What happens after this event is published?
- Which startup configuration activates this handler?

### Type and implementation

- Which concrete implementation is used for this interface?
- What constructs and returns this type?

### Tests

- Which tests exercise the authorization path?
- What production symbols does this integration test reach?

### Change impact

- Which important flows changed after this agent task?
- Did the edit add a new cross-module dependency?
- Which test relationship disappeared?

### Conceptual plus structural

- Where is access control enforced?
- How does retry behavior work across the job pipeline?

Every question needs a hand-checked gold set of required symbols, relations, and source spans.

## Retrieval metrics

- Required-symbol recall.
- Required-relation recall.
- Context precision: useful retrieved chunks divided by total retrieved chunks.
- Path correctness: correct edges divided by displayed edges.
- Unsupported-edge count.
- Token count.
- Useful evidence per 1,000 tokens.
- Query latency.
- Indexing latency after a change.
- Empty-graph-context rate.

Report exact and inferred edges separately.

## Agent metrics

Run Codex and Claude Code through the same MCP interface.

- Task completion.
- Correct files changed.
- Unnecessary files opened or edited.
- Repository tool calls.
- HydraDB query calls.
- Context characters returned.
- Tests passed.
- Rework after an incorrect assumption.

Do not compare hidden reasoning. Compare observable outcomes and tool use.

## Human comprehension study

Even a small structured study is useful. Give participants an unfamiliar demo repository and ask them to:

1. Identify how one important flow works.
2. Identify which context the agent used.
3. Identify what changed after the task.
4. Find the evidence for one relation.

Compare:

- VS Code diff and file list only.
- Product graph path and Change Map.

Measure completion time and answer accuracy. Record qualitative confusion points.

## Graph extraction metrics

- Symbol precision and recall per language fixture.
- Relation precision and recall per predicate.
- Unresolved-reference rate.
- Stable ID rate across unchanged revisions.
- Rename-match precision.
- Stale-edge count after deletion.
- BYOG source size and degree-limit violations.

## Demo acceptance criteria

The demo is ready only when:

- A real repository has been ingested into a real HydraDB database.
- Returned paths visibly contain `origin: "byog"` relations.
- A conceptual question returns a useful multi-hop path.
- The path can be opened to exact source evidence.
- An agent uses the custom MCP interface against HydraDB.
- Agent View highlights the returned path and context.
- A code edit produces a verified HydraDB revision.
- Change Map shows at least one meaningful edge delta.
- A saved System Lens reports a truthful change or remains explicitly unchanged.
- The HydraDB graph-enabled condition beats graph-disabled HydraDB on at least the relational anchor questions.

## Judge-facing evidence

Show these artifacts:

- Architecture diagram with HydraDB at the center.
- Live HydraDB indexing status.
- Raw-to-product mapping of one `query_paths` response.
- BYOG origin and deterministic evidence for one edge.
- Side-by-side graph-disabled versus graph-enabled retrieval.
- Agent View replay.
- Before/after graph delta.
- A small metric table, even if the dataset is modest.

Avoid claims such as “X% better” unless the test set, scoring method, and raw results are available.
