import base64
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RELEASE_EXECUTABLE = "Scheimpflug-OptiMeter-windows-x64.exe"
RELEASE_CHECKSUM = f"{RELEASE_EXECUTABLE}.sha256"


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def _encoded_powershell(script: str) -> str:
    return base64.b64encode(script.encode("utf-16-le")).decode("ascii")


def _windows_process_exists(powershell: Path, process_id: int) -> bool:
    result = subprocess.run(
        [
            str(powershell),
            "-NoProfile",
            "-Command",
            (
                f"if ($null -eq (Get-Process -Id {process_id} "
                "-ErrorAction SilentlyContinue)) { exit 1 }"
            ),
        ],
        check=False,
        capture_output=True,
    )
    return result.returncode == 0


def _stop_windows_process(powershell: Path, process_id: int) -> None:
    subprocess.run(
        [
            str(powershell),
            "-NoProfile",
            "-Command",
            f"Stop-Process -Id {process_id} -Force -ErrorAction SilentlyContinue",
        ],
        check=False,
        capture_output=True,
    )


def test_pyinstaller_spec_builds_one_file_executable():
    spec = _read("packaging/scheimpflug_optimeter.spec")

    assert "a.binaries" in spec
    assert "a.datas" in spec
    assert "COLLECT(" not in spec
    assert "exclude_binaries=True" not in spec


def test_packaging_scripts_use_single_file_build_output():
    smoke_script = _read("packaging/smoke_single_exe.ps1")
    assembly_script = _read("packaging/assemble_single_exe.ps1")

    assert r'dist\Scheimpflug-OptiMeter.exe"' in smoke_script
    assert "Get-CimInstance -ClassName Win32_Process" in smoke_script
    assert "ParentProcessId" in smoke_script
    assert "$trackedProcessIds.Contains($parentPidValue)" in smoke_script
    assert "$snapshotProcessIds.Contains($parentPidValue)" in smoke_script
    assert "$isNewSameExecutable" not in smoke_script
    assert "Test-SameExecutable" not in smoke_script
    assert "$baselineExecutableProcessIds" not in smoke_script
    assert "[DateTime]::UtcNow.AddSeconds(5)" in smoke_script
    assert "Stop-Process -Id $pidValue" in smoke_script
    assert "Stop-Process -Name" not in smoke_script
    assert "taskkill" not in smoke_script.lower()
    assert r'dist\Scheimpflug-OptiMeter.exe"' in assembly_script
    assert f'"{RELEASE_EXECUTABLE}"' in assembly_script
    assert "Get-FileHash" in assembly_script
    assert "Compress-Archive" not in assembly_script


@pytest.mark.skipif(sys.platform != "win32", reason="Windows process-tree contract")
def test_smoke_cleans_descendants_but_preserves_concurrent_same_path_process(tmp_path):
    powershell = (
        Path(os.environ["SYSTEMROOT"])
        / "System32"
        / "WindowsPowerShell"
        / "v1.0"
        / "powershell.exe"
    )
    smoke_script = ROOT / "packaging" / "smoke_single_exe.ps1"
    process_ids_path = tmp_path / "smoke-process-ids.txt"
    escaped_ids_path = str(process_ids_path).replace("'", "''")
    escaped_powershell_path = str(powershell).replace("'", "''")
    sleeper_command = _encoded_powershell("Start-Sleep -Seconds 30")
    launcher_command = _encoded_powershell(
        "\n".join(
            (
                "$child = Start-Process "
                f"-FilePath '{escaped_powershell_path}' "
                f"-ArgumentList '-NoProfile -EncodedCommand {sleeper_command}' "
                "-WindowStyle Hidden -PassThru",
                f"Set-Content -LiteralPath '{escaped_ids_path}' "
                '-Value "$PID`n$($child.Id)" -Encoding ascii',
                "Start-Sleep -Seconds 30",
            )
        )
    )

    smoke_process = None
    unrelated_process = None
    launched_process_ids: list[int] = []
    try:
        smoke_process = subprocess.Popen(
            [
                str(powershell),
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(smoke_script),
                "-Executable",
                str(powershell),
                "-ExecutableArguments",
                f"-NoProfile -EncodedCommand {launcher_command}",
                "-ObservationSeconds",
                "2",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if process_ids_path.exists():
                launched_process_ids = [
                    int(value)
                    for value in process_ids_path.read_text(encoding="ascii").splitlines()
                    if value
                ]
                if len(launched_process_ids) == 2:
                    break
            if smoke_process.poll() is not None:
                break
            time.sleep(0.05)
        assert len(launched_process_ids) == 2

        unrelated_process = subprocess.Popen(
            [
                str(powershell),
                "-NoProfile",
                "-EncodedCommand",
                sleeper_command,
            ]
        )
        stdout, stderr = smoke_process.communicate(timeout=15)

        assert smoke_process.returncode == 0, f"{stdout}\n{stderr}"
        assert "tracked=" in stdout
        assert unrelated_process.poll() is None
        assert all(
            not _windows_process_exists(powershell, process_id)
            for process_id in launched_process_ids
        )
    finally:
        if smoke_process is not None and smoke_process.poll() is None:
            smoke_process.terminate()
            smoke_process.wait(timeout=5)
        if unrelated_process is not None and unrelated_process.poll() is None:
            unrelated_process.terminate()
            unrelated_process.wait(timeout=5)
        for process_id in launched_process_ids:
            _stop_windows_process(powershell, process_id)


def test_ci_and_release_publish_only_stable_executable_assets():
    ci_workflow = _read(".github/workflows/ci.yml")
    release_workflow = _read(".github/workflows/release.yml")

    for workflow in (ci_workflow, release_workflow):
        assert RELEASE_EXECUTABLE in workflow
        assert RELEASE_CHECKSUM in workflow
        assert "Scheimpflug-OptiMeter-windows-x64.zip" not in workflow
        assert "packaging/assemble_single_exe.ps1" in workflow

    assert 'git show-ref --verify --quiet "refs/tags/$tag"' in release_workflow
    assert "Refusing to overwrite existing remote tag" in release_workflow
    assert "Refusing to overwrite existing GitHub release" in release_workflow
    assert "--clobber" not in release_workflow


def test_release_policy_names_the_executable_assets():
    release_policy = _read("docs/release-policy.md")

    assert f"`{RELEASE_EXECUTABLE}`" in release_policy
    assert f"`{RELEASE_CHECKSUM}`" in release_policy
    assert "`Scheimpflug-OptiMeter-windows-x64.zip`" not in release_policy
