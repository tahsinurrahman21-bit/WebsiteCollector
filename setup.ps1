param([string]$Python = '')
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
if (-not (Test-Path -LiteralPath ([IO.Path]::GetPathRoot($projectRoot)))) {
    throw 'Local volume G: is unavailable. Please connect or mount the drive, or select another storage location.'
}
foreach ($name in @('cache', 'cache\pip', 'temp', 'browser_data', 'logs', 'output')) {
    New-Item -ItemType Directory -Path (Join-Path $projectRoot $name) -Force | Out-Null
}
$env:TEMP = Join-Path $projectRoot 'temp'
$env:TMP = $env:TEMP
$env:TMPDIR = $env:TEMP
$env:PIP_CACHE_DIR = Join-Path $projectRoot 'cache\pip'
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $projectRoot 'browser_data\browsers'
$env:PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT = '30000'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONUTF8 = '1'
Set-Location -LiteralPath $projectRoot
$venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
try {
    if (-not (Test-Path -LiteralPath $venvPython)) {
        if (-not $Python) {
            $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
            if ($launcher) {
                foreach ($version in @('-3.11', '-3.12', '-3.13', '-3.14')) {
                    $candidate = & $launcher.Source $version -c 'import sys; print(sys.executable)' 2>$null
                    if ($LASTEXITCODE -eq 0) { $Python = $candidate.Trim(); break }
                }
            }
            if (-not $Python) {
                $command = Get-Command python.exe -ErrorAction SilentlyContinue
                if ($command) { $Python = $command.Source }
            }
        }
        if (-not $Python) { throw 'Install 64-bit Python 3.11 or newer from https://www.python.org/downloads/windows/ . In Customize installation, choose G:\Python311 (or another G: folder). Then rerun setup.bat.' }
        & $Python -c 'import sys, struct; assert (3,11) <= sys.version_info[:2] < (3,15) and struct.calcsize("P") == 8, "Use 64-bit Python 3.11 to 3.14"'
        if ($LASTEXITCODE -ne 0) { throw 'A supported 64-bit Python (3.11 to 3.14) was not found. See README.md.' }
        Write-Host 'Creating the local Python environment on the project drive...'
        & $Python -m venv (Join-Path $projectRoot '.venv')
        if ($LASTEXITCODE -ne 0) { throw 'Could not create the Python environment.' }
    }
    & $venvPython -m ensurepip --upgrade
    if ($LASTEXITCODE -ne 0) { throw 'Could not prepare the package installer.' }
    Write-Host 'Installing Python packages into the project folder...'
    & $venvPython -m pip install --disable-pip-version-check -r (Join-Path $projectRoot 'requirements-lock.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Package installation failed. Check the internet connection and try again.' }
    Write-Host 'Installing Chromium into browser_data on the project drive...'
    & $venvPython -m app.install_browser
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'Trying the standard Playwright browser installer...'
        & $venvPython -m playwright install chromium
        if ($LASTEXITCODE -ne 0) {
            Write-Warning 'Chromium could not be downloaded. The app can use an installed Microsoft Edge or Google Chrome through Playwright. Run setup.bat again to retry Chromium.'
        }
    }
    & $venvPython -m app.diagnostics
    if ($LASTEXITCODE -ne 0) { throw 'A required component is missing. See the diagnostic messages above.' }
    exit 0
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
