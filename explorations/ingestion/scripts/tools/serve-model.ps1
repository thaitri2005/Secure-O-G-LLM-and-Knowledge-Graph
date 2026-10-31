param([ValidateSet('mineru', 'paddle')][string]$Model = 'mineru', [switch]$DryRun)
$ErrorActionPreference = 'Stop'
$base = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$program = "$base/.cache/llama.cpp/llama-server.exe"
if ($Model -eq 'mineru') {
    $weights = "$base/models/mineru-gguf/MinerU2.5-Pro-2604-1.2B.Q8_0.gguf"
    $projector = "$base/models/mineru-gguf/MinerU2.5-Pro-2604-1.2B.mmproj-f16.gguf"
    $portNumber = '8087'
    $alias = 'opendatalab/MinerU2.5-Pro-2604-1.2B'
} else {
    $weights = "$base/models/paddle-gguf/PaddleOCR-VL-1.6-GGUF.gguf"
    $projector = "$base/models/paddle-gguf/PaddleOCR-VL-1.6-GGUF-mmproj.gguf"
    $portNumber = '8088'
    $alias = 'PaddleOCR-VL-1.6'
}
$arguments = @('-m', $weights, '--mmproj', $projector, '--host', '127.0.0.1', '--port', $portNumber,
    '-ngl', '99', '--device', 'Vulkan0', '-c', '8192', '--parallel', '1', '--alias', $alias,
    '--special', '--image-min-tokens', '1024')
if ($DryRun) { Write-Output ($program + ' ' + ($arguments -join ' ')); return }
& $program @arguments
if ($LASTEXITCODE -ne 0) { throw 'Local model server failed.' }
