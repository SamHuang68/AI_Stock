# Parse the actual files without invoking launchers, reports or cleanup actions.
# Run in both Windows PowerShell 5.1 and PowerShell 7: their default encodings differ.
param([string]$RepoRoot = (Split-Path $PSScriptRoot -Parent))

$ErrorActionPreference = 'Stop'
$entryRoots = @('scripts', 'research', 'wavedeck') | ForEach-Object {
    Join-Path $RepoRoot $_
}
$files = @(Get-ChildItem -LiteralPath $entryRoots -Filter '*.ps1' -File -Recurse |
    Sort-Object FullName)
if ($files.Count -eq 0) { throw 'No application PowerShell entrypoints found.' }

$failed = 0
foreach ($file in $files) {
    $tokens = $null
    $parseErrors = $null
    [System.Management.Automation.Language.Parser]::ParseFile(
        $file.FullName, [ref]$tokens, [ref]$parseErrors) | Out-Null
    if ($parseErrors.Count) {
        $failed++
        foreach ($parseError in $parseErrors) {
            Write-Output ('{0}:{1}: {2}: {3}' -f $file.FullName,
                $parseError.Extent.StartLineNumber, $parseError.ErrorId, $parseError.Message)
        }
    }
}
if ($failed) { throw ('PowerShell syntax failed for {0} entrypoint(s).' -f $failed) }
Write-Output ('Parsed {0} entrypoints with PowerShell {1}.' -f $files.Count, $PSVersionTable.PSVersion)
