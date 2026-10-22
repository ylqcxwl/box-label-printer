# -*- coding: utf-8 -*-
"""标题栏上的窗口按钮（最小化 / 最大化 / 关闭），图标由 Qt 现画。

★ 为什么不用「✕ ▢ —」这类字符当图标：
  这些是特殊 Unicode 符号（U+2715 / U+25A2 / U+2014），
  **Win7 上不一定有对应字形**，缺字形时 Qt 画出来的就是空白或方框
  （实测在字体缺失的环境里，关闭按钮整块是空白的，
  只有鼠标悬停变红时才看得出那儿有个按钮）。
  这里是绿色离线程序、目标系统含 Win7，不能赌字体，
  所以改成用 QPainter 画三条线 / 一个方框 —— 任何系统上都一样。
"""

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QColor, QPainter, QPen
from PyQt5.QtWidgets import QPushButton

CLOSE = "close"
MIN = "min"
MAX = "max"

# 常态 / 悬停态的颜色（关闭按钮悬停为红底白叉，与常见窗口一致）
FG = QColor("#5A6068")
FG_HOVER = QColor("#FFFFFF")
BG_HOVER = QColor("#E81123")
BG_PLAIN = QColor("#E9ECF0")


class TitleButton(QPushButton):
    """标题栏按钮：图标自绘，不依赖任何字体字形。

    Args:
        kind: TitleButton.CLOSE / MIN / MAX
        danger: 悬停时是否用红色底（关闭按钮用）
    """

    # 同时作为模块级常量与类属性，两种写法都能用（TitleButton.CLOSE / CLOSE）
    CLOSE = CLOSE
    MIN = MIN
    MAX = MAX

    def __init__(self, kind: str, danger: bool = False, parent=None):
        super().__init__(parent)
        self._kind = kind
        self._danger = danger
        self.setFixedSize(32, 28) if kind == CLOSE else self.setFixedSize(34, 26)
        self.setFlat(True)
        self.setCursor(Qt.ArrowCursor)
        self.setFocusPolicy(Qt.NoFocus)
        # 文字留空：图标全靠 paintEvent 画，避免字体缺字形
        self.setText("")
        # ★ 必须内联覆盖：全局 QSS 给 QPushButton 设了白底 + 边框 + 圆角 + 内边距，
        #   不覆盖的话自绘的叉会被套进一个方块按钮里。
        #   内联样式优先级高于全局 QSS；背景与悬停都由 paintEvent 来画。
        self.setStyleSheet(
            "QPushButton{background:transparent;border:none;"
            "border-radius:0;padding:0;margin:0;}"
            "QPushButton:hover{background:transparent;border:none;}")
        self.setToolTip({"close": "关闭", "min": "最小化",
                         "max": "最大化 / 还原"}.get(kind, ""))

    def paintEvent(self, event) -> None:  # noqa: N802（Qt 的命名）
        """画背景 + 图标（叉 / 横线 / 方框）。"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect()
        hover = self.underMouse() and self.isEnabled()

        # 背景：关闭按钮悬停用红底，其余用浅灰底
        if hover:
            painter.fillRect(rect, BG_HOVER if self._danger else BG_PLAIN)
        fg = FG_HOVER if (hover and self._danger) else FG
        pen = QPen(fg, 1.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        painter.setPen(pen)

        cx, cy = rect.center().x(), rect.center().y()
        if self._kind == CLOSE:
            r = 5.0                       # 叉的半长
            painter.drawLine(QPointF(cx - r, cy - r), QPointF(cx + r, cy + r))
            painter.drawLine(QPointF(cx + r, cy - r), QPointF(cx - r, cy + r))
        elif self._kind == MIN:
            painter.drawLine(QPointF(cx - 5, cy + 4), QPointF(cx + 5, cy + 4))
        else:
            # 最大化：一个方框；还原态用双层方框区分
            painter.drawRect(QRectF(cx - 5, cy - 5, 10, 10))
            if self.text() == "restore":
                painter.drawRect(QRectF(cx - 3, cy - 3, 6, 6))
        painter.end()
