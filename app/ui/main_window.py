# -*- coding: utf-8 -*-
"""主窗口：无边框 + 侧边导航 + 自定义标题栏。

布局（对齐界面设计稿）：
    左侧边栏：LOGO（点击可更换）、打印标签 / 打印记录 / 产品管理 / 设置、版本号（红点提示更新）
    右侧上方：页面副标题 + 最小化 / 最大化 / 关闭
    右侧主体：页面堆栈
"""

import ctypes
import sys
from datetime import datetime
from typing import Optional

from PyQt5.QtCore import (QDateTime, QEvent, QPoint, Qt, QThread, QTimer,
                          pyqtSignal)
from PyQt5.QtGui import QColor, QGuiApplication, QIcon
from PyQt5.QtWidgets import (QButtonGroup, QFrame, QGraphicsDropShadowEffect,
                             QHBoxLayout, QLabel, QMainWindow, QPushButton,
                             QSizeGrip, QStackedWidget, QToolButton,
                             QVBoxLayout, QWidget)

# Windows 原生窗口缩放命中区域（WM_NCHITTEST 返回值）
WM_NCHITTEST = 0x0084
HTLEFT, HTRIGHT = 10, 11
HTTOP, HTTOPLEFT, HTTOPRIGHT = 12, 13, 14
HTBOTTOM, HTBOTTOMLEFT, HTBOTTOMRIGHT = 15, 16, 17
# 边缘可拖拽拉伸的感应宽度（像素）
RESIZE_BORDER = 7

# 侧边导航图标尺寸（原 30px，按需求放大一倍）
NAV_ICON_SIZE = 60

# 无边框窗口的阴影留白：窗体四周留出透明区域供投影绘制，
# 最大化时改为 0（贴满屏幕）
SHADOW_MARGIN = 10

# 拉伸/移动停止后恢复投影的延迟（毫秒）
SHADOW_RESUME_MS = 180

# 窗体底板四周留出的描边宽度（露出自绘的边框与内阴影渐变）
FRAME_INSET = 2

from app.core import backup as backup_mod
from app.core import updater
from app.core.bartender import BarTender
from app.core.db import DB
from app.ui import icons
from app.ui.page_print import PrintPage
from app.ui.page_products import ProductsPage
from app.core.print_service import PrintService
from app.ui.title_button import TitleButton
from app.ui.page_records import RecordsPage
from app.ui.page_settings import SettingsPage
from app.version import AUTHOR, VERSION


class UpdateCheckThread(QThread):
    """后台检查更新（不阻塞启动）。"""
    result = pyqtSignal(object)

    def __init__(self, repo: str, token: str = ""):
        super().__init__()
        self._repo = repo
        self._token = token

    def run(self) -> None:
        self.result.emit(updater.check_latest(self._repo, self._token))


class TitleBar(QFrame):
    """自定义标题栏（可拖动窗口）。"""

    def __init__(self, window: "MainWindow"):
        super().__init__()
        self.setObjectName("titlebar")
        self._window = window
        self._drag_pos: Optional[QPoint] = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 4, 0, 4)
        self.title = QLabel("打印标签 · 扫码录入自动打印")
        self.title.setObjectName("pageTitle")
        # 让鼠标事件穿透标题文字：否则点在文字上无法拖动窗口 / 双击最大化
        self.title.setAttribute(Qt.WA_TransparentForMouseEvents)
        layout.addWidget(self.title)
        layout.addStretch(1)

        # ★ 三个窗口按钮的图标都由 Qt 现画：
        #   原来用「— ▢ ✕」这些特殊符号，Win7 上缺字形会显示成空白或方框
        self.min_btn = TitleButton(TitleButton.MIN)
        self.min_btn.clicked.connect(window.showMinimized)
        layout.addWidget(self.min_btn)
        self.max_btn = TitleButton(TitleButton.MAX)
        self.max_btn.clicked.connect(window.toggle_maximize)
        layout.addWidget(self.max_btn)
        self.close_btn = TitleButton(TitleButton.CLOSE, danger=True)
        self.close_btn.clicked.connect(window.close)
        layout.addWidget(self.close_btn)

    def set_title(self, text: str) -> None:
        self.title.setText(text)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPos() - self._window.frameGeometry().topLeft()

    def mouseMoveEvent(self, event) -> None:
        if self._drag_pos is not None and not self._window.isMaximized():
            self._window.move(event.globalPos() - self._drag_pos)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_pos = None

    def mouseDoubleClickEvent(self, event) -> None:
        self._window.toggle_maximize()


class ShadowRoot(QWidget):
    """不透明窗体底板：白底 + 细边框 + 四周内阴影渐变。

    为什么这样画：无边框窗口若用半透明背景（WA_TranslucentBackground）配合
    QGraphicsDropShadowEffect 才能有外投影，但半透明窗口在改变尺寸时 Qt 需要重建
    backing store，会有 1~2 帧来不及绘制被合成成黑色（录屏实测亮度由 195 骤降到
    130 的闪黑帧）。改为不透明窗口后完全没有重绘空隙，边界则靠这层自绘的
    边框 + 内阴影渐变来保证——在任何背景色下都能看清窗口轮廓。
    """

    EDGE = 8           # 内阴影渐变宽度
    BORDER = "#C3CAD4"  # 边框颜色

    def paintEvent(self, event) -> None:
        from PyQt5.QtGui import QLinearGradient, QPainter
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        p.fillRect(self.rect(), Qt.white)

        w, h, e = self.width(), self.height(), self.EDGE
        shadow = QColor(0, 0, 0, 46)

        def grad(x0, y0, x1, y1, x, y, ww, hh):
            g = QLinearGradient(x0, y0, x1, y1)
            g.setColorAt(0.0, shadow)
            g.setColorAt(1.0, QColor(0, 0, 0, 0))
            p.fillRect(x, y, ww, hh, g)

        grad(0, 0, 0, e, 0, 0, w, e)                 # 上
        grad(0, h, 0, h - e, 0, h - e, w, e)         # 下
        grad(0, 0, e, 0, 0, 0, e, h)                 # 左
        grad(w, 0, w - e, 0, w - e, 0, e, h)         # 右

        p.setPen(QColor(self.BORDER))
        p.drawRect(0, 0, w - 1, h - 1)


class NavButton(QPushButton):
    """侧边导航按钮：图标在上、文字在下，整体居中。

    采用「图标在上、文字在下」而不是 QPushButton 默认的「图标+文字横向排列」：
    横向排列时文字长度不同（如 4 字的「打印标签」与 2 字的「设置」）
    会导致各按钮的图标左右错位；改为竖排后，图标与文字各自居中，
    与上方选项天然对齐，两字的「设置」按分散对齐排版即可保持整齐。
    """

    def __init__(self, text: str, icon: QIcon):
        super().__init__()
        self.setObjectName("navBtn")
        self.setCheckable(True)
        self.setMinimumHeight(104)
        self.setCursor(Qt.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 8, 6, 8)
        layout.setSpacing(4)
        self.icon_label = QLabel()
        self.icon_label.setObjectName("navIcon")
        self.icon_label.setAlignment(Qt.AlignCenter)
        self.icon_label.setPixmap(icon.pixmap(NAV_ICON_SIZE, NAV_ICON_SIZE))
        self.icon_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.text_label = QLabel(text)
        self.text_label.setObjectName("navText")
        self.text_label.setAlignment(Qt.AlignCenter)
        self.text_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        layout.addWidget(self.icon_label)
        layout.addWidget(self.text_label)

    def set_nav_icon(self, icon: QIcon) -> None:
        """设置导航图标（用于更换 LOGO 等场景）。"""
        self.icon_label.setPixmap(icon.pixmap(NAV_ICON_SIZE, NAV_ICON_SIZE))


class SideBar(QFrame):
    """左侧导航栏。"""

    page_changed = pyqtSignal(int)
    logo_change_requested = pyqtSignal()

    LOGO_CLICKS_REQUIRED = 10        # 连点次数达到该值才允许更换 LOGO
    LOGO_CLICK_INTERVAL_MS = 1500    # 两次点击间隔超过该值则重新计数

    def __init__(self):
        super().__init__()
        self.setObjectName("sidebar")
        self.setFixedWidth(152)      # 侧边栏收窄，把宽度让给内容区

        self._logo_clicks = 0
        self._last_logo_click = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 16, 10, 10)
        layout.setSpacing(6)

        self.logo_btn = QToolButton()
        self.logo_btn.setFixedSize(80, 80)
        self.logo_btn.setCursor(Qt.PointingHandCursor)
        self._reset_logo_tooltip()
        self.logo_btn.setStyleSheet("border: none;")
        self.logo_btn.clicked.connect(self._on_logo_clicked)
        layout.addWidget(self.logo_btn, 0, Qt.AlignHCenter)
        layout.addSpacing(16)

        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        # 「设置」用全角空格做分散对齐，占位宽度与上方三个四字选项一致
        self.nav_defs = [
            ("打印标签", icons.printer_icon),
            ("打印记录", icons.clock_icon),
            ("产品管理", icons.cube_icon),
            ("设　置", icons.gear_icon),
        ]
        self.buttons = []
        for i, (text, icon_fn) in enumerate(self.nav_defs):
            # 按目标尺寸直接绘制矢量图标（比把 48px 位图放大更清晰）
            btn = NavButton(text, icon_fn(size=NAV_ICON_SIZE))
            self.group.addButton(btn, i)
            layout.addWidget(btn)
            self.buttons.append(btn)
        self.group.buttonClicked[int].connect(self.page_changed.emit)

        layout.addStretch(1)

        # 版本号居中显示在侧边栏底部
        version_row = QHBoxLayout()
        version_row.addStretch(1)
        self.version_label = QLabel(f"V{VERSION}")
        self.version_label.setObjectName("versionLabel")
        self.red_dot = QLabel("●")
        self.red_dot.setStyleSheet("color:#D43030;font-size:10px;")
        self.red_dot.setToolTip("有新版本可用，请到 设置 -> 系统设置 检查更新")
        self.red_dot.hide()
        version_row.addWidget(self.version_label)
        version_row.addWidget(self.red_dot)
        version_row.addStretch(1)
        layout.addLayout(version_row)

    # ---- LOGO 防误触：需连续点击 10 次才能更换 ----
    def _reset_logo_tooltip(self) -> None:
        self.logo_btn.setToolTip(
            f"连续点击 {self.LOGO_CLICKS_REQUIRED} 次可更换 LOGO")

    def _on_logo_clicked(self) -> None:
        """LOGO 更换需要连续点击 10 次，避免误触改掉图标。

        两次点击间隔超过 LOGO_CLICK_INTERVAL_MS 即视为重新开始计数；
        每次点击后用气泡提示还差几次。
        """
        now = QDateTime.currentMSecsSinceEpoch()
        if now - self._last_logo_click > self.LOGO_CLICK_INTERVAL_MS:
            self._logo_clicks = 0
        self._last_logo_click = now
        self._logo_clicks += 1

        remain = self.LOGO_CLICKS_REQUIRED - self._logo_clicks
        if remain > 0:
            self.logo_btn.setToolTip(f"再连续点击 {remain} 次可更换 LOGO")
            return
        self._logo_clicks = 0
        self._reset_logo_tooltip()
        self.logo_change_requested.emit()

    def refresh_logo(self) -> None:
        self.logo_btn.setIcon(QIcon(icons.load_logo(74)))
        from PyQt5.QtCore import QSize
        self.logo_btn.setIconSize(QSize(74, 74))

    def set_update_hint(self, show: bool) -> None:
        self.red_dot.setVisible(show)


class MainWindow(QMainWindow):
    """应用主窗口。"""

    # 窗口尺寸/位置记忆（存放于 settings 表 JSON 值）
    GEOMETRY_SETTING = "window_geometry"

    SUBTITLES = {
        0: "打印标签 · 扫码录入自动打印",
        1: "打印记录 · 查询 / 导出 / 重打印",
        2: "产品管理 · 录入与导入导出",
        3: "设置 · 规则与系统配置",
    }

    def __init__(self, db: DB):
        super().__init__()
        self.db = db
        self.bartender = BarTender(mock=db.get_bool("bartender_mock"))
        # 阴影相关属性必须最先初始化：Qt 在构建界面期间就会派发 move/resize 事件，
        # 若此时属性还不存在，事件回调里访问它们会抛 AttributeError。
        self._shadow_mode = "qt"          # 占位，稍后按系统能力改成 "dwm"
        self._dwm_applied_after_show = False
        self._shadow_effect = None
        self._update_info: Optional[dict] = None

        self.setWindowFlags(Qt.FramelessWindowHint)
        self.setMinimumSize(1024, 680)   # 允许自由拉伸到更小的尺寸（高度稍后按内容重算）
        self.setWindowTitle("标签打印")
        self.setWindowIcon(QIcon(icons.load_logo(64)))

        # ---- 外层容器：仅在「Qt 特效阴影」模式下才需要半透明 + 留白 ----
        # 优先用 DWM 原生阴影（窗口保持不透明）：
        # 半透明窗口（WA_TranslucentBackground）在改变尺寸时，Qt 的 backing store
        # 需要重建，会有 1~2 帧来不及绘制、被系统合成成黑色 —— 录屏实测会出现
        # 亮度由 195 骤降到 130 的「闪黑」帧。不透明窗口则完全没有这个问题。
        self._shadow_mode = "dwm" if self._enable_dwm_shadow() else "qt"
        if self._shadow_mode == "qt":
            self.setAttribute(Qt.WA_TranslucentBackground)
        margin = 0 if self._shadow_mode == "dwm" else SHADOW_MARGIN

        root = QWidget()
        root.setObjectName("shadowHost")
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(margin, margin, margin, margin)

        # ---- 内层窗体：不透明白底 + 细边框 + 内阴影渐变，承载全部内容 ----
        frame = ShadowRoot()
        frame.setObjectName("shadowRoot")
        frame_layout = QHBoxLayout(frame)
        # 留出 2px：否则子元素（侧边栏、内容区）会盖住底板自绘的边框与内阴影渐变
        frame_layout.setContentsMargins(FRAME_INSET, FRAME_INSET,
                                        FRAME_INSET, FRAME_INSET)
        frame_layout.setSpacing(0)
        self._shadow_host_layout = root_layout
        shadow = QGraphicsDropShadowEffect(frame)
        shadow.setBlurRadius(22)
        shadow.setOffset(0, 2)
        shadow.setColor(QColor(0, 0, 0, 90))
        self._shadow_effect = shadow
        if self._shadow_mode == "qt":
            # 只有回退方案才挂 Qt 特效（它每帧都要把整窗渲染到离屏纹理）
            frame.setGraphicsEffect(shadow)
        root_layout.addWidget(frame)

        self.sidebar = SideBar()
        self.sidebar.refresh_logo()
        self.sidebar.logo_change_requested.connect(self._change_logo)
        self.sidebar.page_changed.connect(self._switch_page)
        frame_layout.addWidget(self.sidebar)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        self.titlebar = TitleBar(self)
        right_layout.addWidget(self.titlebar)

        self.stack = QStackedWidget()
        # ★ 全程序共用一个常驻打印线程：BarTender 的 COM 连接有线程亲和性，
        #   每次打印新建线程会让连接跨线程复用而报错（时好时坏的根源）
        self.print_service = PrintService(self.bartender, self)
        self.print_page = PrintPage(db, self.bartender, self,
                                    print_service=self.print_service)
        self.print_service.done.connect(self.print_page._on_service_done)
        self.print_service.failed.connect(self.print_page._on_service_failed)
        self.records_page = RecordsPage(db, self.bartender, self,
                                       print_service=self.print_service)
        self.print_service.done.connect(self.records_page._on_reprint_done)
        self.print_service.failed.connect(self.records_page._on_reprint_failed)
        self.products_page = ProductsPage(db, self)
        self.settings_page = SettingsPage(db, self)
        for page in (self.print_page, self.records_page,
                     self.products_page, self.settings_page):
            self.stack.addWidget(page)
        right_layout.addWidget(self.stack, 1)
        frame_layout.addWidget(right, 1)
        self.setCentralWidget(root)

        # 最小高度按内容自动计算：保证产品列表最少 2 行时，
        # 其余固定区域（产品详情、箱号、SN 输入等）不被压缩变形
        self.print_page.layout().activate()
        self.print_page.apply_detail_height()
        # 最小高度取「打印页内容实算」与「布局最小需求」的较大值：
        # 只用布局的 minimumSizeHint 会偏小（QLabel 的 minimumSizeHint 远小于内容），
        # 窗口压过头时各区域就会互相重叠。
        # ★ 取所有页面的最大值：设置页是两列五张卡片，比打印页更高，
        #   只按打印页算的话，切到设置页时下半截会被裁掉
        page_min = max(self.print_page.min_content_height(),
                       self.print_page.layout().minimumSize().height(),
                       self.settings_page.min_content_height())
        self.setMinimumHeight(page_min + self.titlebar.sizeHint().height() + 10
                              + self._shadow_inset() * 2)

        # 恢复上次人为调整后的窗口尺寸；无记录时按最小尺寸打开
        self._geometry_ready = False
        self._restore_window_geometry()

        self.sidebar.buttons[0].setChecked(True)
        self._switch_page(0)

        self.settings_page.settings_saved.connect(self._on_settings_saved)

        # 自动备份：每分钟检查一次是否到达备份时间点
        self._backup_timer = QTimer(self)
        self._backup_timer.timeout.connect(self._auto_backup_check)
        self._backup_timer.start(60 * 1000)

        # 右下角缩放手柄：给用户一个可拖拽的视觉提示
        self._size_grip = QSizeGrip(self)
        self._size_grip.setFixedSize(18, 18)
        self._size_grip.raise_()

        # 启动时自动检查更新（可关闭，不影响离线使用）
        if self.db.get_bool("auto_check_update") and self.db.get_setting("update_repo"):
            self._check_update()

    def resizeEvent(self, event) -> None:
        """保持缩放手柄贴在右下角（避开阴影留白），并延迟保存窗口尺寸。

        同时暂停投影特效：QGraphicsDropShadowEffect 会把整个窗口子树先渲染到
        离屏纹理再做模糊，拉伸时每帧都要重做一遍（实测约 20ms/帧），
        是拖动过程中掉帧闪烁的主因。停手后再恢复，观感几乎无差别。
        """
        super().resizeEvent(event)
        if getattr(self, "_size_grip", None):
            margin = 0 if self.isMaximized() else self._shadow_inset()
            self._size_grip.move(self.width() - 18 - margin,
                                 self.height() - 18 - margin)
        self._suspend_shadow()
        self._save_window_geometry()

    # ---------------- 阴影 ----------------

    def _shadow_inset(self) -> int:
        """当前阴影模式下窗体四周需要留出的空白（DWM 模式为 0）。"""
        return 0 if getattr(self, "_shadow_mode", "dwm") == "dwm" else SHADOW_MARGIN

    def _enable_dwm_shadow(self) -> bool:
        """启用 Windows DWM 原生阴影（窗口保持不透明）。

        无边框窗口默认没有系统阴影；通过 DwmExtendFrameIntoClientArea 把边框
        向客户区扩展 1px，DWM 就会为该窗口绘制标准投影。相比 QGraphicsDropShadowEffect，
        它由系统合成器负责，零重绘开销，也不会引入半透明窗口的闪黑问题。

        Returns:
            成功返回 True；调用失败（非 Windows / 系统不支持）返回 False，
            由调用方回退到 Qt 特效方案。
        """
        if not sys.platform.startswith("win"):
            return False
        try:
            class MARGINS(ctypes.Structure):
                _fields_ = [("cxLeftWidth", ctypes.c_int),
                            ("cxRightWidth", ctypes.c_int),
                            ("cyTopHeight", ctypes.c_int),
                            ("cyBottomHeight", ctypes.c_int)]

            margins = MARGINS(1, 1, 1, 1)
            hr = ctypes.windll.dwmapi.DwmExtendFrameIntoClientArea(
                int(self.winId()), ctypes.byref(margins))
            return hr == 0
        except Exception:
            return False

    def showEvent(self, event) -> None:
        """首次显示后再补一次 DWM 调用（部分系统需在窗口可见后才生效）。"""
        super().showEvent(event)
        if self._shadow_mode == "dwm" and not self._dwm_applied_after_show:
            self._dwm_applied_after_show = True
            self._enable_dwm_shadow()

    def _suspend_shadow(self) -> None:
        """拉伸/移动期间暂停投影，并启动恢复定时器（防抖）。"""
        if self._shadow_mode == "dwm":
            return   # DWM 阴影由系统绘制，无离屏重绘开销，无需暂停
        effect = getattr(self, "_shadow_effect", None)
        if effect is None:
            return
        if effect.isEnabled() and not self.isMaximized():
            effect.setEnabled(False)
        if getattr(self, "_shadow_timer", None) is None:
            self._shadow_timer = QTimer(self)
            self._shadow_timer.setSingleShot(True)
            self._shadow_timer.setInterval(SHADOW_RESUME_MS)
            self._shadow_timer.timeout.connect(self._resume_shadow)
        self._shadow_timer.start()

    def _resume_shadow(self) -> None:
        """拉伸结束后恢复投影，并重算产品详情区高度（宽度可能已变）。

        仅 Qt 特效模式需要开关特效；DWM 模式由系统绘制，无需处理。
        """
        if self._shadow_mode == "dwm":
            page = getattr(self, "print_page", None)
            if page is not None:
                page.apply_detail_height()
            return
        effect = getattr(self, "_shadow_effect", None)
        if effect is not None and not self.isMaximized():
            effect.setEnabled(True)
        page = getattr(self, "print_page", None)
        if page is not None:
            page.apply_detail_height()

    def changeEvent(self, event) -> None:
        """窗口最大化/还原时切换阴影留白（最大化时贴满屏幕，不留阴影）。"""
        super().changeEvent(event)
        if event.type() == QEvent.WindowStateChange:
            self._apply_shadow_margins()

    def _apply_shadow_margins(self) -> None:
        """最大化时取消外层留白并关闭投影，还原时恢复。

        最大化时投影本身看不见（窗体已贴满屏幕），但特效仍会强制整窗离屏重绘，
        因此直接关掉，避免白白的渲染开销。
        """
        if self._shadow_mode == "dwm":
            return   # DWM 模式下无留白，最大化时系统也不画阴影
        layout = getattr(self, "_shadow_host_layout", None)
        if layout is None:
            return
        m = 0 if self.isMaximized() else SHADOW_MARGIN
        layout.setContentsMargins(m, m, m, m)
        effect = getattr(self, "_shadow_effect", None)
        if effect is not None:
            effect.setEnabled(m > 0)

    def moveEvent(self, event) -> None:
        """窗口移动后同样暂停投影（拖动窗口时也不做离屏重绘）并延迟保存位置。"""
        super().moveEvent(event)
        self._suspend_shadow()
        self._save_window_geometry()

    # ---------------- 窗口尺寸记忆 ----------------

    def _restore_window_geometry(self) -> None:
        """恢复上次人为调整后的窗口尺寸与位置。

        规则：
        - 有记录 -> 按记录恢复（含最大化状态）；记录过小则抬到当前最小尺寸；
          窗口若已在屏幕外（换了显示器）则居中；
        - 无记录（首次使用 / 清过设置）-> 用**最小尺寸**居中打开。
        """
        screen = QGuiApplication.primaryScreen().availableGeometry()
        geo = self.db.get_json(self.GEOMETRY_SETTING)

        def center(w: int, h: int) -> tuple:
            return (screen.center().x() - w // 2, screen.center().y() - h // 2)

        w = h = 0
        if isinstance(geo, dict) and geo.get("w") and geo.get("h"):
            w = max(int(geo["w"]), self.minimumWidth())
            h = max(int(geo["h"]), self.minimumHeight())
            x, y = int(geo.get("x", 0)), int(geo.get("y", 0))
        if not w:
            # 无记录：以最小尺寸居中打开
            w, h = self.minimumWidth(), self.minimumHeight()
            x, y = center(w, h)
        if (x + w < screen.left() or x > screen.right()
                or y + h < screen.top() or y > screen.bottom()):
            x, y = center(w, h)
        self.setGeometry(x, y, w, h)
        self._geometry_ready = True
        if isinstance(geo, dict) and geo.get("maximized"):
            # 先按记录设好「还原态」几何，再最大化，保证还原后仍是该尺寸
            self.showMaximized()

    def _save_window_geometry(self) -> None:
        """延迟保存窗口尺寸与位置（防抖，避免拉伸过程中频繁写库）。

        仅在窗口就绪后记录：初始化时的布局自适应尺寸不算人为拉伸。
        最大化状态下保存 normalGeometry（还原后的真实尺寸），保证下次还原大小正确。
        """
        if not getattr(self, "_geometry_ready", False):
            return
        if getattr(self, "_geometry_timer", None) is None:
            self._geometry_timer = QTimer(self)
            self._geometry_timer.setSingleShot(True)
            self._geometry_timer.setInterval(600)
            self._geometry_timer.timeout.connect(self._write_window_geometry)
        self._geometry_timer.start()

    def _write_window_geometry(self) -> None:
        rect = self.normalGeometry()
        self.db.set_json(self.GEOMETRY_SETTING, {
            "x": rect.x(), "y": rect.y(),
            "w": rect.width(), "h": rect.height(),
            "maximized": self.isMaximized(),
        })

    # ---------------- 窗口行为 ----------------

    def toggle_maximize(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def _hit_zone(self, pos: QPoint) -> int:
        """判断鼠标位置处于窗口的哪条边 / 哪个角（用于自由拉伸）。

        Args:
            pos: 相对窗口左上角的坐标

        Returns:
            WM_NCHITTEST 命中区域常量，非边缘区域返回 0
        """
        left = pos.x() <= RESIZE_BORDER
        right = pos.x() >= self.width() - RESIZE_BORDER
        top = pos.y() <= RESIZE_BORDER
        bottom = pos.y() >= self.height() - RESIZE_BORDER

        if left and top:
            return HTTOPLEFT
        if right and top:
            return HTTOPRIGHT
        if left and bottom:
            return HTBOTTOMLEFT
        if right and bottom:
            return HTBOTTOMRIGHT
        if left:
            return HTLEFT
        if right:
            return HTRIGHT
        if top:
            return HTTOP
        if bottom:
            return HTBOTTOM
        return 0

    def nativeEvent(self, eventType, message):
        """无边框窗口的原生事件处理：把边缘拖拽交回 Windows 实现自由拉伸。

        无边框（FramelessWindowHint）会禁用窗口原生缩放与阴影，
        这里通过 WM_NCHITTEST 把 7px 边缘区域声明为可拉伸区，
        由系统接管拖拽逻辑（保留原生手感，且不需要自己模拟鼠标事件）。
        """
        retval, result = super().nativeEvent(eventType, message)
        if not sys.platform.startswith("win"):
            return retval, result
        if eventType not in ("windows_generic_MSG", "windows_dispatcher_MSG"):
            return retval, result
        if self.isMaximized():  # 最大化状态下禁止拉伸
            return retval, result
        try:
            from ctypes.wintypes import MSG
            msg = MSG.from_address(int(message))
            if msg.message != WM_NCHITTEST:
                return retval, result
            # lParam 低 16 位为 x、高 16 位为 y（屏幕坐标，有符号）
            x = ctypes.c_short(msg.lParam & 0xFFFF).value
            y = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value
            zone = self._hit_zone(self.mapFromGlobal(QPoint(x, y)))
            if zone:
                return True, zone
        except Exception:
            pass
        return retval, result

    def closeEvent(self, event) -> None:
        # 关闭前立刻写回尺寸（防抖定时器可能还没到点）
        self._write_window_geometry()
        # ★ 先停打印线程再释放 BarTender：
        #   反过来的话，线程里正在进行的打印会碰到已关闭的 COM 对象
        if self.print_service.isRunning():
            self.print_service.stop()
        self.bartender.quit()  # 退出时释放 BarTender，不留后台进程
        self.db.close()
        event.accept()

    # ---------------- 页面与 LOGO ----------------

    def _switch_page(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        self.titlebar.set_title(self.SUBTITLES.get(index, ""))
        if index == 0:
            self.print_page.reload()
        elif index == 1:
            self.records_page.reload()
        elif index == 2:
            self.products_page.reload()
        elif index == 3:
            self.settings_page.reload()

    def _change_logo(self) -> None:
        if icons.change_logo(self):
            self._refresh_app_icon()

    def _refresh_app_icon(self) -> None:
        """重新读取 LOGO 并同步到侧边栏与窗口（任务栏）图标。"""
        self.sidebar.refresh_logo()
        self.setWindowIcon(QIcon(icons.load_logo(64)))

    # ---------------- 更新 ----------------

    def _check_update(self) -> None:
        self._update_thread = UpdateCheckThread(
            self.db.get_setting("update_repo"),
            self.db.get_setting("update_token") or "")
        self._update_thread.result.connect(self._on_update_result)
        self._update_thread.start()

    def _on_update_result(self, info: Optional[dict]) -> None:
        """启动时的后台检查结果。

        ★ 这里**不弹窗**：启动就弹令牌窗口太打扰。
          需要令牌时只在设置页留一句提示，由用户点「检查更新」时再问。
        """
        self._update_info = info if (info or {}).get("status") == "update" else None
        self.sidebar.set_update_hint(bool(self._update_info))
        if isinstance(info, dict) and info.get("need_token"):
            self.settings_page.show_token_needed(info)
        else:
            self.settings_page.show_update_result(info)

    def _on_settings_saved(self) -> None:
        self.bartender.mock = self.db.get_bool("bartender_mock")
        self.print_page.refresh_rules()
        # 列表设置 / 字段映射可能变了，刷新各页的列结构
        self.print_page.reload()
        self.products_page.reload()
        # ★ 记录页要用 on_settings_saved 而不是 reload：
        #   改了「默认显示周期」后需要重新初始化日期范围，
        #   否则看起来只有重启程序才生效。
        self.records_page.on_settings_saved()

    # ---------------- 自动备份 ----------------

    def _auto_backup_check(self) -> None:
        if not self.db.get_bool("auto_backup"):
            return
        target = self.db.get_setting("backup_time", "18:00")
        now = datetime.now()
        if now.strftime("%H:%M") < target:
            return
        if self.db.get_setting("last_backup_date") == now.strftime("%Y-%m-%d"):
            return
        try:
            dest = backup_mod.backup_dir(self.db.get_setting("backup_dir"))
            keep = int(self.db.get_setting("backup_keep", 3) or 3)
            backup_mod.do_backup(dest, keep)
            self.db.set_setting("last_backup_date", now.strftime("%Y-%m-%d"))
        except Exception:
            pass  # 自动备份失败不打断使用，手动备份会提示错误
