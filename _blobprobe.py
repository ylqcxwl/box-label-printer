# -*- coding: utf-8 -*-
"""逐个文件调用 GitHub 的 git/blobs 接口，找出到底哪个文件导致 HTTP 400。

用法: set GH_TOKEN=... && python _blobprobe.py <commit-sha>
"""
import base64
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")

TOKEN = os.environ["GH_TOKEN"]
REPO = "ylqcxwl/box-label-printer"
COMMIT = sys.argv[1] if len(sys.argv) > 1 else "HEAD"


def git(*args) -> bytes:
    return subprocess.run(["git", *args], capture_output=True,
                          check=True).stdout


def post_blob(content: bytes) -> tuple:
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/git/blobs",
        data=json.dumps({"content": base64.b64encode(content).decode("ascii"),
                         "encoding": "base64"}).encode("utf-8"),
        method="POST",
        headers={"Authorization": f"Bearer {TOKEN}",
                 "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")[:200]


lines = git("ls-tree", "-r", COMMIT).decode("utf-8").splitlines()
print(f"共 {len(lines)} 个文件，逐个试 blobs 接口…\n")

bad = []
for line in lines:
    meta, path = line.split("\t", 1)
    sha = meta.split()[2]
    try:
        content = git("cat-file", "-p", sha)
    except subprocess.CalledProcessError:
        print(f"  [跳过] 读不出内容: {path}")
        continue
    status, info = post_blob(content)
    if status >= 400:
        print(f"  [失败 {status}] {path}  ({len(content)} 字节)")
        print(f"           {info}")
        bad.append(path)
    else:
        print(f"  [OK]      {path}  ({len(content)} 字节)")

print(f"\n失败 {len(bad)} 个：")
for p in bad:
    print("   -", p)
