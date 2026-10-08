$ErrorActionPreference = 'Stop'
$adbPath = 'C:\Users\lenovo\Tools\android-platform-tools\platform-tools\adb.exe'
$target = '127.0.0.1:15555'
$workspace = (Get-Item -LiteralPath (Join-Path $PSScriptRoot '../..')).FullName
$manifestPath = Join-Path $workspace 'outputs/rk3568-boot-package-20261005/build/original-freeze-v1/original-ram-manifest-v1.json'
$receiptPath = Join-Path $PSScriptRoot 'stage-original-v1.json'
if (Test-Path -LiteralPath $receiptPath) { throw 'Refusing to overwrite receipt' }
if ((Get-FileHash -LiteralPath $manifestPath).Hash.ToLowerInvariant() -ne '68f16cc3d2ae80e315d3787e04f99e87b8458c90321b7bcee41a94ac370f6cb2') { throw 'Original manifest changed' }
$manifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
if ($manifest.kind -ne 'ORIGINAL_BACKUP_RAM_ONLY' -or $manifest.bytes -ne 41943040 -or $manifest.flash -ne $false) { throw 'Wrong manifest contract' }
$packagePath = Join-Path $workspace $manifest.package_path
if ((Get-Item -LiteralPath $packagePath).Length -ne 41943040 -or (Get-FileHash -LiteralPath $packagePath).Hash.ToLowerInvariant() -ne $manifest.sha256) { throw 'Original package changed' }
$scriptPath = Join-Path $PSScriptRoot 'prepare-original-android.sh'
$record = [ordered]@{timestamp=(Get-Date -Format o); target=$target; package_sha256=$manifest.sha256; script_sha256=(Get-FileHash -LiteralPath $scriptPath).Hash.ToLowerInvariant(); commands=@(); flash=$false; saveenv=$false}
function Invoke-Adb([string[]]$arguments) {
    $ErrorActionPreference = 'Continue'
    $reply = & $adbPath -s $target @arguments 2>&1
    $code = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    $script:record.commands += @{arguments=$arguments; exit_code=$code; output=($reply -join "`n")}
    [IO.File]::WriteAllText($receiptPath, ($script:record | ConvertTo-Json -Depth 8))
    Write-Host ($reply -join "`n")
    if ($code -ne 0) { throw 'ADB staging operation failed; receipt preserved' }
    return ($reply -join "`n")
}
$work='/data/local/tmp/rtctrl-bootm-original-20261005-v1'
$preflight='set -eu; test $(id -u) = 0; test $(uname -r) = 4.19.232; test $(getprop sys.boot_completed) = 1; test ! -e ' + $work + '; test ! -L ' + $work + '; mkdir -m 700 ' + $work + '; test $(realpath ' + $work + ') = ' + $work
[void](Invoke-Adb @('shell', ('su 0 sh -c ''' + $preflight + '''')))
[void](Invoke-Adb @('push',$packagePath,($work+'/boot-original.img')))
[void](Invoke-Adb @('push',$scriptPath,($work+'/prepare-original-android.sh')))
$reply = Invoke-Adb @('shell',('su 0 sh '+$work+'/prepare-original-android.sh'))
if ($reply -notmatch '(?m)^ORIGINAL_BOOT_40MIB_CACHED_SHA_VERIFIED_NO_FLASH\r?$') { throw 'Cache staging final marker missing' }
$record.completed=$true
[IO.File]::WriteAllText($receiptPath, ($record | ConvertTo-Json -Depth 8))
