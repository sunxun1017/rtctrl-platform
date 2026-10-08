$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)

$boardPort = [IO.Ports.SerialPort]::new('COM8', 1500000, 'None', 8, 'One')
$boardPort.Handshake = [IO.Ports.Handshake]::None
$boardPort.DtrEnable = $false
$boardPort.RtsEnable = $false
$boardPort.ReadBufferSize = 1048576
$boardPort.WriteTimeout = 3000
$boardPort.Encoding = [Text.Encoding]::UTF8

try {
    $boardPort.Open()
    [Console]::WriteLine('{"type":"ready","port":"COM8"}')
    $pendingLine = [Console]::In.ReadLineAsync()

    while ($true) {
        if ($boardPort.BytesToRead -gt 0) {
            $received = $boardPort.ReadExisting()
            $event = @{ type = 'rx'; text = $received }
            [Console]::WriteLine(($event | ConvertTo-Json -Compress))
        }

        if ($pendingLine.IsCompleted) {
            $line = $pendingLine.GetAwaiter().GetResult()
            if ($null -eq $line) {
                break
            }

            $request = $line | ConvertFrom-Json
            if ($request.type -eq 'quit') {
                break
            }

            if ($request.type -eq 'write') {
                $bytes = [Convert]::FromBase64String($request.base64)
                $boardPort.Write($bytes, 0, $bytes.Length)
            }

            $pendingLine = [Console]::In.ReadLineAsync()
        }

        Start-Sleep -Milliseconds 10
    }
} finally {
    if ($boardPort.IsOpen) {
        $boardPort.Close()
    }
    $boardPort.Dispose()
}
