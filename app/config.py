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
# 模板（.btw）默认放在 data 目录下的 templates：
# 与数据库、备份、打印记录归到一起，整个 data 拷走就是完整的一套。
# 设置页留空即用这里，用户也可以改成自己的网络盘目录
TEMPLATES_DIR: Path = DATA_DIR / "templates"


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
    """返回只读资源目录（打包后为 contents_directory 里的 assets）。

    PyInstaller 6.x 用 contents_directory='runtime' 时，sys._MEIPASS
    指向 <程序根目录>/runtime，所以 assets 会落在 runtime/assets，
    正好满足「根目录只保留 exe + data + 一个文件夹」的要求。
    """
    base = Path(getattr(sys, "_MEIPASS", ROOT))
    return base / "assets"


ASSETS_DIR: Path = assets_dir()
DEFAULT_LOGO: Path = ASSETS_DIR / "logo.png"
CUSTOM_LOGO: Path = DATA_DIR / "custom_logo.png"

# 运行时「生成」的图片（下拉/微调框箭头）放到 data/assets。
# ★ 不能放程序根目录：根目录约定只保留 启动文件 + data/ + runtime/，
#   在根目录再建 assets/ 会破坏这个结构。
# 与 ASSETS_DIR 区分：ASSETS_DIR 打包后指向 runtime/assets（随包资源），
# 这里是用户数据目录，永远可写。
ASSETS_WRITE_DIR: Path = DATA_DIR / "assets"


def ensure_dirs() -> None:
    """启动时确保数据目录与模板目录存在。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    RECORDS_DIR.mkdir(parents=True, exist_ok=True)
    # 模板目录也一并建出来：用户第一次打开设置就知道 .btw 该放哪
    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
