$ErrorActionPreference = "Stop"
$oldSub = "1026bf75-8146-43b4-8f2c-32e69ef52837"
$dahSub = "147c97bd-bed0-4b4c-b031-fc5a6e9a4cd6"
$rg = "DevMachine"

$ids = az resource list --resource-group $rg --subscription $oldSub --query "[].id" -o json | ConvertFrom-Json
Write-Host "Moving $($ids.Count) resources to DAH/$rg ..."

az resource move `
    --ids $ids `
    --destination-group $rg `
    --destination-subscription-id $dahSub

if ($LASTEXITCODE -eq 0) {
    Write-Host "MOVE COMPLETED."
} else {
    Write-Host "MOVE FAILED with exit code $LASTEXITCODE"
    exit 1
}

Write-Host "`n=== Resources now in DAH/DevMachine ==="
az resource list --resource-group $rg --subscription $dahSub --query "[].{name:name,type:type}" -o table

Write-Host "`n=== Remaining in old sub DevMachine ==="
az resource list --resource-group $rg --subscription $oldSub --query "[].name" -o tsv
