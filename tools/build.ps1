<# Standard release entry point. PyInstaller owns bundling; uv/Hatchling own Python distributions.
   Requires uv 0.13.8. -DownloadOcr explicitly prepares the three bundled OCR assets.
   The dedicated build environment never changes a running development/GPU environment. #>
param([switch]$Offline, [switch]$DownloadOcr, [switch]$CpuWheelOnly)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
if ($Offline -and $DownloadOcr) { throw 'Use -Offline with existing OCR assets, or -DownloadOcr.' }
$uv = if (Get-Command uv -ErrorAction SilentlyContinue) { (Get-Command uv).Source } else { Join-Path $PWD '.bootstrap/Scripts/uv.exe' }
if ((& $uv --version) -notmatch '^uv 0\.13\.8(?:\s|$)') { throw 'Install uv 0.13.8 before building.' }
$env:UV_PROJECT_ENVIRONMENT = Join-Path $PWD '.venv-build'
$env:UV_CACHE_DIR = Join-Path $PWD '.uv-cache'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $PWD '.python'
$env:PYTHONUTF8 = '1'
if ($Offline) { $env:UV_OFFLINE = '1' }
& $uv sync --locked --python 3.12.16 --no-default-groups --group cpu --group llm-common --group bundle
if ($LASTEXITCODE -ne 0) { throw 'Build environment setup failed.' }
$python = Join-Path $env:UV_PROJECT_ENVIRONMENT 'Scripts/python.exe'
# Upstream's PEP 517 backend owns compilation, native-library installation and wheel metadata.
# The compiler must already be installed (MSVC Build Tools on Windows CI/developer machines).
$env:PIP_CACHE_DIR = Join-Path $PWD '.pip-cache'
$wheelArgs = @('wheel', '--no-deps', '--no-build-isolation', '--require-hashes', '--no-binary=llama-cpp-python',
    '--config-settings=cmake.define.GGML_NATIVE=OFF', '--config-settings=cmake.define.GGML_OPENMP=OFF',
    '--wheel-dir=build/upstream-cpu', '--requirement=packaging/cpu-runtime.txt')
if (-not $Offline) {
    & $python -m pip @wheelArgs
    if ($LASTEXITCODE -ne 0) { throw 'Upstream CPU build failed. Install C++ Build Tools; see engineering/building.md.' }
    & $python -m delvewheel repair --analyze-existing --ignore-existing --wheel-dir build/cpu-runtime build/upstream-cpu/llama_cpp_python-0.3.37-py3-none-win_amd64.whl
    if ($LASTEXITCODE -ne 0) { throw 'CPU wheel dependency repair failed.' }
}
$cpuWheel = Get-Item 'build/cpu-runtime/llama_cpp_python-0.3.37-py3-none-win_amd64.whl'
$cpuHash = (Get-FileHash -LiteralPath $cpuWheel.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
if ($Offline -and (Get-Content -LiteralPath ($cpuWheel.FullName + '.sha256')) -ne "$cpuHash  $($cpuWheel.Name)") {
    throw 'Offline CPU wheel checksum mismatch. Run an online build again.'
}
"$cpuHash  $($cpuWheel.Name)`n" | Set-Content -LiteralPath ($cpuWheel.FullName + '.sha256') -Encoding ascii -NoNewline
& $uv pip install --offline --no-deps --python $python $cpuWheel.FullName
if ($LASTEXITCODE -ne 0) { throw 'Upstream CPU wheel installation failed.' }
if ($CpuWheelOnly) { Write-Host "Built $($cpuWheel.FullName)"; exit 0 }
# Native dependency discovery must not pick DLLs from unrelated applications on PATH.
$env:PATH = @((Split-Path -Parent $python), (Split-Path -Parent $uv), "$env:SystemRoot/System32", $env:SystemRoot) -join ';'
$env:PYINSTALLER_CONFIG_DIR = Join-Path $PWD 'build/pyinstaller-cache'
if ($DownloadOcr) {
    & $python tools/setup_models.py
    if ($LASTEXITCODE -ne 0) { throw 'OCR asset preparation failed.' }
}
& $uv build --no-build-isolation --python $python --out-dir dist
if ($LASTEXITCODE -ne 0) { throw 'Python distribution build failed.' }
# Bundle the exact wheel made by Hatchling, with the same standard SHA-256 sidecar as releases.
$appVersion = & $python -c "import tomllib; print(tomllib.load(open('pyproject.toml', 'rb'))['project']['version'])"
$appWheel = Get-Item "dist/jp_overlay-$appVersion-py3-none-any.whl"
$appHash = (Get-FileHash -LiteralPath $appWheel.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
"$appHash  $($appWheel.Name)`n" | Set-Content -LiteralPath ($appWheel.FullName + '.sha256') -Encoding ascii -NoNewline
# Dependency-only exports stay stable across application versions and are also runtime inputs.
New-Item -ItemType Directory -Force build/runtime-locks | Out-Null
foreach ($profile in @('cpu', 'nvidia', 'amd')) {
    $groups = @{cpu=@('cpu','llm-cpu'); nvidia=@('gpu','gemma'); amd=@('cpu','gemma-vulkan')}[$profile]
    & $uv export --locked --offline --no-default-groups --no-emit-project --group $groups[0] --group $groups[1] --format pylock.toml --output-file "build/runtime-locks/pylock.$profile.toml" --quiet
    if ($LASTEXITCODE -ne 0) { throw "Dependency export failed for $profile." }
}
& $python -m PyInstaller --noconfirm --clean --workpath build/pyinstaller --distpath dist packaging/DanteJP.spec
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed.' }
Copy-Item -LiteralPath packaging/README.txt,packaging/THIRD-PARTY.txt -Destination dist/DanteJP
Compress-Archive -LiteralPath dist/DanteJP -DestinationPath dist/DanteJP-windows-x64.zip -Force
$outputs = @(Get-Item dist/DanteJP-windows-x64.zip) + @(Get-ChildItem dist/jp_overlay-*.whl,dist/jp_overlay-*.tar.gz)
foreach ($file in $outputs) {
    $hash = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    # LF sidecars also work with GNU sha256sum in the Linux release job.
    "$hash  $($file.Name)`n" | Set-Content -LiteralPath ($file.FullName + '.sha256') -Encoding ascii -NoNewline
}
Write-Host 'Built dist/DanteJP-windows-x64.zip and standard wheel/source distributions.'
