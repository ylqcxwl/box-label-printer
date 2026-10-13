# -*- coding: utf-8 -*-
"""通过 GitHub Git Data API 把本地提交历史原样推送到远端仓库。

为什么不用 `git push`：
    本机存在沙箱代理（http_proxy=127.0.0.1:6909），它放行 api.github.com，
    但对 github.com 返回 502，且绕过代理后直连也被拒（Could not connect）。
    `git push` 走的是 github.com，因此无法使用；而 REST API（api.github.com）
    完全可用，于是改用 Git Data API 逐个对象上传：blob -> tree -> commit -> ref。

这样做的好处：
    - 保留完整的提交历史（每条本地 commit 都会生成对应的远端 commit，
      作者、时间、提交信息、父子关系都一致）
    - blob 是内容寻址的，两次提交里内容相同的文件只上传一次

用法::

    set GH_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx
    python tools/push_via_api.py --name box-label-printer --branch main
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

API = "https://api.github.com"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
# Git Data API 单次 blob 上限 100MB，超过会直接拒绝
MAX_BLOB_BYTES = 100 * 1024 * 1024


class GitHub:
    """极简 GitHub REST 客户端（只依赖标准库）。"""

    def __init__(self, token: str) -> None:
        self._token = token

    def _request(self, method: str, path: str,
                 payload: Optional[Dict[str, Any]] = None) -> Tuple[int, Any]:
        """发起请求，返回 (状态码, JSON 或错误信息)。

        对偶发失败自动重试：本机走沙箱代理，实测会间歇性返回
        `403 The rule did not run because of a timeout` 或连接错误，
        重试一次基本都能过（曾遇到 PUT 首次 403、重试即 201）。
        """
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8") \
            if payload is not None else None
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        }
        last_status, last_info = 0, None
        for attempt in range(3):
            req = urllib.request.Request(API + path, data=data,
                                         method=method, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    body = resp.read().decode("utf-8")
                    return resp.status, (json.loads(body) if body else None)
            except urllib.error.HTTPError as exc:
                raw = exc.read().decode("utf-8", errors="replace")
                try:
                    last_status, last_info = exc.code, (
                        json.loads(raw) if raw else None)
                except json.JSONDecodeError:
                    last_status, last_info = exc.code, {"message": raw[:300]}
                # 只有这类明显是代理/服务端抖动的状态码才重试
                if exc.code not in (403, 500, 502, 503, 504):
                    return last_status, last_info
            except (urllib.error.URLError, TimeoutError, OSError):
                last_status, last_info = 0, {"message": "网络错误"}
            if attempt < 2:
                print(f"    请求失败（{last_status}），重试 {attempt + 2}/3 …")
                time.sleep(2 * (attempt + 1))
        return last_status, last_info

    def call(self, method: str, path: str,
             payload: Optional[Dict[str, Any]] = None) -> Any:
        """发起请求；非 2xx 直接抛出并带上接口返回的具体原因。"""
        status, info = self._request(method, path, payload)
        if status >= 300:
            raise RuntimeError(f"{method} {path} 失败（HTTP {status}）：{info}")
        return info


def git(*args: str, binary: bool = False) -> Any:
    """在项目根目录执行 git 命令。

    Args:
        *args: git 参数
        binary: True 时返回原始字节（用于取 blob 内容）

    Raises:
        RuntimeError: git 返回非 0
    """
    proc = subprocess.run(
        ["git", "-C", str(PROJECT_ROOT), *args],
        capture_output=True,
        encoding=None if binary else "utf-8",
        errors="replace" if not binary else None,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} 失败："
                           f"{proc.stderr.decode('utf-8', 'replace')[:300]}")
    return proc.stdout


def commit_list(branch: str) -> List[str]:
    """返回该分支从最早到最新的 commit sha。"""
    out = git("rev-list", "--reverse", branch)
    return [line.strip() for line in out.splitlines() if line.strip()]


def commit_meta(sha: str) -> Dict[str, str]:
    """取提交的作者信息与提交信息。"""
    sep = "\x1f"
    out = git("log", "-1", f"--format=%an{sep}%ae{sep}%aI{sep}%B", sha)
    name, email, date, message = out.split(sep, 3)
    return {"name": name, "email": email, "date": date,
            "message": message.rstrip("\n")}


def tree_entries(sha: str) -> List[Tuple[str, str, str]]:
    """取提交的完整文件列表，返回 [(mode, blob_sha, path)]。

    用 -z 让 git 以 NUL 结尾输出，避免中文路径被引号转义。
    """
    raw = git("ls-tree", "-r", "-z", sha, binary=True)
    entries: List[Tuple[str, str, str]] = []
    for record in raw.split(b"\x00"):
        if not record:
            continue
        meta, _, path = record.partition(b"\t")
        mode, _type, blob = meta.split(b" ", 2)
        entries.append((mode.decode(), blob.decode(),
                        path.decode("utf-8", errors="replace")))
    return entries


def blob_content(blob_sha: str) -> bytes:
    """取某个 blob 的原始内容。"""
    return git("cat-file", "blob", blob_sha, binary=True)


def build_tree(gh: "GitHub", owner: str, repo: str,
               entries: List[Tuple[str, str, str]],
               blob_cache: Dict[str, str]) -> str:
    """按路径递归构建目录树，返回根 tree 的 sha。

    ★ 为什么要递归而不是一次性提交所有路径：
      GitHub 的 create-tree 只会**自动创建一层**中间目录。
      实测 `a/b.txt` 能建（201），但 `.github/workflows/build.yml` 这种
      **两层嵌套**会直接返回 404 Not Found。
      所以必须自底向上为每个目录显式创建 tree 对象，
      再用 mode=040000 / type=tree 把它挂到父目录上。
    """
    root: Dict[str, Any] = {}
    for mode, blob_sha, path in entries:
        parts = path.split("/")
        node = root
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = (mode, blob_sha)

    def make(node: Dict[str, Any]) -> str:
        items: List[Dict[str, str]] = []
        for name, value in node.items():
            if isinstance(value, dict):                 # 子目录
                items.append({"path": name, "mode": "040000",
                              "type": "tree", "sha": make(value)})
            else:                                       # 文件
                mode, blob_sha = value
                items.append({"path": name, "mode": mode,
                              "type": "blob", "sha": blob_cache[blob_sha]})
        return gh.call("POST", f"/repos/{owner}/{repo}/git/trees",
                       {"tree": items})["sha"]

    return make(root)


def ensure_non_empty(gh: GitHub, owner: str, repo: str, branch: str) -> None:
    """空仓库要先「激活」：Git Data API 对零提交仓库一律返回 409。

    做法是用 contents 接口塞一个一次性的占位文件，让仓库产生第一个提交。
    它只是跳板——最后会把分支强制指回真正的历史，这个提交就变成游离对象
    被 GitHub 回收，不会留在历史里。
    """
    status, _ = gh._request("GET", f"/repos/{owner}/{repo}/commits?per_page=1")
    if status == 200:
        return
    if status != 409:
        raise RuntimeError(f"检查仓库是否为空失败（HTTP {status}）")
    print("  仓库为空，先用占位文件激活…")
    gh.call("PUT", f"/repos/{owner}/{repo}/contents/.init", {
        "message": "chore: init (临时占位，随后会被真实历史覆盖)",
        "content": base64.b64encode(b"placeholder\n").decode("ascii"),
        "branch": branch,
    })


def push_history(gh: GitHub, owner: str, repo: str, branch: str,
                 excludes: List[str] = None) -> str:
    """把本地分支的每条提交依次搬到远端，返回最后一次的 commit sha。

    Args:
        excludes: 需要跳过的路径前缀。
            ★ 典型场景：`.github/workflows/`。GitHub 要求令牌带 `workflow`
            范围才能提交工作流文件，否则即使 blob/tree/commit 都创建成功，
            最后一步更新分支引用也会返回 **404 Not Found**（不是明确的 403，
            极易误判）。用只勾了 `repo` 的令牌时必须把工作流目录排除掉。
    """
    ensure_non_empty(gh, owner, repo, branch)
    excludes = excludes or []
    blob_cache: Dict[str, str] = {}      # 本地 blob sha -> 远端 blob sha
    parent: Optional[str] = None
    last = ""

    for sha in commit_list(branch):
        meta = commit_meta(sha)
        entries = tree_entries(sha)
        skipped = [e for e in entries
                   if any(e[2].startswith(p) for p in excludes)]
        if skipped:
            entries = [e for e in entries if e not in skipped]
            print(f"    （跳过 {len(skipped)} 个受限路径："
                  f"{', '.join(e[2] for e in skipped[:3])}…）")
        print(f"  提交 {sha[:7]}：{meta['message'].splitlines()[0]}"
              f"（{len(entries)} 个文件）")

        for _mode, blob_sha, path in entries:
            if blob_sha in blob_cache:
                continue
            content = blob_content(blob_sha)
            if len(content) > MAX_BLOB_BYTES:
                raise RuntimeError(
                    f"{path} 超过 Git Data API 的 100MB 上限（{len(content)} 字节）")
            info = gh.call("POST", f"/repos/{owner}/{repo}/git/blobs", {
                "content": base64.b64encode(content).decode("ascii"),
                "encoding": "base64",
            })
            blob_cache[blob_sha] = info["sha"]

        tree_sha = build_tree(gh, owner, repo, entries, blob_cache)
        payload: Dict[str, Any] = {
            "message": meta["message"],
            "tree": tree_sha,
            "parents": [parent] if parent else [],
            "author": {"name": meta["name"], "email": meta["email"],
                       "date": meta["date"]},
        }
        commit = gh.call("POST", f"/repos/{owner}/{repo}/git/commits", payload)
        parent = commit["sha"]
        last = commit["sha"]

    # 更新引用前先确认远端确实有这个 commit，避免把 404 怪到 PATCH 头上
    check, info = gh._request("GET", f"/repos/{owner}/{repo}/git/commits/{last}")
    if check != 200:
        raise RuntimeError(f"刚创建的 commit {last[:7]} 在远端查不到：{info}")
    print(f"  已确认远端存在 commit {last}")

    # 真正的历史是「无父提交」开始的，与占位提交没有祖先关系，
    # 属于非快进更新，因此必须 force=True
    status, _ = gh._request("GET", f"/repos/{owner}/{repo}/git/refs/heads/{branch}")
    if status == 200:
        gh.call("PATCH", f"/repos/{owner}/{repo}/git/refs/heads/{branch}",
                {"sha": last, "force": True})
        print(f"  已强制更新 refs/heads/{branch} -> {last[:7]}（覆盖占位提交）")
    else:
        gh.call("POST", f"/repos/{owner}/{repo}/git/refs",
                {"ref": f"refs/heads/{branch}", "sha": last})
        print(f"  已创建 refs/heads/{branch} -> {last[:7]}")
    return last


def main() -> None:
    parser = argparse.ArgumentParser(description="用 Git Data API 推送本地历史")
    parser.add_argument("--owner", default="", help="仓库所有者，留空则取令牌对应的账号")
    parser.add_argument("--name", required=True, help="仓库名")
    parser.add_argument("--branch", default="main", help="本地分支名")
    parser.add_argument("--exclude", action="append", default=[],
                        help="排除的路径前缀，可重复指定（详见 push_history 说明）")
    args = parser.parse_args()

    token = os.environ.get("GH_TOKEN", "").strip()
    if not token:
        raise SystemExit("请先在环境变量 GH_TOKEN 中设置 GitHub 令牌")

    gh = GitHub(token)
    owner = args.owner or gh.call("GET", "/user")["login"]
    print(f"目标仓库：{owner}/{args.name}（分支 {args.branch}）")
    last = push_history(gh, owner, args.name, args.branch, args.exclude)

    # 远端默认分支若不是 main，顺手改过来
    info = gh.call("GET", f"/repos/{owner}/{args.name}")
    if info.get("default_branch") != args.branch:
        gh.call("PATCH", f"/repos/{owner}/{args.name}",
                {"default_branch": args.branch})
        print(f"  默认分支已改为 {args.branch}")

    print(f"\n完成：https://github.com/{owner}/{args.name}")


if __name__ == "__main__":
    main()
