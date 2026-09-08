$ErrorActionPreference = "Stop"
$RepoDir = Split-Path -Parent $PSScriptRoot
$DistDir = Join-Path $RepoDir "dist"
New-Item -ItemType Directory -Force -Path $DistDir | Out-Null
$env:CGO_ENABLED = "0"
$env:GOTOOLCHAIN = "go1.27.0"
$env:GOPROXY = "off"
Push-Location $RepoDir
try {
    go build -trimpath -buildvcs=false -o (Join-Path $DistDir "undo.exe") ./cmd/undo
}
finally {
    Pop-Location
}
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host "built $(Join-Path $DistDir 'undo.exe')"
