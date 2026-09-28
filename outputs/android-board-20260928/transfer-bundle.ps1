$ErrorActionPreference='Stop'
$dir='\\wsl.localhost\Ubuntu-22.04\home\sx\projects\rtctrl-platform\outputs\android-board-20260928'
$runSerial=[scriptblock]::Create([IO.File]::ReadAllText("$dir/serial-command.ps1"))
$expected='61293bdd27721122e9b5a2b1a21d794ffb1f899534330288f89249a60cbb1c47'
$total=362916
$chunkSize=8192
$combined=New-Object IO.MemoryStream
for($index=0;$index -lt [Math]::Ceiling($total/$chunkSize);$index++) {
  $good=$false
  for($attempt=1;$attempt -le 4;$attempt++) {
    $read="dd if=/data/local/tmp/rtctrl-hw-20260928/hardware-bundle.tar.gz bs=$chunkSize skip=$index count=1 2>/dev/null"
    $command="echo __CHUNK_BEGIN__; su 0 sh -c '$read | sha256sum; $read | base64'; echo __CHUNK_END__"
    $result=& $runSerial -Name ("17-chunk-{0:D3}-try{1}" -f $index,$attempt) -Command $command -Seconds 1
    $lines=$result -split "`r?`n"
    $hashLine=$lines | Where-Object {$_ -match '^[0-9a-f]{64}\s+-\s*$'} | Select-Object -First 1
    if(-not $hashLine){continue}
    $remoteHash=$hashLine.Substring(0,64)
    $encoded=($lines | Where-Object {$_ -match '^[A-Za-z0-9+/]{4,}={0,2}$'}) -join ''
    try{$bytes=[Convert]::FromBase64String($encoded)}catch{continue}
    $sha=[Security.Cryptography.SHA256]::Create()
    $actual=([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace('-','').ToLowerInvariant()
    $sha.Dispose()
    if($actual -ne $remoteHash){continue}
    $want=[Math]::Min($chunkSize,$total-$index*$chunkSize)
    if($bytes.Length -ne $want){continue}
    [IO.File]::WriteAllBytes(("$dir/chunk-{0:D3}.bin" -f $index),$bytes)
    $combined.Write($bytes,0,$bytes.Length)
    Add-Content "$dir/transfer-verification.tsv" "$index`t$attempt`t$($bytes.Length)`t$actual"
    $good=$true
    break
  }
  if(-not $good){throw "Chunk $index failed all retries"}
  if($index%10 -eq 0){"Verified chunk $index"}
}
$bundle=$combined.ToArray()
$sha=[Security.Cryptography.SHA256]::Create()
$actual=([BitConverter]::ToString($sha.ComputeHash($bundle))).Replace('-','').ToLowerInvariant()
$sha.Dispose()
if($actual -ne $expected){throw "Bundle SHA256 mismatch $actual"}
[IO.File]::WriteAllBytes("$dir/hardware-bundle.tar.gz",$bundle)
[IO.File]::WriteAllText("$dir/bundle-verified.txt","bytes=$($bundle.Length)`nsha256=$actual`n")
"BUNDLE VERIFIED: $($bundle.Length) bytes $actual"
