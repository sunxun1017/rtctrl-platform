$ErrorActionPreference = 'Stop'
$adb = 'C:\Users\lenovo\Tools\android-platform-tools\platform-tools\adb.exe'
$target = '127.0.0.1:15555'
[void][IO.Directory]::CreateDirectory((Join-Path $PSScriptRoot 'private'))
$receiptPath = Join-Path $PSScriptRoot 'private/reclaim-v3.json'
if (Test-Path -LiteralPath $receiptPath) { throw 'Refusing to overwrite receipt' }
$manifestPath = Join-Path $PSScriptRoot 'build/host-backups-v1/manifest.json'
$manifestSha = 'edcdef3726fc4329d4f043733127702b4c2c96095f72cc80fde7c8a963e46805'
if ((Get-FileHash -Algorithm SHA256 -LiteralPath $manifestPath).Hash.ToLowerInvariant() -ne $manifestSha) {
    throw 'Host backup manifest changed'
}
$manifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
if ($manifest.files.Count -ne 3 -or $manifest.total_bytes -ne 104398336) {
    throw 'Host backup manifest shape changed'
}
foreach ($file in $manifest.files) {
    $backup = Join-Path $PSScriptRoot ('build/host-backups-v1/' + $file.name + '.Image')
    $item = Get-Item -LiteralPath $backup
    if ($item.Length -ne $file.bytes -or
        (Get-FileHash -Algorithm SHA256 -LiteralPath $backup).Hash.ToLowerInvariant() -ne $file.sha256) {
        throw ('Host backup mismatch: ' + $file.name)
    }
}
$script = Join-Path $PSScriptRoot 'reclaim-android.sh'
$scriptSha = '60a87545e385d35f88b264848bbd8e4ed252e9ab1c1ef98c76d974233dbc68e7'
if ((Get-FileHash -Algorithm SHA256 -LiteralPath $script).Hash.ToLowerInvariant() -ne $scriptSha) {
    throw 'Reviewed script changed'
}
$record = [ordered]@{
    timestamp=(Get-Date -Format o)
    host_manifest_sha256=$manifestSha
    script_sha256=$scriptSha
    sections=[ordered]@{}
}
function Save-Receipt {
    [IO.File]::WriteAllText($receiptPath, ($record | ConvertTo-Json -Depth 8))
}
function Run-Board([string]$name, [string]$command) {
    if ($command.Contains("'")) { throw 'Unreviewed shell quoting' }
    $ErrorActionPreference = 'Continue'
    $reply = & $adb -s $target shell ("su 0 sh -c '" + $command + "'") 2>&1
    $rc = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    $text = $reply -join "`n"
    $record.sections[$name] = @{command=$command; exit_code=$rc; output=$text}
    Save-Receipt
    if ($rc -ne 0) { throw ('Board stage failed: ' + $name) }
    Write-Host ($name + ': ' + $text)
    return $text
}
Save-Receipt
$work = '/data/local/tmp/rtctrl-cache-reuse-20261005-v3'
[void](Run-Board 'new_directory' ("test ! -e " + $work + " && test ! -L " + $work + " && mkdir " + $work + " && chmod 700 " + $work))
$ErrorActionPreference = 'Continue'
$push = & $adb -s $target push $script ($work + '/reclaim-android.sh') 2>&1
$pushRc = $LASTEXITCODE
$ErrorActionPreference = 'Stop'
$record.sections.push = @{exit_code=$pushRc; output=($push -join "`n")}
Save-Receipt
if ($pushRc -ne 0) { throw 'Script upload failed' }
$remoteSha = Run-Board 'uploaded_sha256' ('sha256sum ' + $work + '/reclaim-android.sh')
if ($remoteSha.Trim() -ne ($scriptSha + '  ' + $work + '/reclaim-android.sh')) {
    throw 'Uploaded reviewed script mismatch'
}
$result = Run-Board 'reclaim' ('/system/bin/sh ' + $work + '/reclaim-android.sh')
if ($result -notmatch '(?m)^CACHE_THREE_ARCHIVED_IMAGES_RECLAIMED\r?$') {
    throw 'Reclaim success marker missing'
}
$record.completed = $true
Save-Receipt
