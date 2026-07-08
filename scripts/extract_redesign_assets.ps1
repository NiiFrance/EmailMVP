$ErrorActionPreference = "Stop"
$f = "C:\Users\HP ProBook\Desktop\Azure Customers\EmailMVP\Cloudware Campaign Generator (offline).html"
$c = Get-Content $f -Raw

$s = $c.IndexOf('<script type="__bundler/manifest"')
$te = $c.IndexOf('>', $s) + 1
$e = $c.IndexOf('</script>', $te)
$manifest = ($c.Substring($te, $e - $te).Trim() | ConvertFrom-Json)

$ts = $c.IndexOf('<script type="__bundler/template"')
$tte = $c.IndexOf('>', $ts) + 1
$tee = $c.IndexOf('</script>', $tte)
$template = ($c.Substring($tte, $tee - $tte).Trim() | ConvertFrom-Json)

$outDir = "C:\Users\HP ProBook\Desktop\Azure Customers\EmailMVP\frontend\assets"
$fontDir = Join-Path $outDir "fonts"
New-Item -ItemType Directory -Path $fontDir -Force | Out-Null

function Decode-Entry($entry) {
    $bytes = [Convert]::FromBase64String($entry.data)
    if ($entry.compressed) {
        $ms = New-Object System.IO.MemoryStream(,$bytes)
        $gz = New-Object System.IO.Compression.GZipStream($ms, [System.IO.Compression.CompressionMode]::Decompress)
        $out = New-Object System.IO.MemoryStream
        $gz.CopyTo($out); $gz.Dispose(); $ms.Dispose()
        $bytes = $out.ToArray(); $out.Dispose()
    }
    return $bytes
}

Write-Host "=== Saving fonts by UUID ==="
$count = 0
foreach ($prop in $manifest.PSObject.Properties) {
    if ($prop.Value.mime -eq "font/woff2") {
        $bytes = Decode-Entry $prop.Value
        [System.IO.File]::WriteAllBytes((Join-Path $fontDir "$($prop.Name).woff2"), $bytes)
        $count++
    }
}
Write-Host "  saved $count woff2 files"

Write-Host "=== Building fonts.css ==="
$styleMatches = [regex]::Matches($template, '(?s)<style>(.*?)</style>')
$allCss = ($styleMatches | ForEach-Object { $_.Groups[1].Value }) -join "`n"
$faceMatches = [regex]::Matches($allCss, '(?s)@font-face\s*\{.*?\}')
$facesCss = ($faceMatches | ForEach-Object { $_.Value }) -join "`n`n"
$facesCss = [regex]::Replace($facesCss, 'url\("([0-9a-fA-F-]{36})"\)', 'url("fonts/$1.woff2")')
Set-Content -Path (Join-Path $outDir "fonts.css") -Value $facesCss -Encoding utf8
Write-Host "  fonts.css: $($faceMatches.Count) @font-face rules"

Get-ChildItem $outDir -Filter "*.woff2" | Remove-Item -Force -ErrorAction SilentlyContinue

Write-Host "=== Done ==="
Write-Host ("Logo present: " + (Test-Path (Join-Path $outDir 'cloudware-logo.png')))
Write-Host ("Fonts dir count: " + (Get-ChildItem $fontDir).Count)
