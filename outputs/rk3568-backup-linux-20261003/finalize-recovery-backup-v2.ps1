$ErrorActionPreference = 'Stop'
$taskAdb = 'C:\Users\lenovo\Tools\android-platform-tools\platform-tools\adb.exe'
$taskRoot = (Get-Item -LiteralPath $PSScriptRoot).FullName
$taskReceipt = Join-Path $taskRoot 'recovery-fresh-after-v2.json'
if (Test-Path -LiteralPath $taskReceipt) { throw 'Fresh evidence path required' }
$taskRecord = [ordered]@{
    timestamp = (Get-Date).ToString('o')
    read_only = $true
    partition_write = $false
    sections = [ordered]@{}
}
function Read-TaskShell {
    param([string]$Name, [string]$Command)
    $ErrorActionPreference = 'Continue'
    $taskOutput = & $taskAdb -s 127.0.0.1:15555 shell $Command 2>&1
    $taskExit = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    $taskRecord.sections[$Name] = @{command=$Command; exit_code=$taskExit; output=($taskOutput -join "`n")}
    if ($taskExit -ne 0) { throw ('Readonly check failed: ' + $Name) }
    return ($taskOutput -join "`n").Trim()
}
try {
    $taskIdentity = Read-TaskShell 'fresh_android' 'id -u; uname -r; getprop ro.build.version.release; getprop sys.boot_completed'
    if ($taskIdentity -ne "0`n4.19.232`n11`n1") { throw 'Expected ready rooted Android' }
    if ((Read-TaskShell 'bytes_after' 'blockdev --getsize64 /dev/block/by-name/recovery') -ne '100663296') { throw 'Recovery size changed' }
    if ((Read-TaskShell 'sha_after' 'sha256sum /dev/block/by-name/recovery') -ne 'a94f4e7f0180844aa9ec67253276879f7407c9a85d2138c7636d764048890933  /dev/block/by-name/recovery') { throw 'Recovery SHA changed' }
    $null = Read-TaskShell 'seven_protected_sha_after' 'sha256sum /dev/block/by-name/boot /dev/block/by-name/uboot /dev/block/by-name/trust /dev/block/by-name/dtbo /dev/block/by-name/vbmeta /cache/rtctrl-source-userspace-20261004/rootfs.ext4 /cache/rtctrl-network-rootfs-20261004/rootfs.img'
    $null = Read-TaskShell 'battery' 'dumpsys battery'
} finally {
    [IO.File]::WriteAllText($taskReceipt, ($taskRecord | ConvertTo-Json -Depth 8), [Text.UTF8Encoding]::new($false))
}
wsl.exe -d Ubuntu-22.04 -- python3 /home/sx/projects/rtctrl-platform/outputs/rk3568-backup-linux-20261003/extract-recovery-backup-v2.py
if ($LASTEXITCODE -ne 0) { throw 'Host recovery finalization failed' }
