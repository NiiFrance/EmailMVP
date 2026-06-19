$sub = "147c97bd-bed0-4b4c-b031-fc5a6e9a4cd6"
$u = az cognitiveservices usage list --location eastus2 --subscription $sub -o json | ConvertFrom-Json
Write-Host "=== gpt-5 family quotas in eastus2 (DAH) ==="
$u | Where-Object { $_.name.value -match 'gpt-5' } | ForEach-Object {
    Write-Host ("  {0}  limit={1} used={2}" -f $_.name.value, $_.limit, $_.currentValue)
}
