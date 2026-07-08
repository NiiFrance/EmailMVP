$sub = "147c97bd-bed0-4b4c-b031-fc5a6e9a4cd6"
$apps = @(
    @{ name = "azfnirirsysk6fe5y"; rg = "rg-emailmvp-cloudware-eastus2"; label = "Cloudware" },
    @{ name = "azfnwr44s4smhlpo6"; rg = "rg-emailmvp-eastus2"; label = "Reliance" },
    @{ name = "azfn36hgx2ruxoshw"; rg = "rg-emailmvp-dah"; label = "DAH-third" }
)
foreach ($a in $apps) {
    $info = az functionapp show --name $a.name --resource-group $a.rg --subscription $sub --query "{loc:location,kind:kind,linuxFxVersion:siteConfig.linuxFxVersion}" -o json | ConvertFrom-Json
    Write-Host ("{0,-12} loc={1}  kind={2}  fx={3}" -f $a.label, $info.loc, $info.kind, $info.linuxFxVersion)
}
