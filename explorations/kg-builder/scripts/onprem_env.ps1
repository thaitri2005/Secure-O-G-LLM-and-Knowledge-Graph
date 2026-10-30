# Dot-source to load configs/runtime/onprem.env into the current PowerShell session:
#   . ./scripts/onprem_env.ps1
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
foreach ($line in Get-Content (Join-Path $ProjectRoot "configs/runtime/onprem.env")) {
    if ($line -match '^\s*([A-Z0-9_]+)=(.*)$') {
        $value = $Matches[2].Trim()
        if ($value.StartsWith("./")) { $value = Join-Path $ProjectRoot $value.Substring(2) }
        Set-Item -Path "Env:$($Matches[1])" -Value $value
    }
}
New-Item -ItemType Directory -Force -Path $env:TEMP | Out-Null
