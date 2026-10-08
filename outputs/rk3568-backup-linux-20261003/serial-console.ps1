param(
    [Parameter(Mandatory=$true)][string]$CommandFile,
    [ValidateSet('UBoot', 'Linux')][string]$Mode = 'UBoot',
    [string]$EvidenceName = 'serial-session.raw.txt'
)
$ErrorActionPreference = 'Stop'
if ([IO.Path]::GetFileName($EvidenceName) -ne $EvidenceName) { throw 'EvidenceName must be a filename' }
$steps = Get-Content -Raw -LiteralPath $CommandFile | ConvertFrom-Json
$port = [IO.Ports.SerialPort]::new('COM8', 1500000, 'None', 8, 'One')
$port.Handshake = [IO.Ports.Handshake]::None
$port.DtrEnable = $false
$port.RtsEnable = $false
$port.ReadBufferSize = 1048576
$port.ReadTimeout = 100
$capture = [Text.StringBuilder]::new()
function Read-Board([double]$seconds) {
    $timer = [Diagnostics.Stopwatch]::StartNew()
    $reply = [Text.StringBuilder]::new()
    $buffer = [byte[]]::new(8192)
    while ($timer.Elapsed.TotalSeconds -lt $seconds) {
        try {
            $count = $port.Read($buffer, 0, $buffer.Length)
            $text = [Text.Encoding]::ASCII.GetString($buffer, 0, $count)
            [void]$reply.Append($text)
            [void]$capture.Append($text)
        } catch [TimeoutException] {}
    }
    return $reply.ToString()
}
try {
    $port.Open()
    $newline = if ($Mode -eq 'UBoot') { "`r" } else { "`n" }
    $port.Write($newline)
    Write-Output (Read-Board 0.3)
    foreach ($step in $steps) {
        $command = [string]$step.command
        for ($offset = 0; $offset -lt $command.Length; $offset += 32) {
            $port.Write($command.Substring($offset, [Math]::Min(32, $command.Length - $offset)))
            Start-Sleep -Milliseconds 5
        }
        $port.Write($newline)
        $waitSeconds = if ($step.wait) { [double]$step.wait } else { 1.0 }
        $reply = Read-Board $waitSeconds
        Write-Output $reply
        if ($step.expect -and -not [regex]::IsMatch($reply, [string]$step.expect)) {
            throw "Expected response missing for command: $command"
        }
    }
} finally {
    [IO.File]::WriteAllText((Join-Path $PSScriptRoot $EvidenceName), $capture.ToString())
    if ($port.IsOpen) { $port.Close() }
    $port.Dispose()
}
