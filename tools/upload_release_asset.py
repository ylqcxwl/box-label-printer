# -*- coding: utf-8 -*-
"""把本地文件上传为 GitHub Release 的附件。

用法::

    set GH_TOKEN=ghp_xxxx
    python tools/upload_release_asset.py <release_id> <本地文件路径> [附件名]

坑：
  * 上传走的是 **uploads.github.com**，不是 api.github.com；
  * 附件名含中文时要做 URL 编码，否则请求会失败。
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")

TOKEN = os.environ.get("GH_TOKEN", "").strip()
RELEASE_ID = sys.argv[1]
FILE_PATH = sys.argv[2]
ASSET_NAME = sys.argv[3] if len(sys.argv) > 3 else os.path.basename(FILE_PATH)
REPO = os.environ.get("GH_REPO", "ylqcxwl/box-label-printer")

CONTENT_TYPES = {
    ".zip": "application/zip",
    ".exe": "application/octet-stream",
    ".txt": "text/plain",
}


def main() -> None:
    if not TOKEN:
        raise SystemExit("请先设置环境变量 GH_TOKEN")
    if not os.path.isfile(FILE_PATH):
        raise SystemExit(f"文件不存在：{FILE_PATH}")

    ext = os.path.splitext(ASSET_NAME)[1].lower()
    ctype = CONTENT_TYPES.get(ext, "application/octet-stream")
    size = os.path.getsize(FILE_PATH)
    print(f"准备上传：{ASSET_NAME}（{size // 1048576} MB，{ctype}）")

    url = (f"https://uploads.github.com/repos/{REPO}/releases/{RELEASE_ID}"
           f"/assets?name={urllib.parse.quote(ASSET_NAME)}")
    with open(FILE_PATH, "rb") as fh:
        data = fh.read()

    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Authorization": f"Bearer {TOKEN}",
                 "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28",
                 "Content-Type": ctype,
                 "Content-Length": str(len(data))})
    try:
        with urllib.request.urlopen(req, timeout=1800) as resp:
            info = json.loads(resp.read().decode("utf-8"))
        print("上传成功")
        print("  附件名:", info["name"])
        print("  大小  :", info["size"] // 1048576, "MB")
        print("  下载  :", info["browser_download_url"])
    except urllib.error.HTTPError as exc:
        raise SystemExit("上传失败 HTTP %s：%s"
                         % (exc.code, exc.read().decode("utf-8", "replace")[:300]))


if __name__ == "__main__":
    main()
