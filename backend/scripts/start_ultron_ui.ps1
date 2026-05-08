param(
    [string]$BackendDir = "",
    [switch]$NoInstall
)

$ErrorActionPreference = "Stop"

if (-not $BackendDir) {
    $BackendDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
}

Set-Location $BackendDir

if (-not $NoInstall) {
    python -m pip install PyQt5==5.15.11 vosk==0.3.45 sounddevice==0.5.1
}

python .\run_ultron_ui.py

