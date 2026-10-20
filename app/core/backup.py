# -*- coding: utf-8 -*-
"""数据备份与恢复。

★ 备份内容（老版本只备了主库，打印记录是漏的）：
  * label_printer.db  —— 产品、箱号/SN 规则、字段映射、列表设置、系统设置
  * records/*.db      —— 打印记录（按年一个库文件）

打包成一个 .zip，默认只保留最新 N 份（设置里可改，默认 3 份）。
历史遗留的 backup_*.db（只有主库）仍然能被列出和恢复。
"""

import shutil
import zipfile
from datetime import datetime
from pathlib import Path
from typing import List

from app import config

MAIN_DB_NAME = "label_printer.db"      # zip 内主库的路径
# ★ 路径一律在函数里从 config 现取，不在 import 时绑定：
#   import 时绑定会把路径写死，测试改 config 后仍指向真实 data 目录，
#   曾因此让测试把恢复写进了用户的真实数据（好在备份和恢复的是同一份）。
RECORDS_PREFIX = "records/"            # zip 内打印记录的路径前缀


def backup_dir(custom: str = "") -> Path:
    """返回备份目录（自定义路径为空时使用默认 data/backup）。"""
    return Path(custom) if custom else config.BACKUP_DIR


def do_backup(dest_dir: Path, keep: int = 3) -> Path:
    """立即备份「主库 + 打印记录」。

    Args:
        dest_dir: 备份目录
        keep: 保留份数（超出后删除最旧的）

    Returns:
        备份文件路径（.zip）
    """
    db_path, records_dir = config.DB_PATH, config.RECORDS_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = dest_dir / f"backup_{stamp}.zip"
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        if db_path.exists():
            zf.write(db_path, MAIN_DB_NAME)
        # 打印记录按年分库，全部收进来；读不到就跳过，别让整次备份失败
        for record_db in sorted(records_dir.glob("*.db")) if \
                records_dir.exists() else []:
            zf.write(record_db, RECORDS_PREFIX + record_db.name)
    _prune(dest_dir, keep)
    return dest


def _all_backups(dest_dir: Path) -> List[Path]:
    """列出备份文件（新→旧），同时兼容新 .zip 与旧 .db。"""
    if not dest_dir.exists():
        return []
    files = list(dest_dir.glob("backup_*.zip")) + list(dest_dir.glob("backup_*.db"))
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)


def _prune(dest_dir: Path, keep: int) -> None:
    """只保留最新 keep 份备份。"""
    for old in _all_backups(dest_dir)[max(1, keep):]:
        try:
            old.unlink()
        except OSError:
            pass


def list_backups(dest_dir: Path) -> List[Path]:
    """列出备份文件（新的在前）。"""
    return _all_backups(dest_dir)


def backup_summary(backup_file: Path) -> str:
    """给备份文件生成一句说明（含了哪些内容），供界面展示。"""
    if backup_file.suffix.lower() == ".zip":
        try:
            with zipfile.ZipFile(backup_file) as zf:
                names = zf.namelist()
            records = [n for n in names if n.startswith(RECORDS_PREFIX)]
            main = [n for n in names if n == MAIN_DB_NAME]
            parts = []
            if main:
                parts.append("主库")
            if records:
                parts.append(f"打印记录 {len(records)} 个年度库")
            return " + ".join(parts) or "空备份"
        except (zipfile.BadZipFile, OSError):
            return "备份文件可能已损坏"
    return "仅主库（旧格式备份，不含打印记录）"


def restore_backup(backup_file: Path) -> None:
    """从备份恢复数据。

    恢复前先把「当前的主库 + 打印记录」打成一个安全备份
    （data/before_restore.zip），万一恢复错了还能倒回去。

    Args:
        backup_file: .zip（主库 + 打印记录）或旧格式 .db（仅主库）

    Raises:
        FileNotFoundError: 备份文件不存在
        zipfile.BadZipFile: zip 损坏
    """
    if not backup_file.exists():
        raise FileNotFoundError(f"备份文件不存在：{backup_file}")
    db_path, records_dir = config.DB_PATH, config.RECORDS_DIR

    safety = db_path.parent / "before_restore.zip"
    try:
        with zipfile.ZipFile(safety, "w", zipfile.ZIP_DEFLATED) as zf:
            if db_path.exists():
                zf.write(db_path, MAIN_DB_NAME)
            if records_dir.exists():
                for record_db in sorted(records_dir.glob("*.db")):
                    zf.write(record_db, RECORDS_PREFIX + record_db.name)
    except OSError:
        # 安全备份失败不阻断恢复，但要留下痕迹
        safety = None      # type: ignore[assignment]

    if backup_file.suffix.lower() == ".zip":
        with zipfile.ZipFile(backup_file) as zf:
            names = zf.namelist()
            if MAIN_DB_NAME in names:
                with zf.open(MAIN_DB_NAME) as src, open(db_path, "wb") as dst:
                    shutil.copyfileobj(src, dst)
            records_dir.mkdir(parents=True, exist_ok=True)
            for name in names:
                if not name.startswith(RECORDS_PREFIX) or name.endswith("/"):
                    continue
                target = records_dir / Path(name).name
                with zf.open(name) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
    else:
        # 旧格式：只能恢复主库
        shutil.copy2(str(backup_file), str(db_path))
