$ErrorActionPreference = "Stop"
# Old sub: Foundry gpt-5.5 stays here
$oldSub = "1026bf75-8146-43b4-8f2c-32e69ef52837"
# New sub: apps move here
$dahSub = "147c97bd-bed0-4b4c-b031-fc5a6e9a4cd6"

Write-Host "=== Fetching Foundry credentials from old subscription ==="
$ep = az cognitiveservices account show --name azai-emailmvp-foundry --resource-group rg-emailmvp-foundry-eastus2 --subscription $oldSub --query "properties.endpoint" -o tsv
$key = az cognitiveservices account keys list --name azai-emailmvp-foundry --resource-group rg-emailmvp-foundry-eastus2 --subscription $oldSub --query "key1" -o tsv
Write-Host "Endpoint: $ep (key length $($key.Length))"

# --- Cloudware ---
$cw = "C:\Users\HP ProBook\Desktop\Azure Customers\_deploy-cloudware"
$cwRg = "rg-emailmvp-cloudware-eastus2"
Write-Host "=== Creating Cloudware RG in DAH ==="
az group create --name $cwRg --location eastus2 --subscription $dahSub --query "properties.provisioningState" -o tsv

Write-Host "=== Deploying Cloudware infra (Bicep) to DAH ==="
az deployment group create --resource-group $cwRg --subscription $dahSub `
    --template-file "$cw\infra\main.bicep" `
    --parameters environmentName=cloudware location=eastus2 `
        azureOpenAiEndpoint=$ep azureOpenAiApiKey=$key azureOpenAiDeployment=gpt-5.5 `
    --query "{state:properties.provisioningState,fn:properties.outputs.functionAppName.value,swa:properties.outputs.staticWebAppName.value,swaHost:properties.outputs.staticWebAppHostname.value}" -o json
