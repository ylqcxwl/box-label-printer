# -*- coding: utf-8 -*-
"""把本地文件上传为 GitHub Release 的附件。

用法::

    set GH_TOKEN=ghp_xxxx
    python tools/upload_release_asset.py <release_id> <本地文件路径> [附件名]

坑：
  * 上传走的是 **uploads.github.com**，不是 api.github.com；
  * ★★ **附件名只能用 ASCII**：实测把「标签打印_v0.0.1.zip」放进
    `?name=`（已做 UTF-8 百分号编码）传上去，GitHub 会把中文**整个剥掉**，
    返回的附件名变成 `_v0.0.1.zip`，且不会报错。
    所以 `name` 用英文名，中文名改放在 `label`（显示名）里。
  * `label` 要另调一次 `PATCH /releases/assets/{id}` 设置，它支持中文。
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
LABEL = os.environ.get("ASSET_LABEL", "")   # 中文显示名（可选）

CONTENT_TYPES = {
    ".zip": "application/zip",
    ".exe": "application/octet-stream",
    ".txt": "text/plain",
}


def set_label(asset_id: int, label: str) -> None:
    """给附件设中文显示名（label 字段支持中文，name 不支持）。"""
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/releases/assets/{asset_id}",
        data=json.dumps({"name": None, "label": label},
              ensure_ascii=False).encode("utf-8"),
        method="PATCH",
        headers={"Authorization": f"Bearer {TOKEN}",
                 "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            info = json.loads(resp.read().decode("utf-8"))
        print("  显示名:", info.get("label"))
    except urllib.error.HTTPError as exc:
        print("  设置显示名失败 HTTP", exc.code)


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
    except urllib.error.HTTPError as exc:
        raise SystemExit("上传失败 HTTP %s：%s"
                         % (exc.code, exc.read().decode("utf-8", "replace")[:300]))

    print("上传成功")
    print("  附件名:", info["name"])
    print("  大小  :", info["size"] // 1048576, "MB")
    print("  下载  :", info["browser_download_url"])
    if LABEL:
        set_label(info["id"], LABEL)

    # 附件名若含非 ASCII，GitHub 会把那部分静默剥掉（无报错）。
    # 这里比对一下，提醒使用者改用 ASCII 名 + label 显示中文。
    if info["name"] != ASSET_NAME:
        print(f"  ⚠ 实际附件名与传入的不一致（{ASSET_NAME!r} -> "
              f"{info['name']!r}）：GitHub 不允许附件名含非 ASCII，"
              f"请改用英文名，中文名放到 label 里。")
        if LABEL:
            set_label(info["id"], LABEL)


if __name__ == "__main__":
    main()
