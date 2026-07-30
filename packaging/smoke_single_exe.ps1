[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [string]$Executable = "dist\Scheimpflug-OptiMeter.exe",

    [Parameter(Mandatory = $false)]
    [string]$ExecutableArguments = "",

    [Parameter(Mandatory = $false)]
    [ValidateRange(1, 30)]
    [int]$ObservationSeconds = 5
)

$ErrorActionPreference = "Stop"
$resolvedExecutable = (Resolve-Path -LiteralPath $Executable).Path
$workingDirectory = Split-Path -Parent $resolvedExecutable
$applicationProcess = $null
$trackedProcessIds = [Collections.Generic.HashSet[int]]::new()

function Get-ProcessSnapshot {
    return @(
        Get-CimInstance -ClassName Win32_Process |
            Select-Object ProcessId, ParentProcessId, ExecutablePath, Name
    )
}

function Update-TrackedProcessIds {
    param(
        [Parameter(Mandatory = $true)]
        [object[]]$Snapshot
    )

    $snapshotProcessIds = [Collections.Generic.HashSet[int]]::new()
    foreach ($processEntry in $Snapshot) {
        $null = $snapshotProcessIds.Add([int]$processEntry.ProcessId)
    }

    $changed = $true
    while ($changed) {
        $changed = $false
        foreach ($processEntry in $Snapshot) {
            $pidValue = [int]$processEntry.ProcessId
            if ($trackedProcessIds.Contains($pidValue)) {
                continue
            }

            $parentPidValue = [int]$processEntry.ParentProcessId
            $isTrackedDescendant = (
                $trackedProcessIds.Contains($parentPidValue) -and
                $snapshotProcessIds.Contains($parentPidValue)
            )
            if ($isTrackedDescendant) {
                $null = $trackedProcessIds.Add($pidValue)
                $changed = $true
            }
        }
    }
}

function Get-TrackedProcesses {
    param(
        [Parameter(Mandatory = $true)]
        [object[]]$Snapshot
    )

    Update-TrackedProcessIds -Snapshot $Snapshot
    return @(
        $Snapshot |
            Where-Object {
                $trackedProcessIds.Contains([int]$_.ProcessId)
            }
    )
}

function Get-ProcessDepth {
    param(
        [Parameter(Mandatory = $true)]
        [object]$Process,

        [Parameter(Mandatory = $true)]
        [hashtable]$ProcessesById
    )

    $depth = 0
    $parentPidValue = [int]$Process.ParentProcessId
    $visitedIds = [Collections.Generic.HashSet[int]]::new()
    while (
        $trackedProcessIds.Contains($parentPidValue) -and
        $ProcessesById.ContainsKey($parentPidValue) -and
        $visitedIds.Add($parentPidValue)
    ) {
        $depth += 1
        $parentPidValue = [int]$ProcessesById[$parentPidValue].ParentProcessId
    }
    return $depth
}

function Stop-TrackedProcessTree {
    param(
        [Parameter(Mandatory = $true)]
        [object[]]$Snapshot
    )

    $trackedProcesses = @(Get-TrackedProcesses -Snapshot $Snapshot)
    $processesById = @{}
    foreach ($processEntry in $trackedProcesses) {
        $processesById[[int]$processEntry.ProcessId] = $processEntry
    }

    $stopOrder = @(
        $trackedProcesses |
            ForEach-Object {
                [pscustomobject]@{
                    Process = $_
                    Depth = Get-ProcessDepth -Process $_ -ProcessesById $processesById
                }
            } |
            Sort-Object -Property Depth -Descending
    )
    foreach ($target in $stopOrder) {
        $pidValue = [int]$target.Process.ProcessId
        Stop-Process -Id $pidValue -Force -ErrorAction SilentlyContinue
    }
}

try {
    $startParameters = @{
        FilePath = $resolvedExecutable
        WorkingDirectory = $workingDirectory
        WindowStyle = "Hidden"
        PassThru = $true
    }
    if (-not [string]::IsNullOrWhiteSpace($ExecutableArguments)) {
        $startParameters.ArgumentList = $ExecutableArguments
    }
    $applicationProcess = Start-Process @startParameters
    $applicationPid = $applicationProcess.Id
    $null = $trackedProcessIds.Add($applicationPid)

    $observationDeadline = [DateTime]::UtcNow.AddSeconds($ObservationSeconds)
    do {
        Update-TrackedProcessIds -Snapshot @(Get-ProcessSnapshot)
        Start-Sleep -Milliseconds 100
    } while ([DateTime]::UtcNow -lt $observationDeadline)

    $applicationProcess.Refresh()
    if ($applicationProcess.HasExited) {
        throw "Application exited during startup (PID=$applicationPid, exit=$($applicationProcess.ExitCode))."
    }

    Write-Output "Single-file application started successfully (PID=$applicationPid)."
}
finally {
    if ($null -ne $applicationProcess) {
        $cleanupDeadline = [DateTime]::UtcNow.AddSeconds(5)
        do {
            $cleanupSnapshot = @(Get-ProcessSnapshot)
            $remainingProcesses = @(Get-TrackedProcesses -Snapshot $cleanupSnapshot)
            if ($remainingProcesses.Count -eq 0) {
                break
            }
            Stop-TrackedProcessTree -Snapshot $cleanupSnapshot
            Start-Sleep -Milliseconds 100
        } while ([DateTime]::UtcNow -lt $cleanupDeadline)

        $finalSnapshot = @(Get-ProcessSnapshot)
        $remainingProcesses = @(Get-TrackedProcesses -Snapshot $finalSnapshot)
        if ($remainingProcesses.Count -gt 0) {
            $remainingSummary = (
                $remainingProcesses |
                    ForEach-Object {
                        "PID=$($_.ProcessId), name=$($_.Name), path=$($_.ExecutablePath)"
                    }
            ) -join "; "
            throw "Executable smoke-test process tree is still running: $remainingSummary"
        }

        Write-Output (
            "Stopped executable smoke-test process tree " +
            "(root PID=$($applicationProcess.Id), tracked=$($trackedProcessIds.Count))."
        )
    }
}
