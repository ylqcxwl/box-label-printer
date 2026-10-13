# -*- coding: utf-8 -*-
"""数据备份与恢复。

备份内容 = 整个 data 数据库文件（label_printer.db），
默认只保留最新 N 份（可在设置中修改，默认 3 份）。
"""

import shutil
from datetime import datetime
from pathlib import Path
from typing import List

from app.config import BACKUP_DIR, DB_PATH


def backup_dir(custom: str = "") -> Path:
    """返回备份目录（自定义路径为空时使用默认 data/backup）。"""
    return Path(custom) if custom else BACKUP_DIR


def do_backup(dest_dir: Path, keep: int = 3) -> Path:
    """立即备份数据库。

    Args:
        dest_dir: 备份目录
        keep: 保留份数（超出后删除最旧的）

    Returns:
        备份文件路径
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = dest_dir / f"backup_{stamp}.db"
    shutil.copy2(str(DB_PATH), str(dest))
    _prune(dest_dir, keep)
    return dest


def _prune(dest_dir: Path, keep: int) -> None:
    """只保留最新 keep 份备份。"""
    backups = sorted(dest_dir.glob("backup_*.db"),
                     key=lambda p: p.stat().st_mtime, reverse=True)
    for old in backups[max(1, keep):]:
        try:
            old.unlink()
        except OSError:
            pass


def list_backups(dest_dir: Path) -> List[Path]:
    """列出备份文件（新的在前）。"""
    if not dest_dir.exists():
        return []
    return sorted(dest_dir.glob("backup_*.db"),
                  key=lambda p: p.stat().st_mtime, reverse=True)


def restore_backup(backup_file: Path) -> None:
    """从备份恢复数据库（恢复前自动对当前库做一次安全备份）。"""
    if not backup_file.exists():
        raise FileNotFoundError(f"备份文件不存在：{backup_file}")
    safety = DB_PATH.with_suffix(".before_restore.db")
    if DB_PATH.exists():
        shutil.copy2(str(DB_PATH), str(safety))
    shutil.copy2(str(backup_file), str(DB_PATH))
