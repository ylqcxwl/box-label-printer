# -*- coding: utf-8 -*-
"""软件更新检查与下载（基于 GitHub Releases，可完全关闭，不影响离线使用）。"""

import json
import urllib.error
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


def check_latest(repo: str, token: str = "") -> dict:
    """检查最新版本，返回**结构化结果**（不再用 None 混淆“没更新”和“查不到”）。

    ★ 两个原来导致「永远查不到更新」的坑：
      1. `/releases/latest` **不返回预发布版（prerelease）**。
         本项目的发布全是测试版预发布，所以永远查不到。
         → 改为读 `/releases` 列表，自己按版本号取最大。
      2. 仓库私有时匿名请求一律 404，和「仓库不存在」无法区分，
         界面只能静默当作“无更新”。
         → 区分状态码给出明确提示，并支持传入访问令牌。

    Args:
        repo: owner/repo 或完整 GitHub 地址
        token: 可选 GitHub 访问令牌（私有仓库必须）；只用于本次请求

    Returns:
        {"status": "update"|"none"|"error"|"skip",
         "version": 最新版本号（可能为空串）,
         "url": 下载地址（zip 优先）,
         "notes": 发布说明,
         "message": 给用户看的一句话,
         "need_token": 是否需要（重新）填写访问令牌}
    """
    repo = normalize_repo(repo)
    if not repo:
        return {"status": "skip", "version": "", "url": "", "notes": "",
                "message": "未填写仓库地址", "need_token": False}

    url = f"https://api.github.com/repos/{repo}/releases"
    headers = dict(UA)
    headers["Accept"] = "application/vnd.github+json"
    headers["X-GitHub-Api-Version"] = "2022-11-28"
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            releases = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # need_token：这类失败只有「补一个（有效）令牌」才能解决，
        # 界面据此弹窗索要令牌，其它错误就没必要打扰用户
        if exc.code == 401:
            msg, need = "访问令牌无效或已过期，需要重新填写", True
        elif exc.code == 404:
            if token:
                msg, need = "令牌无权访问该仓库，需要重新填写", True
            else:
                msg, need = "仓库不存在，或是私有仓库（需要提供访问令牌）", True
        elif exc.code == 403:
            msg, need = "请求过于频繁（GitHub 接口限流），请稍后再试", False
        else:
            msg, need = f"检查失败（HTTP {exc.code}）", False
        return {"status": "error", "version": "", "url": "", "notes": "",
                "message": msg, "need_token": need}
    except (urllib.error.URLError, OSError, TimeoutError):
        return {"status": "error", "version": "", "url": "", "notes": "",
                "message": "网络连接失败，请检查网络或代理设置", "need_token": False}
    except json.JSONDecodeError:
        return {"status": "error", "version": "", "url": "", "notes": "",
                "message": "返回内容无法解析", "need_token": False}

    if not isinstance(releases, list) or not releases:
        return {"status": "none", "version": VERSION, "url": "", "notes": "",
                "message": f"没有发布记录（当前 v{VERSION}）",
                "need_token": False}

    # 按版本号取最大，而不是取第一条——发布顺序不一定等于版本顺序
    best = None
    for rel in releases:
        if rel.get("draft"):
            continue
        tag = str(rel.get("tag_name") or "")
        if not tag:
            continue
        if best is None or parse_version(tag) > parse_version(
                best.get("tag_name", "")):
            best = rel
    if best is None:
        return {"status": "none", "version": VERSION, "url": "", "notes": "",
                "message": f"没有可用发布（当前 v{VERSION}）",
                "need_token": False}

    latest = str(best.get("tag_name") or "")
    asset_url = ""
    for asset in best.get("assets", []):
        if asset.get("name", "").lower().endswith(".zip"):
            asset_url = asset.get("browser_download_url", "")
            break
    notes = str(best.get("body") or "")
    pre = "（测试版）" if best.get("prerelease") else ""

    if parse_version(latest) <= parse_version(VERSION):
        return {"status": "none", "version": latest, "url": asset_url,
                "notes": notes,
                "message": f"已是最新版本 v{VERSION}{pre}",
                "need_token": False}
    return {"status": "update", "version": latest, "url": asset_url,
            "notes": notes,
            "message": f"发现新版本 {latest}{pre}（当前 v{VERSION}）",
            "need_token": False}


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
