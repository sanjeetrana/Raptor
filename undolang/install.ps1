param(
    [string]$SourceBinary = ".\undo.exe",
    [string]$InstallDir = "$env:LOCALAPPDATA\UndoLang\bin",
    [switch]$InstallGo,
    [switch]$NoInstallGo
)

$ErrorActionPreference = "Stop"
$temporaryBinary = $null
$goVersion = "1.27.0"

function Test-CompatibleGo {
    param([Parameter(Mandatory = $true)][string]$Path)
    $previousToolchain = $env:GOTOOLCHAIN
    try {
        $env:GOTOOLCHAIN = "local"
        $version = (& $Path version 2>$null | Out-String).Trim()
        return $version -match "\bgo1\.27(?:\.\d+)?(?:\s|$)"
    }
    catch {
        return $false
    }
    finally {
        if ($null -eq $previousToolchain) {
            Remove-Item Env:GOTOOLCHAIN -ErrorAction SilentlyContinue
        }
        else {
            $env:GOTOOLCHAIN = $previousToolchain
        }
    }
}

function Get-ExistingGo {
    $command = Get-Command go -CommandType Application -ErrorAction SilentlyContinue
    if ($command -and (Test-CompatibleGo -Path $command.Source)) {
        return $command.Source
    }
    return $null
}

function Install-PinnedGo {
    $architecture = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString().ToLowerInvariant()
    switch ($architecture) {
        "x64" { $goArch = "amd64" }
        "arm64" { $goArch = "arm64" }
        default { throw "automatic Go bootstrap does not support Windows architecture '$architecture'; install Go 1.27.x manually" }
    }

    $archive = "go$goVersion.windows-$goArch.zip"
    $expected = switch ($archive) {
        "go1.27.0.windows-amd64.zip" { "f0c0a0d33ba94f4d2c5dbc887334ce678b21813504ddb3aafcb06e60a5a667c4" }
        "go1.27.0.windows-arm64.zip" { "6e0156b9788209931dd340fadc04171ce15063c17b51c92e7b86b51109626e90" }
        default { throw "no pinned Go checksum for $archive" }
    }

    $toolchainDir = Join-Path $env:LOCALAPPDATA "UndoLang\toolchains\go$goVersion"
    $goCommand = Join-Path $toolchainDir "bin\go.exe"
    if (Test-Path -LiteralPath $goCommand -PathType Leaf) {
        if (-not (Test-CompatibleGo -Path $goCommand)) {
            throw "existing toolchain is not a compatible Go $goVersion: $toolchainDir"
        }
        return $goCommand
    }
    if (Test-Path -LiteralPath $toolchainDir) {
        throw "toolchain directory exists but is incomplete: $toolchainDir (remove it manually and retry)"
    }

    $temporaryRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("undolang-go-" + [System.Guid]::NewGuid())
    try {
        New-Item -ItemType Directory -Path $temporaryRoot | Out-Null
        $archivePath = Join-Path $temporaryRoot $archive
        Write-Host "Downloading Go $goVersion for windows/$goArch from go.dev..."
        Invoke-WebRequest -UseBasicParsing -Uri "https://go.dev/dl/$archive" -OutFile $archivePath
        $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $archivePath).Hash.ToLowerInvariant()
        if ($actual -ne $expected) {
            throw "Go archive checksum mismatch for $archive"
        }
        Expand-Archive -LiteralPath $archivePath -DestinationPath $temporaryRoot
        $extracted = Join-Path $temporaryRoot "go"
        if (-not (Test-Path -LiteralPath (Join-Path $extracted "bin\go.exe") -PathType Leaf)) {
            throw "Go archive did not contain the expected toolchain"
        }

        $parent = Split-Path -Parent $toolchainDir
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
        if (Test-Path -LiteralPath $toolchainDir) {
            throw "toolchain directory appeared during installation: $toolchainDir"
        }
        Move-Item -LiteralPath $extracted -Destination $toolchainDir
        Write-Host "Installed Go $goVersion at $toolchainDir (user-local)."
        return $goCommand
    }
    finally {
        if (Test-Path -LiteralPath $temporaryRoot) {
            Remove-Item -LiteralPath $temporaryRoot -Recurse -Force
        }
    }
}

try {
    if ($InstallGo -and $NoInstallGo) {
        throw "-InstallGo and -NoInstallGo cannot be used together"
    }
    if (-not (Test-Path -LiteralPath $SourceBinary -PathType Leaf)) {
        if ($SourceBinary -ne ".\undo.exe" -or -not (Test-Path -LiteralPath ".\go.mod" -PathType Leaf)) {
            throw "UndoLang binary not found: $SourceBinary"
        }
        $goCommand = Get-ExistingGo
        if (-not $goCommand) {
            if ($NoInstallGo) {
                throw "Go 1.27.x is required to build the source tree; rerun without -NoInstallGo to install Go $goVersion locally"
            }
            $goCommand = Install-PinnedGo
        }
        $temporaryBinary = Join-Path ([System.IO.Path]::GetTempPath()) ("undolang-install-" + [System.Guid]::NewGuid() + ".exe")
        Write-Host "Building UndoLang from the local source tree with $goCommand..."
        $env:GOPROXY = "off"
        $env:GOTOOLCHAIN = "local"
        $env:CGO_ENABLED = "0"
        & $goCommand build -trimpath -buildvcs=false -o $temporaryBinary ./cmd/undo
        if ($LASTEXITCODE -ne 0) { throw "Go build failed" }
        $SourceBinary = $temporaryBinary
    }

    New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
    $destination = Join-Path $InstallDir "undo.exe"
    Copy-Item -LiteralPath $SourceBinary -Destination $destination -Force
    Write-Host "Installed UndoLang at $destination"
    if (($env:PATH -split ";") -notcontains $InstallDir) {
        Write-Host "Add $InstallDir to your user PATH to invoke 'undo' directly."
    }
}
finally {
    if ($temporaryBinary -and (Test-Path -LiteralPath $temporaryBinary)) {
        Remove-Item -LiteralPath $temporaryBinary -Force
    }
}
