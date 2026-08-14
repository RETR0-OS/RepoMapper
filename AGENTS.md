# Agent Navigation Index

This repo is a Hack Hydra project workspace. It is currently mostly product and architecture notes, not implementation code.

## Start Here

Read [.agents/README.md](.agents/README.md) first. It explains the project direction, the central HydraDB rule, and the recommended reading order.

The active project direction is Track B: a HydraDB-backed VS Code extension for repository observability in the age of agentic coding.

## Repo Map

- `.agents/` - main product, architecture, graph model, evaluation, roadmap, and decision documents.
- `.agents/research/` - source notes and dated HydraDB research findings.
- `tracks/` - original hackathon track idea notes.
- `.gitignore` - currently ignores `tracks/`.

## Key Documents

- `.agents/product.md` - product definition, users, core modes, demo story.
- `.agents/hydradb.md` - verified HydraDB capabilities and limits.
- `.agents/architecture.md` - component boundaries and data flow.
- `.agents/graph-model.md` - graph nodes, relations, evidence, and revisions.
- `.agents/vscode-experience.md` - human-facing VS Code extension behavior.
- `.agents/agent-interface.md` - agent-facing tools, context paths, and path events.
- `.agents/ingestion-and-sync.md` - deterministic analysis and HydraDB synchronization.
- `.agents/evolution.md` - graph diffs and living system lenses.
- `.agents/evaluation.md` - how to prove graph-backed retrieval helps.
- `.agents/roadmap.md` - build order and acceptance criteria.
- `.agents/decisions.md` - decisions already made.
- `.agents/open-questions.md` - unresolved choices and current recommendations.

## Track Notes

- `tracks/A.md` - supply chain blast radius idea.
- `tracks/B.md` - code graphs for IDE assistants idea.

## Working Rules

- Keep language plain, direct, and explainable.
- Treat HydraDB as the required knowledge and retrieval substrate.
- Do not replace HydraDB with a local graph store or silent fallback.
- Preserve user changes and avoid unrelated rewrites.
- Record material product or architecture decisions in `.agents/decisions.md`.
- Record new HydraDB research findings in `.agents/research/sources.md` with a verification date.
- Prefer focused graph views over rendering a whole-repo hairball.
- Keep exact and inferred relations visually and structurally distinct.
