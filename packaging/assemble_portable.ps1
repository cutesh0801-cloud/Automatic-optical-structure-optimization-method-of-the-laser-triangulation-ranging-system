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

$versionLine = Select-String `
    -LiteralPath (Join-Path $repositoryRoot "pyproject.toml") `
    -Pattern '^version\s*=\s*"([^"]+)"\s*$' |
    Select-Object -First 1
if ($null -eq $versionLine) {
    throw "Could not resolve project.version from pyproject.toml."
}
$applicationVersion = $versionLine.Matches[0].Groups[1].Value
$gitCommit = (& git -C $repositoryRoot rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($gitCommit)) {
    throw "Could not resolve the source commit for build-info.json."
}
$releaseTag = $env:SCHEIMPFLUG_RELEASE_TAG
if ([string]::IsNullOrWhiteSpace($releaseTag)) {
    $releaseTag = "local"
}
$buildInfo = [ordered]@{
    schema_version      = 1
    application_version = $applicationVersion
    release_tag         = $releaseTag
    git_commit          = $gitCommit
}
$buildInfo |
    ConvertTo-Json |
    Set-Content -LiteralPath (Join-Path $applicationPath "build-info.json") -Encoding utf8

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

Compress-Archive -LiteralPath $applicationPath -DestinationPath $archivePath -Force
$archiveHash = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
$checksumPath = "$archivePath.sha256"
"$archiveHash  $(Split-Path -Leaf $archivePath)" |
    Set-Content -LiteralPath $checksumPath -Encoding ascii

Write-Output "Portable archive: $archivePath"
Write-Output "SHA-256: $archiveHash"
