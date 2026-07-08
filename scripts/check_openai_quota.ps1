$ErrorActionPreference = "Continue"
$sub = "147c97bd-bed0-4b4c-b031-fc5a6e9a4cd6"
foreach ($r in @("eastus2", "swedencentral")) {
    Write-Host "=== $r (OpenAI quotas with limit > 0) ==="
    $u = az cognitiveservices usage list --location $r --subscription $sub -o json 2>$null | ConvertFrom-Json
    $hits = $u | Where-Object { $_.limit -gt 0 -and $_.name.value -match 'OpenAI' }
    if ($hits) {
        $hits | ForEach-Object { Write-Host ("  {0}  limit={1} used={2}" -f $_.name.value, $_.limit, $_.currentValue) }
    } else {
        Write-Host "  none"
    }
}
