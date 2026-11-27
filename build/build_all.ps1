# Builds everything: the app, the app package and the installer.
# Run from PowerShell:   powershell -ExecutionPolicy Bypass -File C:\AsenaMask\build\build_all.ps1
param([string]$ComfySource = "", [string]$ComfyVersion = "", [switch]$NoExperimental)
# One command builds everything: the normal installer (NVIDIA) AND the experimental one (AMD Radeon + Intel Arc in one exe).
# Add -NoExperimental to skip the experimental installer.
$Experimental = -not $NoExperimental
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

Write-Host "== 1/4  Build tools" -ForegroundColor Magenta
$venv = Join-Path $root "build\venv"
if (!(Test-Path "$venv\Scripts\python.exe")) {
    # find a real Python (the Microsoft Store "python" shortcut does not count)
    $base = $null
    $cands = @("$root\venv\Scripts\python.exe", "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
               "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe", "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe")
    foreach ($c in $cands) { if (Test-Path $c) { $base = $c; break } }
    if (-not $base) {
        try { $p = (& py -3 -c "import sys;print(sys.executable)" 2>$null); if ($p -and (Test-Path $p)) { $base = $p } } catch {}
    }
    if (-not $base) { throw "No Python found. Install Python 3.12 from python.org (tick 'Add to PATH') or edit the path list in build_all.ps1." }
    Write-Host "Using Python: $base"
    & $base -m venv $venv
    if ($LASTEXITCODE -ne 0) { throw "Could not create the build environment" }
}
$py = "$venv\Scripts\python.exe"
& $py -m pip install --upgrade pip --quiet
& $py -m pip install pyside6 av pillow numpy pyinstaller certifi --quiet
$assets = Join-Path $root "asenamask\assets"

Write-Host "== 2/4  Building the app (Asena Mask.exe)" -ForegroundColor Magenta
& $py -m PyInstaller --noconfirm --clean --windowed --collect-data certifi --name "Asena Mask" `
    --icon "$assets\icon.ico" --version-file "$root\build\version_app.txt" `
    --add-data "$assets;asenamask\assets" `
    --exclude-module torch --exclude-module cv2 --exclude-module tkinter --exclude-module matplotlib `
    --distpath "$root\build\dist" --workpath "$root\build\work" --specpath "$root\build" `
    "$root\main.py"
if ($LASTEXITCODE -ne 0) { throw "App build failed" }

Write-Host "== 3/4  Making the app package" -ForegroundColor Magenta
$extra = @()
if ($ComfySource) { $extra += @("--comfy-source", $ComfySource) }
if ($ComfyVersion) { $extra += @("--comfy-version", $ComfyVersion) }
& $py "$root\build\make_package.py" @extra
if ($LASTEXITCODE -ne 0) { throw "Packaging failed" }

$flavor = "$root\installer\flavor.py"
function Build-Installer($name, $exp) {
    Set-Content -Path $flavor -Value ("EXPERIMENTAL = " + $(if ($exp) { "True" } else { "False" })) -Encoding ascii
& $py -m PyInstaller --noconfirm --clean --onefile --windowed --collect-data certifi --name $name `
    --icon "$assets\icon.ico" --version-file "$root\build\version_setup.txt" `
    --paths "$root" --paths "$root\installer" `
    --add-data "$assets\icon.ico;asenamask\assets" --add-data "$assets\logo.png;asenamask\assets" `
    --add-data "$assets\sounds;asenamask\assets\sounds" `
    --exclude-module torch --exclude-module cv2 --exclude-module tkinter --exclude-module matplotlib `
    --exclude-module av --exclude-module numpy --exclude-module PIL `
    --distpath "$root\release" --workpath "$root\build\work_setup" --specpath "$root\build" `
    "$root\installer\setup_main.py"
    if ($LASTEXITCODE -ne 0) { throw "Installer build failed" }
}

Write-Host "== 4/4  Building the installer" -ForegroundColor Magenta
Build-Installer "Asena Mask Setup" $false
if ($Experimental) {
    Write-Host "== Extra: experimental AMD / Intel installer" -ForegroundColor Magenta
    Build-Installer "Asena Mask Setup EXPERIMENTAL AMD-Intel" $true
    Set-Content -Path $flavor -Value "EXPERIMENTAL = False" -Encoding ascii
}

& $py "$root\build\make_source_zip.py"

Write-Host ""
Write-Host "Done. Files are in $root\release :" -ForegroundColor Green
Get-ChildItem "$root\release" | Select-Object Name, @{n="MB";e={[math]::Round($_.Length/1MB,1)}}
