$ErrorActionPreference = "Stop"
$sub = "147c97bd-bed0-4b4c-b031-fc5a6e9a4cd6"
$rg = "rg-emailmvp-foundry-eastus2"
$acct = "azai-emailmvp-foundry-dah"

Write-Host "=== Creating resource group ==="
az group create --name $rg --location eastus2 --subscription $sub --query "properties.provisioningState" -o tsv

Write-Host "=== Creating Foundry (AIServices) account ==="
az cognitiveservices account create `
    --name $acct `
    --resource-group $rg `
    --subscription $sub `
    --location eastus2 `
    --kind AIServices `
    --sku S0 `
    --custom-domain $acct `
    --yes `
    --query "{name:name,state:properties.provisioningState,endpoint:properties.endpoint}" -o json

Write-Host "=== Creating gpt-5.5 deployment ==="
az cognitiveservices account deployment create `
    --name $acct `
    --resource-group $rg `
    --subscription $sub `
    --deployment-name "gpt-5.5" `
    --model-name "gpt-5.5" `
    --model-version "2026-04-24" `
    --model-format OpenAI `
    --sku-name "GlobalStandard" `
    --sku-capacity 10 `
    --query "{name:name,state:properties.provisioningState}" -o json

Write-Host "=== Done ==="
az cognitiveservices account show --name $acct --resource-group $rg --subscription $sub --query "properties.endpoint" -o tsv
