param()
# Read only the connected, user-authorized Wi-Fi profile; keep its key in memory.
$ErrorActionPreference = 'Stop'
$keyText = $null
$profileText = $null
$secure = $null
try {
    $interfaces = & netsh wlan show interfaces
    if ($LASTEXITCODE -ne 0) { throw 'Cannot read connected Wi-Fi interface' }
    $ssids = @($interfaces | ForEach-Object {
        if ($_ -match '^\s*SSID\s*:\s*(.+?)\s*$') { $Matches[1] }
    })
    if ($ssids.Count -ne 1) { throw 'Expected one connected Wi-Fi profile' }
    $profileText = & netsh wlan show profile "name=$($ssids[0])" key=clear
    if ($LASTEXITCODE -ne 0) { throw 'Cannot read authorized current profile' }
    $keys = @($profileText | ForEach-Object {
        if ($_ -match '^\s*(?:Key Content|关键内容|密钥内容)\s*:\s*(.+?)\s*$') { $Matches[1] }
    })
    if ($keys.Count -ne 1) { throw 'Current profile has no usable PSK' }
    $keyText = $keys[0]
    $secure = ConvertTo-SecureString $keyText -AsPlainText -Force
    & (Join-Path $PSScriptRoot 'private/send-credential.ps1') -Password $secure -Ssid $ssids[0]
} finally {
    $keyText = $null
    $keys = $null
    $profileText = $null
    if ($secure) { $secure.Dispose() }
}
