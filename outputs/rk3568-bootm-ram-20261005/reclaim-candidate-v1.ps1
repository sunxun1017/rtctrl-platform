$ErrorActionPreference = 'Stop'
$adb = 'C:\Users\lenovo\Tools\android-platform-tools\platform-tools\adb.exe'
$target = '127.0.0.1:15555'
$workspace = (Get-Item -LiteralPath (Join-Path $PSScriptRoot '../..')).FullName
$receiptPath = Join-Path $PSScriptRoot 'reclaim-candidate-v1-result.json'
if (Test-Path -LiteralPath $receiptPath) { throw 'Refusing to overwrite receipt' }
$manifestPath = Join-Path $workspace 'outputs/rk3568-boot-package-20261005/build/ram-candidate-v1/manifest.json'
$manifestSha = '21f1bb72b5508cdbbf8fabe6b3a141c154ef123106028bd657c70d3e662c89ce'
$backupPath = Join-Path $workspace 'outputs/rk3568-boot-package-20261005/build/ram-candidate-v1/boot-padded.img'
$backupSha = 'c55feb66c8acb9e66cc89af7c8a70077419b16a2a32fdaadb74ee068170d4d3e'
if ((Get-FileHash -LiteralPath $manifestPath).Hash.ToLowerInvariant() -ne $manifestSha) { throw 'Frozen manifest changed' }
if ((Get-Item -LiteralPath $backupPath).Length -ne 41943040 -or
    (Get-FileHash -LiteralPath $backupPath).Hash.ToLowerInvariant() -ne $backupSha) { throw 'Complete host backup changed' }
$scriptPath = Join-Path $PSScriptRoot 'reclaim-candidate-v1-android.sh'
$scriptSha = 'e375a068e7f5a32979392f8a02223dbca30ceb75824e2c802726376425691cd6'
if ((Get-FileHash -LiteralPath $scriptPath).Hash.ToLowerInvariant() -ne $scriptSha) { throw 'Reviewed script changed' }
$record = [ordered]@{
    timestamp=(Get-Date -Format o)
    host_manifest_sha256=$manifestSha
    backup_sha256=$backupSha
    script_sha256=$scriptSha
    reclaimed_path='/cache/rtctrl-bootm-ram-20261005-v1/boot-linux-ram-v1.img'
    reclaimed_bytes=41943040
    sections=[ordered]@{}
}
function Save-Receipt {
    [IO.File]::WriteAllText($receiptPath, ($record | ConvertTo-Json -Depth 8))
}
function Run-Board([string]$name, [string]$command) {
    if ($command.Contains("'")) { throw 'Unreviewed quoting' }
    $ErrorActionPreference = 'Continue'
    $reply = & $adb -s $target shell ("su 0 sh -c '" + $command + "'") 2>&1
    $rc = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    $result = $reply -join "`n"
    $record.sections[$name] = @{command=$command; exit_code=$rc; output=$result}
    Save-Receipt
    Write-Host ($name + ': ' + $result)
    if ($rc -ne 0) { throw ('Board operation failed: ' + $name) }
    return $result
}
Save-Receipt
$work = '/data/local/tmp/rtctrl-bootm-reclaim-20261005-v1'
[void](Run-Board 'new_directory' ('test ! -e ' + $work + ' && test ! -L ' + $work + ' && mkdir -m 700 ' + $work + ' && test $(realpath ' + $work + ') = ' + $work))
$ErrorActionPreference = 'Continue'
$reply = & $adb -s $target push $scriptPath ($work + '/reclaim.sh') 2>&1
$rc = $LASTEXITCODE
$ErrorActionPreference = 'Stop'
$record.sections.push = @{exit_code=$rc; output=($reply -join "`n")}
Save-Receipt
if ($rc -ne 0) { throw 'Upload failed' }
$remoteSha = Run-Board 'uploaded_sha256' ('sha256sum ' + $work + '/reclaim.sh')
if ($remoteSha.Trim() -ne ($scriptSha + '  ' + $work + '/reclaim.sh')) { throw 'Uploaded script changed' }
$check = Run-Board 'check' ('/system/bin/sh ' + $work + '/reclaim.sh --check')
if ($check -notmatch '(?m)^CANDIDATE_V1_AND_PROTECTED_INPUTS_VERIFIED\r?$') { throw 'Preflight marker missing' }
$result = Run-Board 'reclaim' ('/system/bin/sh ' + $work + '/reclaim.sh --reclaim')
if ($result -notmatch '(?m)^CANDIDATE_V1_ARCHIVED_CACHE_COPY_RECLAIMED\r?$') { throw 'Reclaim marker missing' }
$record.completed = $true
Save-Receipt
