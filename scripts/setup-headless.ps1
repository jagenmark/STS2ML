param(
    [string]$GameRoot = 'C:/Program Files (x86)/Steam/steamapps/common/Slay the Spire 2'
)
$ErrorActionPreference = 'Stop'
$Sts2Root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $Sts2Root
$Sts2Revision = 'fec723a21741a1a33a4f54dc9b28c50df31d6e45'
$Sts2Upstream = Join-Path $Sts2Root 'artifacts/upstreams/sts2-cli'
$Sts2SdkRoot = Join-Path $Sts2Root 'artifacts/tools/dotnet'
$Sts2Python = Join-Path $Sts2Root '.venv/cpu/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $Sts2Python)) { throw 'Create the CPU Python environment first.' }
$Sts2Release = Get-Content -LiteralPath (Join-Path $GameRoot 'release_info.json') -Raw | ConvertFrom-Json
if ($Sts2Release.version -ne 'v0.111.0' -or $Sts2Release.commit -ne '41cef1ea') {
    throw 'This headless profile requires game v0.111.0 / 41cef1ea.'
}
$Sts2Assembly = Join-Path $GameRoot 'data_sts2_windows_x86_64/sts2.dll'
if ((Get-FileHash -LiteralPath $Sts2Assembly -Algorithm SHA256).Hash -ne '0861bfa1df347538d932f22d580e75420f08082792eb914e53b4882764acdbe9') {
    throw 'Unqualified Windows game assembly; do not bypass the build check.'
}
if (-not (Test-Path -LiteralPath (Join-Path $Sts2SdkRoot 'dotnet.exe'))) {
    New-Item -ItemType Directory -Force artifacts/tools | Out-Null
    $Sts2Metadata = Invoke-RestMethod 'https://builds.dotnet.microsoft.com/dotnet/release-metadata/9.0/releases.json'
    $Sts2Sdk = $Sts2Metadata.releases.sdk | Where-Object { $_.version -eq '9.0.320' } | Select-Object -First 1
    $Sts2File = $Sts2Sdk.files | Where-Object { $_.rid -eq 'win-x64' -and $_.name -like '*.zip' } | Select-Object -First 1
    if (-not $Sts2File -or -not $Sts2File.url.StartsWith('https://builds.dotnet.microsoft.com/')) {
        throw 'Pinned Microsoft SDK download not found.'
    }
    @{ version = $Sts2Sdk.version; file = $Sts2File } | ConvertTo-Json -Depth 5 | Set-Content artifacts/tools/dotnet-sdk-source.json
    Invoke-WebRequest -Uri $Sts2File.url -OutFile artifacts/tools/dotnet-sdk.zip
    if ((Get-FileHash artifacts/tools/dotnet-sdk.zip -Algorithm SHA512).Hash -ne $Sts2File.hash) {
        throw 'SDK checksum mismatch.'
    }
    Expand-Archive -LiteralPath artifacts/tools/dotnet-sdk.zip -DestinationPath $Sts2SdkRoot
}
if (-not (Test-Path -LiteralPath $Sts2Upstream)) {
    git clone https://github.com/wuhao21/sts2-cli.git $Sts2Upstream
    if ($LASTEXITCODE) { throw 'Clone failed.' }
    git -C $Sts2Upstream checkout --detach $Sts2Revision
    if ($LASTEXITCODE) { throw 'Pinned checkout failed.' }
}
if ((git -C $Sts2Upstream rev-parse HEAD).Trim() -ne $Sts2Revision) { throw 'Wrong upstream revision.' }
& $Sts2Python (Join-Path $PSScriptRoot 'apply-headless-patches.py')
if ($LASTEXITCODE) { throw 'Pinned headless patch validation failed.' }
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'headless/ObservationExport.cs') -Destination (Join-Path $Sts2Upstream 'src/Sts2Headless/ObservationExport.cs')
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'headless/TrainingSupport.cs') -Destination (Join-Path $Sts2Upstream 'src/Sts2Headless/TrainingSupport.cs')
$Sts2Lib = Join-Path $Sts2Upstream 'lib'
New-Item -ItemType Directory -Force $Sts2Lib,artifacts/tools/sts2-patcher | Out-Null
$Sts2Dlls = @('sts2.dll','SmartFormat.dll','SmartFormat.ZString.dll','Sentry.dll','Sentry.Godot.dll','Steamworks.NET.dll','MonoMod.Backports.dll','MonoMod.ILHelpers.dll','0Harmony.dll','System.IO.Hashing.dll')
foreach ($Sts2Dll in $Sts2Dlls) {
    Copy-Item -LiteralPath (Join-Path "$GameRoot/data_sts2_windows_x86_64" $Sts2Dll) -Destination (Join-Path $Sts2Lib $Sts2Dll)
}
Copy-Item -LiteralPath "$Sts2Lib/sts2.dll" -Destination "$Sts2Lib/sts2.dll.original"
# Reuse the pinned setup's exact patcher; only local library copies are patched.
@'
from pathlib import Path
setup = Path('artifacts/upstreams/sts2-cli/setup.sh').read_text(encoding='utf-8')
for name, marker in [('Patcher.csproj', 'PROJ'), ('Program.cs', 'CSHARP')]:
    body = setup.split("<< '" + marker + "'\n", 1)[1].split('\n' + marker, 1)[0]
    (Path('artifacts/tools/sts2-patcher') / name).write_text(body + '\n', encoding='utf-8')
'@ | & $Sts2Python -
if ($LASTEXITCODE) { throw 'Could not extract the pinned patcher.' }
& $Sts2Python artifacts/upstreams/sts2-cli/scripts/extract_localization.py "$GameRoot/SlayTheSpire2.pck"
if ($LASTEXITCODE) { throw 'Localization extraction failed.' }
$env:DOTNET_ROOT = $Sts2SdkRoot
$env:DOTNET_CLI_TELEMETRY_OPTOUT = '1'
$env:DOTNET_NOLOGO = '1'
& "$Sts2SdkRoot/dotnet.exe" run --project artifacts/tools/sts2-patcher/Patcher.csproj -- "$Sts2Lib/sts2.dll"
if ($LASTEXITCODE) { throw 'Game library patching failed.' }
& "$Sts2SdkRoot/dotnet.exe" build artifacts/upstreams/sts2-cli/src/Sts2Headless/Sts2Headless.csproj -c Release --nologo -v minimal
if ($LASTEXITCODE) { throw 'Headless build failed.' }
