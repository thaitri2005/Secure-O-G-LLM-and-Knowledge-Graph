param([ValidateSet('ak3', 'reports')][string]$Corpus = 'ak3', [string]$RunName = '', [switch]$Refresh)
$ErrorActionPreference = 'Stop'
$base = Split-Path $PSScriptRoot -Parent
if (-not $RunName) { $RunName = $Corpus }
$destination = [IO.Path]::GetFullPath((Join-Path $base "runs/prototype/$RunName"))
$allowed = [IO.Path]::GetFullPath((Join-Path $base 'runs')) + [IO.Path]::DirectorySeparatorChar
if (-not $destination.StartsWith($allowed, [StringComparison]::OrdinalIgnoreCase)) { throw 'Run directory escaped the exploration.' }
$env:PYTHONPATH = Join-Path $base 'src'
$env:PYTHONDONTWRITEBYTECODE = '1'
$arguments = @('-B', '-m', 'ingest_prototype.cli', '--corpus', $Corpus, '--run', $destination)
if ($Refresh) { $arguments += '--refresh' }
& "$base/.venvs/docling/Scripts/python.exe" @arguments
if ($LASTEXITCODE -ne 0) { throw 'Corpus processing failed.' }
