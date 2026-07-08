$ErrorActionPreference = "Stop"
$sub = "8538aabe-e5de-4e8c-a29d-2914ecf1e65e"
$rg = "rg-emailmvp-foundry-eastus2"
$acct = "azai-emailmvp-foundry-dah2"

Write-Host "=== Creating resource group ==="
az group create --name $rg --location eastus2 --subscription $sub --query "properties.provisioningState" -o tsv

Write-Host "=== Creating Foundry (AIServices) account ==="
az cognitiveservices account create `
    --name $acct --resource-group $rg --subscription $sub `
    --location eastus2 --kind AIServices --sku S0 --custom-domain $acct --yes `
    --query "{name:name,state:properties.provisioningState,endpoint:properties.endpoint}" -o json

Write-Host "=== Deploying gpt-5.4-mini (DataZoneStandard) ==="
az cognitiveservices account deployment create `
    --name $acct --resource-group $rg --subscription $sub `
    --deployment-name "gpt-5.4-mini" --model-name "gpt-5.4-mini" --model-version "2026-03-17" `
    --model-format OpenAI --sku-name "DataZoneStandard" --sku-capacity 10 `
    --query "{name:name,state:properties.provisioningState}" -o json

Write-Host "=== Endpoint ==="
az cognitiveservices account show --name $acct --resource-group $rg --subscription $sub --query "properties.endpoint" -o tsv
