export interface ReleaseTarget {
  vscodeTarget: string
  os: string
  arch: string
  artifact: string
  platformKey: "windows" | "mac" | "linux"
}

export const releaseTargets: ReleaseTarget[] = [
  { vscodeTarget: "win32-x64", os: "Windows", arch: "x64", artifact: "argus-win32-x64.vsix", platformKey: "windows" },
  { vscodeTarget: "win32-arm64", os: "Windows", arch: "ARM64", artifact: "argus-win32-arm64.vsix", platformKey: "windows" },
  { vscodeTarget: "darwin-x64", os: "macOS", arch: "Intel x64", artifact: "argus-darwin-x64.vsix", platformKey: "mac" },
  { vscodeTarget: "darwin-arm64", os: "macOS", arch: "Apple silicon", artifact: "argus-darwin-arm64.vsix", platformKey: "mac" },
  { vscodeTarget: "linux-x64", os: "Linux", arch: "x64", artifact: "argus-linux-x64.vsix", platformKey: "linux" },
  { vscodeTarget: "linux-arm64", os: "Linux", arch: "ARM64", artifact: "argus-linux-arm64.vsix", platformKey: "linux" },
]

export const installCommand = (artifact: string) =>
  `code --install-extension ${artifact}`

const RELEASES_BASE = "https://github.com/RETR0-OS/Argus/releases/latest/download"

export const downloadUrl = (artifact: string) => `${RELEASES_BASE}/${artifact}`
