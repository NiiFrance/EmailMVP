param(
    [string]$FunctionApp = "azfnocp2inqabawqu",
    [string]$ResourceGroup = "rg-emailmvp-dah",
    [string]$Subscription = "8538aabe-e5de-4e8c-a29d-2914ecf1e65e",
    [string]$Table = "SnovioCreds"
)
$ErrorActionPreference = "Stop"
$cs = az functionapp config appsettings list --name $FunctionApp --resource-group $ResourceGroup --subscription $Subscription --query "[?name=='AzureWebJobsStorage'].value" -o tsv
if (-not $cs) { Write-Host "No connection string"; exit 1 }
az storage entity query --table-name $Table --connection-string $cs --query "items[].{pk:PartitionKey, rk:RowKey}" -o table
