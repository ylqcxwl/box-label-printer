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
# 模板（.btw）默认放在程序根目录下的 templates；
# 设置页留空即用这里，用户也可以改成自己的网络盘目录
TEMPLATES_DIR: Path = ROOT / "templates"


def resolve_template_dir(setting: str = "") -> Path:
    """确定模板目录：设置里填了就用它，否则用程序根目录下的 templates。

    Args:
        setting: 设置页「模板文件夹」里填的路径，可为空

    Returns:
        模板目录（不保证已存在，由调用方按需创建）
    """
    text = (setting or "").strip()
    return Path(text) if text else TEMPLATES_DIR


def assets_dir() -> Path:
    """返回资源目录（PyInstaller 打包后位于 _MEIPASS 临时目录）。"""
    base = Path(getattr(sys, "_MEIPASS", ROOT))
    return base / "assets"


ASSETS_DIR: Path = assets_dir()
DEFAULT_LOGO: Path = ASSETS_DIR / "logo.png"
CUSTOM_LOGO: Path = DATA_DIR / "custom_logo.png"


def ensure_dirs() -> None:
    """启动时确保数据目录与模板目录存在。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    RECORDS_DIR.mkdir(parents=True, exist_ok=True)
    # 模板目录也一并建出来：用户第一次打开设置就知道 .btw 该放哪
    try:
        TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass       # 只读盘等异常不影响程序启动
