$ErrorActionPreference = 'Stop'
$taskAdb = 'C:\Users\lenovo\Tools\android-platform-tools\platform-tools\adb.exe'
$taskRoot = (Get-Item -LiteralPath $PSScriptRoot).FullName
$taskImage = Join-Path $taskRoot 'original\recovery.img'
$taskPartial = Join-Path $taskRoot 'original\recovery.img.partial'
$taskReceipt = Join-Path $taskRoot 'recovery-backup-v1.json'
foreach ($taskPath in @($taskImage, $taskPartial, $taskReceipt)) {
    if (Test-Path -LiteralPath $taskPath) { throw 'Fresh backup paths required' }
}
$taskExpectedSha = 'a94f4e7f0180844aa9ec67253276879f7407c9a85d2138c7636d764048890933'
$taskExpectedBytes = 100663296
$taskRecord = [ordered]@{
    timestamp = (Get-Date).ToString('o')
    read_only = $true
    partition_write = $false
    copied_bytes = 0
    completed = $false
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
    if ((Read-TaskShell 'bytes_before' 'blockdev --getsize64 /dev/block/by-name/recovery') -ne "$taskExpectedBytes") { throw 'Recovery size changed' }
    $taskExpectedLine = $taskExpectedSha + '  /dev/block/by-name/recovery'
    if ((Read-TaskShell 'sha_before' 'sha256sum /dev/block/by-name/recovery') -ne $taskExpectedLine) { throw 'Recovery SHA changed' }

    $taskInfo = [Diagnostics.ProcessStartInfo]::new()
    $taskInfo.FileName = $taskAdb
    $taskInfo.Arguments = '-s 127.0.0.1:15555 exec-out /system/bin/dd if=/dev/block/by-name/recovery bs=1048576'
    $taskInfo.UseShellExecute = $false
    $taskInfo.CreateNoWindow = $true
    $taskInfo.RedirectStandardOutput = $true
    $taskInfo.RedirectStandardError = $true
    $taskProcess = [Diagnostics.Process]::new()
    $taskProcess.StartInfo = $taskInfo
    if (-not $taskProcess.Start()) { throw 'Could not start readonly transfer' }
    $taskStderr = $taskProcess.StandardError.ReadToEndAsync()
    $taskFile = [IO.File]::Open($taskPartial, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try {
        $taskProcess.StandardOutput.BaseStream.CopyTo($taskFile)
        $taskRecord.copied_bytes = $taskFile.Length
    } finally {
        $taskFile.Dispose()
    }
    $taskProcess.WaitForExit()
    $taskRecord.sections.transfer = @{arguments=$taskInfo.Arguments; exit_code=$taskProcess.ExitCode; stderr=$taskStderr.GetAwaiter().GetResult()}
    if ($taskProcess.ExitCode -ne 0 -or $taskRecord.copied_bytes -ne $taskExpectedBytes) { throw 'Incomplete recovery readback' }
    $taskHostSha = (Get-FileHash -LiteralPath $taskPartial -Algorithm SHA256).Hash.ToLower()
    if ($taskHostSha -ne $taskExpectedSha) { throw 'Readback complete SHA mismatch' }
    if ((Read-TaskShell 'sha_after' 'sha256sum /dev/block/by-name/recovery') -ne $taskExpectedLine) { throw 'Recovery SHA changed during readback' }
    $taskRecord.sha256 = $taskHostSha
    $taskRecord.protected_sha_after = Read-TaskShell 'seven_protected_sha_after' 'sha256sum /dev/block/by-name/boot /dev/block/by-name/uboot /dev/block/by-name/trust /dev/block/by-name/dtbo /dev/block/by-name/vbmeta /cache/rtctrl-source-userspace-20261004/rootfs.ext4 /cache/rtctrl-network-rootfs-20261004/rootfs.img'
    Move-Item -LiteralPath $taskPartial -Destination $taskImage
    $taskRecord.completed = $true
    Write-Host ('RECOVERY_READONLY_BACKUP_VERIFIED bytes=' + $taskRecord.copied_bytes + ' sha256=' + $taskHostSha)
} finally {
    [IO.File]::WriteAllText($taskReceipt, ($taskRecord | ConvertTo-Json -Depth 8), [Text.UTF8Encoding]::new($false))
}
