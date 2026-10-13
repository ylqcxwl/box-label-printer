@echo off
chcp 65001 >nul
REM ============================================
REM  本地一键打包脚本（需要 Python 3.8.10 x86）
REM ============================================
cd /d %~dp0

echo [1/3] 安装依赖...
pip install -r requirements.txt || goto :error

echo [2/3] 生成图标...
python tools\make_icons.py || goto :error

echo [3/3] PyInstaller 打包...
pyinstaller --clean --noconfirm 标签打印.spec || goto :error

echo.
echo ============================================
echo  打包完成：dist\标签打印\标签打印.exe
echo ============================================
pause
exit /b 0

:error
echo.
echo 打包失败，请检查上方错误信息。
pause
exit /b 1
