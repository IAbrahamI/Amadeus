# Builds Amadeus-<version>-x64-setup.exe on Windows: the desktop app with its own Python and the core inside, so nothing
# else has to be installed for it to start. It installs for the current user only (no administrator), into
# %LOCALAPPDATA%\Amadeus, and starts at login. No paid signature: Windows SmartScreen shows "More info -> Run anyway"
# the first time (docs/INSTALL.md explains it).
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path "$PSScriptRoot\..\..").Path
Set-Location $Root
$Version = (Get-Content VERSION -Raw).Trim()
$PyRelease = "20261026"; $PyVersion = "3.13.18"
$PySha = "ebe90cc1dce2dd2d7afa1f0aa9b6c269c7c0174aeabdc6a801381602b7283424"
$Out = Join-Path $Root "dist\windows"
$Stage = Join-Path $Out "stage"
New-Item -ItemType Directory -Force -Path $Out | Out-Null
if (Test-Path $Stage) { Remove-Item -Recurse -Force $Stage }
New-Item -ItemType Directory -Force -Path $Stage | Out-Null

# 1. its own Python (python-build-standalone, checked against its published checksum)
$Tarball = Join-Path $Out "python-$PyVersion-windows.tar.gz"
if (-not (Test-Path $Tarball)) {
  Invoke-WebRequest -UseBasicParsing -Uri "https://github.com/astral-sh/python-build-standalone/releases/download/$PyRelease/cpython-$PyVersion+$PyRelease-x86_64-pc-windows-msvc-install_only.tar.gz" -OutFile $Tarball
}
if ((Get-FileHash -Algorithm SHA256 $Tarball).Hash.ToLower() -ne $PySha) { throw "The Python download doesn't match its checksum." }
tar -xzf $Tarball -C $Stage
if (-not (Test-Path "$Stage\python\python.exe")) { throw "No python.exe in the Python download." }

# 2. the core (only what it needs when running)
git archive --format=tar -o "$Out\core.tar" HEAD core VERSION LICENSE
tar -xf "$Out\core.tar" -C $Stage
Remove-Item "$Out\core.tar"
Remove-Item -Recurse -Force "$Stage\core\tests", "$Stage\core\desktop-tauri"

# 3. the desktop app and its installer, with both inside (tauri.conf.json stays as it is for Linux and the Mac)
Push-Location core\desktop-tauri
$Config = @{
  bundle = @{
    active = $true; targets = @("nsis"); icon = @("icons/icon.ico", "icons/icon.png")
    resources = @{ "../../dist/windows/stage/python/" = "python/"; "../../dist/windows/stage/core/" = "core/"; "../../dist/windows/stage/VERSION" = "VERSION" }
    windows = @{ nsis = @{ installMode = "currentUser"; displayLanguageSelector = $false } }
  }
} | ConvertTo-Json -Depth 6
$ConfigFile = Join-Path $Out "tauri.windows.json"  # (a file: JSON on a command line loses its quotes on the way)
Set-Content -Path $ConfigFile -Value $Config -Encoding utf8
$env:CARGO_TARGET_DIR = Join-Path $Root ".tauri-build\target"
npx --yes @tauri-apps/cli@2.12.4 build --bundles nsis --config $ConfigFile -- --locked
if ($LASTEXITCODE -ne 0) { throw "The desktop app didn't build." }
Pop-Location

$Setup = Get-ChildItem "$Root\.tauri-build\target\release\bundle\nsis\*-setup.exe" | Select-Object -First 1
Copy-Item $Setup.FullName (Join-Path $Out "Amadeus-$Version-x64-setup.exe") -Force
Write-Host "Built $Out\Amadeus-$Version-x64-setup.exe"
