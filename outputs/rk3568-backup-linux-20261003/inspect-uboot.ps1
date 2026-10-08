$ErrorActionPreference = 'Stop'
$evidenceDirectory = $PSScriptRoot
if (-not $evidenceDirectory) {
    throw 'Run this saved script with -File so evidence stays beside the script'
}

$boardPort = [IO.Ports.SerialPort]::new('COM8', 1500000, 'None', 8, 'One')
$boardPort.Handshake = [IO.Ports.Handshake]::None
$boardPort.DtrEnable = $false
$boardPort.RtsEnable = $false
$boardPort.ReadBufferSize = 1048576
$boardPort.Encoding = [Text.Encoding]::ASCII
$capture = [Text.StringBuilder]::new()

function Read-Board([double]$seconds) {
    $timer = [Diagnostics.Stopwatch]::StartNew()
    $reply = [Text.StringBuilder]::new()
    while ($timer.Elapsed.TotalSeconds -lt $seconds) {
        if ($boardPort.BytesToRead -gt 0) {
            $text = $boardPort.ReadExisting()
            [void]$capture.Append($text)
            [void]$reply.Append($text)
        }
        Start-Sleep -Milliseconds 2
    }
    return $reply.ToString()
}

function Write-Board([string]$command) {
    for ($offset = 0; $offset -lt $command.Length; $offset += 32) {
        $length = [Math]::Min(32, $command.Length - $offset)
        $boardPort.Write($command.Substring($offset, $length))
        Start-Sleep -Milliseconds 5
    }
    $boardPort.Write("`r")
}

try {
    $boardPort.Open()
    $boardPort.Write("`n")
    [void](Read-Board 0.3)

    # Android accepts LF on this console; U-Boot commands below use CR.
    $boardPort.Write("getprop ro.build.version.release`n")
    $androidReply = Read-Board 1.5
    Write-Output $androidReply
    if (-not [regex]::IsMatch($androidReply, '(?m)^11\r?$')) {
        throw 'Android 11 serial shell was not confirmed; no reboot sent'
    }
    $boardPort.Write("su 0 setprop sys.powerctl reboot`n")
    [void](Read-Board 0.25)

    $timer = [Diagnostics.Stopwatch]::StartNew()
    $entered = $false
    while ($timer.Elapsed.TotalSeconds -lt 25) {
        $boardPort.Write([byte[]]@(3, 3), 0, 2)
        [void](Read-Board 0.025)
        if ([regex]::IsMatch($capture.ToString(), '(?m)^=>\s*$')) {
            $entered = $true
            break
        }
    }

    if (-not $entered) {
        [void](Read-Board 10)
        throw 'No U-Boot prompt captured; inspect the raw log before further action'
    }

    $commands = @(
        'version',
        'bdinfo',
        'help booti',
        'help ext4load',
        'help ext4ls',
        'help fdt',
        'help reset',
        'help crc32',
        'printenv bootcmd bootdelay loadaddr kernel_addr_r fdt_addr_r ramdisk_addr_r',
        'printenv initrd_high fdt_high bootm_low bootm_size bootm_mapsize',
        'mmc list',
        'part list mmc 0',
        'ext4ls mmc 0:c /rtctrl-linux-20261003'
    )
    foreach ($command in $commands) {
        Write-Board $command
        $reply = Read-Board 0.8
        Write-Output $reply
    }
    Write-Output 'UBOOT_INSPECTION_COMPLETE_NO_SAVEENV'
} finally {
    [IO.File]::WriteAllText((Join-Path $evidenceDirectory 'uboot-console.raw.txt'), $capture.ToString())
    if ($boardPort.IsOpen) {
        $boardPort.Close()
    }
    $boardPort.Dispose()
}
