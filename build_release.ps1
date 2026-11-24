<#
.SYNOPSIS
    Builds the standalone Windows release ZIP of Website Collector.

.DESCRIPTION
    1. Creates an isolated build environment in .venv-build
    2. Installs the pinned runtime packages plus PyInstaller
    3. Builds dist\WebsiteCollector\WebsiteCollector.exe (one-folder app)
    4. Optionally downloads Chromium into dist\WebsiteCollector\browser_data\browsers
    5. Copies README, LICENSE and third-party notices
    6. Creates release\WebsiteCollector-<version>-windows-x64.zip and a SHA-256 file

    Nothing in app\ is modified.

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File .\build_release.ps1
    powershell -NoProfile -ExecutionPolicy Bypass -File .\build_release.ps1 -NoBrowser
#>
param(
    [string]$Python = '',
    [switch]$NoBrowser
)
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
Set-Location -LiteralPath $root

$version = (Select-String -LiteralPath (Join-Path $root 'app\__init__.py') -Pattern '__version__\s*=\s*"([^"]+)"').Matches[0].Groups[1].Value
Write-Host "Building Website Collector $version" -ForegroundColor Cyan

if (-not $Python) {
    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($launcher) { $Python = (& $launcher.Source -3.11 -c 'import sys; print(sys.executable)' 2>$null) }
    if (-not $Python) { $Python = (Get-Command python.exe -ErrorAction Stop).Source }
}
$Python = $Python.Trim()

$venv = Join-Path $root '.venv-build'
$vpy = Join-Path $venv 'Scripts\python.exe'
if (-not (Test-Path -LiteralPath $vpy)) {
    & $Python -m venv $venv
    if ($LASTEXITCODE) { throw 'Could not create the build environment.' }
}
& $vpy -m pip install --disable-pip-version-check --upgrade pip
& $vpy -m pip install --disable-pip-version-check -r (Join-Path $root 'requirements-lock.txt') -r (Join-Path $root 'requirements-build.txt')
if ($LASTEXITCODE) { throw 'Package installation failed.' }

foreach ($dir in 'build', 'dist') {
    $p = Join-Path $root $dir
    if (Test-Path -LiteralPath $p) { Remove-Item -LiteralPath $p -Recurse -Force }
}

& $vpy -m PyInstaller --noconfirm --clean --distpath (Join-Path $root 'dist') --workpath (Join-Path $root 'build') (Join-Path $root 'packaging\WebsiteCollector.spec')
if ($LASTEXITCODE) { throw 'PyInstaller build failed.' }

$app = Join-Path $root 'dist\WebsiteCollector'
if (-not $NoBrowser) {
    Write-Host 'Downloading Chromium into the release folder...'
    $env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $app 'browser_data\browsers'
    & $vpy -m playwright install chromium --no-shell
    if ($LASTEXITCODE) { throw 'Chromium download failed. Use -NoBrowser to ship without it (the app then uses Microsoft Edge).' }
    Remove-Item Env:\PLAYWRIGHT_BROWSERS_PATH
}

foreach ($doc in 'README.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md', 'CHANGELOG.md') {
    Copy-Item -LiteralPath (Join-Path $root $doc) -Destination $app
}
$imgDir = Join-Path $app 'docs\images'
New-Item -ItemType Directory -Path $imgDir -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $root 'docs\images\interface-preview.png') -Destination $imgDir

$release = Join-Path $root 'release'
New-Item -ItemType Directory -Path $release -Force | Out-Null
$zip = Join-Path $release "WebsiteCollector-$version-windows-x64.zip"
if (Test-Path -LiteralPath $zip) { Remove-Item -LiteralPath $zip -Force }
Compress-Archive -Path $app -DestinationPath $zip -CompressionLevel Optimal
$hash = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLower()
"$hash  $(Split-Path $zip -Leaf)" | Set-Content -LiteralPath "$zip.sha256" -Encoding ascii

$sizeMb = [math]::Round((Get-Item -LiteralPath $zip).Length / 1MB, 1)
Write-Host ''
Write-Host "Release ZIP: $zip ($sizeMb MB)" -ForegroundColor Green
Write-Host "SHA-256:     $hash"
Write-Host 'Test it: extract the ZIP to a new folder and double-click WebsiteCollector.exe'
