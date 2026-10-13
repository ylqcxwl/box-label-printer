# -*- coding: utf-8 -*-
"""路径与环境配置。

设计原则：纯绿色、可离线运行。所有数据（SQLite、备份、打印日志）
都放在程序根目录下的 data/ 目录，复制整个文件夹到任何电脑即可直接使用。
"""

import sys
from pathlib import Path


def app_root() -> Path:
    """返回程序根目录（打包后为 exe 所在目录）。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


ROOT: Path = app_root()
DATA_DIR: Path = ROOT / "data"
BACKUP_DIR: Path = DATA_DIR / "backup"
DB_PATH: Path = DATA_DIR / "label_printer.db"
PRINT_LOG: Path = DATA_DIR / "print_log.txt"
# 打印记录单独存放：按年一个库文件，避免单文件过大导致查询卡顿
RECORDS_DIR: Path = DATA_DIR / "records"


def assets_dir() -> Path:
    """返回资源目录（PyInstaller 打包后位于 _MEIPASS 临时目录）。"""
    base = Path(getattr(sys, "_MEIPASS", ROOT))
    return base / "assets"


ASSETS_DIR: Path = assets_dir()
DEFAULT_LOGO: Path = ASSETS_DIR / "logo.png"
CUSTOM_LOGO: Path = DATA_DIR / "custom_logo.png"


def ensure_dirs() -> None:
    """启动时确保数据目录存在。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    RECORDS_DIR.mkdir(parents=True, exist_ok=True)
