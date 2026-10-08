param(
    [Parameter(Mandatory=$true)]
    [ValidatePattern('^[0-9a-f]{64}$')]
    [string]$NewBoardManifestSha256
)
$ErrorActionPreference = 'Stop'
$taskDir = (Get-Item -LiteralPath $PSScriptRoot).FullName
$taskRepo = (Get-Item -LiteralPath (Join-Path $taskDir '../..')).FullName
$taskAdb = 'C:\Users\lenovo\Tools\android-platform-tools\platform-tools\adb.exe'
$taskReceipt = Join-Path $taskDir 'build/audio-v4-reclaim-for-v5.json'
$taskNewManifestPath = Join-Path $taskDir 'build/board-audio-v5/input-manifest.json'
$taskOldManifestPath = Join-Path $taskDir 'build/board-audio-v4/input-manifest.json'
$taskOldSha = 'eb2da84a0ab0eb7fc615f641ab2880bb067a72ec5b972a109e7237472243afe6'
$taskOldFile = '/cache/rtctrl-audio-bootm-20261005-v4/boot-audio.img'
$taskOldDir = '/cache/rtctrl-audio-bootm-20261005-v4'
$taskNewDir = '/cache/rtctrl-audio-bootm-20261005-v5'

function Assert-TaskOrdinaryHost {
    param([string]$Path)
    $taskItem = Get-Item -LiteralPath $Path
    if ($taskItem.PSIsContainer -or $taskItem.LinkType -or
        ($taskItem.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw 'Ordinary host backup required'
    }
    $taskAncestor = $taskItem.Directory
    while ($null -ne $taskAncestor) {
        $taskAncestorItem = Get-Item -LiteralPath $taskAncestor.FullName
        if (-not $taskAncestorItem.PSIsContainer -or
            ($taskAncestorItem.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw 'Host ancestor link rejected'
        }
        if ($taskAncestor.FullName -eq $taskRepo) { break }
        $taskAncestor = $taskAncestor.Parent
    }
    if ($null -eq $taskAncestor) { throw 'Repository host input required' }
    return $taskItem
}

if (Test-Path -LiteralPath $taskReceipt) { throw 'Fresh reclaim receipt required' }
[void](Assert-TaskOrdinaryHost $taskNewManifestPath)
[void](Assert-TaskOrdinaryHost $taskOldManifestPath)
if ((Get-FileHash -LiteralPath $taskNewManifestPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $NewBoardManifestSha256) {
    throw 'Accepted new board package identity differs'
}
if ((Get-FileHash -LiteralPath $taskOldManifestPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne '127e12854aa68fe80aa5655dbea89d86a0b8b1db4f54911610649e585fb4092f') {
    throw 'Old protected baseline differs'
}
$taskNew = Get-Content -Raw -LiteralPath $taskNewManifestPath | ConvertFrom-Json
$taskOld = Get-Content -Raw -LiteralPath $taskOldManifestPath | ConvertFrom-Json
if ($taskNew.host_verified -ne $true -or $taskNew.mode -ne 'RAM_ONLY_NOT_FLASH_READY' -or $taskNew.remote -ne $taskNewDir) {
    throw 'Accepted fresh v5 package required'
}
if (($taskNew.protected_sha256 -join "`n") -ne ($taskOld.protected_sha256 -join "`n") -or
    ($taskNew.native_cached_sha256 -join "`n") -ne ($taskOld.native_cached_sha256 -join "`n")) {
    throw 'Protected and native baselines differ'
}
foreach ($taskEntry in $taskNew.files) {
    if ($taskEntry.source -match '[\\:]|(^|/)\.\.?(/|$)' -or $taskEntry.source.StartsWith('/')) {
        throw 'POSIX repository source required'
    }
    $taskPath = Join-Path $taskRepo $taskEntry.source
    $taskItem = Assert-TaskOrdinaryHost $taskPath
    if ($taskItem.Length -ne $taskEntry.bytes -or
        (Get-FileHash -LiteralPath $taskPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $taskEntry.sha256) {
        throw 'New accepted host input changed'
    }
}
$taskBackup = Join-Path $taskRepo 'outputs/rk3568-audio-package-20261005/build/ram-audio-v4/boot-padded.img'
$taskBackupItem = Assert-TaskOrdinaryHost $taskBackup
if ($taskBackupItem.Length -ne 41943040 -or
    (Get-FileHash -LiteralPath $taskBackup -Algorithm SHA256).Hash.ToLowerInvariant() -ne $taskOldSha) {
    throw 'Complete old test image backup differs'
}
$taskRecord = [ordered]@{
    timestamp = (Get-Date -Format o)
    new_board_manifest_sha256 = $NewBoardManifestSha256
    tool_sha256 = (Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash.ToLowerInvariant()
    exact_removed_path = $taskOldFile
    host_backup = $taskBackup
    host_backup_sha256 = $taskOldSha
    host_backup_bytes = 41943040
    commands = @()
    cache_file_removed = $false
    protected_after_verified = $false
    recursive_delete = $false
    partition_flash = $false
    saveenv = $false
    network_configuration_changed = $false
    completed = $false
}

function Save-TaskRecord {
    [IO.File]::WriteAllText($taskReceipt, ($script:taskRecord | ConvertTo-Json -Depth 9), [Text.UTF8Encoding]::new($false))
}

function Invoke-TaskAdb {
    param([string]$Command)
    $ErrorActionPreference = 'Continue'
    $taskReply = & $taskAdb -s 127.0.0.1:15555 shell $Command 2>&1
    $taskCode = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    $script:taskRecord.commands += @{command=$Command; exit_code=$taskCode; output=($taskReply -join "`n")}
    Save-TaskRecord
    if ($taskCode -ne 0) { throw 'Reclaim check failed; evidence retained' }
    return ($taskReply -join "`n").Trim()
}

function Assert-TaskProtected {
    $taskProtected = 'sha256sum ' + (($script:taskOld.protected_sha256 | ForEach-Object { ($_ -split '  ', 2)[1] }) -join ' ')
    $taskNative = 'sha256sum ' + (($script:taskOld.native_cached_sha256 | ForEach-Object { ($_ -split '  ', 2)[1] }) -join ' ')
    if ((Invoke-TaskAdb $taskProtected) -ne ($script:taskOld.protected_sha256 -join "`n")) {
        throw 'Seven protected inputs differ'
    }
    if ((Invoke-TaskAdb $taskNative) -ne ($script:taskOld.native_cached_sha256 -join "`n")) {
        throw 'Three native inputs differ'
    }
}

Save-TaskRecord
if ((Invoke-TaskAdb 'id -u; uname -r; getprop ro.build.version.release; getprop sys.boot_completed') -ne "0`n4.19.232`n11`n1") {
    throw 'Original Android identity differs'
}
Assert-TaskProtected
$taskDirectoryCheck = 'test -d /cache && test ! -L /cache && test $(realpath /cache) = /cache' +
    ' && test -d ' + $taskOldDir + ' && test ! -L ' + $taskOldDir +
    ' && test $(realpath ' + $taskOldDir + ') = ' + $taskOldDir +
    ' && test ! -e ' + $taskNewDir + ' && test ! -L ' + $taskNewDir + ' && echo AUDIO_V5_RECLAIM_PATHS_VERIFIED'
if ((Invoke-TaskAdb $taskDirectoryCheck) -ne 'AUDIO_V5_RECLAIM_PATHS_VERIFIED') {
    throw 'Exact ordinary cache path check failed'
}
$taskStatCommand = 'test -f ' + $taskOldFile + ' && test ! -L ' + $taskOldFile +
    ' && test $(realpath ' + $taskOldFile + ') = ' + $taskOldFile +
    ' && stat -c %u:%g:%h:%s:%F ' + $taskOldFile
if ((Invoke-TaskAdb $taskStatCommand) -ne '0:0:1:41943040:regular file') {
    throw 'Old test image type, owner, links or bytes differ'
}
if ((Invoke-TaskAdb ('sha256sum ' + $taskOldFile)) -ne ($taskOldSha + '  ' + $taskOldFile)) {
    throw 'Old test image full SHA differs'
}
[void](Invoke-TaskAdb ('rm -- ' + $taskOldFile))
$taskRecord.cache_file_removed = $true
Save-TaskRecord
[void](Invoke-TaskAdb ('test ! -e ' + $taskOldFile + ' && test ! -L ' + $taskOldFile + ' && sync'))
Assert-TaskProtected
$taskRecord.protected_after_verified = $true
[void](Invoke-TaskAdb 'df -k /cache')
$taskRecord.completed = $true
Save-TaskRecord
Write-Output 'AUDIO_OLD_V4_BACKED_TEST_IMAGE_RECLAIMED_PROTECTED_SHA_UNCHANGED'
