# -*- coding: utf-8 -*-
"""矢量图标（QPainter 运行时绘制，无外部图片依赖）。

logo 优先使用 assets/logo.png 或用户自定义 logo，绘制版仅作兜底。
"""

from pathlib import Path
from typing import Optional

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import (QBrush, QColor, QIcon, QPainter, QPainterPath, QPen,
                         QPixmap)
from PyQt5.QtWidgets import QFileDialog, QWidget

from app.config import CUSTOM_LOGO, DEFAULT_LOGO


def _pixmap(size: int) -> tuple:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    return pm, p


def printer_icon(color: str = "#1F2329", size: int = 48) -> QIcon:
    pm, p = _pixmap(size)
    pen = QPen(QColor(color), size * 0.07, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    u = size / 24.0
    p.drawRect(QRectF(7 * u, 3 * u, 10 * u, 5 * u))            # 上纸槽
    p.drawRoundedRect(QRectF(3 * u, 9 * u, 18 * u, 8 * u), 2 * u, 2 * u)  # 机身
    p.drawRect(QRectF(7 * u, 14 * u, 10 * u, 7 * u))           # 出纸
    p.drawLine(QPointF(9 * u, 17 * u), QPointF(15 * u, 17 * u))
    p.end()
    return QIcon(pm)


def clock_icon(color: str = "#1F2329", size: int = 48) -> QIcon:
    pm, p = _pixmap(size)
    pen = QPen(QColor(color), size * 0.07, Qt.SolidLine, Qt.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    u = size / 24.0
    p.drawEllipse(QRectF(4 * u, 4 * u, 16 * u, 16 * u))
    p.drawLine(QPointF(12 * u, 12 * u), QPointF(12 * u, 7 * u))
    p.drawLine(QPointF(12 * u, 12 * u), QPointF(16 * u, 12 * u))
    p.end()
    return QIcon(pm)


def cube_icon(color: str = "#1F2329", size: int = 48) -> QIcon:
    pm, p = _pixmap(size)
    pen = QPen(QColor(color), size * 0.07, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    u = size / 24.0
    path = QPainterPath(QPointF(12 * u, 3 * u))
    path.lineTo(20 * u, 7.5 * u)
    path.lineTo(20 * u, 16.5 * u)
    path.lineTo(12 * u, 21 * u)
    path.lineTo(4 * u, 16.5 * u)
    path.lineTo(4 * u, 7.5 * u)
    path.closeSubpath()
    p.drawPath(path)
    p.drawLine(QPointF(4 * u, 7.5 * u), QPointF(12 * u, 12 * u))
    p.drawLine(QPointF(20 * u, 7.5 * u), QPointF(12 * u, 12 * u))
    p.drawLine(QPointF(12 * u, 12 * u), QPointF(12 * u, 21 * u))
    p.end()
    return QIcon(pm)


def gear_icon(color: str = "#1F2329", size: int = 48) -> QIcon:
    pm, p = _pixmap(size)
    pen = QPen(QColor(color), size * 0.065, Qt.SolidLine, Qt.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    u = size / 24.0
    cx, cy, r = 12 * u, 12 * u, 4.6 * u
    import math
    for i in range(8):
        ang = math.radians(i * 45)
        x1 = cx + (r + 1.2 * u) * math.cos(ang)
        y1 = cy + (r + 1.2 * u) * math.sin(ang)
        x2 = cx + (r + 3.2 * u) * math.cos(ang)
        y2 = cy + (r + 3.2 * u) * math.sin(ang)
        p.drawLine(QPointF(x1, y1), QPointF(x2, y2))
    p.drawEllipse(QPointF(cx, cy), r, r)
    p.end()
    return QIcon(pm)


def tag_pixmap(size: int = 96) -> QPixmap:
    """蓝色圆角方块 + 白色标签图形（默认 LOGO 兜底绘制）。"""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, size, size), size * 0.22, size * 0.22)
    p.fillPath(path, QBrush(QColor("#0066CC")))
    p.setPen(QPen(QColor("#FFFFFF"), size * 0.05, Qt.SolidLine, Qt.RoundCap,
                  Qt.RoundJoin))
    p.setBrush(Qt.NoBrush)
    u = size / 24.0
    tag = QPainterPath(QPointF(6 * u, 6 * u))
    tag.lineTo(13 * u, 6 * u)
    tag.lineTo(18 * u, 12.5 * u)
    tag.lineTo(11 * u, 19.5 * u)
    tag.lineTo(6 * u, 14.5 * u)
    tag.closeSubpath()
    p.drawPath(tag)
    p.setBrush(QBrush(QColor("#FFFFFF")))
    p.drawEllipse(QPointF(9.5 * u, 9.8 * u), 1.1 * u, 1.1 * u)
    p.end()
    return pm


def load_logo(size: int = 96) -> QPixmap:
    """加载 LOGO：优先用户自定义，其次内置资源，最后绘制兜底。"""
    for path in (CUSTOM_LOGO, DEFAULT_LOGO):
        if Path(path).exists():
            pm = QPixmap(str(path))
            if not pm.isNull():
                return pm.scaled(size, size, Qt.KeepAspectRatio,
                                 Qt.SmoothTransformation)
    return tag_pixmap(size)


def ensure_arrow_png(color: str = "#5A6068", size: int = 16,
                     direction: str = "down") -> Path:
    """生成箭头图片（供下拉框 / 日期框 / 微调框使用），返回其绝对路径。

    图片写入 data/assets 而非打包资源目录——打包后 _MEIPASS 为只读临时目录。

    Args:
        direction: "down"（默认，下拉箭头）或 "up"（微调框上箭头）
    """
    out_dir = CUSTOM_LOGO.parent / "assets"
    out_dir.mkdir(parents=True, exist_ok=True)
    # 文件名带上尺寸：下拉框用 16px、微调框用 12px，两者互不覆盖
    suffix = "" if size == 16 else f"_{size}"
    path = out_dir / f"arrow_{direction}{suffix}.png"
    if path.exists():
        return path

    pm, p = _pixmap(size)
    pen = QPen(QColor(color), size * 0.14, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    if direction == "up":
        p.drawLine(QPointF(size * 0.26, size * 0.62), QPointF(size * 0.50, size * 0.36))
        p.drawLine(QPointF(size * 0.74, size * 0.62), QPointF(size * 0.50, size * 0.36))
    else:
        p.drawLine(QPointF(size * 0.26, size * 0.40), QPointF(size * 0.50, size * 0.64))
        p.drawLine(QPointF(size * 0.74, size * 0.40), QPointF(size * 0.50, size * 0.64))
    p.end()
    pm.save(str(path), "PNG")
    return path


def change_logo(parent: QWidget) -> bool:
    """弹出文件选择框更换 LOGO（复制到 data/custom_logo.png）。"""
    src, _ = QFileDialog.getOpenFileName(
        parent, "选择 LOGO 图片", "", "图片文件 (*.png *.jpg *.jpeg *.bmp *.ico)")
    if not src:
        return False
    CUSTOM_LOGO.parent.mkdir(parents=True, exist_ok=True)
    pm = QPixmap(src)
    if pm.isNull():
        return False
    pm.save(str(CUSTOM_LOGO), "PNG")
    return True


def reset_logo() -> bool:
    """恢复默认 LOGO（删除 data/custom_logo.png）。

    Returns:
        原本存在自定义 LOGO 并已删除返回 True；本来就是默认图标返回 False。
    """
    path = Path(CUSTOM_LOGO)
    if not path.exists():
        return False
    try:
        path.unlink()
    except OSError:
        return False
    return True
