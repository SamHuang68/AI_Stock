$ErrorActionPreference = 'Stop'

$tailscale = 'C:\Program Files\Tailscale\tailscale.exe'
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
