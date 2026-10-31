param([switch]$DryRun)
$ErrorActionPreference = 'Stop'
$base = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$program = "$base/.venvs/opendataloader-pdf/Scripts/python.exe"
$arguments = @('-m', 'opendataloader_pdf.hybrid_server', '--host', '127.0.0.1', '--port', '5002',
    '--device', 'cpu', '--ocr-lang', 'en')
if ($DryRun) { Write-Output ($program + ' ' + ($arguments -join ' ')); return }
$env:HF_HOME = "$base/.cache/huggingface"
$env:TORCH_HOME = "$base/.cache/torch"
$env:EASYOCR_MODULE_PATH = "$base/.cache/easyocr"
New-Item -ItemType Directory -Force "$base/.cache/easyocr/model" | Out-Null
Copy-Item 'data/interim/ocr_models/*.pth' "$base/.cache/easyocr/model/"
& $program @arguments
if ($LASTEXITCODE -ne 0) { throw 'Local hybrid server failed.' }
