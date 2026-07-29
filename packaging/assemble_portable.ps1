[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [string]$ApplicationDirectory = "dist\Scheimpflug-OptiMeter",

    [Parameter(Mandatory = $false)]
    [string]$OutputArchive = "Scheimpflug-OptiMeter-windows-x64.zip"
)

$ErrorActionPreference = "Stop"
$repositoryRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$applicationPath = (Resolve-Path -LiteralPath (Join-Path $repositoryRoot $ApplicationDirectory)).Path
$archivePath = Join-Path $repositoryRoot $OutputArchive

Copy-Item -LiteralPath (Join-Path $repositoryRoot "README.md") -Destination $applicationPath -Force
Copy-Item -LiteralPath (Join-Path $repositoryRoot "LICENSE") -Destination $applicationPath -Force
Copy-Item -LiteralPath (Join-Path $repositoryRoot "CHANGELOG.md") -Destination $applicationPath -Force
Copy-Item -LiteralPath (Join-Path $repositoryRoot "docs") -Destination $applicationPath -Recurse -Force
Copy-Item -LiteralPath (Join-Path $repositoryRoot "examples") -Destination $applicationPath -Recurse -Force

$forbiddenDocuments = Get-ChildItem -LiteralPath $applicationPath -Recurse -File |
    Where-Object { $_.Extension.ToLowerInvariant() -in @(".pdf", ".xls", ".xlsx") }
if ($forbiddenDocuments) {
    $forbiddenPaths = ($forbiddenDocuments.FullName -join [Environment]::NewLine)
    throw "Portable bundle contains forbidden source-document types:$([Environment]::NewLine)$forbiddenPaths"
}

$pypylonFiles = Get-ChildItem -LiteralPath $applicationPath -Recurse -File |
    Where-Object { $_.Name -match "pypylon" }
if ($pypylonFiles) {
    $pypylonPaths = ($pypylonFiles.FullName -join [Environment]::NewLine)
    throw "Standard portable bundle unexpectedly contains pypylon:$([Environment]::NewLine)$pypylonPaths"
}

Compress-Archive -LiteralPath $applicationPath -DestinationPath $archivePath -Force
$archiveHash = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
$checksumPath = "$archivePath.sha256"
"$archiveHash  $(Split-Path -Leaf $archivePath)" |
    Set-Content -LiteralPath $checksumPath -Encoding ascii

Write-Output "Portable archive: $archivePath"
Write-Output "SHA-256: $archiveHash"
