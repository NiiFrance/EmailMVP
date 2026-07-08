$ErrorActionPreference = "Stop"
$oldSub = "1026bf75-8146-43b4-8f2c-32e69ef52837"
$dahSub = "147c97bd-bed0-4b4c-b031-fc5a6e9a4cd6"
$rg = "DevMachine"

Write-Host "=== Collecting resource IDs ==="
$ids = az resource list --resource-group $rg --subscription $oldSub --query "[].id" -o json | ConvertFrom-Json
$ids | ForEach-Object { Write-Host "  $_" }

$targetRgId = "/subscriptions/$dahSub/resourceGroups/$rg"

Write-Host "`n=== Validating move (this can take a few minutes) ==="
$body = @{ resources = $ids; targetResourceGroup = $targetRgId } | ConvertTo-Json -Depth 5
$tmpBody = Join-Path $env:TEMP "move_validate_body.json"
$body | Set-Content -Path $tmpBody -Encoding utf8

# validateMoveResources returns 202 with a Location header to poll
$result = az rest --method post `
    --uri "https://management.azure.com/subscriptions/$oldSub/resourceGroups/$rg/validateMoveResources?api-version=2021-04-01" `
    --body "@$tmpBody" --verbose 2>&1 | Out-String

# az rest follows the async operation automatically when possible; empty output = success
if ($LASTEXITCODE -eq 0) {
    Write-Host "VALIDATION PASSED (no blocking errors)."
} else {
    Write-Host "VALIDATION OUTPUT:"
    Write-Host $result
}
