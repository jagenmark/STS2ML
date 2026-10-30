param(
    [Parameter(Mandatory=$true)][string]$Experiment,
    [int]$AfterPid = 0,
    [int]$Workers = 4
)
$ErrorActionPreference = 'Stop'
$Sts2Root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $Sts2Root
$Sts2Experiment = (Resolve-Path -LiteralPath $Experiment).Path
if ($AfterPid) {
    $Sts2Previous = Get-Process -Id $AfterPid -ErrorAction SilentlyContinue
    if ($Sts2Previous) { $Sts2Previous.WaitForExit() }
}
if (Test-Path -LiteralPath (Join-Path $Sts2Experiment 'STOP')) {
    throw 'STOP is present; recovery will not override a requested stop.'
}
$Sts2Status = Get-Content -LiteralPath (Join-Path $Sts2Experiment 'status.json') -Raw | ConvertFrom-Json
if ($Sts2Status.stage -eq 'complete') { Write-Output 'Experiment already complete.'; exit 0 }
if ($Sts2Status.stage -ne 'failed') { throw 'Expected a failed, exited runner; refusing concurrent recovery.' }
$Sts2Config = Get-Content -LiteralPath (Join-Path $Sts2Experiment 'config.json') -Raw | ConvertFrom-Json
$Sts2Python = Join-Path $Sts2Root '.venv/cpu/Scripts/python.exe'
$Sts2Dotnet = Join-Path $Sts2Root 'artifacts/tools/dotnet/dotnet.exe'
$Sts2Upstream = Join-Path $Sts2Root 'artifacts/upstreams/sts2-cli/src/Sts2Headless'

# The running collection held the old DLLs open. Install the audited host fix
# only after it exits, then verify real event effects before retrying episodes.
& $Sts2Python scripts/apply-headless-patches.py
if ($LASTEXITCODE) { throw 'Host patch validation failed.' }
foreach ($Sts2Helper in @('ObservationExport.cs','TrainingSupport.cs','PresentationFix.cs')) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot "headless/$Sts2Helper") -Destination (Join-Path $Sts2Upstream $Sts2Helper)
}
& $Sts2Dotnet build artifacts/upstreams/sts2-cli/src/Sts2Headless/Sts2Headless.csproj -c Release --nologo -v quiet
if ($LASTEXITCODE) { throw 'Host build failed.' }
& $Sts2Dotnet run --project tests/native-events/Events.csproj -c Release -- $Sts2Root
if ($LASTEXITCODE) { throw 'Native event effects failed qualification.' }

$Sts2Args = @('scripts/train-act1.py','--output',$Sts2Experiment,'--resume','--allow-host-update','--workers',"$Workers")
foreach ($Sts2Field in @('runs','samples','roots_per_fight','query_probability','prefix','epochs','evaluate','device')) {
    $Sts2Args += '--' + $Sts2Field.Replace('_','-')
    $Sts2Args += [System.Convert]::ToString($Sts2Config.$Sts2Field, [Globalization.CultureInfo]::InvariantCulture)
}
if ($Sts2Config.macro_checkpoint) { $Sts2Args += @('--macro-checkpoint',[string]$Sts2Config.macro_checkpoint) }
if ($Sts2Config.collect_only) { $Sts2Args += '--collect-only' }
$Sts2Runner = if ($Sts2Config.device -like 'cuda*') { Join-Path $Sts2Root '.venv/rocm/Scripts/python.exe' } else { $Sts2Python }
& $Sts2Runner @Sts2Args
if ($LASTEXITCODE) { throw 'Resumed experiment failed; inspect its status and error logs.' }
