param(
    [Parameter(Mandatory=$true)][ValidateSet("cloudware","reliance")][string]$App
)
$ErrorActionPreference = "Stop"
$sub = "8538aabe-e5de-4e8c-a29d-2914ecf1e65e"          # target: DAH Subscription
$foundryRg = "rg-emailmvp-foundry-eastus2"
$foundry = "azai-emailmvp-foundry-dah2"
$deployment = "gpt-5.4-mini"

Write-Host "=== Fetching target Foundry credentials ==="
$ep = az cognitiveservices account show --name $foundry --resource-group $foundryRg --subscription $sub --query "properties.endpoint" -o tsv
$key = az cognitiveservices account keys list --name $foundry --resource-group $foundryRg --subscription $sub --query "key1" -o tsv
Write-Host "Endpoint: $ep (key length $($key.Length))"

if ($App -eq "cloudware") {
    $src = "C:\Users\HP ProBook\Desktop\Azure Customers\_deploy-cloudware"
    $rg = "rg-emailmvp-cloudware-eastus2"
    $envName = "cloudware"
    Write-Host "=== Creating Cloudware RG in target ==="
    az group create --name $rg --location eastus2 --subscription $sub --query "properties.provisioningState" -o tsv
    Write-Host "=== Deploying Cloudware infra (Bicep) ==="
    az deployment group create --resource-group $rg --subscription $sub `
        --template-file "$src\infra\main.bicep" `
        --parameters environmentName=$envName location=eastus2 `
            azureOpenAiEndpoint=$ep azureOpenAiApiKey=$key azureOpenAiDeployment=$deployment `
        --query "{state:properties.provisioningState,fn:properties.outputs.functionAppName.value,swa:properties.outputs.staticWebAppName.value,swaHost:properties.outputs.staticWebAppHostname.value}" -o json
}
else {
    $src = "C:\Users\HP ProBook\Desktop\Azure Customers\_deploy-reliance"
    $rg = "rg-emailmvp-eastus2"
    $envName = "emailmvp"
    Write-Host "=== Creating Reliance RG in target ==="
    az group create --name $rg --location eastus2 --subscription $sub --query "properties.provisioningState" -o tsv
    Write-Host "=== Deploying Reliance infra (Bicep) ==="
    az deployment group create --resource-group $rg --subscription $sub `
        --template-file "$src\infra\main.bicep" `
        --parameters environmentName=$envName location=eastus2 `
            anthropicBaseUrl=$ep anthropicApiKey=$key `
        --query "{state:properties.provisioningState,fn:properties.outputs.functionAppName.value,swa:properties.outputs.staticWebAppName.value,swaHost:properties.outputs.staticWebAppHostname.value}" -o json
    $out = az deployment group show --resource-group $rg --subscription $sub --name main --query "properties.outputs" -o json | ConvertFrom-Json
    $fn = $out.functionAppName.value
    Write-Host "=== Patching Reliance app settings to AZURE_OPENAI_* ($fn) ==="
    az functionapp config appsettings set --name $fn --resource-group $rg --subscription $sub `
        --settings "AZURE_OPENAI_ENDPOINT=$ep" "AZURE_OPENAI_API_KEY=$key" "AZURE_OPENAI_DEPLOYMENT=$deployment" "SCM_DO_BUILD_DURING_DEPLOYMENT=true" -o none
    az functionapp config appsettings delete --name $fn --resource-group $rg --subscription $sub --setting-names WEBSITE_RUN_FROM_PACKAGE -o none 2>$null
    Write-Host "Patched."
}
