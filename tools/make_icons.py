# -*- coding: utf-8 -*-
"""生成 assets/logo.png 与 logo.ico。

默认：用代码绘制「蓝色圆角方块 + 白色标签」。
自定义：把一张图片另存为 assets/logo_source.png，本脚本会优先用它，
        自动居中裁成正方形、缩放到 256，并生成多尺寸 ico。

★ 为什么要这个源文件：
  打包前（build.bat / GitHub Actions）都会跑本脚本。如果直接替换
  assets/logo.ico 或 logo.png，一打包就会被覆盖回默认图。
  放 logo_source.png 才是「改一次、以后每次打包都生效」的做法。

用法：python tools/make_icons.py
"""

import sys
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw

# 标准输出强制 UTF-8：Windows 控制台默认是 cp1252/GBK，
# 下面打印「已生成：…」这类中文时会抛 UnicodeEncodeError。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ASSETS = Path(__file__).resolve().parent.parent / "assets"
SOURCE = ASSETS / "logo_source.png"   # 可选：自定义图标源图
ICO_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48),
             (64, 64), (128, 128), (256, 256)]


def draw_logo(size: int) -> Image.Image:
    """绘制内置默认 LOGO（蓝色圆角方块 + 白色标签轮廓）。"""
    scale = 4  # 超采样抗锯齿
    s = size * scale
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    radius = int(s * 0.22)
    d.rounded_rectangle([0, 0, s - 1, s - 1], radius=radius, fill="#0066CC")

    u = s / 24.0
    # 白色标签轮廓
    points = [(6 * u, 6 * u), (13 * u, 6 * u), (18 * u, 12.5 * u),
              (11 * u, 19.5 * u), (6 * u, 14.5 * u)]
    width = max(2, int(s * 0.05))
    d.line(points + [points[0]], fill="#FFFFFF", width=width, joint="curve")
    # 标签圆孔
    cx, cy, r = 9.5 * u, 9.8 * u, 1.2 * u
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill="#FFFFFF")
    return img.resize((size, size), Image.LANCZOS)


def load_source(size: int = 256) -> Optional[Image.Image]:
    """读取自定义源图并居中裁成正方形。

    Args:
        size: 输出边长，默认 256。

    Returns:
        处理好的 RGBA 图像；没有源图或读取失败时返回 None（回退到内置图）。
    """
    if not SOURCE.exists():
        return None
    try:
        with Image.open(SOURCE) as raw:
            img = raw.convert("RGBA")
    except Exception as exc:      # noqa: BLE001 图片损坏时静默回退，不阻断打包
        print(f"自定义源图读取失败，改用内置 LOGO：{exc}")
        return None

    w, h = img.size
    side = min(w, h)
    left, top = (w - side) // 2, (h - side) // 2
    img = img.crop((left, top, left + side, top + side))
    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    """生成 logo.png / logo.ico，优先使用自定义源图。"""
    ASSETS.mkdir(parents=True, exist_ok=True)
    logo = load_source(256)
    if logo is None:
        logo = draw_logo(256)
        print("图标来源：内置默认图")
    else:
        print(f"图标来源：自定义源图 {SOURCE.name}")

    logo.save(ASSETS / "logo.png")
    logo.save(ASSETS / "logo.ico", sizes=ICO_SIZES)
    print(f"已生成: {ASSETS / 'logo.png'}")
    print(f"已生成: {ASSETS / 'logo.ico'}")


if __name__ == "__main__":
    main()
