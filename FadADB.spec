# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

import sys
from pathlib import Path

# Set the path to the state file to ensure it's in the same directory as the exe
state_file = 'fadadb_state.json'
icon_file = 'assets/img/FadADB-ico.ico'

a = Analysis(
    ['FadADB.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('assets/img/FadADB-ico.ico', 'assets/img'),
        ('assets/img/FadADB-png.png', 'assets/img'),
    ],  # Bundle icon and screenshots
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='FadADB',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    console=True,
    icon=[icon_file],
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='FadADB'
)
