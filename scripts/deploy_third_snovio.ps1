$ErrorActionPreference = "Stop"
$sub = "8538aabe-e5de-4e8c-a29d-2914ecf1e65e"
$foundryRg = "rg-emailmvp-foundry-eastus2"
$foundry = "azai-emailmvp-foundry-dah2"
$deployment = "gpt-5.4-mini"
$src = "C:\Users\HP ProBook\Desktop\Azure Customers\EmailMVP"   # snovio branch = main workspace
$rg = "rg-emailmvp-dah"
$envName = "dahmvp"

$ep = az cognitiveservices account show --name $foundry --resource-group $foundryRg --subscription $sub --query "properties.endpoint" -o tsv
$key = az cognitiveservices account keys list --name $foundry --resource-group $foundryRg --subscription $sub --query "key1" -o tsv
Write-Host "Endpoint: $ep (key length $($key.Length))"

# Generate a Fernet key (urlsafe base64 of 32 random bytes) for per-session Snov.io credential encryption
$bytes = New-Object byte[] 32
[System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
$fernet = [Convert]::ToBase64String($bytes).Replace('+','-').Replace('/','_')
Write-Host "Generated Fernet key (length $($fernet.Length))"

Write-Host "=== Re-deploying snovio-branch infra to $rg (env $envName) ==="
az deployment group create --resource-group $rg --subscription $sub `
    --template-file "$src\infra\main.bicep" `
    --parameters environmentName=$envName location=eastus2 `
        azureOpenAiEndpoint=$ep azureOpenAiApiKey=$key azureOpenAiDeployment=$deployment `
        snovioSessionEncryptionKey=$fernet `
    --query "{state:properties.provisioningState,fn:properties.outputs.functionAppName.value,swa:properties.outputs.staticWebAppName.value,swaHost:properties.outputs.staticWebAppHostname.value}" -o json
