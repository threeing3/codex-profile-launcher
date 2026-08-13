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
$requiredRuntimeDlls = @(
    "ffi.dll",
    "libbz2.dll",
    "liblzma.dll",
    "sqlite3.dll",
    "tcl86t.dll",
    "tk86t.dll"
)

if (-not (Test-Path -LiteralPath $icon -PathType Leaf)) {
    throw "Application icon not found: $icon"
}

if (-not (Test-Path -LiteralPath $python)) {
    python -m venv $venv
}

$pythonBase = (& $python -c "import sys; print(sys.base_prefix)").Trim()
if ($LASTEXITCODE -ne 0 -or -not $pythonBase) {
    throw "Unable to determine the Python runtime base directory."
}
$runtimeDllDirectory = Join-Path $pythonBase "Library\bin"
$runtimeBinaryArguments = @()
foreach ($dllName in $requiredRuntimeDlls) {
    $dllPath = Join-Path $runtimeDllDirectory $dllName
    if (-not (Test-Path -LiteralPath $dllPath -PathType Leaf)) {
        throw "Required Python runtime DLL not found: $dllPath"
    }
    $runtimeBinaryArguments += "--add-binary"
    $runtimeBinaryArguments += "$dllPath;."
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
    @runtimeBinaryArguments `
    --distpath $dist `
    --workpath $build `
    --specpath $build `
    (Join-Path $PSScriptRoot "app.py")
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE."
}

$applicationInternalDirectory = Join-Path $dist "CodexProfiles\_internal"
foreach ($dllName in $requiredRuntimeDlls) {
    $bundledDll = Join-Path $applicationInternalDirectory $dllName
    if (-not (Test-Path -LiteralPath $bundledDll -PathType Leaf)) {
        throw "Build validation failed; runtime DLL was not bundled: $bundledDll"
    }
}

$applicationExecutable = Join-Path $dist "CodexProfiles\CodexProfiles.exe"
$verificationTitle = "Codex Profiles Build Verification"
$previousVerificationTitle = $env:CODEX_PROFILE_LAUNCHER_TITLE
$matchingProcesses = @()
try {
    $env:CODEX_PROFILE_LAUNCHER_TITLE = $verificationTitle
    $verificationProcess = Start-Process `
        -FilePath $applicationExecutable `
        -WindowStyle Hidden `
        -PassThru
    $deadline = (Get-Date).AddSeconds(15)
    do {
        Start-Sleep -Milliseconds 500
        $verificationProcess.Refresh()
        $matchingProcesses = Get-Process CodexProfiles -ErrorAction SilentlyContinue | Where-Object {
            $_.Path -eq $applicationExecutable
        }
        foreach ($process in $matchingProcesses) {
            $process.Refresh()
        }
        $expectedWindow = $matchingProcesses | Where-Object {
            $_.MainWindowTitle -eq $verificationTitle
        }
        $errorWindow = $matchingProcesses | Where-Object {
            $_.MainWindowTitle -match "Unhandled exception|Failed to execute script"
        }
    } while (
        -not $verificationProcess.HasExited -and
        -not $expectedWindow -and
        -not $errorWindow -and
        (Get-Date) -lt $deadline
    )
    if ($verificationProcess.HasExited -or -not $expectedWindow -or $errorWindow) {
        $observedTitles = ($matchingProcesses | ForEach-Object { $_.MainWindowTitle }) -join "; "
        throw "Runtime verification failed; observed window titles: $observedTitles"
    }
}
finally {
    $matchingProcesses = Get-Process CodexProfiles -ErrorAction SilentlyContinue | Where-Object {
        $_.Path -eq $applicationExecutable
    }
    foreach ($process in $matchingProcesses) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
    }
    foreach ($process in $matchingProcesses) {
        Wait-Process -Id $process.Id -ErrorAction SilentlyContinue
    }
    $env:CODEX_PROFILE_LAUNCHER_TITLE = $previousVerificationTitle
}

Write-Host "Runtime verification passed: $applicationExecutable"
