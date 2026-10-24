# Read readiness through the same binding and identity checks as the launcher.
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'start_wavedeck.ps1') -WaveDeckRoot $PSScriptRoot -NoBrowser
$originalRole = $env:ST_RUNTIME_ROLE
$originalBinding = $env:ST_DATA_BINDING
try {
    $root = [IO.Path]::GetFullPath((Resolve-Path -LiteralPath $PSScriptRoot).ProviderPath).TrimEnd('\', '/')
    $runtime = $null
    if (Set-WaveDeckBindingEnvironment -WaveDeckRoot $root) {
        $pythonExe = Resolve-WaveDeckPython -WaveDeckRoot $root
        $runtime = Get-WaveDeckRuntime -WaveDeckRoot $root -PythonExe $pythonExe
    }
    $watch = [Diagnostics.Stopwatch]::StartNew()
    while ($watch.Elapsed.TotalSeconds -lt 25) {
        $port = Find-WaveDeckService -WaveDeckRoot $root -Runtime $runtime -TimeoutSec (25 - $watch.Elapsed.TotalSeconds)
        if ($null -ne $port) { exit 0 }
        Start-Sleep -Milliseconds 700
    }
    exit 1
} catch {
    Write-Warning "WaveDeck 尚未就緒：$($_.Exception.Message)"
    exit 1
} finally {
    $env:ST_RUNTIME_ROLE = $originalRole
    $env:ST_DATA_BINDING = $originalBinding
}
