[CmdletBinding()]
param(
    [switch]$SkipModels
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPath = Join-Path $ProjectRoot ".venv"
$VenvPython = Join-Path $VenvPath "Scripts\python.exe"

Set-Location $ProjectRoot

function Invoke-CheckedStep {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][scriptblock]$Command
    )

    Write-Host ""
    Write-Host "==> $Name" -ForegroundColor Cyan
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Name failed with exit code $LASTEXITCODE."
    }
}

function Find-Python313 {
    $launcher = Get-Command "py.exe" -ErrorAction SilentlyContinue
    if ($null -ne $launcher) {
        $detected = & $launcher.Source -3.13 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
        if (($LASTEXITCODE -eq 0) -and ($detected -eq "3.13")) {
            return @{
                Command = $launcher.Source
                Arguments = @("-3.13")
            }
        }
    }

    $python = Get-Command "python.exe" -ErrorAction SilentlyContinue
    if ($null -ne $python) {
        $detected = & $python.Source -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
        if (($LASTEXITCODE -eq 0) -and ($detected -eq "3.13")) {
            return @{
                Command = $python.Source
                Arguments = @()
            }
        }
    }

    return $null
}

Write-Host ""
Write-Host "BioShift automated setup" -ForegroundColor Green
Write-Host "Project: $ProjectRoot"

$PythonInfo = Find-Python313
if ($null -eq $PythonInfo) {
    throw @"
Python 3.13 (64-bit) was not found.
Install it from https://www.python.org/downloads/windows/, enable 'Add Python to PATH',
then close and reopen this terminal before running install.bat again.
"@
}

$BasePython = $PythonInfo.Command
$BaseArguments = $PythonInfo.Arguments

$architecture = & $BasePython @BaseArguments -c "import struct; print(struct.calcsize('P') * 8)"
if (($LASTEXITCODE -ne 0) -or ($architecture -ne "64")) {
    throw "BioShift requires a 64-bit Python 3.13 installation."
}

$version = & $BasePython @BaseArguments --version
Write-Host "Using $version at $BasePython"

if (-not (Test-Path -LiteralPath $VenvPython)) {
    Invoke-CheckedStep "Creating the isolated Python environment" {
        & $BasePython @BaseArguments -m venv $VenvPath
    }
} else {
    Write-Host ""
    Write-Host "==> Reusing the existing .venv" -ForegroundColor Cyan
}

Invoke-CheckedStep "Updating pip" {
    & $VenvPython -m pip install --upgrade pip --disable-pip-version-check
}

Invoke-CheckedStep "Installing the CPU build of PyTorch" {
    & $VenvPython -m pip install torch==2.13.0 torchvision==0.28.0 --index-url https://download.pytorch.org/whl/cpu --disable-pip-version-check
}

Invoke-CheckedStep "Installing BioShift dependencies" {
    & $VenvPython -m pip install -r (Join-Path $ProjectRoot "requirements.txt") --disable-pip-version-check
}

if (-not $SkipModels) {
    Invoke-CheckedStep "Downloading BioShift model files (approximately 4 GB)" {
        & $VenvPython (Join-Path $ProjectRoot "download_models.py")
    }
}

Invoke-CheckedStep "Verifying the installation" {
    if ($SkipModels) {
        & $VenvPython (Join-Path $ProjectRoot "verify_install.py") --skip-models
    } else {
        & $VenvPython (Join-Path $ProjectRoot "verify_install.py")
    }
}

Write-Host ""
Write-Host "BioShift is installed successfully." -ForegroundColor Green
Write-Host "Start it with: .\start.bat"
Write-Host "Then open:    http://127.0.0.1:5000"
