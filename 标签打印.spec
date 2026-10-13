# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置（onedir 模式：启动快、允许多文件、纯绿色）。

打包产物：dist/标签打印/标签打印.exe（整个目录复制到任何电脑即可运行）
"""

import struct

from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

# 目标架构跟随所用解释器：32 位 Python -> x86（Win7 兼容），
# 64 位 Python -> 自动（x86_64）。这样同一份 spec 在 CI（x86）与本地（x64）都能用。
TARGET_ARCH = 'x86' if struct.calcsize('P') * 8 == 32 else None

hiddenimports = (
    collect_submodules('win32com') + [
        'win32com.client',
        'pythoncom',
        'pywintypes',
        'win32timezone',
        'win32print',
        'openpyxl',
    ]
)

a = Analysis(
    ['app/main.py'],
    pathex=[],
    binaries=[],
    datas=[('assets', 'assets')],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 精简体积、加快启动：排除不需要的大型库
        'PyQt5.QtWebEngine', 'PyQt5.QtWebEngineWidgets', 'PyQt5.QtWebEngineCore',
        'PyQt5.QtBluetooth', 'PyQt5.QtMultimedia', 'PyQt5.QtMultimediaWidgets',
        'PyQt5.QtNetwork', 'PyQt5.QtQml', 'PyQt5.QtQuick', 'PyQt5.QtQuickWidgets',
        'PyQt5.QtSql', 'PyQt5.QtTest', 'PyQt5.QtXml', 'PyQt5.Qt3DCore',
        'tkinter', 'numpy', 'pandas', 'matplotlib',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='标签打印',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,               # 不用 UPX：避免杀软误报，保证稳定性
    console=False,           # 无控制台窗口
    disable_windowed_traceback=False,
    target_arch=TARGET_ARCH,  # 解释器是 32 位 -> x86（Win7 兼容）；64 位 -> 跟随
    icon='assets/logo.ico',
    version='file_version_info.txt',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='标签打印',
)
