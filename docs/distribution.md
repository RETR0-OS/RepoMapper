# Packaging and distribution

Argus is released as five platform-specific VSIX packages. Each package includes the TypeScript extension and a native one-directory Python service build.

## Release targets

| VS Code target | Operating system | Architecture |
| --- | --- | --- |
| `win32-x64` | Windows | x64 |
| `darwin-x64` | macOS | Intel x64 |
| `darwin-arm64` | macOS | Apple silicon |
| `linux-x64` | Linux | x64 |
| `linux-arm64` | Linux | ARM64 |

These are desktop packages. Do not mark them compatible with web, Codespaces, Remote SSH, WSL-hosted extension processes, Alpine, or ARMHF.

Windows on ARM64 has no package of its own. The managed service needs the
`cryptography` package, PyPI publishes no `win_arm64` wheel for it, and the ARM
runner cannot build one from source. Windows on ARM64 installs the `win32-x64`
package and runs it under emulation.

## Development setup

Run these commands from PowerShell in the repository root. The packaging extra
installs PyInstaller, SBOM tooling, and the license inventory tool in addition
to the normal development dependencies.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev,packaging]"

Push-Location .\extension
npm ci
Pop-Location
```

Python 3.11 or newer, Node.js 20 or newer, and VS Code 1.96 or newer are
required to build from source. End users do not need these tools.

### Run all checks

The checked-in script runs Python lint and tests, TypeScript checking, extension
tests, the production webview build, npm audit, and a VSIX dry run.

```powershell
.\scripts\check.ps1
```

Useful focused commands while developing are:

```powershell
python -m pytest -q
python -m ruff check service evaluation demo tests packaging
python -m ruff format --check service evaluation demo tests packaging

Push-Location .\extension
npm run check
npm test
npm run build
npm audit --audit-level=high
Pop-Location
```

### Run the UI preview

The standalone preview exercises the six webview modes using clearly labeled
fixture data. It does not start HydraDB or claim to show repository results.

```powershell
Push-Location .\extension
npm run preview
```

Open the URL printed by the command. Press `Ctrl+C`, then run `Pop-Location`
when finished.

### Run an Extension Development Host

Build the TypeScript extension, then open a second VS Code window that loads
this checkout as the extension under development:

```powershell
Push-Location .\extension
npm run build
Pop-Location

code --extensionDevelopmentPath="$PWD\extension"
```

This command uses the service bundle currently staged under
`extension/resources/service`. To test a freshly changed Python service, build
and stage it first using the next section.

## Build a local VSIX

PyInstaller does not cross-compile. Run these commands on the operating system
and architecture named by `$target`. The following example builds Windows x64;
replace the target only when running on its matching native machine.

```powershell
$target = "win32-x64"

python -m PyInstaller --noconfirm --clean packaging/hydra_graph.spec
python packaging/smoke_managed.py `
  --bundle dist/hydra-graph `
  --target $target
python packaging/stage_service.py `
  --source dist/hydra-graph `
  --extension extension `
  --target $target

New-Item -ItemType Directory -Force .\artifacts | Out-Null
Push-Location .\extension
npm ci
npm run check
npm test
npm run build
npx vsce package `
  --target $target `
  --ignore-other-target-folders `
  --out "..\artifacts\repository-map-$target.vsix"
Pop-Location
```

The resulting local package is unsigned and intended only for development. It
still contains the complete native service, so the test machine does not need
Python or Node.

### Install and test the local package

```powershell
$target = "win32-x64"
code --install-extension ".\artifacts\repository-map-$target.vsix" --force
code .
```

In VS Code, run **Developer: Reload Window**, then run **Argus: Setup**
from the Command Palette. Complete the masked HydraDB setup, review the index
preview, cancel once to prove cancellation is safe, then confirm a fresh
preview. Exercise Repository, Explore, Trace, Observe, Compare, and Preserve.

To remove the development installation:

```powershell
code --uninstall-extension hack-hydra.hydra-repository-observability
```

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

## Create local release metadata

After building one local target, create its Python and Node SBOMs, checksums,
and Python dependency license inventory:

```powershell
$target = "win32-x64"

cyclonedx-py environment `
  --output-format JSON `
  --output-file ".\artifacts\repository-map-$target.python.cdx.json"

Push-Location .\extension
npm sbom --json |
  Set-Content -Encoding utf8 "..\artifacts\repository-map-$target.node.cdx.json"
Pop-Location

python packaging/release_metadata.py .\artifacts
Get-Content .\artifacts\SHA256SUMS.json
```

These commands create evidence for a local build. They do not sign, notarize,
publish, or prove another platform target.

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

### Build the signed release matrix

The GitHub Actions workflow builds all six native targets. A version tag also
enables Windows signing, macOS signing/notarization, and provenance attestation.
Configure the release secrets described in the workflow before pushing a tag.

```powershell
$version = "0.1.0"
git tag "v$version"
git push origin "v$version"
```

These commands create and push a public release tag. Run them only after the
version is final, the working tree is clean, the complete check passes, and the
required signing secrets are configured. Monitor **Build platform extensions**
in GitHub Actions and download all six `repository-map-<target>` artifacts.

### Publish verified VSIX packages

After completing staging acceptance on the downloaded signed packages, publish
them with VS Code Marketplace authentication. This example uses the supported
Microsoft Entra credential flow instead of placing a Marketplace token in the
command line:

```powershell
Push-Location .\extension
$packages = Get-ChildItem ..\artifacts\repository-map-*.vsix |
  ForEach-Object { $_.FullName }
npx vsce publish --azure-credential --packagePath $packages
Pop-Location
```

Publishing changes the Marketplace. Review `$packages` before running the
command and do not publish unsigned local packages.

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
