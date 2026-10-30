$ErrorActionPreference = "Stop"
$Project = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
. (Join-Path $PSScriptRoot "onprem_env.ps1")
$env:PYTHONPATH = (Join-Path $Project "src") + [IO.Path]::PathSeparator + (Join-Path $Project "tests")
Push-Location $Project
try {
    Write-Output "Reproduction uses a soft planning budget and a 5400-second hard safety limit; default workers: 2."
    & (Join-Path $Project ".venvs/kggen/Scripts/python.exe") -B (Join-Path $PSScriptRoot "reproduce.py") @args
    $code = $LASTEXITCODE
} finally { Pop-Location }
exit $code
