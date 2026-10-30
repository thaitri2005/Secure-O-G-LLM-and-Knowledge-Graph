param(
    [switch]$VerifyOnly,
    [switch]$Clone,
    [string]$WheelDir = "",
    [string]$Python312 = "",
    [string]$Python39 = ""
)
$ErrorActionPreference = "Stop"
if ($VerifyOnly -and ($Clone -or $WheelDir)) {
    throw "-VerifyOnly cannot be combined with -Clone or -WheelDir."
}
$Project = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
. (Join-Path $PSScriptRoot "onprem_env.ps1")
$env:PYTHONPATH = Join-Path $Project "src"
function Invoke-Checked([string]$Exe, [string[]]$Arguments) {
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Command failed with exit code $LASTEXITCODE" }
}
if (-not $VerifyOnly -and -not $WheelDir -and -not $Clone) {
    throw "Supply -WheelDir for offline installation, -Clone for pinned repositories, or -VerifyOnly."
}
if ($Clone) {
    $bootstrap = if ($Python312) { $Python312 } else { Join-Path $Project ".venvs/kggen/Scripts/python.exe" }
    Invoke-Checked $bootstrap @("-B", (Join-Path $PSScriptRoot "clone_repos.py"))
    if (-not $WheelDir) { exit 0 }
}
if ($WheelDir -and -not $VerifyOnly) {
    $WheelDir = (Resolve-Path -LiteralPath $WheelDir).Path
    foreach ($name in @("kggen", "edc", "gliner")) {
        $venv = Join-Path $Project ".venvs/$name"
        $python = Join-Path $venv "Scripts/python.exe"
        if (-not (Test-Path -LiteralPath $python)) {
            $base = if ($name -eq "edc") { $Python39 } else { $Python312 }
            if (-not $base) { throw "Supply the matching Python executable for $name." }
            Invoke-Checked $base @("-m", "venv", $venv)
        }
        Invoke-Checked $python @("-m", "pip", "install", "--no-index", "--find-links", $WheelDir,
            "-r", (Join-Path $Project "configs/requirements/$name.txt"))
    }
    # Install from an isolated copy so upstream clones remain pristine.
    $python = Join-Path $Project ".venvs/kggen/Scripts/python.exe"
    Invoke-Checked $python @("-B", (Join-Path $PSScriptRoot "setup_verify.py"), "--install-local", "--wheels", $WheelDir)
}
Invoke-Checked (Join-Path $Project ".venvs/kggen/Scripts/python.exe") @("-B", (Join-Path $PSScriptRoot "setup_verify.py"))
