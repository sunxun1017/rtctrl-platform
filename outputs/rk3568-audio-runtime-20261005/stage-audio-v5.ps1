param(
    [Parameter(Mandatory=$true)][string]$InputManifest,
    [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ManifestSha256
)
$ErrorActionPreference = 'Stop'
$taskDirectory = (Get-Item -LiteralPath $PSScriptRoot).FullName
$taskRepo = (Get-Item -LiteralPath (Join-Path $taskDirectory '../..')).FullName
$taskAdb = 'C:\Users\lenovo\Tools\android-platform-tools\platform-tools\adb.exe'
function Assert-TaskOrdinaryHost {
    param([string]$Path)
    $taskItem = Get-Item -LiteralPath $Path
    if ($taskItem.PSIsContainer -or $taskItem.LinkType -or
        ($taskItem.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw 'Ordinary host source required'
    }
    $taskAncestor = $taskItem.Directory
    while ($null -ne $taskAncestor) {
        $taskAncestorItem = Get-Item -LiteralPath $taskAncestor.FullName
        if (-not $taskAncestorItem.PSIsContainer -or
            ($taskAncestorItem.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw 'Ordinary host directory ancestors required'
        }
        if ($taskAncestor.FullName -eq $taskRepo) { break }
        $taskAncestor = $taskAncestor.Parent
    }
    if ($null -eq $taskAncestor) { throw 'Repository source required' }
    return $taskItem
}
$taskManifestPath = (Assert-TaskOrdinaryHost $InputManifest).FullName
$taskFixedManifest = (Get-Item -LiteralPath (Join-Path $taskDirectory 'build/board-audio-v5/input-manifest.json')).FullName
if ($taskManifestPath -ne $taskFixedManifest -or
    (Get-FileHash -LiteralPath $taskManifestPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ManifestSha256) {
    throw 'Accepted exact v5 board manifest identity required'
}
if (-not $taskManifestPath.StartsWith($taskRepo + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Repository input manifest required'
}
$taskManifest = Get-Content -Raw -LiteralPath $taskManifestPath | ConvertFrom-Json
if ($taskManifest.host_verified -ne $true -or $taskManifest.mode -ne 'RAM_ONLY_NOT_FLASH_READY') {
    throw 'Completed host package/ABI review required'
}
$taskRemote = '/cache/rtctrl-audio-bootm-20261005-v5'
if ($taskManifest.remote -ne $taskRemote -or $taskManifest.board_tested -ne $false -or $taskManifest.start_allowed -ne $false) {
    throw 'Fresh RAM-only v5 trial inputs required'
}
$taskNames = @($taskManifest.files | ForEach-Object { $_.name })
$taskExpectedNames = @('boot-audio.img', 'snd-soc-rk817.ko', 'alsa-inspect', 'pcm-transfer', 'audio-session-guard', 'pcm-peer-idle', 'stage-aux.sh', 'audio-files.sha256')
if ($taskNames.Count -ne 8 -or @($taskNames | Sort-Object -Unique).Count -ne 8 -or
    @(Compare-Object $taskNames $taskExpectedNames).Count -ne 0) {
    throw 'Exact eight v5 files required'
}
$taskReceipt = Join-Path $taskDirectory 'build/audio-stage-v5.json'
if (Test-Path -LiteralPath $taskReceipt) { throw 'Fresh staging receipt required' }
$taskTotal = [long]0
foreach ($taskEntry in $taskManifest.files) {
    if ($taskEntry.name -notmatch '^[a-z0-9][a-z0-9.-]*$' -or $taskEntry.source -match '[\\:]|(^|/)\.\.?(/|$)' -or $taskEntry.source.StartsWith('/')) {
        throw 'Simple file name and POSIX repository source required'
    }
    $taskPath = Join-Path $taskRepo $taskEntry.source
    $taskItem = Assert-TaskOrdinaryHost $taskPath
    if (-not $taskItem.FullName.StartsWith($taskRepo + '\', [StringComparison]::OrdinalIgnoreCase) -or $taskItem.LinkType) {
        throw 'Ordinary repository input required'
    }
    if ($taskItem.Length -ne $taskEntry.bytes -or (Get-FileHash -LiteralPath $taskPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $taskEntry.sha256) {
        throw 'Reviewed input changed; no upload sent'
    }
    $taskTotal += $taskItem.Length
}
$taskRecord = [ordered]@{
    timestamp=(Get-Date -Format o)
    tool_sha256=(Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash.ToLowerInvariant()
    input_manifest_sha256=(Get-FileHash -LiteralPath $taskManifestPath -Algorithm SHA256).Hash.ToLowerInvariant()
    remote=$taskRemote
    files=$taskManifest.files
    completed=$false
    partition_write=$false
    flash=$false
    saveenv=$false
    network_configuration_changed=$false
    commands=@()
}
function Invoke-TaskAdb {
    param([string[]]$Arguments)
    $ErrorActionPreference = 'Continue'
    $taskReply = & $taskAdb -s 127.0.0.1:15555 @Arguments 2>&1
    $taskCode = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    $script:taskRecord.commands += @{arguments=$Arguments; exit_code=$taskCode; output=($taskReply -join "`n")}
    [IO.File]::WriteAllText($taskReceipt, ($script:taskRecord | ConvertTo-Json -Depth 9), [Text.UTF8Encoding]::new($false))
    if ($taskCode -ne 0) { throw 'Audio staging operation failed; evidence retained' }
    return ($taskReply -join "`n").Trim()
}
$taskIdentity = Invoke-TaskAdb @('shell', 'id -u; uname -r; getprop ro.build.version.release; getprop sys.boot_completed')
if ($taskIdentity -ne "0`n4.19.232`n11`n1") { throw 'Fresh Android identity differs' }
$taskProtectedCommand = 'sha256sum /dev/block/by-name/boot /dev/block/by-name/uboot /dev/block/by-name/trust /dev/block/by-name/dtbo /dev/block/by-name/vbmeta /cache/rtctrl-source-userspace-20261004/rootfs.ext4 /cache/rtctrl-network-rootfs-20261004/rootfs.img'
$taskSeven = Invoke-TaskAdb @('shell', $taskProtectedCommand)
if ($taskSeven -ne ($taskManifest.protected_sha256 -join "`n")) { throw 'Seven protected inputs differ' }
$taskNative = Invoke-TaskAdb @('shell', 'sha256sum /cache/rtctrl-pid1-20261005-v3/rootfs-pid1.ext4 /cache/rtctrl-pid1-20261005-v3/initramfs-pid1.cpio.gz /cache/rtctrl-rcu-reset-20261004/Image')
if ($taskNative -ne ($taskManifest.native_cached_sha256 -join "`n")) { throw 'Unchanged native inputs differ' }
$taskSpace = Invoke-TaskAdb @('shell', 'df -k /cache')
if ($taskSpace -notmatch '(?m)^/dev/block/mmcblk2p12\s+\d+\s+\d+\s+(\d+)\s+') { throw 'Current cache filesystem unavailable' }
if ([long]$Matches[1] * 1024 -lt $taskTotal + 16777216) { throw 'Cache headroom insufficient' }
$taskPreflight = 'test $(realpath /cache) = /cache && test ! -e ' + $taskRemote + ' && test ! -L ' + $taskRemote + ' && mkdir -m 700 ' + $taskRemote + ' && test $(realpath ' + $taskRemote + ') = ' + $taskRemote
[void](Invoke-TaskAdb @('shell', $taskPreflight))
foreach ($taskEntry in $taskManifest.files) {
    $taskDestination = $taskRemote + '/' + $taskEntry.name
    [void](Invoke-TaskAdb @('push', (Join-Path $taskRepo $taskEntry.source), $taskDestination))
    [void](Invoke-TaskAdb @('shell', ('chmod 600 ' + $taskDestination)))
    $taskStat = Invoke-TaskAdb @('shell', ('test ! -L ' + $taskDestination + ' && test $(realpath ' + $taskDestination + ') = ' + $taskDestination + ' && stat -c %u:%g:%h:%s:%F ' + $taskDestination))
    if ($taskStat -ne ('0:0:1:' + $taskEntry.bytes + ':regular file')) { throw 'Uploaded ordinary file identity differs' }
    $taskDigest = Invoke-TaskAdb @('shell', ('sha256sum ' + $taskDestination))
    if ($taskDigest -ne ($taskEntry.sha256 + '  ' + $taskDestination)) { throw 'Uploaded complete SHA differs' }
}
[void](Invoke-TaskAdb @('shell', 'sync'))
if ((Invoke-TaskAdb @('shell', $taskProtectedCommand)) -ne $taskSeven) { throw 'Protected inputs changed' }
if ((Invoke-TaskAdb @('shell', 'sha256sum /cache/rtctrl-pid1-20261005-v3/rootfs-pid1.ext4 /cache/rtctrl-pid1-20261005-v3/initramfs-pid1.cpio.gz /cache/rtctrl-rcu-reset-20261004/Image')) -ne $taskNative) { throw 'Native inputs changed' }
$taskRecord.completed=$true
[IO.File]::WriteAllText($taskReceipt, ($taskRecord | ConvertTo-Json -Depth 9), [Text.UTF8Encoding]::new($false))
Write-Output 'AUDIO_ORDINARY_CACHE_INPUTS_FULL_SHA_VERIFIED_NO_FLASH'
