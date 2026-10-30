param([string]$OutDir = "dist", [string]$ThirdParty = "")

$ErrorActionPreference = "Stop"
$Project = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..")).TrimEnd('\', '/')
try {
    if (-not [IO.Path]::IsPathRooted($OutDir)) { $OutDir = Join-Path $Project $OutDir }
    $OutDir = [IO.Path]::GetFullPath($OutDir)
} catch {
    Write-Error "Invalid output directory." -ErrorAction Continue
    exit 2
}
if (-not $OutDir.StartsWith($Project + '\', [StringComparison]::OrdinalIgnoreCase)) {
    Write-Error "Output directory must stay inside the project." -ErrorAction Continue
    exit 2
}
if ($ThirdParty) {
    Write-Error "Upstream source repositories are excluded from publication packages." -ErrorAction Continue
    exit 2
}
$required = @('LICENSE', 'src/kgbuilder/__init__.py', 'results/expected_results.json',
    'data/benchmarks/bsee_gold/v1/adjudicated.jsonl', 'data/benchmarks/bsee_gold/v2/adjudicated.jsonl')
foreach ($entry in $required) {
    if (-not (Test-Path -LiteralPath (Join-Path $Project $entry) -PathType Leaf)) {
        Write-Error "Required package entry is missing: $entry" -ErrorAction Continue
        exit 1
    }
}
$exclude = '(^|/)(\.git|\.venvs|\.venv|\.cache|\.neo4j|dist|runs|third_party|__pycache__|\.vscode|\.agents)(/|$)|(^|/)\.env($|\.(?!example$))|\.py[cod]$|^research(/|$)'
function Get-PackageFiles([string]$Path) {
    foreach ($entry in Get-ChildItem -LiteralPath $Path -Force) {
        $rel = $entry.FullName.Substring($Project.Length + 1).Replace('\', '/')
        if ($entry.PSIsContainer) {
            if (($rel + '/') -notmatch $exclude) { Get-PackageFiles -Path $entry.FullName }
        } elseif ($rel -notmatch $exclude) { $entry }
    }
}
$files = @(Get-PackageFiles -Path $Project | Where-Object {
    -not $_.FullName.StartsWith($OutDir + '\', [StringComparison]::OrdinalIgnoreCase)
} | Sort-Object FullName)
New-Item -ItemType Directory -Path $OutDir -Force | Out-Null
$zip = Join-Path $OutDir ('kg-builder_' + (Get-Date -Format yyyyMMdd_HHmmss_fff) + '.zip')
Add-Type -AssemblyName System.IO.Compression, System.IO.Compression.FileSystem
$archive = [IO.Compression.ZipFile]::Open($zip, 'Create')
try {
    foreach ($file in $files) {
        $rel = $file.FullName.Substring($Project.Length + 1).Replace('\', '/')
        [IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
            $archive, $file.FullName, $rel, [IO.Compression.CompressionLevel]::Optimal) | Out-Null
    }
} finally { $archive.Dispose() }
Write-Output ("ZIP: {0}`nFiles: {1}" -f $zip, $files.Count)
exit 0
