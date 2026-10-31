param([switch]$Install, [switch]$FetchSources,
    [string[]]$Tools = @('docling', 'ocrmypdf'))
$ErrorActionPreference = 'Stop'
$base = Split-Path $PSScriptRoot -Parent
$repository = Split-Path (Split-Path $base -Parent) -Parent
$lock = Get-Content "$base/configs/inputs.lock.json" -Raw | ConvertFrom-Json
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PIP_CACHE_DIR = "$base/.cache/pip"
$env:GIT_LFS_SKIP_SMUDGE = '1'
$env:GIT_TERMINAL_PROMPT = '0'
if ($FetchSources) {
    foreach ($source in $lock.upstream) {
        if (-not $source.commit) { continue }
        $destination = "$base/third_party/$($source.name)"
        if (Test-Path "$destination/.git") {
            if ((& git -C $destination rev-parse HEAD) -ne $source.commit) { throw "Source pin differs: $($source.name)" }
            continue
        }
        & git init $destination
        if ($LASTEXITCODE) { throw 'Source initialization failed.' }
        & git -C $destination remote add origin $source.url
        & git -C $destination fetch --depth 1 origin $source.commit
        if ($LASTEXITCODE) { throw 'Pinned source fetch failed.' }
        & git -C $destination checkout --detach FETCH_HEAD
        if ($LASTEXITCODE) { throw 'Pinned checkout failed.' }
    }
}
foreach ($tool in $Tools) {
    $python = "$base/.venvs/$tool/Scripts/python.exe"
    if ($Install -and -not (Test-Path $python)) {
        & "$repository/.venv/Scripts/python.exe" -m venv "$base/.venvs/$tool"
        if ($LASTEXITCODE) { throw "Environment creation failed: $tool" }
        & $python -m pip install -r "$base/configs/requirements-$tool.txt" -c "$base/configs/environments/$tool.txt"
        if ($LASTEXITCODE) { throw "Pinned package installation failed: $tool" }
    }
    if (-not (Test-Path $python)) { throw "Missing environment: $tool. Use -Install to create it." }
    & $python -B -c 'import sys; print(sys.version.split()[0])'
    if ($LASTEXITCODE) { throw "Environment verification failed: $tool" }
}
$env:PYTHONPATH = Join-Path $base 'src'
& "$base/.venvs/docling/Scripts/python.exe" -B "$base/scripts/tools/verify_assets.py"
if ($LASTEXITCODE) { throw 'Local assets do not match the input lock.' }
Write-Output 'Pinned local environments and assets verified.'
