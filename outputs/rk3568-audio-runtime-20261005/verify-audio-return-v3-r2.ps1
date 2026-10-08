$ErrorActionPreference = 'Stop'
$taskDir = (Get-Item -LiteralPath $PSScriptRoot).FullName
$taskManifestPath = Join-Path $taskDir 'build/board-audio-v3/input-manifest.json'
$taskReceipt = Join-Path $taskDir 'build/audio-return-v3-r2.json'
$taskAdb = 'C:\Users\lenovo\Tools\android-platform-tools\platform-tools\adb.exe'
if (Test-Path -LiteralPath $taskReceipt) { throw 'Fresh return evidence required' }
if ((Get-FileHash -LiteralPath $taskManifestPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne '42fa9e8d5d3c2441ba912d0cbda7d5257371d96be6255bc8478f70854d373b36') {
    throw 'Frozen trial identity differs'
}
$taskManifest = Get-Content -Raw -LiteralPath $taskManifestPath | ConvertFrom-Json
$taskRecord = [ordered]@{timestamp=(Get-Date -Format o); completed=$false; commands=@(); partition_write=$false; flash=$false; saveenv=$false; network_configuration_changed=$false}
function Read-TaskAdb {
    param([string]$Command)
    $ErrorActionPreference = 'Continue'
    if ($Command.Contains("'")) { throw 'Fixed read-only command quoting differs' }
    $taskWireCommand = "su 0 sh -c '" + $Command + "'"
    $taskReply = & $taskAdb -s 127.0.0.1:15555 shell $taskWireCommand 2>&1
    $taskCode = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    $script:taskRecord.commands += @{command=$Command; wire_command=$taskWireCommand; exit_code=$taskCode; output=($taskReply -join "`n")}
    [IO.File]::WriteAllText($taskReceipt, ($script:taskRecord | ConvertTo-Json -Depth 8), [Text.UTF8Encoding]::new($false))
    if ($taskCode -ne 0) { throw 'Read-only return check failed; evidence retained' }
    return ($taskReply -join "`n").Trim()
}
if ((Read-TaskAdb 'id -u; uname -r; getprop ro.build.version.release; getprop sys.boot_completed') -ne "0`n4.19.232`n11`n1") {
    throw 'Fresh original Android identity differs'
}
$taskProtectedCommand = 'sha256sum /dev/block/by-name/boot /dev/block/by-name/uboot /dev/block/by-name/trust /dev/block/by-name/dtbo /dev/block/by-name/vbmeta /cache/rtctrl-source-userspace-20261004/rootfs.ext4 /cache/rtctrl-network-rootfs-20261004/rootfs.img'
if ((Read-TaskAdb $taskProtectedCommand) -ne ($taskManifest.protected_sha256 -join "`n")) {
    throw 'Seven protected identities differ'
}
if ((Read-TaskAdb 'sha256sum /cache/rtctrl-pid1-20261005-v3/rootfs-pid1.ext4 /cache/rtctrl-pid1-20261005-v3/initramfs-pid1.cpio.gz /cache/rtctrl-rcu-reset-20261004/Image') -ne ($taskManifest.native_cached_sha256 -join "`n")) {
    throw 'Native cached input identities differ'
}
[void](Read-TaskAdb 'dumpsys battery')
[void](Read-TaskAdb 'df -k /cache')
$taskRecord.completed=$true
[IO.File]::WriteAllText($taskReceipt, ($taskRecord | ConvertTo-Json -Depth 8), [Text.UTF8Encoding]::new($false))
Write-Output 'AUDIO_NORMAL_REBOOT_ORIGINAL_ANDROID_SEVEN_SHA_MATCHED'
