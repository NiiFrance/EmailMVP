$ErrorActionPreference = "Stop"
$f = "C:\Users\HP ProBook\Desktop\Azure Customers\EmailMVP\Cloudware Campaign Generator (offline).html"
$c = Get-Content $f -Raw
$ts = $c.IndexOf('<script type="__bundler/template"')
$tte = $c.IndexOf('>', $ts) + 1
$tee = $c.IndexOf('</script>', $tte)
$html = ($c.Substring($tte, $tee - $tte).Trim() | ConvertFrom-Json)
# Strip the long <style> font blocks so the structural markup is readable
$body = $html
$styleStart = $body.IndexOf('<style>')
$styleEnd = $body.LastIndexOf('</style>')
if ($styleStart -ge 0 -and $styleEnd -gt $styleStart) {
    $body = $body.Substring(0, $styleStart) + "<!-- [fonts stripped] -->" + $body.Substring($styleEnd + 8)
}
Set-Content -Path "$env:TEMP\design_full.html" -Value $body -Encoding utf8
Write-Host ("Saved design_full.html, length " + $body.Length)
