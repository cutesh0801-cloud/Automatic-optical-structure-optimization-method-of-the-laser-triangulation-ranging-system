[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [string]$Executable = "dist\Scheimpflug-OptiMeter\Scheimpflug-OptiMeter.exe",

    [Parameter(Mandatory = $false)]
    [ValidateRange(1, 30)]
    [int]$ObservationSeconds = 5
)

$ErrorActionPreference = "Stop"
$resolvedExecutable = (Resolve-Path -LiteralPath $Executable).Path
$workingDirectory = Split-Path -Parent $resolvedExecutable
$portableProcess = $null

try {
    $portableProcess = Start-Process `
        -FilePath $resolvedExecutable `
        -WorkingDirectory $workingDirectory `
        -WindowStyle Hidden `
        -PassThru
    $portablePid = $portableProcess.Id

    Start-Sleep -Seconds $ObservationSeconds
    $portableProcess.Refresh()
    if ($portableProcess.HasExited) {
        throw "Portable application exited during startup (PID=$portablePid, exit=$($portableProcess.ExitCode))."
    }

    Write-Output "Portable application started successfully (PID=$portablePid)."
}
finally {
    if ($null -ne $portableProcess) {
        $portablePid = $portableProcess.Id
        $exactProcess = Get-Process -Id $portablePid -ErrorAction SilentlyContinue
        if ($null -ne $exactProcess) {
            Stop-Process -Id $portablePid
            $null = $exactProcess.WaitForExit(5000)
            Write-Output "Stopped portable smoke-test process (PID=$portablePid)."
        }

        if ($null -ne (Get-Process -Id $portablePid -ErrorAction SilentlyContinue)) {
            throw "Portable smoke-test process is still running (PID=$portablePid)."
        }
    }
}
