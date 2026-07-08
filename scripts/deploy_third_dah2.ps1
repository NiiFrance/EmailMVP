$ErrorActionPreference = "Stop"
$sub = "8538aabe-e5de-4e8c-a29d-2914ecf1e65e"
$foundryRg = "rg-emailmvp-foundry-eastus2"
$foundry = "azai-emailmvp-foundry-dah2"
$deployment = "gpt-5.4-mini"
$src = "C:\Users\HP ProBook\Desktop\Azure Customers\_deploy-cloudware"
$rg = "rg-emailmvp-dah"
$envName = "dahmvp"

$ep = az cognitiveservices account show --name $foundry --resource-group $foundryRg --subscription $sub --query "properties.endpoint" -o tsv
$key = az cognitiveservices account keys list --name $foundry --resource-group $foundryRg --subscription $sub --query "key1" -o tsv
Write-Host "Endpoint: $ep (key length $($key.Length))"

Write-Host "=== Creating RG $rg in target ==="
az group create --name $rg --location eastus2 --subscription $sub --query "properties.provisioningState" -o tsv

Write-Host "=== Deploying third Cloudware instance infra ==="
az deployment group create --resource-group $rg --subscription $sub `
    --template-file "$src\infra\main.bicep" `
    --parameters environmentName=$envName location=eastus2 `
        azureOpenAiEndpoint=$ep azureOpenAiApiKey=$key azureOpenAiDeployment=$deployment `
    --query "{state:properties.provisioningState,fn:properties.outputs.functionAppName.value,swa:properties.outputs.staticWebAppName.value,swaHost:properties.outputs.staticWebAppHostname.value}" -o json
