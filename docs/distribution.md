# Packaging and distribution

Repository Map is released as six platform-specific VSIX packages. Each package includes the TypeScript extension and a native one-directory Python service build.

## Release targets

| VS Code target | Operating system | Architecture |
| --- | --- | --- |
| `win32-x64` | Windows | x64 |
| `win32-arm64` | Windows | ARM64 |
| `darwin-x64` | macOS | Intel x64 |
| `darwin-arm64` | macOS | Apple silicon |
| `linux-x64` | Linux | x64 |
| `linux-arm64` | Linux | ARM64 |

These are desktop packages. Do not mark them compatible with web, Codespaces, Remote SSH, WSL-hosted extension processes, Alpine, or ARMHF.

## Build pipeline

The release matrix performs these steps on the native target runner:

1. create a locked Python environment;
2. run Ruff and the complete Python suite;
3. build the service with PyInstaller one-directory mode;
4. smoke-test the executable;
5. sign the native binary where required;
6. stage the service and write its protocol/hash manifest;
7. run TypeScript checks, tests, production build, and npm audit;
8. package the target-specific VSIX;
9. create checksums, SBOMs, dependency licenses, and provenance metadata;
10. upload release artifacts.

The package never downloads a runtime on first launch. End users do not need Python or Node.

## Signing

Windows release jobs use the configured code-signing certificate and timestamp service. macOS jobs codesign the application bundle with hardened runtime, submit it for notarization, and staple the result. Unsigned local development packages must not be presented as production artifacts.

## Marketplace publication

Before publishing:

- verify the publisher and repository metadata;
- use a version that matches the release tag;
- run the complete six-target matrix;
- verify every checksum and SBOM;
- inspect the VSIX file list for source secrets or developer artifacts;
- install on clean machines without Python or Node;
- complete the credentialed staging smoke test;
- validate current Codex and Claude Code OAuth registration.

Publish each VSIX with its corresponding Marketplace target. Do not publish one host-built binary as a universal package.

## Staging acceptance

A release is not ready based on fixtures alone. The staging run must cover:

- read-only connection test;
- initial index and verified restart;
- repository query and evidence navigation;
- dirty and clean automatic revisions;
- Compare publication;
- Preserve save and drift;
- Observe session and cursor behavior;
- Codex and Claude Code OAuth access;
- profile reuse and profile switching;
- refresh rotation and revocation;
- service restart and occupied-port recovery.

Record the checksums, exact clients, target package, service protocol, repository identity, and observable results. Never record a database name or API key.
