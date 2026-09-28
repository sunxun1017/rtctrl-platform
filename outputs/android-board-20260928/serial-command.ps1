param([Parameter(Mandatory=$true)][string]$Name,[Parameter(Mandatory=$true)][string]$Command,[int]$Seconds=3)
$ErrorActionPreference='Stop'
$outDir='\\wsl.localhost\Ubuntu-22.04\home\sx\projects\rtctrl-platform\outputs\android-board-20260928'
$stamp=(Get-Date).ToString('o')
[IO.File]::WriteAllText((Join-Path $outDir "$Name.command.sh"),$Command+"`n")
Add-Content -LiteralPath (Join-Path $outDir 'session.log') -Value "$stamp COM6 1500000 8N1 DTR=false RTS=false $Name wait=$Seconds"
$port=New-Object IO.Ports.SerialPort 'COM6',1500000,'None',8,'One'
$port.DtrEnable=$false
$port.RtsEnable=$false
$port.ReadBufferSize=1048576
$raw=New-Object IO.MemoryStream
try {
  $port.Open()
  $port.Write("`r")
  Start-Sleep -Milliseconds 200
  $port.Write($Command+"`r")
  $timer=[Diagnostics.Stopwatch]::StartNew()
  do {
    $count=$port.BytesToRead
    if($count -gt 0){$buffer=New-Object byte[] $count; $got=$port.Read($buffer,0,$count); $raw.Write($buffer,0,$got)}
    Start-Sleep -Milliseconds 20
  } while($timer.Elapsed.TotalSeconds -lt $Seconds)
} finally {
  if($port.IsOpen){$port.Close()}
  [IO.File]::WriteAllBytes((Join-Path $outDir "$Name.raw.bin"),$raw.ToArray())
  $decoded=[Text.Encoding]::UTF8.GetString($raw.ToArray())
  [IO.File]::WriteAllText((Join-Path $outDir "$Name.output.txt"),$decoded)
  $raw.Dispose()
}
$decoded
