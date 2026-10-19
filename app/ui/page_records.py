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
from PyQt5.QtWidgets import (QApplication, QCheckBox, QDateEdit, QFileDialog, QFrame,
                             QHBoxLayout, QInputDialog, QLabel,
                             QLineEdit, QMessageBox, QPushButton,
                             QStyledItemDelegate, QTableWidget,
                             QTableWidgetItem, QVBoxLayout, QWidget)

from app.core import excel_io, listconfig
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
ROW_CHECKED_BG_CSS = "#E3F0FF"


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
        widget = self._table.cellWidget(row, 0)
        if widget is None:
            return False
        chk = widget.findChild(QCheckBox)
        return bool(chk and chk.isChecked())

    def paint(self, painter, option, index) -> None:
        # 第 0 列是勾选框容器（有自己的底色），不在这里重复铺
        if index.column() > 0 and self._checked(index.row()):
            painter.fillRect(option.rect, ROW_CHECKED_BG)
        super().paint(painter, option, index)


class ReprintWorker(QThread):
    """重打印线程。"""
    ok = pyqtSignal(str)
    fail = pyqtSignal(str)

    def __init__(self, bartender: BarTender, template: Path,
                 data: Dict[str, str], printer: str, box_no: str):
        super().__init__()
        self._bt = bartender
        self._template = template
        self._data = data
        self._printer = printer
        self._box_no = box_no

    def run(self) -> None:
        try:
            self._bt.print_label(self._template, self._data,
                                 self._printer or None, copies=1)
            self.ok.emit(self._box_no)
        except Exception as exc:
            self.fail.emit(str(exc))


def default_record_columns(db: DB) -> List[Dict[str, Any]]:
    """打印记录默认列（基础列 + 产品字段列 + 尾部列）。

    配置本身在 app/core/listconfig.py 统一维护，这里只做转发，
    方便其它模块（含打包前的验证脚本）继续沿用原函数名。
    """
    return listconfig.defaults("record_columns", db)


class RecordsPage(QWidget):
    """打印记录页。"""

    def __init__(self, db: DB, bartender: BarTender, parent=None):
        super().__init__(parent)
        self.db = db
        self.bartender = bartender
        self._rows: List[Dict[str, Any]] = []
        self._worker = None
        self._width_cache: Dict[str, Any] = {}
        # Shift 范围选择的起点：上一次点击过的行号
        self._last_clicked_row: Optional[int] = None
        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(FILTER_DEBOUNCE_MS)
        self._filter_timer.timeout.connect(self.reload)
        self._build_ui()

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

    def _reset_filter(self) -> None:
        """重置筛选条件：清空 SN / 箱号，日期回到「近一个月 ~ 今天」。"""
        self._filter_timer.stop()
        self.sn_edit.blockSignals(True)
        self.box_edit.blockSignals(True)
        self.date_from.blockSignals(True)
        self.date_to.blockSignals(True)
        self.sn_edit.clear()
        self.box_edit.clear()
        self.date_from.setDate(QDate.currentDate().addMonths(-1))
        self.date_to.setDate(QDate.currentDate())
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
        for r in self._rows:
            row_idx = self.table.rowCount()
            self.table.insertRow(row_idx)
            chk_widget = QWidget()
            # 给容器一个 objectName，行底色只作用于它自身，不会染到里面的复选框
            chk_widget.setObjectName("rowChk")
            lay = QHBoxLayout(chk_widget)
            chk = QCheckBox()
            chk.setToolTip("点击勾选；按住 Shift 再点，可一次性选/取消一整段")
            # 用 clicked 而不是 toggled/stateChanged：
            # setChecked() 不会触发 clicked，所以「全选」「Shift 范围选择」
            # 里批量改状态都不会递归进来
            chk.clicked.connect(lambda _c, r=row_idx: self._on_row_click(r))
            lay.addWidget(chk)
            lay.setAlignment(Qt.AlignCenter)
            lay.setContentsMargins(0, 0, 0, 0)
            self.table.setCellWidget(row_idx, 0, chk_widget)
            for col_idx, (cid, _) in enumerate(columns, start=1):
                self.table.setItem(row_idx, col_idx,
                                   QTableWidgetItem(str(r.get(cid, ""))))
        # 列宽只在「列结构变化」时算一次，之后固定：
        # 否则每次查询结果变化整张表的列宽都会跳
        freeze_widths(self.table, self._width_cache,
                      signature=tuple(label for _, label in columns),
                      min_width=76, max_width=300,
                      overrides={0: 44})
        self.count_label.setText(f"共 {len(self._rows)} 条")

    # ================= 行选中着色 =================

    def _row_checkbox(self, row: int) -> Optional[QCheckBox]:
        """取该行的勾选框（找不到时返回 None）。"""
        widget = self.table.cellWidget(row, 0)
        return widget.findChild(QCheckBox) if widget is not None else None

    def _row_checked(self, row: int) -> bool:
        """该行的勾选框当前是否被选中。"""
        chk = self._row_checkbox(row)
        return bool(chk and chk.isChecked())

    # ================= Shift 范围快速选择 =================

    def _on_row_click(self, row: int) -> None:
        """处理某一行勾选框的点击。

        按住 Shift 时，把「上次点击的行」到「这一行」之间的所有行
        一起设成同一状态，实现范围快速选择（与资源管理器里选文件一致）。
        不按 Shift 就只处理当前这一行。
        """
        chk = self._row_checkbox(row)
        if chk is None:
            return
        target = chk.isChecked()
        if (QApplication.keyboardModifiers() & Qt.ShiftModifier
                and self._last_clicked_row is not None
                and self._last_clicked_row != row):
            lo, hi = sorted((self._last_clicked_row, row))
            for r in range(lo, hi + 1):
                box = self._row_checkbox(r)
                if box is not None and box.isChecked() != target:
                    box.setChecked(target)      # 不触发 clicked，不会递归
            self._repaint_rows(range(lo, hi + 1))
        else:
            self._paint_row(row, target)
        self._last_clicked_row = row

    def _repaint_rows(self, rows) -> None:
        """批量刷新若干行的显示（底色 + 勾选框容器背景）。"""
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
        widget = self.table.cellWidget(row, 0)
        if widget is not None:
            widget.setStyleSheet(
                f"QWidget#rowChk {{ background: {ROW_CHECKED_BG_CSS}; }}"
                if checked else "")
            widget.update()


# 记录表要用委托画行底色，见 RecordRowDelegate 的说明

    def _selected_rows(self) -> List[int]:
        result = []
        for r in range(self.table.rowCount()):
            chk = self.table.cellWidget(r, 0).findChild(QCheckBox)
            if chk and chk.isChecked():
                result.append(r)
        return result

    def _toggle_select_all(self) -> None:
        rows = self.table.rowCount()
        if not rows:
            return
        checked = [bool(self.table.cellWidget(r, 0).findChild(QCheckBox).isChecked())
                   for r in range(rows)]
        target = not all(checked)
        for r in range(rows):
            self.table.cellWidget(r, 0).findChild(QCheckBox).setChecked(target)
        # setChecked 不会触发 clicked，着色得自己补一次
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
        from app.ui.export_choice import ExportChoiceDialog
        dlg = ExportChoiceDialog(
            default_format=self.db.get_setting("sheet_name_format", "yy.MM.dd")
            or "yy.MM.dd",
            record_count=len(rows), parent=self)
        if dlg.exec_() != QDialog.Accepted:
            return
        group_by_date, sheet_fmt = dlg.result()
        try:
            sheets = excel_io.export_records(
                Path(path), self.record_columns(),
                [self._rows[r] for r in rows],
                group_by_date=group_by_date, sheet_name_format=sheet_fmt)
            if group_by_date:
                detail = "、".join(f"{k}（{v} 条）" for k, v in sheets.items())
                QMessageBox.information(
                    self, "完成",
                    f"已导出 {len(rows)} 条记录，共 {len(sheets)} 个 sheet：\n{detail}")
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

        total = int(snapshot.get("shuliang", 0) or len(records))
        data: Dict[str, str] = {}
        for f in self.db.list_fields():
            if int(f.get("kind", 0) or 0) == KIND_PRINT:
                continue
            data[f["datasource"]] = str(snapshot.get(f["fkey"], ""))
        # 箱号按「字段映射」里配置的数据源名写入（默认 xianghao）
        for f in self.db.list_print_fields():
            if f["fkey"] == "xianghao":
                data[f["datasource"]] = box_no
        for i in range(total):
            data[str(i + 1)] = records[i]["sn"] if i < len(records) else ""

        self._worker = ReprintWorker(
            self.bartender, template_path, data,
            resolve_printer(self.db.get_setting("default_printer", "")), box_no)
        self._worker.ok.connect(
            lambda bn: QMessageBox.information(self, "完成", f"箱号 {bn} 已重新打印"))
        self._worker.fail.connect(
            lambda msg: QMessageBox.critical(self, "重打印失败", msg))
        self._worker.start()
