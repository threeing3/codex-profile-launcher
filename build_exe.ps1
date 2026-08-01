$ErrorActionPreference = "Stop"

$venv = Join-Path $PSScriptRoot ".venv-build"
$python = Join-Path $venv "Scripts\python.exe"
$dist = Join-Path $PSScriptRoot "dist-v0.10"
$build = Join-Path $PSScriptRoot "build-v0.10"

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
    --distpath $dist `
    --workpath $build `
    --specpath $build `
    (Join-Path $PSScriptRoot "app.py")
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE."
}
