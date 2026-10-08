$ErrorActionPreference = 'Stop'
$adbPath = 'C:\Users\lenovo\Tools\android-platform-tools\platform-tools\adb.exe'
$target = '127.0.0.1:15555'
$workspace = (Get-Item -LiteralPath (Join-Path $PSScriptRoot '../..')).FullName
$manifestPath = Join-Path $workspace 'outputs/rk3568-boot-package-20261005/build/ram-candidate-v2/manifest.json'
$receiptPath = Join-Path $PSScriptRoot 'stage-candidate-v2.json'
if (Test-Path -LiteralPath $receiptPath) { throw 'Refusing to overwrite receipt' }
if ((Get-FileHash -LiteralPath $manifestPath).Hash.ToLowerInvariant() -ne 'a7532336f38cb2cd249551647292da0d331f47f7af5222c52e66f10660b6e551') { throw 'Candidate manifest changed' }
$manifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
if ($manifest.status -ne 'RAM_ONLY_NOT_FLASH_READY' -or $manifest.flash_authorized -ne $false) { throw 'Wrong candidate contract' }
$packagePath = Join-Path $workspace 'outputs/rk3568-boot-package-20261005/build/ram-candidate-v2/boot-padded.img'
$packageSha = '67f351b822887c5e2fae10c099760a126d20daee2e9b2931b945a1176af37dbe'
if ((Get-Item -LiteralPath $packagePath).Length -ne 41943040 -or (Get-FileHash -LiteralPath $packagePath).Hash.ToLowerInvariant() -ne $packageSha) { throw 'Candidate package changed' }
$scriptPath = Join-Path $PSScriptRoot 'prepare-candidate-v2-android.sh'
$record = [ordered]@{timestamp=(Get-Date -Format o); target=$target; package_sha256=$packageSha; script_sha256=(Get-FileHash -LiteralPath $scriptPath).Hash.ToLowerInvariant(); commands=@(); flash=$false; saveenv=$false}
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
$work='/data/local/tmp/rtctrl-bootm-candidate-20261005-v2'
$preflight=@(
    'test $(id -u) = 0',
    'test $(uname -r) = 4.19.232',
    'test $(getprop sys.boot_completed) = 1',
    ('test ! -e ' + $work),
    ('test ! -L ' + $work),
    ('mkdir -m 700 ' + $work),
    ('test $(realpath ' + $work + ') = ' + $work)
) -join ' && '
[void](Invoke-Adb @('shell', ('su 0 sh -c ''' + $preflight + '''')))
[void](Invoke-Adb @('push',$packagePath,($work+'/boot-linux-ram-v2.img')))
[void](Invoke-Adb @('push',$scriptPath,($work+'/prepare-candidate-v2-android.sh')))
$reply = Invoke-Adb @('shell',('su 0 sh '+$work+'/prepare-candidate-v2-android.sh'))
if ($reply -notmatch '(?m)^LINUX_BOOT_V2_40MIB_CACHED_SHA_VERIFIED_RAM_ONLY_NO_FLASH\r?$') { throw 'Candidate staging final marker missing' }
$record.completed=$true
[IO.File]::WriteAllText($receiptPath, ($record | ConvertTo-Json -Depth 8))
