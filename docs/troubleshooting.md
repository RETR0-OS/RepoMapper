# Troubleshooting

This guide starts with the packaged extension. Developer-only problems are at the end.

## Setup did not appear

Run **Repository Map: Set Up Repository Map**. Make sure a local folder is open. Remote workspaces, WSL extension hosts, Codespaces, and web VS Code are not supported in this release.

In a multi-root workspace, open a file in the intended folder or select it from the native picker.

## Read access test failed

Repository Map does not show the stored key or database. Check the values outside the extension, then:

- run **Replace HydraDB API Key** to enter a replacement key;
- run **Remove Project Database Binding**, then setup, to enter the database again;
- confirm normal HTTPS access to HydraDB is allowed by the machine/network.

The test is read-only. Failure does not upload repository data.

## Managed service is unavailable

Try **Repository Map: Refresh Repository Map**. A stale window session is invalidated automatically after a network or authentication failure; the next request can take ownership and restart the service.

Open **Output: Repository Map Service** for bounded diagnostics. Do not paste secrets into issue reports.

If the bundled service hash or protocol is wrong, reinstall the exact platform package. The extension intentionally refuses an unknown or modified binary.

## Port 8765 is occupied

The extension chooses a stable alternate loopback port automatically. Run **Configure Agents** again if an existing Codex or Claude Code registration still points to an old port. Repository Map never edits agent configuration silently.

## Index preview changed or expired

Preview tokens are single-use and expire after ten minutes. They are also rejected when analyzed files change. Run **Index Workspace with HydraDB** again, review the new revision/scope, and reconfirm.

## Indexing is failed or indeterminate

Do not treat the last revision label as proof that all old content remains visible. Retry only after HydraDB is available and review the full new preview. A successful full sync restores a verified manifest.

If a legacy manifest had a database field, Repository Map removes it. A mismatched secure binding leaves the project unverified until a new confirmed index succeeds.

## Git identity changed

Run **Review Repository Identity**. Repository Map keeps the existing ID unless it can prove that migration will not orphan indexed current or evolution sources. An unindexed local identity can migrate with its SecretStorage binding. An indexed identity requires an explicit data reset/migration outside this release.

Raw remote URLs are never shown because they may contain credentials.

## Codex or Claude Code was not detected

Run the client from a normal terminal and confirm its executable is on the VS Code extension-host `PATH`. Restart VS Code after installing a client, then run **Configure Agents** again.

The command previews exactly what it will run. It does not overwrite client config files.

## OAuth did not complete

- Keep VS Code and the project open.
- Allow VS Code to handle its own `vscode://` URI.
- Check that the client uses a loopback HTTP redirect and PKCE S256.
- Restart agent setup if the 60-second code expired.
- Reauthorize after refresh-token revocation.

If several projects are open, select the intended project in the native consent UI. A closed or ambiguous project is rejected.

## MCP stops after closing VS Code

This is expected. MCP shares the managed service and is available only while VS Code runs. Reopen the project and retry the agent action.

## Observe stopped

Observe fails closed on revision drift, root mismatch, inactive session, malformed events, or an evicted history cursor. Use **Restart follow** after restoring one verified revision. It never skips a missing event range.

## Compare cannot finish

Index the before state, start the comparison, make the change, index the changed state, then finish. The before and after verified revisions must differ. Both checkpoints remain local until HydraDB confirms delta publication.

## Preserve has no grounded lens

Open a verified HydraDB view containing at least one exact connected edge. A System Lens cannot be created from preview data, automatic relations, empty views, or unverified revisions.

## Developer mode

Only contributors should enable `hydra.developerMode`. In that mode, install the Python and Node dependencies from [Development](development.md), start the service separately, and use the developer loopback URL. Environment credentials belong only to that explicit process and do not test SecretStorage/managed IPC behavior.
