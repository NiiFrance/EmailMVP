$sub = "147c97bd-bed0-4b4c-b031-fc5a6e9a4cd6"
$apps = @(
    @{ name = "azfnirirsysk6fe5y"; rg = "rg-emailmvp-cloudware-eastus2"; label = "Cloudware" },
    @{ name = "azfnwr44s4smhlpo6"; rg = "rg-emailmvp-eastus2"; label = "Reliance" },
    @{ name = "azfn36hgx2ruxoshw"; rg = "rg-emailmvp-dah"; label = "DAH-third" }
)
foreach ($a in $apps) {
    Write-Host ("===== {0} ({1}) =====" -f $a.label, $a.name)
    $planId = az functionapp show --name $a.name --resource-group $a.rg --subscription $sub --query "appServicePlanId" -o tsv
    $plan = az appservice plan show --ids $planId --subscription $sub --query "{name:name,tier:sku.tier,size:sku.name,capacity:sku.capacity,reserved:reserved,workerCount:numberOfWorkers}" -o json | ConvertFrom-Json
    Write-Host ("  Plan: {0} | Tier: {1} | Size: {2} | Capacity: {3} | Linux: {4}" -f $plan.name, $plan.tier, $plan.size, $plan.capacity, $plan.reserved)
    # also how many apps share this plan
    $count = az appservice plan show --ids $planId --subscription $sub --query "numberOfSites" -o tsv
    Write-Host ("  Apps on plan: {0}" -f $count)
}
