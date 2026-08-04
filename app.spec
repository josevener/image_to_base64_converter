# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build specification for Developer Toolbox."""

from PyInstaller.utils.hooks import collect_data_files


assets = collect_data_files("PIL")

analysis = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[("assets", "assets"), *assets],
    hiddenimports=["PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(analysis.pure)

executable = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="DeveloperToolbox",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon="assets/icon.ico",
)

bundle = COLLECT(
    executable,
    analysis.binaries,
    analysis.zipfiles,
    analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="DeveloperToolbox",
)
