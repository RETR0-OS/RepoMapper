param(
  [Parameter(Mandatory = $true)][string]$Executable,
  [Parameter(Mandatory = $true)][string]$CertificateBase64,
  [Parameter(Mandatory = $true)][string]$CertificatePassword
)

$ErrorActionPreference = "Stop"
$certificatePath = Join-Path $env:RUNNER_TEMP "repository-map-signing.pfx"
[IO.File]::WriteAllBytes($certificatePath, [Convert]::FromBase64String($CertificateBase64))
try {
  $certificate = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2(
    $certificatePath,
    $CertificatePassword,
    [System.Security.Cryptography.X509Certificates.X509KeyStorageFlags]::EphemeralKeySet
  )
  $result = Set-AuthenticodeSignature `
    -FilePath $Executable `
    -Certificate $certificate `
    -TimestampServer "http://timestamp.digicert.com" `
    -HashAlgorithm SHA256
  if ($result.Status -ne "Valid") {
    throw "Windows signature is not valid: $($result.StatusMessage)"
  }
} finally {
  Remove-Item -LiteralPath $certificatePath -Force -ErrorAction SilentlyContinue
}
