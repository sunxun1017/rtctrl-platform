$ErrorActionPreference = 'Stop'
$taskDir = (Get-Item -LiteralPath $PSScriptRoot).FullName
$taskManifestPath = Join-Path $taskDir 'build/board-audio-v4/input-manifest.json'
$taskReceipt = Join-Path $taskDir 'build/android-before-audio-v5-protection.json'
$taskAdb = 'C:\Users\lenovo\Tools\android-platform-tools\platform-tools\adb.exe'
$taskExpectedManifest = '127e12854aa68fe80aa5655dbea89d86a0b8b1db4f54911610649e585fb4092f'

if (Test-Path -LiteralPath $taskReceipt) {
    throw 'Fresh before-trial evidence required'
}
if ((Get-FileHash -LiteralPath $taskManifestPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $taskExpectedManifest) {
    throw 'Previously verified protected baseline differs'
}
$taskManifest = Get-Content -Raw -LiteralPath $taskManifestPath | ConvertFrom-Json
$taskRecord = [ordered]@{
    timestamp = (Get-Date -Format o)
    completed = $false
    mode = 'READ_ONLY_ORIGINAL_ANDROID_BEFORE_V5_TRIAL'
    protected_baseline_manifest_sha256 = $taskExpectedManifest
    tool_sha256 = (Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash.ToLowerInvariant()
    endpoint = '127.0.0.1:15555'
    commands = @()
    partition_write = $false
    flash = $false
    saveenv = $false
    network_configuration_changed = $false
}

function Save-TaskRecord {
    [IO.File]::WriteAllText(
        $taskReceipt,
        ($script:taskRecord | ConvertTo-Json -Depth 8),
        [Text.UTF8Encoding]::new($false)
    )
}

function Read-TaskAdb {
    param([string]$Command)
    if ($Command.Contains("'")) {
        throw 'Fixed read-only command quoting differs'
    }
    $taskWireCommand = "su 0 sh -c '" + $Command + "'"
    $taskStarted = Get-Date
    $ErrorActionPreference = 'Continue'
    $taskReply = & $taskAdb -s 127.0.0.1:15555 shell $taskWireCommand 2>&1
    $taskCode = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    $script:taskRecord.commands += @{
        command = $Command
        wire_command = $taskWireCommand
        exit_code = $taskCode
        elapsed_seconds = ((Get-Date) - $taskStarted).TotalSeconds
        output = ($taskReply -join "`n")
    }
    Save-TaskRecord
    if ($taskCode -ne 0) {
        throw 'Read-only before-trial check failed; evidence retained'
    }
    return ($taskReply -join "`n").Trim()
}

Save-TaskRecord
$taskIdentity = 'id -u; uname -r; getprop ro.build.version.release; getprop sys.boot_completed'
if ((Read-TaskAdb $taskIdentity) -ne "0`n4.19.232`n11`n1") {
    throw 'Fresh original Android identity differs'
}
$taskProtectedCommand = @(
    'sha256sum'
    '/dev/block/by-name/boot'
    '/dev/block/by-name/uboot'
    '/dev/block/by-name/trust'
    '/dev/block/by-name/dtbo'
    '/dev/block/by-name/vbmeta'
    '/cache/rtctrl-source-userspace-20261004/rootfs.ext4'
    '/cache/rtctrl-network-rootfs-20261004/rootfs.img'
) -join ' '
if ((Read-TaskAdb $taskProtectedCommand) -ne ($taskManifest.protected_sha256 -join "`n")) {
    throw 'Seven protected identities differ'
}
$taskNativeCommand = @(
    'sha256sum'
    '/cache/rtctrl-pid1-20261005-v3/rootfs-pid1.ext4'
    '/cache/rtctrl-pid1-20261005-v3/initramfs-pid1.cpio.gz'
    '/cache/rtctrl-rcu-reset-20261004/Image'
) -join ' '
if ((Read-TaskAdb $taskNativeCommand) -ne ($taskManifest.native_cached_sha256 -join "`n")) {
    throw 'Native cached input identities differ'
}
[void](Read-TaskAdb 'df -k /cache')
$taskRecord.completed = $true
Save-TaskRecord
Write-Output 'AUDIO_V5_BEFORE_ORIGINAL_ANDROID_SEVEN_PROTECTED_THREE_NATIVE_SHA_MATCHED'
