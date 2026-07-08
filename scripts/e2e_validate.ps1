param(
    [string]$AppHost,
    [string]$PromptId = "cold_email"
)

$ErrorActionPreference = "Stop"
$tmp = Join-Path $env:TEMP "redeploy-e2e-$PromptId.csv"
if ($PromptId -eq "leads") {
    $csv = "first_name,last_name,organization,email`r`nSarah,Mensah,Acme Corp,sarah@acme.com"
} else {
    $csv = "first_name,last_name,organization,title,email,license_renewal,engagement_objectives`r`nJane,Doe,Contoso Ltd,IT Director,jane.doe@contoso.com,2026-09-30,Renew CSP licenses and discuss Azure migration"
}
[System.IO.File]::WriteAllText($tmp, $csv, (New-Object System.Text.UTF8Encoding $false))

Write-Host "=== Upload to $AppHost (prompt=$PromptId) ==="
$jobId = $null
try {
    $form = @{ file = Get-Item $tmp; prompt_id = $PromptId }
    $up = Invoke-RestMethod -Uri "https://$AppHost/api/upload" -Method Post -Form $form -TimeoutSec 120
    Write-Host ("Upload response: " + ($up | ConvertTo-Json -Compress))
    $jobId = $up.jobId; if (-not $jobId) { $jobId = $up.job_id }; if (-not $jobId) { $jobId = $up.id }
} catch {
    $body = $_.ErrorDetails.Message
    $code = $null
    try { $code = [int]$_.Exception.Response.StatusCode } catch {}
    if ($body) { Write-Host ("UPLOAD HTTP $code : $body") }
    else { Write-Host ("UPLOAD ERROR: " + $_.Exception.Message) }
    exit 1
}

if (-not $jobId) { Write-Host "No jobId returned; cannot poll."; exit 1 }
Write-Host "jobId = $jobId"

Write-Host "=== Polling status ==="
$done = $false
for ($i = 0; $i -lt 90; $i++) {
    Start-Sleep -Seconds 5
    try {
        $st = Invoke-RestMethod -Uri "https://$AppHost/api/status/$jobId" -Method Get -TimeoutSec 60
        $status = $st.runtimeStatus; if (-not $status) { $status = $st.status }
        Write-Host ("[{0}] status={1} progress={2}" -f $i, $status, ($st.customStatus | ConvertTo-Json -Compress))
        if ($status -in @("Completed","Failed","Terminated")) { $done = $true; $finalStatus = $status; break }
    } catch {
        Write-Host ("STATUS ERROR: " + $_.Exception.Message)
    }
}

if ($done -and $finalStatus -eq "Completed") {
    Write-Host "=== Downloading result ==="
    try {
        $out = Join-Path $env:TEMP ("result_" + ($AppHost.Split('.')[0]) + ".csv")
        Invoke-WebRequest -Uri "https://$AppHost/api/download/$jobId" -OutFile $out -TimeoutSec 120
        Write-Host "Downloaded to $out"
        Write-Host "--- First 600 chars ---"
        (Get-Content $out -Raw).Substring(0, [Math]::Min(600, (Get-Content $out -Raw).Length)) | Write-Host
    } catch {
        Write-Host ("DOWNLOAD ERROR: " + $_.Exception.Message)
    }
} else {
    Write-Host "Job did not complete successfully (status=$finalStatus)."
}
