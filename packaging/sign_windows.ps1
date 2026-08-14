param(
  [Parameter(Mandatory = $true)][string]$Bundle,
  [Parameter(Mandatory = $true)][string]$CertificateBase64,
  [Parameter(Mandatory = $true)][string]$CertificatePassword
)

$ErrorActionPreference = "Stop"
$bundlePath = (Resolve-Path -LiteralPath $Bundle).Path
$mainExecutable = Join-Path $bundlePath "hydra-graph.exe"
if (-not (Test-Path -LiteralPath $mainExecutable -PathType Leaf)) {
  throw "Managed service executable is missing: $mainExecutable"
}
$certificatePath = Join-Path $env:RUNNER_TEMP "repository-map-signing.pfx"
[IO.File]::WriteAllBytes($certificatePath, [Convert]::FromBase64String($CertificateBase64))
try {
  $certificate = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2(
    $certificatePath,
    $CertificatePassword,
    [System.Security.Cryptography.X509Certificates.X509KeyStorageFlags]::EphemeralKeySet
  )
  $nativeFiles = Get-ChildItem -LiteralPath $bundlePath -Recurse -File |
    Where-Object { $_.Extension -in @(".exe", ".dll", ".pyd") }
  if (-not $nativeFiles) {
    throw "Managed service bundle contains no signable Windows files."
  }
  foreach ($file in $nativeFiles) {
    $result = Set-AuthenticodeSignature `
      -FilePath $file.FullName `
      -Certificate $certificate `
      -TimestampServer "http://timestamp.digicert.com" `
      -HashAlgorithm SHA256
    if ($result.Status -ne "Valid") {
      throw "Windows signature is not valid for $($file.Name): $($result.StatusMessage)"
    }
  }
} finally {
  Remove-Item -LiteralPath $certificatePath -Force -ErrorAction SilentlyContinue
}
