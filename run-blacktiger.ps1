# BlackTiger Universal PowerShell Runner (Windows PowerShell & Ubuntu pwsh)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

$python = $null
$isWindows = ($env:OS -eq "Windows_NT") -or ($IsWindows)
if ($PSVersionTable.PSEdition -eq "Core" -and $PSVersionTable.OS -and ($PSVersionTable.OS -notmatch "Windows")) {
    $isWindows = $false
}

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
    throw "Python was not found. Please install Python 3.10+ and retry."
}

$scriptPath = Join-Path $root "blacktiger_app.py"
& $python $scriptPath @args
