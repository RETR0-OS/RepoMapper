# Getting started

This guide describes the packaged desktop extension. It does not require a terminal or a separate service.

## Before you begin

You need:

- local VS Code desktop 1.96 or newer;
- a supported Windows, macOS, or Linux machine;
- a local project folder;
- a HydraDB API key and a database name for that project.

You do not need Python, pip, uv, Node.js, npm, or an MCP process.

## 1. Install and open a project

Install the platform-specific Repository Map package, then open the project folder in VS Code. Repository Map selects the project in this order:

1. the workspace folder containing the active editor;
2. the only open workspace folder;
3. a native folder picker when a multi-root workspace is ambiguous.

Only local `file:` folders are supported. The selected folder is resolved to its canonical path. A parent Git repository does not expand the scan outside the folder you opened.

## 2. Complete first-run setup

The extension offers setup automatically. You can reopen it with **Repository Map: Set Up Repository Map**.

1. Confirm the selected project shown by VS Code.
2. Select an existing HydraDB account profile or create one.
3. Enter the profile API key in the masked field.
4. Enter this project's database name in the masked field.
5. Wait for the read-only connection test.
6. Choose whether to preview the initial index.

A profile owns an API key. A project owns a secret database binding. One profile can be reused across several projects with different databases.

The extension never reveals a stored key or database. Replacing a key requires entering its replacement. Removing a project binding removes the stored database value without deleting HydraDB data.

## 3. Review and confirm indexing

The preview is local analysis only. It shows:

- the exact opened root and repository ID;
- the automatic revision;
- discovered and ignored file counts;
- node and relation counts;
- every generated source card, with a bounded on-screen summary.

A clean Git project uses the full commit SHA as its revision. A dirty or non-Git project uses a deterministic digest of the analyzed content. The confirmation token is single-use and expires after ten minutes. If files change after preview, confirmation is rejected and a new preview is required.

Select **Upload to HydraDB** only after the scope looks right. Repository Map waits for HydraDB to confirm every changed source and deletion. Partial results are shown as failed or indeterminate; they are never relabeled ready.

## 4. Open Repository Map

Open the Repository Map activity item or run **Repository Map: Open Repository Map**. Start with:

- [Repository](views.md#repository) for orientation;
- [Explore](views.md#explore) around a selected entity;
- [Trace](views.md#trace) for a bounded HydraDB path;
- [Observe](observe.md) while an agent works;
- [Compare](compare-and-preserve.md) around a change;
- [Preserve](compare-and-preserve.md) for a shared System Lens.

Selecting a concrete node opens its file and line. Selecting an exact edge opens the evidence that proves it.

## 5. Optionally configure agents

Run **Repository Map: Configure Agents**. The extension detects installed Codex and Claude Code clients, lets you choose them, and previews the exact registration commands. It does not edit their configuration files directly.

The stored registration is only the current loopback `/mcp` URL. On first access:

1. the agent discovers OAuth support;
2. PKCE authorization begins;
3. VS Code opens a native consent flow;
4. you select a registered project if more than one is open;
5. you approve the client name and read-only scopes.

Repository Map must remain open while agents use MCP. See [MCP and agents](mcp-and-agents.md).

## Everyday use

- Run **Index Workspace with HydraDB** after meaningful code changes.
- Use **Start or Finish Comparison** before and after an indexed change; revisions are selected automatically.
- Use **Save as System Lens** only from a verified HydraDB-backed view.
- Use **Replace HydraDB API Key** for credential rotation.
- Use **Review Repository Identity** after initializing Git or changing `origin`.

If setup or indexing fails, no local search result is substituted. See [Troubleshooting](troubleshooting.md).
