param(
    [Parameter(Mandatory=$true)][string]$Bundle,
    [Parameter(Mandatory=$true)][string]$StoreDir,
    [Parameter(Mandatory=$true)][string]$Image
)
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
function Resolve-ProjectPath([string]$value) {
    $resolved = [IO.Path]::GetFullPath((Join-Path $projectRoot $value))
    if (-not $resolved.StartsWith($projectRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Path must be below PROJECT_ROOT'
    }
    # Reject existing reparse points so lexical containment cannot escape PROJECT_ROOT.
    $probe = $resolved
    while ($probe.Length -gt $projectRoot.Length) {
        if (Test-Path -LiteralPath $probe) {
            if ((Get-Item -LiteralPath $probe -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Reparse point is not allowed' }
        }
        $probe = [IO.Path]::GetDirectoryName($probe)
    }
    return $resolved
}
function Get-Sha256([string]$path) {
    $stream = [IO.File]::OpenRead($path)
    $hasher = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($hasher.ComputeHash($stream))).Replace('-', '').ToLowerInvariant() }
    finally { $stream.Dispose(); $hasher.Dispose() }
}
try {
    $bulkPath = Resolve-ProjectPath $Bundle
    $storePath = Resolve-ProjectPath $StoreDir
    if ($storePath -ne (Join-Path $projectRoot '.neo4j\bsee')) { throw 'StoreDir must be .neo4j\bsee' }
    $dataPath = Join-Path $storePath 'data'
    if ((Test-Path -LiteralPath $dataPath) -and @(Get-ChildItem -LiteralPath $dataPath -Force).Count) { throw 'Store data must be absent or empty' }
    $manifest = Get-Content -LiteralPath (Join-Path $bulkPath 'import_manifest.json') -Raw | ConvertFrom-Json
    if ($manifest.format -ne 'kgb.domain_bulk/1') { throw 'Invalid bulk manifest' }
    $expectedArgs = @()
    foreach ($property in $manifest.files.PSObject.Properties) {
        $name = $property.Name
        if ($name -notmatch '^(nodes|rels)_[A-Za-z][A-Za-z0-9_]*\.csv$') { throw 'Invalid CSV name' }
        $file = Join-Path $bulkPath $name
        if ((Get-Sha256 $file) -ne $property.Value.sha256) { throw 'CSV hash mismatch' }
        $prefix = if ($property.Value.kind -eq 'nodes') { '--nodes=' } elseif ($property.Value.kind -eq 'relationships') { '--relationships=' } else { throw 'Invalid CSV kind' }
        $expectedArgs += $prefix + '/import/' + $name
    }
    if ((@($manifest.neo4j_admin_args | Sort-Object) -join "`n") -ne (@($expectedArgs | Sort-Object) -join "`n")) { throw 'Invalid neo4j-admin arguments' }
    if ($Image -notmatch '^[A-Za-z0-9][A-Za-z0-9./:_-]*$') { throw 'Invalid image tag' }
} catch { Write-Error -ErrorAction Continue $_.Exception.Message; exit 2 }
try {
    docker info *> $null
    if ($LASTEXITCODE -ne 0) { throw 'daemon unavailable' }
} catch { Write-Output 'start Docker Desktop'; exit 3 }
try {
    $imageDigest = docker image inspect $Image --format '{{.Id}}' 2>$null
    if ($LASTEXITCODE -ne 0) { throw 'image unavailable' }
} catch { Write-Output 'Image is not cached; no pull performed'; exit 3 }
try {
    $running = docker ps --filter 'name=^/kgb-neo4j-bsee$' --format '{{.Names}}'
    if ($LASTEXITCODE -ne 0) { throw 'container inspection failed' }
} catch { Write-Output 'Cannot inspect running containers'; exit 3 }
if ($running -contains 'kgb-neo4j-bsee') { Write-Output 'Stop kgb-neo4j-bsee before import'; exit 3 }
$logsPath = Join-Path $storePath 'logs'
[IO.Directory]::CreateDirectory($dataPath) | Out-Null
[IO.Directory]::CreateDirectory($logsPath) | Out-Null
$outLog = Join-Path $logsPath 'import.out.txt'
$errLog = Join-Path $logsPath 'import.err.txt'
$importArgs = @('run', '--rm', '--pull=never', '--network=none', '-v', "${dataPath}:/data", '-v', "${bulkPath}:/import:ro", $Image,
                'neo4j-admin', 'database', 'import', 'full', 'neo4j') + @($manifest.neo4j_admin_args) + @('--max-off-heap-memory=4G')
$startedAt = (Get-Date).ToUniversalTime().ToString('o')
$timer = [Diagnostics.Stopwatch]::StartNew()
$ErrorActionPreference = 'Continue'
try {
    docker @importArgs 1> $outLog 2> $errLog
    $result = $LASTEXITCODE
} catch {
    $result = 7
    $_.Exception.Message | Add-Content -LiteralPath $errLog
}
$ErrorActionPreference = 'Stop' 
$record = [ordered]@{ args=$importArgs; image_digest=$imageDigest; exit_code=$result; started_at=$startedAt;
    finished_at=(Get-Date).ToUniversalTime().ToString('o'); wall_seconds=$timer.Elapsed.TotalSeconds; stdout=$outLog; stderr=$errLog }
$record | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $storePath 'import_record.json') -Encoding UTF8
exit $result
