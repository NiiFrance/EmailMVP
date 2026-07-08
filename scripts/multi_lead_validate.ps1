param([string]$AppHost, [string]$PromptId = "leads", [int]$Leads = 2)
$ErrorActionPreference = "Stop"
$tmp = Join-Path $env:TEMP "multi_lead_test.csv"
$rows = @("first_name,last_name,organization,email")
$samples = @(
    "Boluwatife,Oyekoya,Rosetti Pivot,boluwatife.oyekoya@rosettipivot.com",
    "Abamise,Esther,Finatrust MFB,abamise@finatrustmfbank.com",
    "Sarah,Mensah,Acme Corp,sarah@acme.com",
    "John,Doe,Contoso,john.doe@contoso.com"
)
for ($i = 0; $i -lt $Leads; $i++) { $rows += $samples[$i % $samples.Count] }
[System.IO.File]::WriteAllText($tmp, ($rows -join "`r`n"), (New-Object System.Text.UTF8Encoding $false))

$form = @{ file = Get-Item $tmp; prompt_id = $PromptId }
$up = Invoke-RestMethod -Uri "https://$AppHost/api/upload" -Method Post -Form $form -TimeoutSec 120
$jobId = $up.jobId
Write-Host "jobId=$jobId totalLeads=$($up.totalLeads)"
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 5
    $st = Invoke-RestMethod -Uri "https://$AppHost/api/status/$jobId"
    if ($st.status -in @("Completed","Failed")) { Write-Host "status=$($st.status)"; break }
}
$csv = Invoke-RestMethod -Uri "https://$AppHost/api/download/$jobId"
$unavailable = ([regex]::Matches($csv, "Generation unavailable")).Count
Write-Host "=== RESULT ==="
Write-Host ("'Generation unavailable' occurrences: {0}" -f $unavailable)
$csv.Split("`n") | Select-Object -First 4 | ForEach-Object { Write-Host ($_.Substring(0, [Math]::Min(160, $_.Length))) }
