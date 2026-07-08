$ErrorActionPreference = "Stop"
$dahSub = "147c97bd-bed0-4b4c-b031-fc5a6e9a4cd6"
$foundryRg = "rg-emailmvp-foundry-eastus2"
$foundry = "azai-emailmvp-foundry-dah"
$deployment = "gpt-5.4"

Write-Host "=== Fetching DAH Foundry credentials ==="
$ep = az cognitiveservices account show --name $foundry --resource-group $foundryRg --subscription $dahSub --query "properties.endpoint" -o tsv
$key = az cognitiveservices account keys list --name $foundry --resource-group $foundryRg --subscription $dahSub --query "key1" -o tsv
Write-Host "Endpoint: $ep (key length $($key.Length))"

# Cloudware
Write-Host "`n=== Repointing Cloudware (azfnirirsysk6fe5y) ==="
az functionapp config appsettings set --name azfnirirsysk6fe5y --resource-group rg-emailmvp-cloudware-eastus2 --subscription $dahSub `
    --settings "AZURE_OPENAI_ENDPOINT=$ep" "AZURE_OPENAI_API_KEY=$key" "AZURE_OPENAI_DEPLOYMENT=$deployment" -o none
Write-Host "Cloudware repointed."

# Reliance
Write-Host "`n=== Repointing Reliance (azfnwr44s4smhlpo6) ==="
az functionapp config appsettings set --name azfnwr44s4smhlpo6 --resource-group rg-emailmvp-eastus2 --subscription $dahSub `
    --settings "AZURE_OPENAI_ENDPOINT=$ep" "AZURE_OPENAI_API_KEY=$key" "AZURE_OPENAI_DEPLOYMENT=$deployment" -o none
Write-Host "Reliance repointed."
Write-Host "`nBoth apps now use $deployment on $ep"
