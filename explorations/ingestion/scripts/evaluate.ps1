param([string[]]$Runs = @())
$ErrorActionPreference = 'Stop'
$base = Split-Path $PSScriptRoot -Parent
$env:PYTHONPATH = Join-Path $base 'src'
$env:PYTHONDONTWRITEBYTECODE = '1'
$arguments = @('-B', '-m', 'ingest_prototype.evaluate')
if ($Runs.Count) { $arguments += '--runs'; $arguments += $Runs }
& "$base/.venvs/docling/Scripts/python.exe" @arguments
if ($LASTEXITCODE -ne 0) { throw 'Annotation evaluation failed.' }
