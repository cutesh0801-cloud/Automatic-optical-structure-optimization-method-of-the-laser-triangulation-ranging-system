# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, copy_metadata


project_root = Path(SPECPATH).resolve().parent
datas = collect_data_files("scheimpflug_optimeter")
datas += copy_metadata("scheimpflug-optimeter")
application_icon = (
    project_root / "src" / "scheimpflug_optimeter" / "assets" / "app_icon.ico"
)

a = Analysis(
    [str(project_root / "src" / "scheimpflug_optimeter" / "__main__.py")],
    pathex=[str(project_root / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "matplotlib.backends.backend_qtagg",
        "scipy.optimize",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

# The public executable must never carry the locally supplied papers or workbook.
# Matplotlib also ships unused PDF toolbar artwork, so removing all document-like
# data files gives the release artifact a simple, auditable rule.
private_source_suffixes = {".pdf", ".xls", ".xlsx"}
a.datas = [
    entry for entry in a.datas if Path(entry[0]).suffix.lower() not in private_source_suffixes
]

pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Scheimpflug-OptiMeter",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(application_icon),
)
