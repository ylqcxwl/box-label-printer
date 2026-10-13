# -*- coding: utf-8 -*-
"""生成 run.bat（GBK + CRLF，cmd 兼容）。"""

LINES = [
    "@echo off",
    "REM Run from source (no packaging needed)",
    "cd /d %~dp0",
    "",
    "REM Qt5 plugin loader cannot handle non-ASCII paths; use ASCII copy if present",
    'if exist "C:\\wbqt\\plugins\\platforms\\qwindows.dll" set QT_QPA_PLATFORM_PLUGIN_PATH=C:\\wbqt\\plugins\\platforms',
    "",
    "set PY=E:\\文件夹\\WorkBuddy\\.workbuddy\\binaries\\python\\envs\\default\\Scripts\\python.exe",
    'if not exist "%PY%" set PY=python',
    "",
    '"%PY%" app\\main.py',
    "",
]

with open("run.bat", "wb") as f:
    f.write("\r\n".join(LINES).encode("gbk"))
print("run.bat written (GBK + CRLF)")
