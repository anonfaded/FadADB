# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

import sys
import os
from pathlib import Path

# Set the path to the state file to ensure it's in the same directory as the exe
state_file = 'fadadb_state.json'
icon_file = 'assets/img/FadADB-ico.ico'

# Function to collect all files in a directory
def collect_files_recursive(directory, dest_dir):
    files_list = []
    for root, dirs, files in os.walk(directory):
        for file in files:
            source_path = os.path.join(root, file)
            rel_path = os.path.relpath(source_path, start=directory)
            dest_path = os.path.join(dest_dir, rel_path)
            dest_dir_name = os.path.dirname(dest_path)
            files_list.append((source_path, dest_dir_name))
    return files_list

# Collect ADB binaries
adb_data = collect_files_recursive('assets/adb', 'assets/adb')

a = Analysis(
    ['FadADB.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('assets/img/FadADB-ico.ico', 'assets/img'),
        ('assets/img/FadADB-png.png', 'assets/img'),
    ] + adb_data,  # Bundle icon, screenshots, and ADB binaries
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
