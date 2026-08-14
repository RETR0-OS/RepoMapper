$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $true

$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    python -m ruff check service evaluation demo tests
    python -m ruff format --check service evaluation demo tests
    python -m pytest -q

    Push-Location (Join-Path $projectRoot "extension")
    try {
        npm run check
        npm test
        npm run build
        npm audit --audit-level=high
        npm pack --dry-run | Out-Null
    }
    finally {
        Pop-Location
    }
}
finally {
    Pop-Location
}
