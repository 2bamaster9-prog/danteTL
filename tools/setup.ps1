param([switch]$Gpu, [switch]$Gemma)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$env:UV_CACHE_DIR = Join-Path $projectRoot '.uv-cache'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $projectRoot '.python'

if (Get-Command uv -ErrorAction SilentlyContinue) {
    $uvCommand = (Get-Command uv).Source
} else {
    $bootstrapPython = Join-Path $projectRoot '.bootstrap\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $bootstrapPython)) {
        python -m venv (Join-Path $projectRoot '.bootstrap')
        if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 or later is needed for initial setup.' }
    }
    $uvCommand = Join-Path $projectRoot '.bootstrap\Scripts\uv.exe'
    if (-not (Test-Path -LiteralPath $uvCommand)) {
        & $bootstrapPython -m pip install 'uv==0.13.8'
        if ($LASTEXITCODE -ne 0) { throw 'Could not install the project-local uv bootstrap.' }
    }
}

$gemmaArgs = @()
if ($Gemma -or (Test-Path -LiteralPath (Join-Path $projectRoot 'models\gemma-4-e2b\gemma-4-E2B_q4_0-it.gguf'))) {
    $gemmaArgs = @('--group', 'gemma')
}
if ($Gpu) {
    $env:UV_PROJECT_ENVIRONMENT = Join-Path $projectRoot '.venv-gpu'
    & $uvCommand sync --locked --no-default-groups --group gpu --group dev @gemmaArgs
} else {
    $env:UV_PROJECT_ENVIRONMENT = Join-Path $projectRoot '.venv'
    & $uvCommand sync --locked @gemmaArgs
}
if ($LASTEXITCODE -ne 0) { throw 'Dependency setup failed. Check the network connection and retry.' }
Write-Host 'JP Overlay is ready. Double-click Run JP Overlay.cmd.'
