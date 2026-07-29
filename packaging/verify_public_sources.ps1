[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$repositoryRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$trackedPrivateSources = @(
    git -C $repositoryRoot ls-files -- `
        ":(icase)*.pdf" `
        ":(icase)*.xls" `
        ":(icase)*.xlsx" `
        ":(icase)sources/**"
)
if ($LASTEXITCODE -ne 0) {
    throw "Unable to audit tracked files with git ls-files."
}
if ($trackedPrivateSources.Count -gt 0) {
    $trackedPaths = ($trackedPrivateSources -join [Environment]::NewLine)
    throw "Private source documents are tracked:$([Environment]::NewLine)$trackedPaths"
}

Write-Output "No PDF, XLS/XLSX, or sources/ files are tracked."
