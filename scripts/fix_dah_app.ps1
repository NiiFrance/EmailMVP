$ErrorActionPreference = "Stop"
$sub = "147c97bd-bed0-4b4c-b031-fc5a6e9a4cd6"
$rg = "rg-emailmvp-dah"
$foundry = "aif-emailmvp-dah-opjfi"
$vault = "azkv36hgx2ruxoshw"

$ep = az cognitiveservices account show --name $foundry --resource-group $rg --subscription $sub --query "properties.endpoint" -o tsv
$key = az cognitiveservices account keys list --name $foundry --resource-group $rg --subscription $sub --query "key1" -o tsv
Write-Host "Local Foundry endpoint: $ep (key length $($key.Length))"

# Retry secret read/write to allow for RBAC propagation
for ($i = 0; $i -lt 12; $i++) {
    try {
        $cur = az keyvault secret show --vault-name $vault --name "AzureOpenAIEndpoint" --subscription $sub --query "value" -o tsv 2>$null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "Current AzureOpenAIEndpoint secret: $cur"
            break
        }
    } catch {}
    Write-Host "RBAC not propagated yet, waiting... ($i)"
    Start-Sleep -Seconds 15
}

Write-Host "=== Updating secrets ==="
az keyvault secret set --vault-name $vault --name "AzureOpenAIEndpoint" --value $ep --subscription $sub -o none
az keyvault secret set --vault-name $vault --name "AzureOpenAIApiKey" --value $key --subscription $sub -o none
Write-Host "Secrets updated."

Write-Host "=== Updating app setting AZURE_OPENAI_DEPLOYMENT=gpt-5.4 ==="
az functionapp config appsettings set --name "azfn36hgx2ruxoshw" --resource-group $rg --subscription $sub --settings "AZURE_OPENAI_DEPLOYMENT=gpt-5.4" -o none
Write-Host "Done."
