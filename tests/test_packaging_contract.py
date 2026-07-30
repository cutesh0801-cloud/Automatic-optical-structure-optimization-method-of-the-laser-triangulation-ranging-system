from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELEASE_EXECUTABLE = "Scheimpflug-OptiMeter-windows-x64.exe"
RELEASE_CHECKSUM = f"{RELEASE_EXECUTABLE}.sha256"


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


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
    assert "$baselineExecutableProcessIds" in smoke_script
    assert "ParentProcessId" in smoke_script
    assert "Test-SameExecutable" in smoke_script
    assert "[DateTime]::UtcNow.AddSeconds(5)" in smoke_script
    assert "Stop-Process -Id $pidValue" in smoke_script
    assert "Stop-Process -Name" not in smoke_script
    assert "taskkill" not in smoke_script.lower()
    assert r'dist\Scheimpflug-OptiMeter.exe"' in assembly_script
    assert f'"{RELEASE_EXECUTABLE}"' in assembly_script
    assert "Get-FileHash" in assembly_script
    assert "Compress-Archive" not in assembly_script


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
