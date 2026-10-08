param(
    [Parameter(Mandatory=$true)][string]$BoardAddress,
    [Parameter(Mandatory=$true)][ValidateSet('pm0', 'band5')][string]$Mode
)
$ErrorActionPreference = 'Stop'
$resultPath = Join-Path $PSScriptRoot "private/transfer-$Mode.json"
if (Test-Path -LiteralPath $resultPath) { throw 'Transfer evidence already exists' }
$roundtripPath = Join-Path $PSScriptRoot "private/roundtrip-$Mode.json"
$started = [DateTime]::UtcNow.ToString('o')
try {
    & (Join-Path $PSScriptRoot '../rk3568-source-wifi-20261004/transfer-client.ps1') `
        -BoardAddress $BoardAddress -ResultPath $roundtripPath
    $result = Get-Content -Raw -LiteralPath $roundtripPath | ConvertFrom-Json
    $result | Add-Member -NotePropertyName started_utc -NotePropertyValue $started
    $result | Add-Member -NotePropertyName mode -NotePropertyValue $Mode
} catch {
    $result = [ordered]@{
        mode = $Mode
        started_utc = $started
        roundtrip_passed = $false
        error = $_.Exception.Message
    }
}
[IO.File]::WriteAllText($resultPath, ($result | ConvertTo-Json), [Text.UTF8Encoding]::new($false))
$result | ConvertTo-Json
if (-not $result.roundtrip_passed) { exit 1 }
