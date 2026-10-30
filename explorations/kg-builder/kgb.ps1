$ErrorActionPreference = "Stop"
$Project = $PSScriptRoot
. (Join-Path $Project "scripts/onprem_env.ps1")
$env:PYTHONPATH = "$Project/src"
Push-Location $Project
try {
    if ($args.Count -gt 0 -and $args[0] -eq "test") {
        $rest = @()
        if ($args.Count -gt 1) { $rest = $args[1..($args.Count - 1)] }
        & "$Project/.venvs/kggen/Scripts/python.exe" -B "$Project/scripts/prepare_reference.py"
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        & "$Project/.venvs/kggen/Scripts/python.exe" -m unittest discover -s tests -v @rest
    } else {
        & "$Project/.venvs/kggen/Scripts/python.exe" -m kgbuilder @args
    }
    $code = $LASTEXITCODE
} finally { Pop-Location }
exit $code
