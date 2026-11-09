$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "   BlackTiger Unified Setup (PowerShell)" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan

# Detect whether running on Windows or Linux/macOS
$isWindows = ($env:OS -eq "Windows_NT") -or ($IsWindows)
if ($PSVersionTable.PSEdition -eq "Core" -and $PSVersionTable.OS -and ($PSVersionTable.OS -notmatch "Windows")) {
    $isWindows = $false
}

# Locate appropriate Python interpreter
$python = $null

if ($isWindows) {
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($launcher) {
        $candidate = (& $launcher.Source -3.11 -c "import sys; print(sys.executable)" 2>$null).Trim()
        if ($LASTEXITCODE -eq 0 -and $candidate -and (Test-Path $candidate)) {
            $python = $candidate
        } else {
            $candidate = (& $launcher.Source -c "import sys; print(sys.executable)" 2>$null).Trim()
            if ($LASTEXITCODE -eq 0 -and $candidate -and (Test-Path $candidate)) {
                $python = $candidate
            }
        }
    }
}

if (-not $python) {
    $commandsToTry = @("python3.11", "python3", "python")
    foreach ($cmd in $commandsToTry) {
        $found = Get-Command $cmd -ErrorAction SilentlyContinue
        if ($found) {
            $candidate = (& $found.Source -c "import sys; print(sys.executable)" 2>$null).Trim()
            if ($LASTEXITCODE -eq 0 -and $candidate -and (Test-Path $candidate)) {
                $python = $candidate
                break
            }
        }
    }
}

if (-not $python) {
    throw "Python 3.10+ was not found. Please install Python and retry."
}

Write-Host "Detected Python: $python" -ForegroundColor Green

# Check for Tkinter (optional in headless Linux / CLI mode)
& $python -c "import tkinter" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Notice: Tkinter is not installed for this Python. CLI mode will work, but GUI requires Tkinter." -ForegroundColor Yellow
} else {
    Write-Host "Tkinter is available (GUI supported)." -ForegroundColor Green
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$Executable,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code $LASTEXITCODE`: $Executable $($Arguments -join ' ')"
    }
}

function Install-ProjectRequirements {
    param([Parameter(Mandatory = $true)][string]$ProjectPath)

    $environment = Join-Path $ProjectPath ".venv"
    if ($isWindows) {
        $environmentPython = Join-Path $environment "Scripts\python.exe"
    } else {
        $environmentPython = Join-Path $environment "bin/python"
    }
    $requirements = Join-Path $ProjectPath "requirements.txt"
    if (-not (Test-Path $requirements)) {
        Write-Host "Skipping (no requirements.txt): $ProjectPath" -ForegroundColor Yellow
        return
    }

    if (-not (Test-Path $environmentPython)) {
        Write-Host "Creating venv in $environment..." -ForegroundColor Gray
        Invoke-Checked $python @("-m", "venv", $environment)
    }
    Write-Host "Installing dependencies for: $ProjectPath..." -ForegroundColor Gray
    Invoke-Checked $environmentPython @("-m", "pip", "install", "-r", $requirements)
    Write-Host "Dependencies ready: $ProjectPath" -ForegroundColor Green
}

Install-ProjectRequirements (Join-Path $root "spiderfoot")
Install-ProjectRequirements (Join-Path $root "BlackTiger\network_dashboard")
Install-ProjectRequirements (Join-Path $root "BlackTiger\enterprise_audit")
Install-ProjectRequirements (Join-Path $root "Bramhastra")

Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "BlackTiger setup completed successfully!" -ForegroundColor Green
if ($isWindows) {
    Write-Host "Start the toolkit using:" -ForegroundColor Yellow
    Write-Host "  .\run-blacktiger.bat       (Windows GUI)" -ForegroundColor Cyan
    Write-Host "  .\run-blacktiger.ps1       (PowerShell GUI/CLI)" -ForegroundColor Cyan
} else {
    Write-Host "Start the toolkit using:" -ForegroundColor Yellow
    Write-Host "  ./run-blacktiger.sh        (Ubuntu/Linux)" -ForegroundColor Cyan
    Write-Host "  pwsh ./run-blacktiger.ps1  (PowerShell Core)" -ForegroundColor Cyan
}
Write-Host "==================================================" -ForegroundColor Cyan
