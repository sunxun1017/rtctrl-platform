param(
    [Parameter(Mandatory=$true)][string]$BoardAddress,
    [string]$ResultPath = (Join-Path $PSScriptRoot 'transfer-result.json')
)
$ErrorActionPreference = 'Stop'
function Connect-Board {
    $socket = [Net.Sockets.TcpClient]::new()
    try {
        if (-not $socket.ConnectAsync($BoardAddress, 18765).Wait(12000)) {
            throw 'Linux transfer connect timed out'
        }
        $socket.GetStream().ReadTimeout = 15000
        $socket.GetStream().WriteTimeout = 15000
        return $socket
    } catch {
        $socket.Dispose()
        throw
    }
}
function Read-Exact($Stream, [int]$Length) {
    $buffer = [byte[]]::new($Length)
    $offset = 0
    while ($offset -lt $Length) {
        $count = $Stream.Read($buffer, $offset, $Length - $offset)
        if ($count -eq 0) { throw 'Premature transfer EOF' }
        $offset += $count
    }
    return ,$buffer
}
$payload = [byte[]]::new(65536)
for ($index = 0; $index -lt $payload.Length; $index++) {
    $payload[$index] = $index % 256
}
$uploadHash = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($payload)).ToLowerInvariant()
$socket = Connect-Board
try {
    $stream = $socket.GetStream()
    $header = [byte[]]@(80, 0, 1, 0, 0)
    $stream.Write($header, 0, $header.Length)
    $stream.Write($payload, 0, $payload.Length)
    $ack = Read-Exact $stream 3
    if ([Text.Encoding]::ASCII.GetString($ack) -ne "OK`n") { throw 'Upload ACK mismatch' }
} finally { $socket.Dispose() }
$socket = Connect-Board
try {
    $stream = $socket.GetStream()
    $stream.WriteByte(71)
    $size = Read-Exact $stream 4
    $length = [Net.IPAddress]::NetworkToHostOrder([BitConverter]::ToInt32($size, 0))
    if ($length -ne $payload.Length) { throw 'Download length mismatch' }
    $received = Read-Exact $stream $length
} finally { $socket.Dispose() }
$downloadHash = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($received)).ToLowerInvariant()
if ($downloadHash -ne $uploadHash) { throw 'Roundtrip SHA-256 mismatch' }
$result = [ordered]@{
    bytes = $payload.Length
    upload_sha256 = $uploadHash
    download_sha256 = $downloadHash
    roundtrip_passed = $true
}
[IO.File]::WriteAllText($ResultPath, ($result | ConvertTo-Json))
$result | ConvertTo-Json