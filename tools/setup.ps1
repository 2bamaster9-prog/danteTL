param([switch]$Gpu, [switch]$Gemma, [switch]$Amd)
$ErrorActionPreference = 'Stop'
if ($Gpu -and $Amd) { throw 'Choose either NVIDIA or AMD setup.' }
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

# Keep legacy -Gemma accepted; language-model support now accompanies every profile.
if ($Amd) {
    $env:UV_PROJECT_ENVIRONMENT = Join-Path $projectRoot '.venv-amd'
    & $uvCommand sync --locked --no-default-groups --group amd --group gemma-vulkan --group dev
} elseif ($Gpu) {
    $env:UV_PROJECT_ENVIRONMENT = Join-Path $projectRoot '.venv-gpu'
    & $uvCommand sync --locked --no-default-groups --group gpu --group dev --group gemma
} else {
    $env:UV_PROJECT_ENVIRONMENT = Join-Path $projectRoot '.venv'
    & $uvCommand sync --locked --group llm-cpu
}
if ($LASTEXITCODE -ne 0) { throw 'Dependency setup failed. Check the network connection and retry.' }
if ($Amd) { Write-Host 'Ready. Run .venv-amd/Scripts/pythonw.exe -m dantejp, then Models to choose downloads.' }
else { Write-Host 'Ready. Open Run DanteJP.cmd, then Models to choose downloads.' }
