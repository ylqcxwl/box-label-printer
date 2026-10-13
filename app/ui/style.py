# -*- coding: utf-8 -*-
"""全局样式（Apple 风格：白底、细线边框、单一 Action Blue 强调色）。"""

ACCENT = "#0066CC"
TEXT = "#1F2329"
TEXT_SECONDARY = "#8A8F99"
BORDER = "#E3E6EB"
CARD_BG = "#F7F8FA"
DANGER = "#D43030"
SUCCESS = "#1E9E50"

FONT_FAMILY = '"Noto Sans SC", "Microsoft YaHei", "PingFang SC", sans-serif'


def _arrow_url() -> str:
    """生成下拉箭头图片，返回 QSS url() 可用的路径（失败则返回空）。"""
    try:
        from app.ui import icons
        return icons.ensure_arrow_png().as_posix()
    except Exception:
        return ""


def _spin_arrow_url(direction: str) -> str:
    """微调框（QSpinBox）上/下箭头图片路径。"""
    try:
        from app.ui import icons
        return icons.ensure_arrow_png(size=12, direction=direction).as_posix()
    except Exception:
        return ""

QSS = """
* {
    font-family: %(font)s;
    font-size: 14px;
    color: %(text)s;
    outline: none;
}
/* 窗体底板：保持不透明（半透明会导致拉伸时闪黑），
   白底与边框/内阴影由 ShadowRoot.paintEvent 自绘，
   保证与背景颜色相近时也能看清程序边界 */
QWidget#shadowRoot {
    background: #FFFFFF;
}
/* ---------- 侧边栏 ---------- */
QWidget#sidebar {
    background: #F7F8FA;
    border-right: 1px solid %(border)s;
}
QPushButton#navBtn {
    background: transparent;
    border: none;
    border-radius: 12px;
    padding: 8px 4px;
    color: %(text)s;
    text-align: center;
}
QPushButton#navBtn:hover {
    background: #EDF0F4;
}
QPushButton#navBtn:checked {
    background: #E5EEF9;
    color: %(accent)s;
}
/* 导航按钮为「图标在上、文字在下」的自绘结构，选中态需作用到内部标签 */
QPushButton#navBtn:checked QLabel#navText {
    color: %(accent)s;
    font-weight: bold;
}
QPushButton#navBtn:hover QLabel#navText {
    color: %(accent)s;
}
QLabel#navText {
    letter-spacing: 1px;
    font-size: 24px;          /* 导航文字放大一倍（原 14px 继承值） */
    color: %(text)s;
}
QLabel#versionLabel {
    color: %(text_secondary)s;
    font-size: 12px;
    padding: 8px;
}
/* ---------- 标题栏 ---------- */
QWidget#titlebar {
    background: #FFFFFF;
    border-bottom: 1px solid %(border)s;
}
QLabel#pageTitle {
    font-size: 14px;
    color: %(text_secondary)s;
}
QPushButton#winBtn {
    background: transparent;
    border: none;
    font-size: 15px;
    padding: 4px 14px;
    color: %(text)s;
}
QPushButton#winBtn:hover {
    background: #EDF0F4;
}
QPushButton#winClose:hover {
    background: #E81123;
    color: #FFFFFF;
}
/* ---------- 卡片 ---------- */
QFrame#card {
    background: %(card_bg)s;
    border: 1px solid %(border)s;
    border-radius: 10px;
}
QFrame#whiteCard {
    background: #FFFFFF;
    border: 1px solid %(border)s;
    border-radius: 10px;
}
/* ---------- 按钮 ---------- */
QPushButton {
    background: #FFFFFF;
    border: 1px solid %(border)s;
    border-radius: 8px;
    padding: 7px 16px;
}
QPushButton:hover {
    border-color: %(accent)s;
    color: %(accent)s;
}
QPushButton#primary {
    background: %(accent)s;
    border: 1px solid %(accent)s;
    color: #FFFFFF;
    font-weight: bold;
}
QPushButton#primary:hover {
    background: #0A73D9;
    color: #FFFFFF;
}
QPushButton#danger {
    background: %(danger)s;
    border: 1px solid %(danger)s;
    color: #FFFFFF;
    font-weight: bold;
}
QPushButton#danger:hover {
    background: #E04444;
    color: #FFFFFF;
}
QPushButton#dangerOutline {
    background: #FFFFFF;
    border: 1px solid %(danger)s;
    color: %(danger)s;
}
QPushButton#dangerOutline:hover {
    background: #FDF0F0;
}
QPushButton#bigPrimary {
    background: %(accent)s;
    border: none;
    border-radius: 10px;
    color: #FFFFFF;
    font-size: 18px;
    font-weight: bold;
    padding: 14px;
}
QPushButton#bigPrimary:hover {
    background: #0A73D9;
}
/* ---------- 输入框 ---------- */
QLineEdit, QComboBox, QDateEdit, QSpinBox {
    background: #FFFFFF;
    border: 1px solid %(border)s;
    border-radius: 8px;
    padding: 6px 10px;
    selection-background-color: %(accent)s;
}
QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QSpinBox:focus {
    border-color: %(accent)s;
}
QLineEdit#snInput {
    font-size: 30px;      /* 录入的 SN 字号加大，便于核对 */
    padding: 20px 16px;
    border: 2px solid %(accent)s;
    border-radius: 12px;
}
/* 下拉框 / 日期框：右侧下拉按钮 + 箭头 */
QComboBox::drop-down, QDateEdit::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: center right;
    width: 26px;
    border: none;
    border-top-right-radius: 8px;
    border-bottom-right-radius: 8px;
    background: #F4F6F8;
}
QComboBox::drop-down:hover, QDateEdit::drop-down:hover {
    background: #E9EDF2;
}
QComboBox::down-arrow, QDateEdit::down-arrow {
    image: url(%(arrow)s);
    width: 14px;
    height: 14px;
}
QComboBox::down-arrow:disabled, QDateEdit::down-arrow:disabled {
    image: url(%(arrow)s);
}
/* 微调框（QSpinBox）上下按钮：
   ★ 三个关键点，缺一个就会出现「按钮方块盖住输入框」的问题：
   1) subcontrol-origin 用 padding（不是 border）——这样按钮区落在边框**内侧**，
      外框线才会完整地绕过右上 / 右下圆角；
   2) 必须给 border-top-right-radius / border-bottom-right-radius 8px，
      否则 Qt 画的是直角方块，会戳出圆角外；
   3) 不要写死 height，交给 Qt 上下均分（写死百分比高度会让上按钮消失）。
   右侧这块灰底与下拉框、日期框的 drop-down 写法保持一致。 */
QSpinBox {
    padding: 6px 26px 6px 10px;
    min-height: 22px;
}
QSpinBox::up-button {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 22px;
    background: #F4F6F8;
    border: none;
    border-left: 1px solid %(border)s;
    border-top-right-radius: 8px;
}
QSpinBox::down-button {
    subcontrol-origin: padding;
    subcontrol-position: bottom right;
    width: 22px;
    background: #F4F6F8;
    border: none;
    border-left: 1px solid %(border)s;
    border-bottom-right-radius: 8px;
}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {
    background: #E9EDF2;
}
QSpinBox::up-arrow {
    image: url(%(spin_up)s);
    width: 11px;
    height: 11px;
}
QSpinBox::down-arrow {
    image: url(%(spin_down)s);
    width: 11px;
    height: 11px;
}
QSpinBox::up-arrow:disabled, QSpinBox::up-arrow:off {
    image: url(%(spin_up)s);
}
QSpinBox::down-arrow:disabled, QSpinBox::down-arrow:off {
    image: url(%(spin_down)s);
}
QComboBox QAbstractItemView {
    border: 1px solid %(border)s;
    selection-background-color: #E5EEF9;
    selection-color: %(text)s;
}
/* ---------- 表格 ---------- */
QTableWidget {
    background: #FFFFFF;
    border: 1px solid %(border)s;
    border-radius: 10px;
    gridline-color: #F0F1F4;
    selection-background-color: #E5EEF9;
    selection-color: %(text)s;
}
QTableWidget::item {
    padding: 6px;
    border: none;
}
QHeaderView::section {
    background: #FFFFFF;
    border: none;
    border-bottom: 1px solid %(border)s;
    padding: 8px 6px;
    font-weight: bold;
    color: %(text)s;
}
/* 产品表 / 字段映射表：选中态必须一眼可辨——
   默认的浅蓝底（#E5EEF9）在白底表格上几乎看不出来是哪一行被选中 */
QTableWidget#productTable, QTableWidget#fieldTable {
    selection-background-color: %(accent)s;
    selection-color: #FFFFFF;
}
QTableWidget#productTable::item:selected, QTableWidget#fieldTable::item:selected {
    background: %(accent)s;
    color: #FFFFFF;
}
/* ---------- 规则列表（箱号规则 / SN 规则） ---------- */
QTableWidget#ruleTable {
    background: #FFFFFF;
    border: 1px solid %(border)s;
    border-radius: 2px;
    selection-background-color: %(accent)s;
    selection-color: #FFFFFF;
}
QTableWidget#ruleTable::item {
    padding: 4px 8px;
}
QTableWidget#ruleTable::item:selected {
    background: %(accent)s;
    color: #FFFFFF;
}
QTableWidget#ruleTable QHeaderView::section {
    background: #FFFFFF;
    border: none;
    border-bottom: 1px solid %(border)s;
    padding: 10px 6px;
    font-weight: bold;
    color: %(text)s;
}
QTableWidget#ruleTable QTableCornerButton::section {
    background: #FFFFFF;
    border: none;
}
/* ---------- 规则编辑对话框 ---------- */
QDialog#ruleDialog {
    background: #FFFFFF;
    border: 1px solid #D6DAE0;
}
QWidget#dlgTitleBar {
    background: #FFFFFF;
    border-bottom: 1px solid %(border)s;
}
QLabel#dlgTitle {
    font-size: 15px;
    color: %(text)s;
}
QPushButton#dlgClose {
    border: none;
    background: transparent;
    font-size: 16px;
    color: #5A6068;
}
QPushButton#dlgClose:hover {
    background: #E81123;
    color: #FFFFFF;
}
QLabel#dlgSection {
    font-size: 14px;
    font-weight: bold;
    color: %(text)s;
}
QPlainTextEdit#helpBox {
    background: #FFFFFF;
    border: 1px solid #D6DAE0;
    border-radius: 2px;
    padding: 8px;
    font-family: "Consolas", "Microsoft YaHei", monospace;
    font-size: 13px;
    color: #2A2E33;
    selection-background-color: %(accent)s;
}
QPushButton#previewBtn {
    background: #FFFFFF;
    border: 1px dashed #9AA3AE;
    border-radius: 4px;
    color: %(text)s;
    padding: 7px 0;
}
QPushButton#previewBtn:hover {
    border-color: %(accent)s;
    color: %(accent)s;
}
/* 打印页「未打印草稿」提示：橙色系提示条，区别于错误红 */
QLabel#draftHint {
    color: #B25E00;
    background: #FFF6E6;
    border: 1px solid #FFE0B2;
    border-radius: 8px;
    padding: 8px 10px;
    font-size: 12px;
}
/* 规则编辑对话框里的占位符快捷插入按钮 */
QPushButton#tokenBtn {
    background: #F4F6F8;
    border: 1px solid #DDE1E7;
    border-radius: 6px;
    padding: 4px 10px;
    font-size: 12px;
    font-family: "Consolas", "Microsoft YaHei", monospace;
    color: #2A2E33;
}
QPushButton#tokenBtn:hover {
    background: #E5EEF9;
    border-color: %(accent)s;
    color: %(accent)s;
}
/* ---------- 其他 ---------- */
QTabWidget::pane {
    border: 1px solid %(border)s;
    border-radius: 10px;
    top: -1px;
}
QTabBar::tab {
    background: transparent;
    border: none;
    padding: 10px 22px;
    color: %(text)s;
}
QTabBar::tab:selected {
    color: %(accent)s;
    font-weight: bold;
    border-bottom: 2px solid %(accent)s;
}
QLabel#sectionTitle {
    font-size: 13px;
    color: %(text_secondary)s;
}
QLabel#bigRed {
    color: %(danger)s;
    font-size: 34px;
    font-weight: bold;
}
/* 字体属性一律不写在这里：QSS 里只要出现 font-* 就会覆盖 QWidget.setFont()，
   而箱号字号需要按可用宽度动态缩放（见 PrintPage._fit_box_no_font） */
QLabel#boxNo {
    color: %(danger)s;
}
QLabel#statusNotPrinted {
    color: %(danger)s;
    font-size: 22px;
    font-weight: bold;
}
QLabel#statusPrinted {
    color: %(success)s;
    font-size: 22px;
    font-weight: bold;
}
QLabel#detailLabel {
    color: %(text_secondary)s;
    font-size: 11px;
}
QLabel#detailValue {
    font-size: 14px;
}
QCheckBox {
    spacing: 6px;
}
QScrollBar:vertical {
    background: transparent;
    width: 8px;
}
QScrollBar::handle:vertical {
    background: #D0D4DA;
    border-radius: 4px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QToolTip {
    background: #FFFFFF;
    border: 1px solid %(border)s;
    padding: 6px;
}
QMessageBox QPushButton {
    min-width: 72px;
}
""" % {
    "font": FONT_FAMILY,
    "accent": ACCENT,
    "text": TEXT,
    "text_secondary": TEXT_SECONDARY,
    "border": BORDER,
    "card_bg": CARD_BG,
    "danger": DANGER,
    "success": SUCCESS,
    "arrow": _arrow_url(),
    "spin_up": _spin_arrow_url("up"),
    "spin_down": _spin_arrow_url("down"),
}
