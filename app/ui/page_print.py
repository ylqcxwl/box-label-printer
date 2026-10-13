# -*- coding: utf-8 -*-
"""打印标签页面（对齐设计稿第 1 页）。

左侧：产品搜索、产品列表、产品详情（三列）、生产日期/批次、
      当前箱号（红色大字）+ 打印状态、SN 输入框、手动打印按钮。
右侧：今日装箱数（红色大字）、SN 列表（含序号）、全选/删除按钮。
"""

from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from PyQt5.QtCore import QDate, Qt, QThread, pyqtSignal
from PyQt5.QtGui import QFontMetrics
from PyQt5.QtWidgets import (QCheckBox, QComboBox, QDateEdit, QFileDialog,
                             QFrame, QGridLayout, QHBoxLayout, QHeaderView,
                             QLabel, QLineEdit, QMessageBox, QPushButton,
                             QSizePolicy, QTableWidget, QTableWidgetItem,
                             QVBoxLayout, QWidget)

from app.core import listconfig
from app.core import rules as rule_engine
from app.core.bartender import BarTender, PrintError
from app.core.db import DB, KIND_PRINT
from app.config import ROOT

DETAIL_COLS = [
    ["mingcheng", "guige", "xinghao", "yanse"],           # 第一列
    ["sn4", "sku", "code69", "shuliang"],                 # 第二列
    ["sn_rule", "box_rule", "template"],                  # 第三列
]
PRODUCT_TABLE_COLS = ["mingcheng", "guige", "xinghao", "yanse", "sn4", "code69"]

PRODUCT_ROW_HEIGHT = 36      # 产品列表行高
MIN_PRODUCT_ROWS = 2         # 窗口压缩到最小时仍保留的产品行数

# 箱号字号（放大一倍：原 26px -> 52px）与自适应下限
BOX_NO_FONT_MAX = 52
BOX_NO_FONT_MIN = 22


class PrintWorker(QThread):
    """打印线程（避免 COM 调用阻塞界面）。"""
    ok = pyqtSignal(str, list)   # box_no, [(seq, sn), ...]
    fail = pyqtSignal(str)

    def __init__(self, bartender: BarTender, template: Path,
                 data: Dict[str, str], printer: str, box_no: str,
                 sn_pairs: list):
        super().__init__()
        self._bt = bartender
        self._template = template
        self._data = data
        self._printer = printer
        self._box_no = box_no
        self._sn_pairs = sn_pairs

    def run(self) -> None:
        try:
            self._bt.print_label(self._template, self._data,
                                 self._printer or None, copies=1)
            self.ok.emit(self._box_no, self._sn_pairs)
        except PrintError as exc:
            self.fail.emit(str(exc))
        except Exception as exc:
            self.fail.emit(f"打印异常：{exc}")


class PrintPage(QWidget):
    """打印标签页。"""

    def __init__(self, db: DB, bartender: BarTender, parent=None):
        super().__init__(parent)
        self.db = db
        self.bartender = bartender
        self.products: List[Dict] = []
        self.current: Optional[Dict] = None
        self._worker: Optional[PrintWorker] = None
        self._last_print_ok = False
        self._build_ui()
        self.reload()

    # ================= UI =================

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(16)

        # ---------- 左侧 ----------
        left = QVBoxLayout()
        left.setSpacing(12)
        self._left_layout = left

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("输入 SN 前缀或 69 码 / 产品名称搜索")
        self.search_edit.textChanged.connect(self._fill_product_table)
        left.addWidget(self.search_edit)

        # 列由「设置 - 列表设置 - 打印页产品列表」决定，首次填充时按配置生成表头
        self.product_table = QTableWidget(0, len(PRODUCT_TABLE_COLS))
        self.product_table.verticalHeader().setVisible(False)
        self.product_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.product_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.product_table.setSelectionMode(QTableWidget.SingleSelection)
        # 各列等分宽度：与查询结果无关，筛选时列宽不会跳动
        self.product_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        # 上下拉伸窗口时，只有本表格随之伸缩：
        #  - 设行高与表头高度，保证「最少 2 行」有确定的最小高度；
        #  - 用 Expanding 策略 + 拉伸因子 1，让多余空间全部给产品列表。
        self.product_table.horizontalHeader().setFixedHeight(38)
        self.product_table.verticalHeader().setDefaultSectionSize(PRODUCT_ROW_HEIGHT)
        self.product_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.product_table.setMinimumHeight(
            38 + PRODUCT_ROW_HEIGHT * MIN_PRODUCT_ROWS + 2)
        self.product_table.itemSelectionChanged.connect(self._on_select_product)
        left.addWidget(self.product_table, 1)

        # 产品详情（三列）：横向占满整列，纵向按内容固定（不参与拉伸压缩）
        detail_card = QFrame()
        detail_card.setObjectName("card")
        detail_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self.detail_card = detail_card
        detail_layout = QVBoxLayout(detail_card)
        # 收紧内边距与行距，压缩详情区总高度（需求：详情区高度减小）
        detail_layout.setContentsMargins(12, 6, 12, 8)
        detail_layout.setSpacing(2)
        detail_layout.addWidget(self._section("产品详情"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(24)
        self.detail_widgets: Dict[str, QLabel] = {}
        for col, keys in enumerate(DETAIL_COLS):
            col_layout = QVBoxLayout()
            col_layout.setSpacing(3)
            for fkey in keys:
                lbl = QLabel("")
                lbl.setObjectName("detailLabel")
                val = QLabel("-")
                val.setObjectName("detailValue")
                val.setWordWrap(True)
                self.detail_widgets[fkey] = (lbl, val)
                col_layout.addWidget(lbl)
                col_layout.addWidget(val)
            col_layout.addStretch(1)
            grid.addLayout(col_layout, 0, col)
        detail_layout.addLayout(grid)
        left.addWidget(detail_card, 0)

        # 生产日期 + 批次
        date_row = QHBoxLayout()
        date_row.addWidget(QLabel("生产日期"))
        self.date_edit = QDateEdit(QDate.currentDate())
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        self.date_edit.dateChanged.connect(self._on_date_changed)
        date_row.addWidget(self.date_edit, 1)
        date_row.addWidget(QLabel("批次"))
        self.batch_combo = QComboBox()
        self.batch_combo.addItems([str(i) for i in range(10)])
        self.batch_combo.currentTextChanged.connect(self._on_batch_changed)
        date_row.addWidget(self.batch_combo, 1)
        left.addLayout(date_row)

        # 当前箱号 + 状态（上下留白收窄，箱号占更多视觉重心）
        box_card = QFrame()
        box_card.setObjectName("whiteCard")
        self.box_card = box_card
        box_layout = QVBoxLayout(box_card)
        box_layout.setContentsMargins(14, 4, 14, 6)
        box_layout.setSpacing(2)
        head = QHBoxLayout()
        head.addWidget(self._section("当前箱号"))
        head.addStretch(1)
        self.status_label = QLabel("未打印")
        self.status_label.setObjectName("statusNotPrinted")
        head.addWidget(self.status_label)
        box_layout.addLayout(head)
        self.box_no_label = QLabel("-")
        self.box_no_label.setObjectName("boxNo")
        self.box_no_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        base_font = self.box_no_label.font()
        base_font.setPixelSize(BOX_NO_FONT_MAX)   # 箱号放大一倍（原 26px）
        base_font.setBold(True)
        self.box_no_label.setFont(base_font)
        box_layout.addWidget(self.box_no_label)
        left.addWidget(box_card)

        # SN 输入
        self.sn_input = QLineEdit()
        self.sn_input.setObjectName("snInput")
        self.sn_input.setPlaceholderText("扫描或输入 SN（按该产品的 SN 规则自动校验）")
        self.sn_input.returnPressed.connect(self._add_sn)
        left.addWidget(self.sn_input)

        self.manual_btn = QPushButton("手动打印标签")
        self.manual_btn.setObjectName("bigPrimary")
        self.manual_btn.clicked.connect(lambda: self._do_print(manual=True))
        left.addWidget(self.manual_btn)

        root.addLayout(left, 3)

        # ---------- 右侧 ----------
        right = QVBoxLayout()
        right.setSpacing(12)

        count_card = QFrame()
        count_card.setObjectName("whiteCard")
        count_layout = QVBoxLayout(count_card)
        count_layout.setContentsMargins(14, 10, 14, 12)
        self.count_title = self._section("今日装箱数")
        count_layout.addWidget(self.count_title)
        self.count_label = QLabel("0 箱")
        self.count_label.setObjectName("bigRed")
        count_layout.addWidget(self.count_label)
        right.addWidget(count_card)

        sn_card = QFrame()
        sn_card.setObjectName("whiteCard")
        sn_layout = QVBoxLayout(sn_card)
        sn_layout.setContentsMargins(14, 10, 14, 12)
        sn_head = QHBoxLayout()
        sn_head.addWidget(self._section("SN 列表"))
        sn_head.addStretch(1)
        self.sn_count_label = QLabel("已录入 0 / 0")
        self.sn_count_label.setStyleSheet("color:#0066CC;")
        sn_head.addWidget(self.sn_count_label)
        sn_layout.addLayout(sn_head)

        self.sn_table = QTableWidget(0, 3)
        self.sn_table.setHorizontalHeaderLabels(["", "序号", "SN"])
        self.sn_table.verticalHeader().setVisible(False)
        self.sn_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.sn_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.sn_table.setColumnWidth(0, 32)
        self.sn_table.setColumnWidth(1, 60)
        sn_layout.addWidget(self.sn_table, 1)
        # 已录入但未打印时的提示：SN 与产品强绑定，换产品会自动清空，
        # 这里提前告知，避免录了一半换产品才发现白扫了
        self.draft_hint = QLabel("")
        self.draft_hint.setObjectName("draftHint")
        self.draft_hint.setWordWrap(True)
        self.draft_hint.hide()
        sn_layout.addWidget(self.draft_hint)
        right.addWidget(sn_card, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.select_all_btn = QPushButton("全选")
        self.select_all_btn.clicked.connect(self._toggle_select_all)
        btn_row.addWidget(self.select_all_btn)
        self.del_btn = QPushButton("删除所选（重排序号）")
        self.del_btn.setObjectName("dangerOutline")
        self.del_btn.clicked.connect(self._delete_selected_sn)
        btn_row.addWidget(self.del_btn)
        right.addLayout(btn_row)

        root.addLayout(right, 2)

    def _section(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("sectionTitle")
        return lbl

    def _set_box_no(self, text: str) -> None:
        """设置箱号文本，并按可用宽度自动调整字号。

        Args:
            text: 箱号文本（长度随规则不同差异很大）
        """
        self.box_no_label.setText(text)
        self._fit_box_no_font()

    def _fit_box_no_font(self) -> None:
        """把箱号字号缩放到「刚好放得下」：宽度够时保持放大的 52px，
        长箱号或窄窗口时按比例缩小，避免被截断成省略号。
        """
        label = self.box_no_label
        text = label.text()
        if not text:
            return
        avail = max(label.width() - 6, 40)   # 留一点余量，避免贴边
        font = label.font()
        for size in range(BOX_NO_FONT_MAX, BOX_NO_FONT_MIN - 1, -2):
            font.setPixelSize(size)
            if QFontMetrics(font).horizontalAdvance(text) <= avail:
                break
        label.setFont(font)
        # QLabel 的 minimumSizeHint 很小，布局会把它压扁导致箱号上下被裁；
        # 这里把最小高度锁成当前字号的文本高度
        label.setMinimumHeight(QFontMetrics(font).height() + 2)

    def apply_detail_height(self) -> None:
        """把产品详情卡片的最小高度锁定为内容高度。

        为什么必须显式锁定：详情值是可换行的 QLabel，其 minimumSizeHint 很小，
        仅靠 QSizePolicy 仍会被主布局在纵向拉伸时压缩变形。
        在布局激活后按真实宽度算出的 sizeHint 才是准确的内容高度。
        """
        card = getattr(self, "detail_card", None)
        if card is None:
            return
        height = card.sizeHint().height()
        if card.minimumHeight() != height:
            card.setMinimumHeight(height)
        # 宽度变了，可用空间随之变化，箱号字号要重新适配
        self._fit_box_no_font()
        self.lock_fixed_heights()

    def lock_fixed_heights(self) -> None:
        """把不参与伸缩的区域锁成「内容高度」。

        为什么必须锁：QLabel / QFrame 的 minimumSizeHint 往往远小于实际内容，
        窗口被压到很矮时 Qt 会继续压缩它们，导致箱号、按钮等区域互相重叠
        （曾出现下方区域盖住产品详情区的现象）。锁住后布局的最小高度才是真实需求。
        """
        self.detail_card.setMinimumHeight(self.detail_card.sizeHint().height())
        self.box_card.setMinimumHeight(self.box_card.sizeHint().height())
        for widget in (self.search_edit, self.sn_input, self.manual_btn):
            hint = widget.sizeHint().height()
            if widget.minimumHeight() != hint:
                widget.setMinimumHeight(hint)

    def min_content_height(self) -> int:
        """返回本页内容所需的最小高度（左列固定区域 + 产品列表 2 行）。

        用于设置窗口最小高度：直接加总各固定区域的最小高度，
        比依赖布局的 minimumSizeHint 可靠（后者受 QLabel 偏小的 minimumSizeHint 影响）。
        """
        root_margins = self.layout().contentsMargins()
        left = self._left_layout
        date_row_h = max(self.date_edit.sizeHint().height(),
                         self.batch_combo.sizeHint().height())
        fixed = (self.search_edit.minimumHeight()
                 + self.detail_card.minimumHeight()
                 + date_row_h
                 + self.box_card.minimumHeight()
                 + self.sn_input.minimumHeight()
                 + self.manual_btn.minimumHeight())
        return (root_margins.top() + root_margins.bottom() + fixed
                + left.spacing() * 6
                + self.product_table.minimumHeight())

    # 说明：宽度变化会改变详情值 QLabel 的换行行数、进而改变内容高度，
    # 因此由主窗口在拉伸结束后的防抖回调里调用 apply_detail_height() 重算，
    # 而不是在 resizeEvent 里逐帧重算（会额外增加布局开销、加剧拖动掉帧）。

    # ================= 数据 =================

    def reload(self) -> None:
        """进入页面时刷新产品与暂存状态。"""
        self.products = self.db.list_products()
        self._fill_product_table()
        self._restore_selection()

    def refresh_rules(self) -> None:
        """设置变更后刷新箱号预览。"""
        self._refresh_box_no()

    def _product_columns(self) -> List[Dict[str, Any]]:
        """打印页产品列表的显示列（可在「设置 - 列表设置」中配置）。

        全部取消勾选时回退到内置默认列：该表格既是选择器也是数据展示，
        一列都没有会导致行无法选中，进而点不了产品。
        """
        cols = listconfig.visible_columns(self.db, "print_product_columns")
        if cols:
            return cols
        return [{"id": "field:" + k, "label": ""} for k in PRODUCT_TABLE_COLS]

    def _fill_product_table(self) -> None:
        keyword = self.search_edit.text().strip()
        cols = self._product_columns()
        self.product_table.blockSignals(True)
        self.product_table.setColumnCount(len(cols))
        self.product_table.setHorizontalHeaderLabels([c["label"] for c in cols])
        self.product_table.setRowCount(0)
        keys = [listconfig.field_key(c["id"]) for c in cols]
        for p in self.products:
            if keyword:
                hay = " ".join(str(p.get(k, "")) for k in
                               ("sn4", "code69", "mingcheng")).lower()
                if keyword.lower() not in hay:
                    continue
            row = self.product_table.rowCount()
            self.product_table.insertRow(row)
            for col, fkey in enumerate(keys):
                item = QTableWidgetItem(str(p.get(fkey, "")))
                item.setData(Qt.UserRole, p["_id"])
                self.product_table.setItem(row, col, item)
        self.product_table.blockSignals(False)

    def _restore_selection(self) -> None:
        if self.current:
            for row in range(self.product_table.rowCount()):
                item = self.product_table.item(row, 0)
                if item and item.data(Qt.UserRole) == self.current.get("_id"):
                    self.product_table.selectRow(row)
                    return

    def _on_select_product(self) -> None:
        rows = self.product_table.selectionModel().selectedRows()
        if not rows:
            return
        pid = self.product_table.item(rows[0].row(), 0).data(Qt.UserRole)
        # 需求：录入 SN 未满整箱、未手动打印就换产品时，已录 SN 全部作废，
        # 切回来也要重新录入。SN 与产品强绑定，留着旧产品的 SN 极易被误打进
        # 新产品的标签里，因此切换即清空（整箱已打印时列表本来就是空的）。
        old = self.current
        if old is not None and int(old.get("_id", 0)) != int(pid):
            self.db.clear_product_drafts(int(old["_id"]))
        self.current = self.db.get_product(pid)
        self._last_print_ok = False
        self._fill_detail()
        self._load_drafts()
        self._refresh_box_no()
        self._refresh_today_count()

    def _fill_detail(self) -> None:
        fields = {f["fkey"]: f["label"] for f in self.db.list_fields()}
        for fkey, (lbl, val) in self.detail_widgets.items():
            lbl.setText(fields.get(fkey, fkey))
            text = str(self.current.get(fkey, "") or "-") if self.current else "-"
            if fkey == "shuliang" and text != "-":
                text = f"{text} 只/箱"
            val.setText(text)

    # ================= 箱号 =================

    def _current_batch(self) -> str:
        return self.batch_combo.currentText()

    def _current_date(self) -> date:
        d = self.date_edit.date()
        return date(d.year(), d.month(), d.day())

    def _box_rule_pattern(self) -> str:
        if not self.current:
            return ""
        name = str(self.current.get("box_rule", ""))
        rule = self.db.get_box_rule(name)
        return rule["pattern"] if rule else ""

    def _refresh_box_no(self) -> None:
        if not self.current:
            self._set_box_no("-")
            return
        pattern = self._box_rule_pattern()
        if not pattern:
            self._set_box_no("（未选择箱号规则）")
            return
        day = self._current_date()
        month = day.strftime("%Y-%m")
        batch = self._current_batch()
        scope = self.db.box_counter_scope(self.current)
        seq = self.db.peek_counter(scope, month, batch)
        box_no = rule_engine.render_box_no(
            pattern, day=day, seq=seq, batch=batch,
            factory=self.db.get_setting("factory_code", ""),
            prefix=str(self.current.get("sn4", "")))
        self._set_box_no(box_no)
        self._update_status()

    def _on_date_changed(self) -> None:
        """生产日期变更：箱号中的日期占位符随之变化，并切换到该日期的箱数据。

        暂存 SN 按「产品 + 批次 + 生产日期」隔离，日期一变必须重新加载，
        否则会把别的日期的 SN 混进当前箱。
        """
        if self.current:
            self._load_drafts()
        self._refresh_box_no()
        self._refresh_today_count()

    def _on_batch_changed(self) -> None:
        if self.current:
            self._load_drafts()
        self._refresh_box_no()
        self._refresh_today_count()

    def _update_status(self) -> None:
        printed = self._last_print_ok and self.sn_table.rowCount() == 0
        self.status_label.setText("打印完成" if printed else "未打印")
        self.status_label.setObjectName("statusPrinted" if printed
                                        else "statusNotPrinted")
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

    def _refresh_today_count(self) -> None:
        if not self.current:
            self.count_label.setText("0 箱")
            self.count_title.setText("今日装箱数")
            return
        n = self.db.today_boxes(self.current, self._current_batch())
        # 共用计数的规则下，箱号跨产品连续，故标题标明规则名而非产品名
        if self._is_shared_rule():
            title = f"今日装箱数 · {self.current.get('box_rule', '')}（共用计数）"
        else:
            title = f"今日装箱数 · {self.current.get('mingcheng', '')}"
        self.count_title.setText(f"{title} / 批次 {self._current_batch()}")
        self.count_label.setText(f"{n} 箱")

    def _is_shared_rule(self) -> bool:
        """当前产品的箱号规则是否使用共用计数（{&}）。"""
        pattern = self._box_rule_pattern()
        return rule_engine.is_shared_rule(pattern)

    # ================= SN 列表 =================

    def _load_drafts(self) -> None:
        self.sn_table.setRowCount(0)
        if not self.current:
            return
        drafts = self.db.list_drafts(
            self.current["_id"], self._current_batch(),
            self._current_date().strftime("%Y-%m-%d"))
        for d in drafts:
            self._append_sn_row(d["sn"], d["id"])
        self._refresh_sn_count()
        self._refresh_draft_hint()

    def _refresh_draft_hint(self) -> None:
        """当前箱已录但未打印时的提示条。

        切换产品会自动清空这些 SN（SN 与产品强绑定，留着会被误打进别的
        产品标签），这里提前告知，避免录了一半换产品才发现白扫了。
        """
        label = getattr(self, "draft_hint", None)
        if label is None:
            return
        n = self.sn_table.rowCount()
        if not self.current or n == 0:
            label.hide()
            label.setText("")
            return
        total = self._box_capacity()
        tail = f"（整箱 {total} 只，还差 {total - n} 只）" if total else ""
        label.setText(
            f"当前箱已录入 {n} 条 SN，尚未打印{tail}："
            "更换产品会自动清空，切回来也需重新录入。")
        label.show()

    def _box_capacity(self) -> int:
        """整箱容量（只/箱），取不到时返回 0。"""
        if not self.current:
            return 0
        try:
            return int(str(self.current.get("shuliang", "")).strip())
        except (TypeError, ValueError):
            return 0

    def _append_sn_row(self, sn: str, draft_id: Optional[int]) -> None:
        row = self.sn_table.rowCount()
        self.sn_table.insertRow(row)
        chk = QCheckBox()
        chk_widget = QWidget()
        lay = QHBoxLayout(chk_widget)
        lay.addWidget(chk)
        lay.setAlignment(Qt.AlignCenter)
        lay.setContentsMargins(0, 0, 0, 0)
        self.sn_table.setCellWidget(row, 0, chk_widget)
        seq_item = QTableWidgetItem(str(row + 1))
        seq_item.setTextAlignment(Qt.AlignCenter)
        self.sn_table.setItem(row, 1, seq_item)
        sn_item = QTableWidgetItem(sn)
        sn_item.setData(Qt.UserRole, draft_id)
        self.sn_table.setItem(row, 2, sn_item)

    def _resequence(self) -> None:
        for row in range(self.sn_table.rowCount()):
            self.sn_table.item(row, 1).setText(str(row + 1))

    def _refresh_sn_count(self) -> None:
        total = int(self.current.get("shuliang", 0) or 0) if self.current else 0
        self.sn_count_label.setText(f"已录入 {self.sn_table.rowCount()} / {total}")

    def _add_sn(self) -> None:
        if not self.current:
            QMessageBox.warning(self, "提示", "请先选择产品")
            return
        sn = self.sn_input.text().strip()
        self.sn_input.clear()
        if not sn:
            return

        # 1. 按 SN 规则校验（不再单独强制「必须以前缀开头」）
        #    规则里写了 {PREFIX} 就按其所在位置校验；没写就不要求含前缀。
        prefix = str(self.current.get("sn4", ""))
        rule_name = str(self.current.get("sn_rule", ""))
        rule = self.db.get_sn_rule(rule_name) if rule_name else None
        if rule:
            ok, msg = rule_engine.validate_sn(
                rule["pattern"], sn, prefix=prefix,
                batch=self._current_batch(),
                factory=self.db.get_setting("factory_code", ""),
                total_len=rule.get("total_len", 0))
            if not ok:
                QMessageBox.warning(self, "SN 错误", msg)
                return
        # 3. 数据追溯：已存档 SN 禁止录入
        if self.db.sn_exists(sn):
            QMessageBox.warning(self, "重复录入",
                                f"SN {sn} 已打印存档，禁止重复录入")
            return
        # 4. 当前箱内重复
        for row in range(self.sn_table.rowCount()):
            if self.sn_table.item(row, 2).text() == sn:
                QMessageBox.warning(self, "重复录入", f"SN {sn} 已在当前箱内")
                return
        # 5. 超出整箱数
        total = int(self.current.get("shuliang", 0) or 0)
        if total and self.sn_table.rowCount() >= total:
            QMessageBox.warning(self, "已满箱", "当前箱已满，请打印后再录入")
            return

        seq = self.sn_table.rowCount() + 1
        produce_date = self._current_date().strftime("%Y-%m-%d")
        self.db.add_draft(self.current["_id"], self._current_batch(),
                          produce_date, sn, seq)
        draft_id = self.db.query(
            "SELECT id FROM drafts WHERE product_id=? AND batch=? AND "
            "produce_date=? AND sn=?",
            (self.current["_id"], self._current_batch(), produce_date, sn)
        )[0]["id"]
        self._append_sn_row(sn, draft_id)
        self._refresh_sn_count()
        self._refresh_draft_hint()
        self._last_print_ok = False
        self._update_status()
        self.sn_input.setFocus()

        # 达到整箱数自动打印
        if total and self.sn_table.rowCount() >= total:
            self._do_print(manual=False)

    def _toggle_select_all(self) -> None:
        rows = self.sn_table.rowCount()
        if not rows:
            return
        all_checked = all(
            self.sn_table.cellWidget(r, 0).findChild(QCheckBox).isChecked()
            for r in range(rows))
        for r in range(rows):
            self.sn_table.cellWidget(r, 0).findChild(QCheckBox).setChecked(
                not all_checked)

    def _delete_selected_sn(self) -> None:
        ids, rows = [], []
        for r in range(self.sn_table.rowCount()):
            chk = self.sn_table.cellWidget(r, 0).findChild(QCheckBox)
            if chk.isChecked():
                rows.append(r)
                draft_id = self.sn_table.item(r, 2).data(Qt.UserRole)
                if draft_id:
                    ids.append(draft_id)
        if not rows:
            return
        self.db.remove_drafts(ids)
        for r in reversed(rows):
            self.sn_table.removeRow(r)
        self._resequence()
        if self.current:
            self.db.resequence_drafts(self.current["_id"], self._current_batch(),
                                      self._current_date().strftime("%Y-%m-%d"))
        self._refresh_sn_count()
        self._refresh_draft_hint()

    # ================= 打印 =================

    def _do_print(self, manual: bool) -> None:
        if not self.current:
            QMessageBox.warning(self, "提示", "请先选择产品")
            return
        if self._worker and self._worker.isRunning():
            return
        sns = [self.sn_table.item(r, 2).text()
               for r in range(self.sn_table.rowCount())]
        total = int(self.current.get("shuliang", 0) or 0)
        if not sns:
            QMessageBox.warning(self, "提示", "请先录入 SN")
            return
        if manual and total and len(sns) > total:
            QMessageBox.warning(self, "提示", "SN 数量超过整箱数")
            return

        pattern = self._box_rule_pattern()
        if not pattern:
            QMessageBox.warning(self, "提示", "产品未配置箱号规则，请先在产品管理中选择")
            return
        template_name = str(self.current.get("template", "")).strip()
        if not template_name:
            QMessageBox.warning(self, "提示", "产品未配置打印模板")
            return
        template_dir = self.db.get_setting("template_dir") or str(ROOT)
        template_path = Path(template_dir) / template_name

        day = self._current_date()
        batch = self._current_batch()
        month = day.strftime("%Y-%m")
        scope = self.db.box_counter_scope(self.current)
        seq = self.db.peek_counter(scope, month, batch)
        box_no = rule_engine.render_box_no(
            pattern, day=day, seq=seq, batch=batch,
            factory=self.db.get_setting("factory_code", ""),
            prefix=str(self.current.get("sn4", "")))

        # 组装打印数据：产品字段数据源 + 箱号（按映射的数据源名）+ 编号 SN
        data: Dict[str, str] = {}
        for f in self.db.list_fields():
            # 打印字段（箱号等）由程序自动填充，不从产品数据里取
            if int(f.get("kind", 0) or 0) == KIND_PRINT:
                continue
            value = str(self.current.get(f["fkey"], ""))
            # 手动打印不满箱时，装箱数量按实际数量
            if f["fkey"] == "shuliang" and manual and len(sns) < total:
                value = str(len(sns))
            data[f["datasource"]] = value
        # 箱号写进「字段映射」里配置的数据源名：
        # 模板里叫什么名字就填什么（默认 xianghao），这样箱号才能打印出来
        for f in self.db.list_print_fields():
            if f["fkey"] == "xianghao":
                data[f["datasource"]] = box_no
        pad_to = total if total else len(sns)
        for i in range(pad_to):
            data[str(i + 1)] = sns[i] if i < len(sns) else ""

        self._pending = {
            "box_no": box_no, "seq": seq, "month": month, "batch": batch,
            "produce_date": day.strftime("%Y-%m-%d"), "sns": sns,
            "manual": manual, "total": total, "scope": scope,
        }
        sn_pairs = list(enumerate(sns, start=1))
        self.manual_btn.setEnabled(False)
        self.manual_btn.setText("打印中…")
        self._worker = PrintWorker(
            self.bartender, template_path, data,
            self.db.get_setting("default_printer", ""), box_no, sn_pairs)
        self._worker.ok.connect(self._on_print_ok)
        self._worker.fail.connect(self._on_print_fail)
        self._worker.start()

    def _on_print_ok(self, box_no: str, sn_pairs: list) -> None:
        p = self._pending
        # 打印成功才提交流水号（不产生跳号）
        self.db.commit_counter(p["scope"], p["month"], p["batch"], p["seq"])
        # SN 数据存档（空值补齐不入档）
        snapshot = dict(self.current)
        snapshot["shuliang"] = (str(len(p["sns"])) if p["manual"]
                                and len(p["sns"]) < p["total"]
                                else str(self.current.get("shuliang", "")))
        for seq, sn in sn_pairs:
            self.db.add_record(box_no, seq, self.current["_id"], snapshot,
                               sn, p["batch"], p["produce_date"],
                               box_seq=p["seq"])
        # 清空当前箱
        self.db.clear_drafts(self.current["_id"], p["batch"], p["produce_date"])
        self.sn_table.setRowCount(0)
        self._refresh_sn_count()
        self._refresh_draft_hint()
        self._last_print_ok = True
        self._refresh_box_no()      # 刷新为下一箱号
        self._refresh_today_count()
        self._print_done()
        self.sn_input.setFocus()

    def _on_print_fail(self, msg: str) -> None:
        self._print_done()
        QMessageBox.critical(self, "打印失败", msg)

    def _print_done(self) -> None:
        self.manual_btn.setEnabled(True)
        self.manual_btn.setText("手动打印标签")
