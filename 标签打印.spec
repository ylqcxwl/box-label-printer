# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置（onedir + contents_directory）。

目录结构（★ 需求：根目录只留启动文件与 data/，其余全部归到单独文件夹）：

    标签打印/
    ├── 标签打印.exe        # 唯一的程序启动文件
    ├── data/               # 用户数据（模板、数据库、备份、记录）
    └── runtime/            # 所有依赖：DLL/PYD/Qt 插件/assets 图标

★ 为什么必须用 PyInstaller 6.x：
  5.x 的 bootloader 只会在 exe 同目录查找 DLL，硬把文件挪进子目录会
  导致程序打不开。6.x 引入 contents_directory，bootloader 会正确地把
  依赖目录加入搜索路径，且 sys._MEIPASS 指向该子目录。
"""

import struct

from PyInstaller.utils.hooks import collect_submodules

# 目标架构跟随所用解释器：32 位 Python -> x86（Win7 兼容），
# 64 位 Python -> 自动（x86_64）。这样同一份 spec 在 CI（x86）与本地（x64）都能用。
TARGET_ARCH = 'x86' if struct.calcsize('P') * 8 == 32 else None

# 依赖与资源统一放在这个文件夹里，保持程序根目录整洁
CONTENTS_DIR = 'runtime'

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
    # 只带真正的运行资源：源图和运行时生成的箭头都不必进包
    datas=[('assets/logo.png', 'assets'), ('assets/logo.ico', 'assets')],
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
    noarchive=False,
)

pyz = PYZ(a.pure)

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
    contents_directory=CONTENTS_DIR,
    icon='assets/logo.ico',
    version='file_version_info.txt',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='标签打印',
)
