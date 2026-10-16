# -*- coding: utf-8 -*-
"""下载 GitHub Actions 的产物（artifact）到本地。

用法::

    set GH_TOKEN=ghp_xxxx
    python tools/download_artifact.py <artifact_id> <输出目录>

两个坑：
  1. artifact 下载接口会 **302 跳到 Azure Blob**，而跳转目标**不能**带
     GitHub 的 Authorization 头（带了会 401 Server failed to authenticate），
     所以这里禁止自动跟随，手动用「无认证头」的第二次请求去取。
  2. 走沙箱代理时 37MB 可能要半小时以上，建议后台运行。
"""

from __future__ import annotations

import io
import os
import sys
import urllib.error
import urllib.request
import zipfile

sys.stdout.reconfigure(encoding="utf-8")

TOKEN = os.environ.get("GH_TOKEN", "").strip()
ARTIFACT_ID = sys.argv[1]
OUT_DIR = sys.argv[2]
REPO = os.environ.get("GH_REPO", "ylqcxwl/box-label-printer")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """禁止自动跟随重定向，以便手动去掉认证头。"""

    def redirect_request(self, req, fp, code, msg, hdrs, newurl):
        return None


def main() -> None:
    if not TOKEN:
        raise SystemExit("请先设置环境变量 GH_TOKEN")
    url = (f"https://api.github.com/repos/{REPO}"
           f"/actions/artifacts/{ARTIFACT_ID}/zip")
    req = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {TOKEN}",
                      "Accept": "application/vnd.github+json"})
    opener = urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(req, timeout=120) as resp:
            blob = resp.read()
    except urllib.error.HTTPError as exc:
        location = exc.headers.get("Location")
        if not location:
            raise SystemExit(f"下载失败 HTTP {exc.code}："
                             f"{exc.read().decode('utf-8', 'replace')[:200]}")
        print("跳转到 Azure Blob，改用无认证头请求…")
        blob = urllib.request.urlopen(
            urllib.request.Request(location), timeout=1800).read()

    print("下载完成:", len(blob) // 1048576, "MB")
    os.makedirs(OUT_DIR, exist_ok=True)
    zf = zipfile.ZipFile(io.BytesIO(blob))
    print("包内文件:", zf.namelist())
    for name in zf.namelist():
        if name.endswith(".zip"):
            zf.extract(name, OUT_DIR)
            print("已解出:", os.path.join(OUT_DIR, name))


if __name__ == "__main__":
    main()
