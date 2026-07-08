$ErrorActionPreference = "Stop"
$oldSub = "1026bf75-8146-43b4-8f2c-32e69ef52837"
$dahSub = "147c97bd-bed0-4b4c-b031-fc5a6e9a4cd6"
$rg = "DevMachine"

$ids = az resource list --resource-group $rg --subscription $oldSub --query "[].id" -o json | ConvertFrom-Json
# Normalize casing of the resourceGroups segment
$ids = $ids | ForEach-Object { $_ -replace '/resourceGroups/DEVMACHINE/', '/resourceGroups/DevMachine/' }
Write-Host "Moving $($ids.Count) resources:"
$ids | ForEach-Object { Write-Host "  $_" }

$body = @{
    resources = $ids
    targetResourceGroup = "/subscriptions/$dahSub/resourceGroups/$rg"
} | ConvertTo-Json -Depth 5
$tmpBody = Join-Path $env:TEMP "move_body.json"
$body | Set-Content -Path $tmpBody -Encoding utf8

Write-Host "`n=== Executing move via REST (waits for completion) ==="
az rest --method post `
    --uri "https://management.azure.com/subscriptions/$oldSub/resourceGroups/$rg/moveResources?api-version=2021-04-01" `
    --body "@$tmpBody"

if ($LASTEXITCODE -eq 0) {
    Write-Host "MOVE COMPLETED."
} else {
    Write-Host "MOVE FAILED with exit code $LASTEXITCODE"
    exit 1
}

Write-Host "`n=== Resources now in DAH/DevMachine ==="
az resource list --resource-group $rg --subscription $dahSub --query "[].{name:name,type:type}" -o table

Write-Host "`n=== Remaining in old sub DevMachine ==="
$left = az resource list --resource-group $rg --subscription $oldSub --query "[].name" -o tsv
if ($left) { Write-Host $left } else { Write-Host "(empty)" }
