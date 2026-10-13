param([switch]$OpenBrowser, [switch]$ResolveUrl)
$ErrorActionPreference = 'Stop'

function Get-PrivateWebBrowserUrl($ServeConfig) {
    $urls = @()
    foreach ($entry in $ServeConfig.Web.PSObject.Properties) {
        if ($entry.Name -notmatch '\A([a-zA-Z0-9](?:[a-zA-Z0-9.-]*[a-zA-Z0-9])?\.ts\.net):([0-9]+)\z') { continue }
        $dnsName = $Matches[1]
        $portNumber = [int]$Matches[2]
        if ($portNumber -lt 1 -or $portNumber -gt 65535) { continue }
        $listener = $ServeConfig.TCP.PSObject.Properties[[string]$portNumber]
        if (-not $listener -or $listener.Value.HTTPS -isnot [bool] -or -not $listener.Value.HTTPS) { continue }
        $handler = $entry.Value.Handlers.PSObject.Properties['/']
        if (-not $handler -or $handler.Value.Proxy -notin @('http://127.0.0.1:18434', 'http://127.0.0.1:18434/')) { continue }
        $authority = if ($portNumber -eq 443) { $dnsName } else { '{0}:{1}' -f $dnsName, $portNumber }
        $urls += 'https://' + $authority + '/#pulse'
    }
    if ($urls.Count -ne 1) { throw '找不到唯一對應 ST 閘道的 Tailscale HTTPS 路由；請檢查既有 Serve 設定。' }
    return $urls[0]
}

$tailscale = 'C:\Program Files\Tailscale\tailscale.exe'
if ($OpenBrowser -or $ResolveUrl) {
    try {
        if (-not (Test-Path -LiteralPath $tailscale -PathType Leaf)) { throw '找不到已安裝的 Tailscale。' }
        $serveJson = & $tailscale serve status --json
        if ($LASTEXITCODE -ne 0) { throw '無法讀取目前的 Tailscale Serve 設定。' }
        $url = Get-PrivateWebBrowserUrl ($serveJson | Out-String | ConvertFrom-Json)
        if ($OpenBrowser) { Start-Process -FilePath $url }
        Write-Output $url
        exit 0
    } catch {
        Write-Error ('私有網站開啟失敗：' + $_.Exception.Message)
        exit 1
    }
}
$projectRoot = Split-Path -Parent $PSScriptRoot
$logDirectory = Join-Path $projectRoot 'logs'
$outputPath = Join-Path $logDirectory 'tailscale-private-web-status.json'

New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null

$serve = (& $tailscale serve status --json 2>&1 | Out-String).Trim()
$funnel = (& $tailscale funnel status --json 2>&1 | Out-String).Trim()
$config = (& $tailscale serve get-config --all 2>&1 | Out-String).Trim()
$serveText = (& $tailscale serve status 2>&1 | Out-String).Trim()
$funnelText = (& $tailscale funnel status 2>&1 | Out-String).Trim()

[ordered]@{
    capturedAt = [DateTimeOffset]::Now.ToString('o')
    serve = $serve
    funnel = $funnel
    config = $config
    serveText = $serveText
    funnelText = $funnelText
} | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $outputPath -Encoding utf8
