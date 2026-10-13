# -*- coding: utf-8 -*-
"""把本地仓库推送到 GitHub：自动建私有仓库 + 首次推送。

令牌只从环境变量 GH_TOKEN 读取，**不写进任何文件、不进版本库**：
推送时通过 `git -c http.extraheader=...` 临时注入 Authorization 头，
不会把令牌留在 .git/config 的远程地址里。

用法::

    set GH_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx        # Windows cmd
    $env:GH_TOKEN = "ghp_xxxxxxxxxxxxxxxxxxxx"   # PowerShell
    python tools/publish_github.py --name box-label-printer --private

令牌申请：https://github.com/settings/tokens -> Generate new token (classic)
权限勾选 repo（私有仓库必须），建议用完立刻 delete。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

API = "https://api.github.com"
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _api(method: str, path: str, token: str,
         payload: Optional[Dict[str, Any]] = None) -> tuple:
    """调用 GitHub REST API。

    Args:
        method: HTTP 方法
        path: 以 / 开头的接口路径
        token: GitHub 令牌
        payload: 请求体（会被序列化为 JSON）

    Returns:
        (状态码, 解析后的 JSON；无响应体时为 None)

    Raises:
        urllib.error.HTTPError: 由调用方按状态码自行处理
    """
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        API + path,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, (json.loads(body) if body else None)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(body) if body else None
        except json.JSONDecodeError:
            return exc.code, {"message": body}


def _git(*args: str) -> subprocess.CompletedProcess:
    """在项目根目录执行 git 命令（不回显令牌）。"""
    return subprocess.run(
        ["git", "-C", str(PROJECT_ROOT), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def get_login(token: str) -> str:
    """取当前令牌对应的 GitHub 用户名。

    Raises:
        SystemExit: 令牌无效或网络不通
    """
    status, info = _api("GET", "/user", token)
    if status != 200 or not info:
        raise SystemExit(f"令牌校验失败（HTTP {status}）：{info}")
    print(f"  已认证为 GitHub 用户：{info['login']}")
    return info["login"]


def ensure_repo(token: str, login: str, name: str, private: bool,
                description: str) -> str:
    """仓库不存在则创建，已存在则沿用。

    Returns:
        仓库的 html_url
    """
    status, info = _api("GET", f"/repos/{login}/{name}", token)
    if status == 200 and info:
        print(f"  仓库 {login}/{name} 已存在，直接复用")
        return info["html_url"]

    status, info = _api("POST", "/user/repos", token, {
        "name": name,
        "description": description,
        "private": private,
        "auto_init": False,     # 空仓库，历史完全由本地推送决定
        "has_issues": True,
        "has_wiki": False,
        "has_projects": False,
    })
    if status not in (200, 201) or not info:
        raise SystemExit(f"创建仓库失败（HTTP {status}）：{info}")
    print(f"  已创建{'私有' if private else '公开'}仓库：{info['html_url']}")
    return info["html_url"]


def push(token: str, login: str, name: str, branch: str) -> None:
    """绑定远端并推送（令牌只走临时 http.extraheader）。"""
    remote = f"https://github.com/{login}/{name}.git"
    existing = _git("remote", "get-url", "origin")
    if existing.returncode == 0 and existing.stdout.strip() != remote:
        _git("remote", "set-url", "origin", remote)
        print(f"  已更新 origin -> {remote}")
    elif existing.returncode != 0:
        _git("remote", "add", "origin", remote)
        print(f"  已添加 origin -> {remote}")

    # 令牌通过 -c 注入，不会写入 .git/config
    result = subprocess.run(
        ["git", "-C", str(PROJECT_ROOT),
         "-c", f"http.extraheader=AUTHORIZATION: bearer {token}",
         "push", "-u", "origin", branch],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    out = (result.stdout + result.stderr).replace(token, "***")
    print(out.strip() or "  （git 无输出）")
    if result.returncode != 0:
        raise SystemExit(f"推送失败（exit {result.returncode}）")


def main() -> None:
    parser = argparse.ArgumentParser(description="推送本地仓库到 GitHub")
    parser.add_argument("--name", default="box-label-printer", help="仓库名")
    parser.add_argument("--desc", default="外箱标签打印程序（PyQt5 + BarTender COM，绿色免安装）",
                        help="仓库描述")
    parser.add_argument("--public", action="store_true", help="设为公开（默认私有）")
    parser.add_argument("--branch", default="main", help="要推送的分支名")
    args = parser.parse_args()

    token = os.environ.get("GH_TOKEN", "").strip()
    if not token:
        raise SystemExit("请先在环境变量 GH_TOKEN 中设置 GitHub 令牌")

    print(f"准备把 {PROJECT_ROOT.name} 推送到 GitHub 仓库 {args.name}")
    login = get_login(token)
    url = ensure_repo(token, login, args.name, not args.public, args.desc)
    push(token, login, args.name, args.branch)
    print(f"\n完成：{url}")


if __name__ == "__main__":
    main()
