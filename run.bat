@echo off
REM Run from source (no packaging needed)
cd /d %~dp0

REM Qt5 plugin loader cannot handle non-ASCII paths; use ASCII copy if present
if exist "C:\wbqt\plugins\platforms\qwindows.dll" set QT_QPA_PLATFORM_PLUGIN_PATH=C:\wbqt\plugins\platforms

set PY=E:\ÎÄ¼þ¼Ð\WorkBuddy\.workbuddy\binaries\python\envs\default\Scripts\python.exe
if not exist "%PY%" set PY=python

"%PY%" app\main.py
