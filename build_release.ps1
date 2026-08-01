$ErrorActionPreference = "Stop"

$root = $PSScriptRoot
$isccCandidates = @(
    (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
    (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe"),
    (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe")
)
$iscc = $isccCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1

if (-not $iscc) {
    throw "Inno Setup 6 was not found. Install JRSoftware.InnoSetup first."
}

& (Join-Path $root "build_exe.ps1")
& $iscc (Join-Path $root "installer.iss")

$installer = Join-Path $root "dist-v0.10\CodexProfiles-Setup-v0.10.0.exe"
if (-not (Test-Path -LiteralPath $installer)) {
    throw "Installer build failed: $installer"
}

Write-Host "Installer created: $installer"
