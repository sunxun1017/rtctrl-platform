$ErrorActionPreference = 'Stop'
$taskRoot = (Get-Item -LiteralPath $PSScriptRoot).FullName
$taskRepo = (Get-Item -LiteralPath (Join-Path $taskRoot '..\..')).FullName
$taskAdb = 'C:\Users\lenovo\Tools\android-platform-tools\platform-tools\adb.exe'
$taskReceipt = Join-Path $taskRepo 'outputs\rk3568-pid1-20261005\private\android-before-default-address-v1.json'
if (Test-Path -LiteralPath $taskReceipt) { throw 'Fresh evidence path required' }
$taskImage = Join-Path $taskRepo 'outputs\rk3568-boot-package-20261005\build\ram-candidate-v2\boot-padded.img'
$taskPackageSha = '67f351b822887c5e2fae10c099760a126d20daee2e9b2931b945a1176af37dbe'
if ((Get-Item -LiteralPath $taskImage).Length -ne 41943040 -or (Get-FileHash -LiteralPath $taskImage -Algorithm SHA256).Hash.ToLower() -ne $taskPackageSha) { throw 'Host package changed' }
$taskExpected = @'
0db7ae12eebf0f3819e5fb72d9291abb4f12222084d87348a6a95a6a00f21b28  /dev/block/by-name/boot
4758af21c8f5751cc92166baf7a6e4a79c17d0f87ce9bad64a16af91a125447e  /dev/block/by-name/uboot
bb9f8df61474d25e71fa00722318cd387396ca1736605e1248821cc0de3d3af8  /dev/block/by-name/trust
59b971b4300092de56164904d6a1747276eb569acfc31c09dda6569aa5c8e57d  /dev/block/by-name/dtbo
76ff77959f2451ee3838de5b2d90a0e21017345cac4f7ce56c9da7a630edc752  /dev/block/by-name/vbmeta
4fcebae566d889072954b2f5b220474fe9accd75bbb48471023f24841b6ed95e  /cache/rtctrl-source-userspace-20261004/rootfs.ext4
32273043cbc6656612dbf8a2e31866b27080ef26b8ee44b1ad83f91ae6c330a3  /cache/rtctrl-network-rootfs-20261004/rootfs.img
'@
$taskRecord = [ordered]@{timestamp=(Get-Date).ToString('o'); read_only=$true; partition_write=$false; host_package_sha256=$taskPackageSha; sections=[ordered]@{}}
function Read-TaskShell {
    param([string]$Name, [string]$Command)
    $ErrorActionPreference = 'Continue'
    $taskOutput = & $taskAdb -s 127.0.0.1:15555 shell $Command 2>&1
    $taskExit = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    $taskRecord.sections[$Name] = @{command=$Command; exit_code=$taskExit; output=($taskOutput -join "`n")}
    if ($taskExit -ne 0) { throw ('Read-only gate failed: ' + $Name) }
    return ($taskOutput -join "`n").Trim()
}
try {
    if ((Read-TaskShell 'identity' 'id -u; uname -r; getprop ro.build.version.release; getprop sys.boot_completed') -ne "0`n4.19.232`n11`n1") { throw 'Fresh Android identity rejected' }
    $taskSeven = Read-TaskShell 'seven_protected_sha' 'sha256sum /dev/block/by-name/boot /dev/block/by-name/uboot /dev/block/by-name/trust /dev/block/by-name/dtbo /dev/block/by-name/vbmeta /cache/rtctrl-source-userspace-20261004/rootfs.ext4 /cache/rtctrl-network-rootfs-20261004/rootfs.img'
    if ($taskSeven -ne $taskExpected.Replace("`r`n", "`n").Trim()) { throw 'Protected inputs changed' }
    $taskCache = Read-TaskShell 'cache_identities' 'stat -c %u:%g:%h:%s /cache/rtctrl-bootm-ram-20261005-v1/boot-linux-ram-v2.img /cache/rtctrl-pid1-20261005-v3/rootfs-pid1.ext4 /cache/rtctrl-pid1-20261005-v3/initramfs-pid1.cpio.gz'
    if ($taskCache -ne "0:0:1:41943040`n0:0:1:16777216`n0:0:1:972203") { throw 'Cache input identity differs' }
    $taskCachedSha = Read-TaskShell 'cache_sha' 'sha256sum /cache/rtctrl-bootm-ram-20261005-v1/boot-linux-ram-v2.img /cache/rtctrl-pid1-20261005-v3/rootfs-pid1.ext4 /cache/rtctrl-pid1-20261005-v3/initramfs-pid1.cpio.gz'
    $taskCachedExpected = "$taskPackageSha  /cache/rtctrl-bootm-ram-20261005-v1/boot-linux-ram-v2.img`n3a87bd54f44b1e5d20701514c26669d086123e8b2ee8ed9087cc118c12fc679d  /cache/rtctrl-pid1-20261005-v3/rootfs-pid1.ext4`n54db3bb6fa94dd1570a306aa90e3caa6ae5ed7bb6b93d96afcae0c5f8881afef  /cache/rtctrl-pid1-20261005-v3/initramfs-pid1.cpio.gz"
    if ($taskCachedSha -ne $taskCachedExpected) { throw 'Cached input SHA differs' }
    $taskBattery = Read-TaskShell 'battery' 'dumpsys battery'
    if ($taskBattery -notmatch '(?m)^\s*level: (\d+)\s*$' -or [int]$Matches[1] -lt 20) { throw 'Battery gate rejected trial' }
    $taskRecord.accepted = $true
    Write-Output ('DEFAULT_ADDRESS_PREFLIGHT_ACCEPTED battery=' + $Matches[1])
} finally {
    [IO.File]::WriteAllText($taskReceipt, ($taskRecord | ConvertTo-Json -Depth 8), [Text.UTF8Encoding]::new($false))
}
