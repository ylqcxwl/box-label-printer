# -*- coding: utf-8 -*-
"""软件更新检查与下载（基于 GitHub Releases，可完全关闭，不影响离线使用）。"""

import json
import urllib.request
from pathlib import Path
from typing import Callable, Optional

from app.version import VERSION

UA = {"User-Agent": "label-printer-updater"}


def normalize_repo(text: str) -> str:
    """把仓库地址规范为 owner/repo（支持粘贴完整 GitHub 地址）。"""
    text = text.strip().rstrip("/")
    for prefix in ("https://github.com/", "http://github.com/", "github.com/"):
        if text.startswith(prefix):
            text = text[len(prefix):]
            break
    return text


def parse_version(text: str) -> tuple:
    """'v1.2.3' / '1.2.3' -> (1, 2, 3)"""
    parts = []
    for piece in text.lstrip("vV").split("."):
        num = "".join(ch for ch in piece if ch.isdigit())
        parts.append(int(num) if num else 0)
    return tuple(parts)


def check_latest(repo: str) -> Optional[dict]:
    """检查最新版本。

    Args:
        repo: owner/repo 或完整 GitHub 地址（可空，空则返回 None）

    Returns:
        {"version": str, "url": str, "notes": str}；无更新或失败返回 None
    """
    repo = normalize_repo(repo)
    if not repo:
        return None
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=8) as resp:
            info = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None
    latest = info.get("tag_name", "")
    if not latest or parse_version(latest) <= parse_version(VERSION):
        return None
    asset_url = ""
    for asset in info.get("assets", []):
        if asset.get("name", "").endswith(".zip"):
            asset_url = asset.get("browser_download_url", "")
            break
    return {"version": latest, "url": asset_url,
            "notes": info.get("body", "")}


def download_asset(url: str, dest: Path,
                   progress: Optional[Callable[[int], None]] = None) -> Path:
    """下载更新包到本地。

    Args:
        url: 更新包下载地址
        dest: 保存路径
        progress: 进度回调（0-100）

    Returns:
        下载完成的文件路径
    """
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as resp:
        total = int(resp.headers.get("Content-Length", 0))
        done = 0
        with open(dest, "wb") as f:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if progress and total:
                    progress(min(100, int(done * 100 / total)))
    return dest
