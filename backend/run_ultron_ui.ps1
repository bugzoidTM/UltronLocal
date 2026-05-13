$ErrorActionPreference = "Stop"

$Backend = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Backend

python .\run_ultron_ui.py @args
