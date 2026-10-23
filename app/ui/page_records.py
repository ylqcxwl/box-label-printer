# -*- coding: utf-8 -*-
"""打印记录页面（对齐设计稿第 2 页）。

查询：SN / 箱号 / 打印日期范围。
操作：全选、导出选中到 Excel、重打印该箱、删除选中（需密码）。
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PyQt5.QtCore import QDate, Qt, QThread, QTimer, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (QApplication, QDateEdit, QFileDialog, QFrame,
                             QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                             QMessageBox, QPushButton, QStyledItemDelegate,
                             QTableWidget, QTableWidgetItem, QVBoxLayout,
                             QWidget)

from app.core import excel_io, listconfig
from app.core.excel_io import cell_text
from app.core.print_data import build_label_data
from app.core.print_service import PrintService
from app.core.bartender import (BarTender, resolve_printer,
                               template_path as template_path_abs)
from app.core.db import DB, KIND_PRINT
from app.config import resolve_template_dir
from app.ui.table_util import freeze_widths

# 查询条件行的宽度约束。
# 输入框不再写死大宽度：窗口缩小时让它们等比缩小，而不是把整行挤到互相堆叠。
# 窗口最小宽度下这一行大约要占用：18+90+28+90+56+117+14+117+62 + 间距 ≈ 780px。
SN_EDIT_MIN = 90           # SN 输入框最小宽度
BOX_EDIT_MIN = 90          # 箱号输入框最小宽度
SN_STRETCH = 3             # SN 与箱号的空间分配比（箱号更长更常用，占比更大）
BOX_STRETCH = 4
DATE_EDIT_WIDTH = 126      # 日期框宽度：实测 "2026-12-31" 宽 74px，
                           # 再加左内边距 + 26px 下拉按钮 + 边框余量，126 足够且比原来（194）短很多
FILTER_DEBOUNCE_MS = 300   # 输入后多久自动刷新（避免每敲一个字符就查一次库）

# 已勾选行的底色：选中态要「一眼可辨」，浅蓝底在白表格上足够醒目又不刺眼
ROW_CHECKED_BG = QColor("#E3F0FF")


class RecordRowDelegate(QStyledItemDelegate):
    """给「已勾选」的记录整行铺底色。

    ★ 为什么不用 QTableWidgetItem.setBackground：
      本程序给表格套了全局 QSS，**QSS 会接管 item 的背景绘制** ——
      实测 setBackground 的值存进去了（background().color() 读得到），
      但屏幕上完全不显示（对照渲染证实）。
      所以改为在委托里先 fillRect 铺底色，再交给默认绘制处理文字与选中态，
      这样既能看到行底色，也不会丢掉原有的文字排版。
    """

    def __init__(self, table: QTableWidget, parent=None):
        super().__init__(parent)
        self._table = table

    def _checked(self, row: int) -> bool:
        """该行是否勾选（读第 0 列表格项的勾选状态）。

        ★ 原来是每行塞一个 QWidget+QCheckBox 当 cellWidget，
          1 万行就是 1 万个控件——实测 2.6 万行渲染要 17 分钟。
          改成 QTableWidgetItem 自带的勾选状态后，控件数量归零。
        """
        item = self._table.item(row, 0)
        return bool(item is not None
                    and item.checkState() == Qt.Checked)

    def paint(self, painter, option, index) -> None:
        # 整行一起铺（含第 0 列的勾选框列）：
        # 之前只铺 column>0、第 0 列靠给勾选框容器设样式表上色，
        # 但容器尺寸比单元格小一圈（实测 31x18 vs 44x31）且左偏，
        # 结果最左边是个小色块，跟右边铺满整行的蓝色对不齐。
        # 容器本身没有背景色（透明），所以委托铺的底色能透出来。
        if self._checked(index.row()):
            painter.fillRect(option.rect, ROW_CHECKED_BG)
        super().paint(painter, option, index)


def default_record_columns(db: DB) -> List[Dict[str, Any]]:
    """打印记录默认列（基础列 + 产品字段列 + 尾部列）。

    配置本身在 app/core/listconfig.py 统一维护，这里只做转发，
    方便其它模块（含打包前的验证脚本）继续沿用原函数名。
    """
    return listconfig.defaults("record_columns", db)


class RecordsPage(QWidget):
    """打印记录页。"""

    def __init__(self, db: DB, bartender: BarTender, parent=None,
                 print_service=None):
        super().__init__(parent)
        self.db = db
        self.bartender = bartender
        # ★ 与打印页共用同一个常驻打印线程，避免 BarTender 的 COM
        #   连接跨线程复用而报「BarTenderApplication.Formats」
        self._own_service = print_service is None
        self.print_service = print_service or PrintService(bartender, self)
        self._my_tasks: set = set()
        self._rows: List[Dict[str, Any]] = []
        self._width_cache: Dict[str, Any] = {}
        # Shift 范围选择的起点：上一次点击过的行号
        self._last_clicked_row: Optional[int] = None
        # 程序化修改勾选状态期间置 True，避免 itemChanged 递归
        self._applying: bool = False
        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(FILTER_DEBOUNCE_MS)
        self._filter_timer.timeout.connect(self.reload)
        self._build_ui()
        # 打开页面就用「系统设置 - 默认显示周期」初始化日期范围。
        # 先屏蔽信号再设日期，避免 setDate 触发多次 reload
        self.date_from.blockSignals(True)
        self.date_to.blockSignals(True)
        self._apply_default_range()
        self.date_from.blockSignals(False)
        self.date_to.blockSignals(False)
        self.reload()

    # ================= UI =================

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        # 查询条件行
        query_row = QHBoxLayout()
        query_row.setSpacing(10)
        query_row.addWidget(QLabel("SN"))
        self.sn_edit = QLineEdit()
        self.sn_edit.setPlaceholderText("输入 SN")
        self.sn_edit.setMinimumWidth(SN_EDIT_MIN)
        query_row.addWidget(self.sn_edit, SN_STRETCH)
        query_row.addWidget(QLabel("箱号"))
        self.box_edit = QLineEdit()
        self.box_edit.setPlaceholderText("输入箱号")
        self.box_edit.setMinimumWidth(BOX_EDIT_MIN)
        query_row.addWidget(self.box_edit, BOX_STRETCH)
        query_row.addWidget(QLabel("打印日期"))
        self.date_from = QDateEdit(QDate.currentDate().addMonths(-1))
        self.date_from.setCalendarPopup(True)
        self.date_from.setDisplayFormat("yyyy-MM-dd")
        query_row.addWidget(self.date_from)
        query_row.addWidget(QLabel("至"))
        self.date_to = QDateEdit(QDate.currentDate())
        self.date_to.setCalendarPopup(True)
        self.date_to.setDisplayFormat("yyyy-MM-dd")
        query_row.addWidget(self.date_to)
        for w in (self.date_from, self.date_to):
            w.setFixedWidth(DATE_EDIT_WIDTH)
        reset_btn = QPushButton("重置")
        reset_btn.clicked.connect(self._reset_filter)
        query_row.addWidget(reset_btn)
        # 不加尾部 addStretch：让多出来的宽度全部给两个输入框，
        # 窗口变窄时也由它们先让步，其它控件不会被挤到重叠
        root.addLayout(query_row)

        # 无需「查询」按钮：回车立即查询，输入停顿 300ms 也会自动刷新
        for w in (self.sn_edit, self.box_edit):
            w.returnPressed.connect(self._query_now)
            w.textChanged.connect(lambda *_: self._filter_timer.start())
        self.date_from.dateChanged.connect(lambda *_: self.reload())
        self.date_to.dateChanged.connect(lambda *_: self.reload())

        # 操作按钮行
        btn_row = QHBoxLayout()
        self.select_all_btn = QPushButton("全选")
        self.select_all_btn.clicked.connect(self._toggle_select_all)
        btn_row.addWidget(self.select_all_btn)
        export_btn = QPushButton("导出选中到 Excel")
        export_btn.setObjectName("primary")
        export_btn.clicked.connect(self._export_selected)
        btn_row.addWidget(export_btn)
        reprint_btn = QPushButton("重打印该箱")
        reprint_btn.setStyleSheet(
            "QPushButton{background:#1E9E50;border:1px solid #1E9E50;"
            "border-radius:8px;color:#FFFFFF;font-weight:bold;padding:7px 16px;}"
            "QPushButton:hover{background:#27B25E;color:#FFFFFF;}")
        reprint_btn.clicked.connect(self._reprint_box)
        btn_row.addWidget(reprint_btn)
        del_btn = QPushButton("删除选中")
        del_btn.setObjectName("danger")
        del_btn.clicked.connect(self._delete_selected)
        btn_row.addWidget(del_btn)
        btn_row.addStretch(1)
        self.count_label = QLabel("共 0 条")
        self.count_label.setObjectName("sectionTitle")
        btn_row.addWidget(self.count_label)
        # 操作提示：Shift 范围选择是隐藏功能，不写出来没人知道
        hint = QLabel("按住 Shift 点勾选框可一次选一整段")
        hint.setObjectName("recordHint")
        btn_row.addWidget(hint)
        root.addLayout(btn_row)

        # 记录表格
        self.table = QTableWidget(0, 2)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        # 勾选整行的底色靠委托绘制（QSS 会盖掉 setBackground，见委托注释）
        self.table.setItemDelegate(RecordRowDelegate(self.table, self.table))
        # 勾选列用的是表格项自带的勾选框，所以监听 itemChanged
        self.table.itemChanged.connect(self._on_item_changed)
        root.addWidget(self.table, 1)

    # ================= 列配置 =================

    def record_columns(self) -> List[Tuple[str, str]]:
        """读取打印记录显示列（可在「设置 - 列表设置」中勾选/排序）。"""
        return [(c["id"], c["label"])
                for c in listconfig.visible_columns(self.db, "record_columns")]

    def default_columns(self) -> List[Dict[str, Any]]:
        return listconfig.defaults("record_columns", self.db)

    # ================= 数据 =================

    def _query_now(self) -> None:
        """回车立即查询（同时取消还在等待的防抖刷新）。"""
        self._filter_timer.stop()
        self.reload()

    #: 系统设置里可选的默认显示周期 -> 起始日期偏移（天）
    RANGE_OFFSETS = {"1d": 0, "7d": 6, "30d": 29, "90d": 89, "365d": 364}

    def _apply_default_range(self) -> None:
        """按「系统设置 - 打印记录页默认显示周期」设置日期范围。

        all 表示不限制起始日期（用一个足够早的日期），
        其余按天数往前推：1d=今天、7d=近一周、30d=近一月…
        """
        key = (self.db.get_setting("record_default_range") or "30d").strip()
        today = QDate.currentDate()
        if key == "all":
            self.date_from.setDate(QDate(2000, 1, 1))
        else:
            self.date_from.setDate(today.addDays(-self.RANGE_OFFSETS.get(key, 29)))
        self.date_to.setDate(today)

    def _fit_columns(self, sample: int = 300) -> None:
        """按内容自适应列宽（勾选列固定 44）。

        ★ 行数多时只采样前 sample 行：
          Qt 自带的 ResizeToContents 会逐行扫描，几万行时算列宽就要好几秒；
          采样计算的结果几乎一样，但快得多，刷新不卡。
        """
        fm = self.table.fontMetrics()
        rows = min(self.table.rowCount(), sample)
        for c in range(1, self.table.columnCount()):
            head = self.table.horizontalHeaderItem(c)
            widest = fm.width(head.text() if head else "") + 34
            for r in range(rows):
                item = self.table.item(r, c)
                if item is not None:
                    widest = max(widest, fm.width(item.text()) + 34)
            self.table.setColumnWidth(c, min(300, max(76, widest)))
        self.table.setColumnWidth(0, 44)

    def on_settings_saved(self) -> None:
        """系统设置保存后调用：按「默认显示周期」重新初始化日期范围并刷新。

        ★ 为什么需要这个入口：
          默认周期只在页面构造时应用过一次，改完设置后
          只 reload 不会重算日期范围，看起来就像「要重启才生效」。
        """
        self.date_from.blockSignals(True)
        self.date_to.blockSignals(True)
        self._apply_default_range()
        self.date_from.blockSignals(False)
        self.date_to.blockSignals(False)
        self.reload()

    def _reset_filter(self) -> None:
        """重置筛选条件：清空 SN / 箱号，日期按设置的默认周期重新初始化。"""
        self._filter_timer.stop()
        self.sn_edit.blockSignals(True)
        self.box_edit.blockSignals(True)
        self.date_from.blockSignals(True)
        self.date_to.blockSignals(True)
        self.sn_edit.clear()
        self.box_edit.clear()
        self._apply_default_range()
        self.date_from.blockSignals(False)
        self.date_to.blockSignals(False)
        self.sn_edit.blockSignals(False)
        self.box_edit.blockSignals(False)
        self.reload()

    def reload(self) -> None:
        date_from = self.date_from.date().toString("yyyy-MM-dd")
        date_to = self.date_to.date().toString("yyyy-MM-dd")
        records = self.db.query_records(
            sn=self.sn_edit.text().strip(),
            box_no=self.box_edit.text().strip(),
            date_from=date_from, date_to=date_to)
        self._rows = []
        for r in records:
            row: Dict[str, Any] = dict(r)
            snapshot = json.loads(r["snapshot"]) if r.get("snapshot") else {}
            for k, v in snapshot.items():
                row["field:" + k] = v
            self._rows.append(row)

        columns = self.record_columns()
        self.table.setColumnCount(len(columns) + 1)
        self.table.setHorizontalHeaderLabels([""] + [label for _, label in columns])
        self.table.setRowCount(0)

        # ★ 批量填充期间关掉更新与排序：
        #   不关的话每 insertRow / setItem 都会触发一次重绘与重排，
        #   行数一多就是 O(n²)——这是 2.6 万行要渲染 17 分钟的主因之一。
        self.table.setUpdatesEnabled(False)
        self.table.setSortingEnabled(False)
        # itemChanged 会在程序化 setCheckState 时也触发，用这个标志挡住递归
        self._applying = True
        try:
            # 一次性建好所有行，再逐格填值（setRowCount 比逐行 insertRow 快得多）
            self.table.setRowCount(len(self._rows))
            for row_idx, r in enumerate(self._rows):
                chk_item = QTableWidgetItem()
                chk_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled
                                  | Qt.ItemIsSelectable)
                chk_item.setCheckState(Qt.Unchecked)
                self.table.setItem(row_idx, 0, chk_item)
                for col_idx, (cid, _) in enumerate(columns, start=1):
                    self.table.setItem(row_idx, col_idx,
                                       QTableWidgetItem(cell_text(r.get(cid))))
        finally:
            self._applying = False
            self.table.setUpdatesEnabled(True)
        # 按当前内容自适应列宽（用户仍可手动拖动列宽）
        self._fit_columns()
        self.count_label.setText(f"共 {len(self._rows)} 条")

    # ================= 行选中着色 =================

    def _row_item(self, row: int) -> Optional[QTableWidgetItem]:
        """取该行第 0 列（勾选列）的表格项；不存在时返回 None。"""
        return self.table.item(row, 0)

    def _row_checked(self, row: int) -> bool:
        """该行当前是否被勾选。"""
        item = self._row_item(row)
        return bool(item is not None and item.checkState() == Qt.Checked)

    # ================= Shift 范围快速选择 =================

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        """勾选状态变化的处理入口（表格项的勾选框被点/被程序改都会触发）。

        按住 Shift 时，把「上次点击的行」到「这一行」之间的所有行
        一起设成同一状态，实现范围快速选择（与资源管理器里选文件一致）。
        不按 Shift 就只处理当前这一行。

        ★ 与旧实现的区别：以前用 QCheckBox.clicked（只在用户点击时触发），
          现在改用表格项后只能监听 itemChanged，而**程序化 setCheckState
          也会触发它**，所以必须用 self._applying 挡住递归。
        """
        if self._applying or item.column() != 0:
            return
        row = item.row()
        target = item.checkState() == Qt.Checked
        if (QApplication.keyboardModifiers() & Qt.ShiftModifier
                and self._last_clicked_row is not None
                and self._last_clicked_row != row):
            lo, hi = sorted((self._last_clicked_row, row))
            self.set_rows_checked(range(lo, hi + 1), target)
            self._repaint_rows(range(lo, hi + 1))
        else:
            self._paint_row(row, target)
        self._last_clicked_row = row

    def set_rows_checked(self, rows, checked: bool) -> None:
        """批量设置若干行的勾选状态（不会递归触发处理逻辑）。"""
        state = Qt.Checked if checked else Qt.Unchecked
        self._applying = True
        try:
            for r in rows:
                item = self._row_item(r)
                if item is not None and item.checkState() != state:
                    item.setCheckState(state)
        finally:
            self._applying = False

    def _repaint_rows(self, rows) -> None:
        """批量刷新若干行的显示（整行底色）。"""
        for r in rows:
            self._paint_row(r, self._row_checked(r))

    def _paint_row(self, row: int, checked: bool) -> None:
        """勾选状态变化后重画该行。

        底色由 RecordRowDelegate 在绘制时按勾选状态现算，
        这里只需要让表格刷新「这一行」的显示区域。
        """
        if row < 0 or row >= self.table.rowCount():
            return
        index = self.table.model().index(row, 0)
        rect = self.table.visualRect(index)
        rect.setLeft(0)
        rect.setRight(self.table.viewport().width())
        self.table.viewport().update(rect)


# 记录表要用委托画行底色，见 RecordRowDelegate 的说明

    def _selected_rows(self) -> List[int]:
        """已勾选的行号（导出 / 删除选中都用它）。"""
        return [r for r in range(self.table.rowCount()) if self._row_checked(r)]

    def _toggle_select_all(self) -> None:
        rows = self.table.rowCount()
        if not rows:
            return
        checked = [self._row_checked(r) for r in range(rows)]
        target = not all(checked)
        self.set_rows_checked(range(rows), target)
        self._repaint_rows(range(rows))
        # 全选是批量操作，不该成为下一次 Shift 选择的起点
        self._last_clicked_row = None

    # ================= 操作 =================

    def _export_selected(self) -> None:
        rows = self._selected_rows()
        if not rows:
            QMessageBox.information(self, "提示", "请先勾选要导出的记录")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "导出打印记录", "打印记录.xlsx", "Excel 文件 (*.xlsx)")
        if not path:
            return
        # 导出方式在「设置 - 系统设置 - 打印记录导出」里定，这里不再弹窗询问
        group_by_date = (self.db.get_setting("export_mode") or "date") == "date"
        sheet_fmt = self.db.get_setting("sheet_name_format") or "yy.MM.dd"
        try:
            sheets = excel_io.export_records(
                Path(path), self.record_columns(),
                [self._rows[r] for r in rows],
                group_by_date=group_by_date, sheet_name_format=sheet_fmt)
            if group_by_date:
                detail = "、".join(f"{k}（{v} 条）" for k, v in sheets.items())
                QMessageBox.information(
                    self, "完成",
                    f"已导出 {len(rows)} 条记录，共 {len(sheets)} 个工作表：\n{detail}")
            else:
                QMessageBox.information(self, "完成",
                                        f"已导出 {len(rows)} 条记录")
        except Exception as exc:
            QMessageBox.critical(self, "导出失败", str(exc))

    def _delete_selected(self) -> None:
        rows = self._selected_rows()
        if not rows:
            QMessageBox.information(self, "提示", "请先勾选要删除的记录")
            return
        password, ok = QInputDialog.getText(
            self, "删除验证", "删除打印记录需要密码：",
            QLineEdit.Password)
        if not ok:
            return
        if password != self.db.get_setting("delete_password", "123456"):
            QMessageBox.warning(self, "错误", "密码错误，已取消删除")
            return
        confirm = QMessageBox.question(
            self, "确认删除", f"确定删除选中的 {len(rows)} 条打印记录吗？\n"
            "（对应的 SN 存档将一并删除）")
        if confirm != QMessageBox.Yes:
            return
        self.db.delete_records([self._rows[r]["id"] for r in rows])
        self.reload()

    def _reprint_box(self) -> None:
        rows = self._selected_rows()
        if len(rows) != 1:
            QMessageBox.information(self, "提示", "请勾选一条记录（按整箱重打印）")
            return
        box_no = self._rows[rows[0]]["box_no"]
        records = self.db.records_by_box(box_no)
        if not records:
            QMessageBox.warning(self, "错误", "未找到该箱记录")
            return
        snapshot = json.loads(records[0]["snapshot"]) if records[0].get("snapshot") else {}
        template_name = str(snapshot.get("template", "")).strip()
        if not template_name:
            QMessageBox.warning(self, "错误", "记录中缺少打印模板信息")
            return
        template_dir = resolve_template_dir(self.db.get_setting("template_dir"))
        template_path = template_path_abs(template_dir, template_name)

        # ★ 与打印页共用同一套组装逻辑，避免两处走偏导致重打印时
        #   BarTender 拿不到值、只能显示模板自带的默认值。
        sns = [str(r["sn"]) for r in records]
        total = self._box_capacity(records[0], snapshot, len(sns))
        data = build_label_data(self.db, snapshot, box_no, sns, total=total)

    def _box_capacity(self, record: Dict[str, Any], snapshot: Dict[str, Any],
                      sn_count: int) -> int:
        """重打印时该填几个 SN 位。

        ★ 取「产品本身的装箱数量」，不能直接用记录快照里的 shuliang：
          当初**不满箱打印**时，打印页会把快照里的 shuliang 改成实际打印数量
          （如打了 3 个就存 "3"）；拿它当位数的话，模板上第 4 个以后的
          SN 位就不会被赋值，于是打印出来的还是模板自带的示例数据。
          产品被删时再依次回退到快照值、实际记录数。
        """
        pid = int(record.get("product_id") or 0)
        product = self.db.get_product(pid) if pid else None
        for value in ((product or {}).get("shuliang", ""),
                      snapshot.get("shuliang", "")):
            try:
                num = int(str(value).strip() or 0)
            except (TypeError, ValueError):
                continue
            if num > 0:
                return num
        return sn_count

        task_id = self.print_service.submit(
            template_path, data,
            resolve_printer(self.db.get_setting("default_printer", "")),
            box_no, tag=None)
        self._my_tasks.add(task_id)
        self.count_label.setText(f"正在重打 {box_no} …")

    def _on_reprint_done(self, task_id: int, box_no: str, tag) -> None:
        """重打印成功（只处理本页提交的任务）。"""
        if task_id not in self._my_tasks:
            return
        self._my_tasks.discard(task_id)
        self.count_label.setText(f"共 {len(self._rows)} 条")
        QMessageBox.information(self, "完成", f"箱号 {box_no} 已重新打印")

    def _on_reprint_failed(self, task_id: int, msg: str) -> None:
        """重打印失败（只处理本页提交的任务）。"""
        if task_id not in self._my_tasks:
            return
        self._my_tasks.discard(task_id)
        self.count_label.setText(f"共 {len(self._rows)} 条")
        QMessageBox.critical(self, "重打印失败", msg)
