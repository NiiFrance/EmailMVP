$ErrorActionPreference = "Stop"
$oldSub = "1026bf75-8146-43b4-8f2c-32e69ef52837"
$dahSub = "147c97bd-bed0-4b4c-b031-fc5a6e9a4cd6"

Write-Host "=== Fetching Foundry credentials from old subscription ==="
$ep = az cognitiveservices account show --name azai-emailmvp-foundry --resource-group rg-emailmvp-foundry-eastus2 --subscription $oldSub --query "properties.endpoint" -o tsv
$key = az cognitiveservices account keys list --name azai-emailmvp-foundry --resource-group rg-emailmvp-foundry-eastus2 --subscription $oldSub --query "key1" -o tsv
Write-Host "Endpoint: $ep (key length $($key.Length))"

$rl = "C:\Users\HP ProBook\Desktop\Azure Customers\_deploy-reliance"
$rlRg = "rg-emailmvp-eastus2"
Write-Host "=== Creating Reliance RG in DAH ==="
az group create --name $rlRg --location eastus2 --subscription $dahSub --query "properties.provisioningState" -o tsv

# Reliance main branch Bicep uses Anthropic-named params (legacy naming); values are unused
# at runtime because the app reads AZURE_OPENAI_* which we set post-deploy.
Write-Host "=== Deploying Reliance infra (Bicep) to DAH ==="
az deployment group create --resource-group $rlRg --subscription $dahSub `
    --template-file "$rl\infra\main.bicep" `
    --parameters environmentName=emailmvp location=eastus2 `
        anthropicBaseUrl=$ep anthropicApiKey=$key `
    --query "{state:properties.provisioningState,fn:properties.outputs.functionAppName.value,swa:properties.outputs.staticWebAppName.value,swaHost:properties.outputs.staticWebAppHostname.value}" -o json

# Capture outputs for the app settings patch
$out = az deployment group show --resource-group $rlRg --subscription $dahSub --name main --query "properties.outputs" -o json | ConvertFrom-Json
$fn = $out.functionAppName.value
Write-Host "=== Patching Function App settings to AZURE_OPENAI_* ($fn) ==="
az functionapp config appsettings set --name $fn --resource-group $rlRg --subscription $dahSub `
    --settings "AZURE_OPENAI_ENDPOINT=$ep" "AZURE_OPENAI_API_KEY=$key" "AZURE_OPENAI_DEPLOYMENT=gpt-5.5" "SCM_DO_BUILD_DURING_DEPLOYMENT=true" -o none
az functionapp config appsettings delete --name $fn --resource-group $rlRg --subscription $dahSub --setting-names WEBSITE_RUN_FROM_PACKAGE -o none 2>$null
Write-Host "Settings patched."
