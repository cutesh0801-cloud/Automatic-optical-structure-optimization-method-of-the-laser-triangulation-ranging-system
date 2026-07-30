[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [string]$BuiltExecutable = "dist\Scheimpflug-OptiMeter.exe",

    [Parameter(Mandatory = $false)]
    [string]$OutputExecutable = "Scheimpflug-OptiMeter-windows-x64.exe"
)

$ErrorActionPreference = "Stop"
$repositoryRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$builtExecutablePath = (
    Resolve-Path -LiteralPath (Join-Path $repositoryRoot $BuiltExecutable)
).Path
$outputExecutablePath = [IO.Path]::GetFullPath(
    (Join-Path $repositoryRoot $OutputExecutable)
)

if (
    [string]::Equals(
        $builtExecutablePath,
        $outputExecutablePath,
        [StringComparison]::OrdinalIgnoreCase
    )
) {
    throw "The built executable and release executable paths must be different."
}
if ([IO.Path]::GetExtension($outputExecutablePath) -cne ".exe") {
    throw "The release asset must use the .exe extension."
}

Copy-Item -LiteralPath $builtExecutablePath -Destination $outputExecutablePath -Force

$executableHash = (
    Get-FileHash -LiteralPath $outputExecutablePath -Algorithm SHA256
).Hash.ToLowerInvariant()
$checksumPath = "$outputExecutablePath.sha256"
"$executableHash  $(Split-Path -Leaf $outputExecutablePath)" |
    Set-Content -LiteralPath $checksumPath -Encoding ascii

Write-Output "Windows executable: $outputExecutablePath"
Write-Output "SHA-256: $executableHash"
