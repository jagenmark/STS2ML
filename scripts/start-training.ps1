param(
    [ValidateRange(1, 100)][int]$Pages = 10,
    [ValidateRange(1, 10000)][int]$Epochs = 30,
    [string]$Device = 'cuda:0'
)
$ErrorActionPreference = 'Stop'
$Sts2Repo = Split-Path -Parent $PSScriptRoot
$Sts2Environment = if ($Device -eq 'cpu') { 'cpu' } else { 'rocm' }
$Sts2Python = Join-Path $Sts2Repo ".venv/$Sts2Environment/Scripts/python.exe"
if (-not (Test-Path -LiteralPath $Sts2Python)) { throw "Missing environment: $Sts2Python" }
$Sts2Run = Join-Path $Sts2Repo ('artifacts/v0.111.0/silent-a10/workstation-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
New-Item -ItemType Directory -Path $Sts2Run | Out-Null
$Sts2Arguments = @('-u', 'scripts/train-workstation.py', '--output', ('"' + $Sts2Run + '"'),
    '--pages', $Pages, '--epochs', $Epochs, '--device', $Device)
$Sts2Process = Start-Process -FilePath $Sts2Python -ArgumentList $Sts2Arguments -WorkingDirectory $Sts2Repo -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $Sts2Run 'pipeline.log') -RedirectStandardError (Join-Path $Sts2Run 'training.log')
@{ launcher_pid = $Sts2Process.Id; output = $Sts2Run } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $Sts2Run 'launcher.json') -Encoding utf8
Write-Output "Started: $Sts2Run"
Write-Output "Status: Get-Content '$Sts2Run/status.json'"
Write-Output "Training log: Get-Content '$Sts2Run/training.log' -Tail 20 -Wait"
Write-Output "Stop after current stage: New-Item '$Sts2Run/STOP' -ItemType File"
