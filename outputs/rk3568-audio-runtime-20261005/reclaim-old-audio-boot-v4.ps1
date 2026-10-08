param([Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedInputSha256)
$ErrorActionPreference = 'Stop'
$taskDirectory = (Get-Item -LiteralPath $PSScriptRoot).FullName
$taskRepo = (Get-Item -LiteralPath (Join-Path $taskDirectory '../..')).FullName
$taskAdb = 'C:\Users\lenovo\Tools\android-platform-tools\platform-tools\adb.exe'
$taskReceipt = Join-Path $taskDirectory 'build/cache-reclaim-audio-boot-v4.json'
$taskInput = Join-Path $taskDirectory 'build/board-audio-v4/input-manifest.json'
$taskOldHost = Join-Path $taskRepo 'outputs/rk3568-audio-package-20261005/build/ram-audio-v3/boot-padded.img'
$taskOldRemote = '/cache/rtctrl-audio-bootm-20261005-v3/boot-audio.img'
$taskOldDigest = '5d9e5de346a307edff9dc034f2b396e949b85d83564c1b6cfe9b62467a6ff8ab'
if (Test-Path -LiteralPath $taskReceipt) { throw 'Fresh cache reclaim receipt required' }
if ((Get-FileHash -LiteralPath $taskInput -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedInputSha256) {
    throw 'New prepared package identity differs'
}
$taskManifest = Get-Content -Raw -LiteralPath $taskInput | ConvertFrom-Json
foreach ($taskEntry in $taskManifest.files) {
    $taskFile = Join-Path $taskRepo $taskEntry.source
    $taskItem = Get-Item -LiteralPath $taskFile
    if ($taskItem.LinkType -or $taskItem.Length -ne $taskEntry.bytes -or
        (Get-FileHash -LiteralPath $taskFile -Algorithm SHA256).Hash.ToLowerInvariant() -ne $taskEntry.sha256) {
        throw 'New replacement input differs before reclaim'
    }
}
$taskBackup = Get-Item -LiteralPath $taskOldHost
if ($taskBackup.LinkType -or $taskBackup.Length -ne 41943040 -or
    (Get-FileHash -LiteralPath $taskOldHost -Algorithm SHA256).Hash.ToLowerInvariant() -ne $taskOldDigest) {
    throw 'Byte-exact ordinary host copy of the old cache package required'
}
$taskRecord = [ordered]@{timestamp=(Get-Date -Format o); completed=$false; exact_remote=$taskOldRemote;
    host_copy=$taskOldHost; bytes=41943040; sha256=$taskOldDigest; recursive_delete=$false;
    partition_write=$false; flash=$false; saveenv=$false; network_configuration_changed=$false; commands=@()}
function Invoke-TaskRead {
    param([string]$Command)
    $ErrorActionPreference = 'Continue'
    $taskReply = & $taskAdb -s 127.0.0.1:15555 shell $Command 2>&1
    $taskExit = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    $script:taskRecord.commands += @{command=$Command; exit_code=$taskExit; output=($taskReply -join "`n")}
    [IO.File]::WriteAllText($taskReceipt, ($script:taskRecord | ConvertTo-Json -Depth 9), [Text.UTF8Encoding]::new($false))
    if ($taskExit -ne 0) { throw 'Cache operation failed; evidence preserved' }
    return ($taskReply -join "`n").Trim()
}
if ((Invoke-TaskRead 'id -u; uname -r; getprop ro.build.version.release; getprop sys.boot_completed') -ne "0`n4.19.232`n11`n1") {
    throw 'Fresh original Android identity differs'
}
$taskProtected = 'sha256sum /dev/block/by-name/boot /dev/block/by-name/uboot /dev/block/by-name/trust /dev/block/by-name/dtbo /dev/block/by-name/vbmeta /cache/rtctrl-source-userspace-20261004/rootfs.ext4 /cache/rtctrl-network-rootfs-20261004/rootfs.img'
$taskNative = 'sha256sum /cache/rtctrl-pid1-20261005-v3/rootfs-pid1.ext4 /cache/rtctrl-pid1-20261005-v3/initramfs-pid1.cpio.gz /cache/rtctrl-rcu-reset-20261004/Image'
if ((Invoke-TaskRead $taskProtected) -ne ($taskManifest.protected_sha256 -join "`n")) { throw 'Protected input differs' }
if ((Invoke-TaskRead $taskNative) -ne ($taskManifest.native_cached_sha256 -join "`n")) { throw 'Native input differs' }
[void](Invoke-TaskRead 'df -k /cache')
$taskOrdinary = 'test $(realpath /cache) = /cache && test ! -L /cache/rtctrl-audio-bootm-20261005-v3 && test $(realpath /cache/rtctrl-audio-bootm-20261005-v3) = /cache/rtctrl-audio-bootm-20261005-v3 && test ! -L ' + $taskOldRemote + ' && test $(realpath ' + $taskOldRemote + ') = ' + $taskOldRemote + ' && stat -c %u:%g:%h:%s:%F ' + $taskOldRemote
if ((Invoke-TaskRead $taskOrdinary) -ne '0:0:1:41943040:regular file') { throw 'Exact old ordinary cache file required' }
if ((Invoke-TaskRead ('sha256sum ' + $taskOldRemote)) -ne ($taskOldDigest + '  ' + $taskOldRemote)) {
    throw 'Cache file differs from the host copy'
}
# One previously checked ordinary cache file only; no recursive operation.
[void](Invoke-TaskRead ('rm -- ' + $taskOldRemote + ' && sync && test ! -e ' + $taskOldRemote + ' && test ! -L ' + $taskOldRemote + ' && echo AUDIO_OLD_CACHE_BOOT_EXACT_FILE_RECLAIMED'))
if ((Invoke-TaskRead $taskProtected) -ne ($taskManifest.protected_sha256 -join "`n")) { throw 'Protected input changed' }
if ((Invoke-TaskRead $taskNative) -ne ($taskManifest.native_cached_sha256 -join "`n")) { throw 'Native input changed' }
[void](Invoke-TaskRead 'df -k /cache')
$taskRecord.completed=$true
[IO.File]::WriteAllText($taskReceipt, ($taskRecord | ConvertTo-Json -Depth 9), [Text.UTF8Encoding]::new($false))
Write-Output 'AUDIO_OLD_CACHE_BOOT_RECLAIMED_HOST_FULL_COPY_AND_PROTECTED_SHA_MATCHED'
