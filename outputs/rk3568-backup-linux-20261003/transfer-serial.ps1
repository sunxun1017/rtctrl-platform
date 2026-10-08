param(
    [Parameter(Mandatory = $true)][string]$Destination,
    [string]$PrefixFrom,
    [int]$ChunkBytes = 8192
)

$ErrorActionPreference = 'Stop'
$remoteFile = '/data/local/tmp/rtctrl-boot-20260928/boot-components.tar.gz'
$totalBytes = 18384591
$expectedSha = '8e653d52d144a5a4cf8e18ca2a19211c76a3113509f958e53b259bedb4288380'
$sessionTag = [Guid]::NewGuid().ToString('N').Substring(0, 8)

function Get-BytesHash([byte[]]$bytes) {
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try {
        return [BitConverter]::ToString($algorithm.ComputeHash($bytes)).Replace('-', '').ToLowerInvariant()
    } finally {
        $algorithm.Dispose()
    }
}

$boardPort = [IO.Ports.SerialPort]::new('COM8', 1500000, 'None', 8, 'One')
$boardPort.Handshake = [IO.Ports.Handshake]::None
$boardPort.DtrEnable = $false
$boardPort.RtsEnable = $false
$boardPort.ReadBufferSize = 1048576
$boardPort.ReadTimeout = 100
$boardPort.Encoding = [Text.Encoding]::ASCII

function Invoke-Board([string]$body, [string]$tag) {
    $tag = $sessionTag + $tag
    $command = "su 0 sh -c 'echo ZBEGIN$tag; $body; echo ZEND$tag'"
    $boardPort.DiscardInBuffer()
    for ($offset = 0; $offset -lt $command.Length; $offset += 32) {
        $length = [Math]::Min(32, $command.Length - $offset)
        $boardPort.Write($command.Substring($offset, $length))
        Start-Sleep -Milliseconds 5
    }
    $boardPort.Write("`n")

    $received = [Text.StringBuilder]::new()
    $readBuffer = [byte[]]::new(8192)
    $timer = [Diagnostics.Stopwatch]::StartNew()
    while ($timer.Elapsed.TotalSeconds -lt 8) {
        try {
            $count = $boardPort.Read($readBuffer, 0, $readBuffer.Length)
            [void]$received.Append([Text.Encoding]::ASCII.GetString($readBuffer, 0, $count))
            $text = $received.ToString()
            $match = [regex]::Match($text, "(?ms)^ZBEGIN$tag\r*\n(.*?)^ZEND$tag\r*\n")
            if ($match.Success) {
                return $match.Groups[1].Value
            }
        } catch [TimeoutException] {
            # Wait for actual input instead of polling on the Windows sleep timer.
        }
    }
    throw "Serial response timeout for $tag"
}

$file = $null
try {
    if (-not (Test-Path -LiteralPath $Destination)) {
        if ($PrefixFrom) {
            Copy-Item -LiteralPath $PrefixFrom -Destination $Destination
        } else {
            [IO.File]::WriteAllBytes($Destination, [byte[]]::new(0))
        }
    }

    if ((Get-Item -LiteralPath $Destination).Length -eq $totalBytes) {
        $existingHash = (Get-FileHash -LiteralPath $Destination -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($existingHash -ne $expectedSha) {
            throw 'Existing complete-size destination has a different checksum; leaving it intact'
        }
        Write-Host "VERIFIED bytes=$totalBytes sha256=$existingHash"
        return
    }

    $file = [IO.FileStream]::new($Destination, 'Open', 'ReadWrite', 'Read')
    if ($file.Length -gt $totalBytes) {
        throw 'Existing destination exceeds the expected archive size'
    }
    $resumeOffset = [long]([Math]::Floor($file.Length / $ChunkBytes) * $ChunkBytes)
    $existingLength = $file.Length

    $boardPort.Open()
    $boardPort.Write(([string][char]3) + "`n")
    Start-Sleep -Milliseconds 250

    if ($existingLength -gt 0) {
        $prefixReply = Invoke-Board "head -c $existingLength $remoteFile | sha256sum" 'PREFIX'
        $remotePrefixHash = [regex]::Match($prefixReply, '(?m)^([a-f0-9]{64})\s+-\r*$').Groups[1].Value
        [void]$file.Seek(0, 'Begin')
        $prefixAlgorithm = [Security.Cryptography.SHA256]::Create()
        try {
            $localPrefixHash = [BitConverter]::ToString($prefixAlgorithm.ComputeHash($file)).Replace('-', '').ToLowerInvariant()
        } finally {
            $prefixAlgorithm.Dispose()
        }
        if ($remotePrefixHash -ne $localPrefixHash) {
            throw 'Existing prefix does not match the board archive'
        }
    }

    $file.SetLength($resumeOffset)
    $file.Flush()
    [void]$file.Seek($resumeOffset, 'Begin')
    for ($index = [int]($resumeOffset / $ChunkBytes); $file.Position -lt $totalBytes; $index++) {
        if (Test-Path -LiteralPath ($Destination + '.cancel')) {
            throw 'Transfer cancelled after a verified chunk'
        }
        $readChunk = "dd if=$remoteFile bs=$ChunkBytes skip=$index count=1 2>/dev/null"
        $expectedLength = [int][Math]::Min($ChunkBytes, $totalBytes - $file.Position)
        $success = $false

        for ($attempt = 1; $attempt -le 10; $attempt++) {
            $reply = $null
            try {
                $reply = Invoke-Board "$readChunk | sha256sum; $readChunk | base64" ("CHUNK{0}X{1}" -f $index, $attempt)
                $hashMatch = [regex]::Match($reply, '(?m)^([a-f0-9]{64})\s+-\r*\n')
                if (-not $hashMatch.Success) {
                    throw 'Chunk checksum was not received'
                }
                $payload = $reply.Substring($hashMatch.Index + $hashMatch.Length)
                $bytes = [Convert]::FromBase64String($payload)
                if ($bytes.Length -ne $expectedLength -or (Get-BytesHash $bytes) -ne $hashMatch.Groups[1].Value) {
                    throw 'Chunk length or checksum mismatch'
                }
                $success = $true
                break
            } catch {
                Write-Host "RETRY chunk=$index attempt=$attempt reason=$($_.Exception.Message)"
                if ($reply) {
                    [IO.File]::WriteAllText($Destination + '.failure.raw.txt', $reply)
                }
                if ($_.Exception.Message -like 'Serial response timeout*') {
                    $boardPort.Write(([string][char]3) + "`n")
                }
                Start-Sleep -Milliseconds 100
            }
        }

        if (-not $success) {
            throw "Chunk $index failed after ten attempts"
        }
        # Storage errors terminate the transfer; never retry a partly written chunk.
        $file.Write($bytes, 0, $bytes.Length)
        if (($index % 32) -eq 0 -or $file.Position -eq $totalBytes) {
            $file.Flush()
            Write-Host "TRANSFER bytes=$($file.Position) total=$totalBytes"
        }
    }

    $file.Dispose()
    $file = $null
    $finalHash = (Get-FileHash -LiteralPath $Destination -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($finalHash -ne $expectedSha) {
        throw 'Final archive checksum mismatch'
    }
    Write-Host "VERIFIED bytes=$totalBytes sha256=$finalHash"
} finally {
    if ($file) {
        $file.Dispose()
    }
    if ($boardPort.IsOpen) {
        $boardPort.Close()
    }
    $boardPort.Dispose()
}
