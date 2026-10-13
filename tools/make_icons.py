# -*- coding: utf-8 -*-
"""生成 assets/logo.png 与 logo.ico（蓝色圆角方块 + 白色标签图形）。

用法：python tools/make_icons.py
"""

from pathlib import Path

from PIL import Image, ImageDraw

ASSETS = Path(__file__).resolve().parent.parent / "assets"


def draw_logo(size: int) -> Image.Image:
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


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    logo = draw_logo(256)
    logo.save(ASSETS / "logo.png")
    ico = draw_logo(256)
    ico.save(ASSETS / "logo.ico",
             sizes=[(16, 16), (24, 24), (32, 32), (48, 48),
                    (64, 64), (128, 128), (256, 256)])
    print(f"已生成: {ASSETS / 'logo.png'}")
    print(f"已生成: {ASSETS / 'logo.ico'}")


if __name__ == "__main__":
    main()
