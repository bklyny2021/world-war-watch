# -*- mode: python ; coding: utf-8 -*-
# World War Watch v2.3.1 — PyInstaller spec
# collect_submodules('uvicorn') + collect_submodules('anyio') fixes the
# frozen EXE crashes:
#   ModuleNotFoundError: No module named 'uvicorn.loops.auto'
#   ModuleNotFoundError: No module named 'anyio._backends'
# (uvicorn 0.41 / anyio import submodules dynamically via importlib.)
from PyInstaller.utils.hooks import collect_submodules

a = Analysis(
    ['server.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('data/aircraftDatabase.csv', 'data'),
        ('data/airports.dat', 'data'),
        ('data/labels_10m.json', 'data'),
        ('static', 'static'),
    ],
    hiddenimports=collect_submodules('uvicorn') + collect_submodules('anyio'),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='WorldWarWatch_v2_3_1',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    icon='WorldView.ico',
)
