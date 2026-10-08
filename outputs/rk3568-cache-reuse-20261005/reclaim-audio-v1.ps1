$ErrorActionPreference = 'Stop'
$taskDirectory = (Get-Item -LiteralPath $PSScriptRoot).FullName
$taskRepo = (Get-Item -LiteralPath (Join-Path $taskDirectory '../..')).FullName
$taskAdb = 'C:\Users\lenovo\Tools\android-platform-tools\platform-tools\adb.exe'
$taskPlanPath = Join-Path $taskDirectory 'build/audio-reclaim-plan-v1/host-backup-verification.json'
$taskPlan = Get-Content -Raw -LiteralPath $taskPlanPath | ConvertFrom-Json
$taskReceipt = Join-Path $taskDirectory 'build/audio-reclaim-plan-v1/android-reclaim-v1.json'
if (Test-Path -LiteralPath $taskReceipt) { throw 'Fresh receipt required' }
$taskScript = Join-Path $taskDirectory 'build/audio-reclaim-plan-v1/reclaim-android.sh'
$taskSha = (Get-FileHash -LiteralPath $taskScript -Algorithm SHA256).Hash.ToLowerInvariant()
if ($taskSha -ne $taskPlan.script_sha256 -or $taskSha -ne 'f264da62351ceae5710d046454180dc09f6997b67b3c8262c52717e80655a961') {
    throw 'Exact reviewed reclaim script required'
}
$taskRecord = [ordered]@{
    timestamp=(Get-Date -Format o)
    host_backups=@()
    script_sha256=$taskSha
    script_plan_sha256=(Get-FileHash -LiteralPath $taskPlanPath -Algorithm SHA256).Hash.ToLowerInvariant()
    device_reclaimed=$false
    partition_write=$false
    recursive_delete=$false
    commands=@()
}
foreach ($taskEntry in $taskPlan.files) {
    $taskBackup = Join-Path $taskRepo $taskEntry.host_backup
    $taskItem = Get-Item -LiteralPath $taskBackup
    $taskDigest = (Get-FileHash -LiteralPath $taskBackup -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($taskItem.Length -ne $taskEntry.bytes -or $taskDigest -ne $taskEntry.sha256) {
        throw 'Host backup differs; no device operation sent'
    }
    $taskRecord.host_backups += @{path=$taskEntry.host_backup; bytes=$taskItem.Length; sha256=$taskDigest}
}
function Invoke-TaskAdb {
    param([string]$Command)
    $ErrorActionPreference = 'Continue'
    $taskReply = & $taskAdb -s 127.0.0.1:15555 shell $Command 2>&1
    $taskCode = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    $script:taskRecord.commands += @{command=$Command; exit_code=$taskCode; output=($taskReply -join "`n")}
    [IO.File]::WriteAllText($taskReceipt, ($script:taskRecord | ConvertTo-Json -Depth 8), [Text.UTF8Encoding]::new($false))
    if ($taskCode -ne 0) { throw 'Device reclaim check failed; evidence preserved' }
    return ($taskReply -join "`n").Trim()
}
$taskRemote = '/data/local/tmp/rtctrl-audio-reclaim-20261005-v1/reclaim.sh'
$taskRemoteDigest = Invoke-TaskAdb ('sha256sum ' + $taskRemote)
if ($taskRemoteDigest -ne ($taskSha + '  ' + $taskRemote)) { throw 'Device script differs; no reclaim sent' }
$taskReply = Invoke-TaskAdb ('sh ' + $taskRemote + ' --reclaim')
if ($taskReply -notmatch '(?m)^AUDIO_EXACT_BACKED_CACHE_FILES_RECLAIMED\r?$') {
    throw 'Reclaim final marker absent; do not assume cleanup passed'
}
$taskRecord.device_reclaimed=$true
[IO.File]::WriteAllText($taskReceipt, ($taskRecord | ConvertTo-Json -Depth 8), [Text.UTF8Encoding]::new($false))
Write-Output $taskReply
