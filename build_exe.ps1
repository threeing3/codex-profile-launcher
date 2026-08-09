param(
    [string]$DistDirectory = "dist-v0.10",
    [string]$BuildDirectory = "build-v0.10"
)

$ErrorActionPreference = "Stop"

$venv = Join-Path $PSScriptRoot ".venv-build"
$python = Join-Path $venv "Scripts\python.exe"
$dist = if ([System.IO.Path]::IsPathRooted($DistDirectory)) { $DistDirectory } else { Join-Path $PSScriptRoot $DistDirectory }
$build = if ([System.IO.Path]::IsPathRooted($BuildDirectory)) { $BuildDirectory } else { Join-Path $PSScriptRoot $BuildDirectory }
$icon = Join-Path $PSScriptRoot "assets\codex-profiles.ico"
$iconData = "$icon;assets"

if (-not (Test-Path -LiteralPath $icon -PathType Leaf)) {
    throw "Application icon not found: $icon"
}

if (-not (Test-Path -LiteralPath $python)) {
    python -m venv $venv
}

& $python -m pip install --disable-pip-version-check -r (Join-Path $PSScriptRoot "requirements-build.txt")
if ($LASTEXITCODE -ne 0) {
    throw "Build dependency installation failed with exit code $LASTEXITCODE."
}

& $python -m PyInstaller `
    --noconfirm `
    --clean `
    --windowed `
    --name "CodexProfiles" `
    --icon $icon `
    --add-data $iconData `
    --distpath $dist `
    --workpath $build `
    --specpath $build `
    (Join-Path $PSScriptRoot "app.py")
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE."
}
