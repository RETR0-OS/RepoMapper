# Managed runtime

The packaged extension owns the full local runtime.

## Startup

The first active VS Code window:

1. loads the installation control key from SecretStorage;
2. checks the last managed port;
3. looks for a compatible service using the version-discovery endpoint;
4. acquires an owner lock in VS Code global storage;
5. validates the bundled executable path and SHA-256 manifest;
6. starts it on `127.0.0.1` with private stdin/stdout IPC;
7. completes a signed project challenge;
8. receives a short-lived project token.

The executable receives no HydraDB credential in argv or environment. The packaged runtime starts with an empty HydraDB configuration and requests credentials through IPC only when an operation needs them.

## Multiple windows

Other VS Code windows use the installation key to sign their own canonical project challenges. The service creates an isolated container per `(canonical root, repository ID)` and issues a token bound to that pair.

If the owner closes, its child stops and its lock is released. An attached window invalidates its stale session after a connection or 401 failure. Its next operation can acquire ownership, restart the service, and register its project again. A crashed owner's stale lock is replaced only after the recorded process is proven absent.

## Port selection

Port 8765 is preferred. If it is unavailable and does not answer with the exact managed protocol, the extension chooses a stable alternative from a small installation-specific range. Only the port number is stored. Agent configuration is changed only through a later confirmed **Configure Agents** run.

## Version and integrity checks

The extension and service share versioned protocols for:

- public service discovery and project challenge;
- framed private IPC;
- query responses;
- ProductViews.

A mismatch fails closed. The extension accepts the previous ProductView schema for one migration release, drops any legacy database field immediately, and refuses unknown versions.

Release builds include a platform manifest with the service executable SHA-256. The extension hashes the executable before every start. Windows and macOS release workflows also require platform signing; macOS artifacts are notarized before publication.

## Shutdown and logs

The owning extension host terminates the service when it is disposed. The service output channel receives bounded printable diagnostics only. Public HydraDB failures are generic so a remote error message cannot echo a key or database into UI, logs, events, or MCP output.
