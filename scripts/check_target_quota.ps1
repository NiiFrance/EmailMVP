$sub = "8538aabe-e5de-4e8c-a29d-2914ecf1e65e"
$u = az cognitiveservices usage list --location eastus2 --subscription $sub -o json 2>$null | ConvertFrom-Json
if (-not $u) { Write-Host "No usage data yet (provider may still be registering)."; return }
Write-Host "=== gpt-5 family quotas in eastus2 (DAH Subscription / target) ==="
$u | Where-Object { $_.name.value -match 'gpt-5' } | ForEach-Object {
    Write-Host ("  {0}  limit={1} used={2}" -f $_.name.value, $_.limit, $_.currentValue)
}
