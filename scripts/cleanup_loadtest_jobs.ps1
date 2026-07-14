param(
    [Parameter(Mandatory=$true)][string[]]$JobIds,
    [string]$Account = "azstocp2inqabawqu",
    [string]$OwnerOid = "" # blank = resolve per job via query
)
# Removes load-test jobs: Jobs table rows + input/output CSV blobs.
$ErrorActionPreference = "Continue"
foreach ($id in $JobIds) {
    $rows = az storage entity query --table-name Jobs --account-name $Account --auth-mode login --filter "RowKey eq '$id'" --query "items[].PartitionKey" -o tsv
    foreach ($pk in $rows) {
        az storage entity delete --table-name Jobs --account-name $Account --auth-mode login --partition-key $pk --row-key $id | Out-Null
    }
    az storage blob delete --account-name $Account --auth-mode login --container-name csv-input --name "$id.csv" 2>$null | Out-Null
    az storage blob delete --account-name $Account --auth-mode login --container-name csv-output --name "$id.csv" 2>$null | Out-Null
    Write-Host "cleaned $id"
}
