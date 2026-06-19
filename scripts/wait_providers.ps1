$sub = "147c97bd-bed0-4b4c-b031-fc5a6e9a4cd6"
for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Seconds 15
    $n = az provider show --namespace Microsoft.Network --subscription $sub --query registrationState -o tsv
    $c = az provider show --namespace Microsoft.Compute --subscription $sub --query registrationState -o tsv
    Write-Host ("poll {0}: Network={1} Compute={2}" -f $i, $n, $c)
    if ($n -eq "Registered" -and $c -eq "Registered") { Write-Host "BOTH REGISTERED"; break }
}
