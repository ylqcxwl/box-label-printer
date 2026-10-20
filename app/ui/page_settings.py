# -*- coding: utf-8 -*-
"""设置页面（对齐设计稿第 4 页）。

五个选项卡：箱号规则 / SN 规则 / 字段映射 / 列表设置 / 系统设置。
"""

from datetime import date
from pathlib import Path
from typing import Callable, Dict, List, Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                             QFileDialog, QFormLayout, QGridLayout, QHBoxLayout,
                             QFrame, QHeaderView, QInputDialog, QLabel, QLineEdit,
                             QListWidget, QListWidgetItem, QMessageBox,
                             QPlainTextEdit, QPushButton, QSpinBox, QTabWidget,
                             QTableWidget, QTableWidgetItem, QTextBrowser,
                             QVBoxLayout, QWidget)

from app.core import backup as backup_mod
from app.core import listconfig
from app.core import rules as rule_engine
from app.core import updater
from app.core.bartender import list_printers, system_default_printer
from app.core.db import DB, KIND_PRINT, KIND_PRODUCT
from app.ui import icons
from app.version import VERSION


class RuleDialog(QDialog):
    """箱号 / SN 规则编辑对话框（无边框，含编写说明与预览）。

    Args:
        mode: "box"（箱号规则，第三项为流水位数）或 "sn"（SN 规则，第三项为总位数）
        db: 用于读取工厂代码，生成预览示例
    """

    def __init__(self, title: str, name: str = "", pattern: str = "",
                 digits: int = 5, remark: str = "", help_text: str = "",
                 mode: str = "box", db: Optional[DB] = None,
                 on_save: Optional[Callable[[tuple], None]] = None,
                 parent=None):
        super().__init__(parent)
        self.mode = mode
        self.db = db
        self._on_save = on_save
        self._drag_pos = None

        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setObjectName("ruleDialog")
        self.setFixedWidth(660)

        root = QVBoxLayout(self)
        root.setContentsMargins(1, 1, 1, 1)
        root.setSpacing(0)

        # ---- 标题栏：图标 + 标题 + 关闭 ----
        bar = QWidget()
        bar.setObjectName("dlgTitleBar")
        bar.setFixedHeight(44)
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(14, 0, 6, 0)
        icon = QLabel()
        icon.setPixmap(icons.gear_icon("#4A5058", 32).pixmap(18, 18))
        bar_layout.addWidget(icon)
        bar_layout.addSpacing(6)
        title_label = QLabel(title)
        title_label.setObjectName("dlgTitle")
        bar_layout.addWidget(title_label)
        bar_layout.addStretch(1)
        close_btn = QPushButton("✕")
        close_btn.setObjectName("dlgClose")
        close_btn.setFixedSize(32, 28)
        close_btn.clicked.connect(self.reject)
        bar_layout.addWidget(close_btn)
        root.addWidget(bar)

        # ---- 表单 ----
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(18, 10, 18, 14)
        body_layout.setSpacing(10)

        form = QFormLayout()
        form.setSpacing(12)
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        form.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)

        self.name_edit = QLineEdit(name)
        form.addRow("规则名称", self.name_edit)
        self.pattern_edit = QLineEdit(pattern)
        self.pattern_edit.setPlaceholderText(
            "如 {YYYY}{MM}{SEQ:5}" if mode == "box"
            else "如 {PREFIX}/{FACTORY}{BATCH}{SEQ:7}")
        form.addRow("规则表达式", self.pattern_edit)

        # 实时预览：紧贴表达式下方，边打字边看结果，不用再点「预览」按钮
        self.preview_value = QLabel("—")
        self.preview_value.setObjectName("livePreview")
        self.preview_value.setWordWrap(True)
        self.preview_value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        form.addRow("实时预览", self.preview_value)

        self.digits_spin = QSpinBox()
        if mode == "box":
            self.digits_spin.setRange(1, 10)
            self.digits_spin.setValue(digits if digits else 5)
            form.addRow("流水位数", self.digits_spin)
        else:
            self.digits_spin.setRange(0, 64)
            self.digits_spin.setSpecialValueText("0")
            self.digits_spin.setValue(digits if digits else 0)
            form.addRow("总位数(0=不校验)", self.digits_spin)

        # 流水号字符集：决定流水位按什么字符进位（纯数字 / 字母 / 16 进制 …）
        seq_row = QHBoxLayout()
        seq_row.setSpacing(8)
        self.seq_system_combo = QComboBox()
        for code, label, desc in rule_engine.SEQ_SYSTEM_CHOICES:
            self.seq_system_combo.addItem(label, code)
            self.seq_system_combo.setItemData(
                self.seq_system_combo.count() - 1, desc, Qt.ToolTipRole)
        seq_row.addWidget(self.seq_system_combo, 1)
        self.seq_custom_edit = QLineEdit()
        self.seq_custom_edit.setPlaceholderText("自定义字符顺序，如 XY 或 0123456789ABC")
        self.seq_custom_edit.setMaxLength(rule_engine.CUSTOM_MAX_CHARS)
        self.seq_custom_edit.setToolTip(
            "按你填的字符顺序进位：填 XY 时，第 1 个是 XXXXX，之后 XXXXY、XXXYX…\n"
            "（显示位数取上面的流水位数）")
        seq_row.addWidget(self.seq_custom_edit, 1)
        form.addRow("流水字符集", seq_row)

        self.remark_edit = QLineEdit(remark)
        form.addRow("备注", self.remark_edit)
        body_layout.addLayout(form)

        # 快捷插入占位符：用网格分行排布。
        # 之前排成一行会被挤窄，按钮文字被截断（如 {PREFIX} 显示成 REFI）。
        tokens = ([("{YYYY}", "{YYYY}"), ("{YY}", "{YY}"), ("{Y}", "{Y}"),
                   ("{MM}", "{MM}"), ("{M}", "{M}"), ("{DD}", "{DD}"),
                   ("{PREFIX}", "{PREFIX}"), ("{FACTORY}", "{FACTORY}"),
                   ("{BATCH}", "{BATCH}"), ("SEQ", ""),
                   # 按钮文字里的 & 会被 Qt 当成快捷键标记（显示成 {}），
                   # 要写成 && 才会显示出真正的 &，插入的仍是 {&}
                   ("{&&}", "{&}")]
                  if mode == "box" else
                  # SN 规则也提供箱号规则里那套年月日占位符
                  [("{YYYY}", "{YYYY}"), ("{YY}", "{YY}"), ("{Y}", "{Y}"),
                   ("{MM}", "{MM}"), ("{M}", "{M}"), ("{DD}", "{DD}"),
                   ("{PREFIX}", "{PREFIX}"), ("{FACTORY}", "{FACTORY}"),
                   ("{BATCH}", "{BATCH}"), ("SEQ", ""),
                   ("{&&}", "{&}")])
        insert_grid = QGridLayout()
        insert_grid.setSpacing(6)
        insert_grid.addWidget(QLabel("快捷插入"), 0, 0)
        # 每行 4 个：按钮带内边距后 {FACTORY} 约需 130px，
        # 一行 6 个会超出对话框宽度被压窄、文字截断（见本轮需求）。
        per_row = 4
        for idx, (label, text) in enumerate(tokens):
            btn = QPushButton(label)
            btn.setObjectName("tokenBtn")
            # 不设固定宽度：让按钮按文字自适应，配合网格分行就不会再截断
            btn.clicked.connect(
                lambda _c, t=text: self._insert_token(
                    t if t else self._current_seq_token()))
            insert_grid.addWidget(btn, idx // per_row, idx % per_row + 1)
        for col in range(1, per_row + 1):
            insert_grid.setColumnStretch(col, 1)
        body_layout.addLayout(insert_grid)

        help_title = QLabel("编写说明")
        help_title.setObjectName("dlgSection")
        body_layout.addWidget(help_title)

        self.help_box = QPlainTextEdit()
        self.help_box.setObjectName("helpBox")
        self.help_box.setReadOnly(True)
        self.help_box.setFixedHeight(170)   # 快捷插入改成 3 行后压缩说明框，避免窗口过高
        self.help_box.setPlainText(help_text)
        body_layout.addWidget(self.help_box)

        # ---- 底部：保存、取消（原来的「预览」按钮已删除，改为实时预览） ----
        bottom = QHBoxLayout()
        bottom.addStretch(1)
        save_btn = QPushButton("保存")
        save_btn.setObjectName("primary")
        save_btn.setFixedWidth(120)
        save_btn.clicked.connect(self._do_save)
        bottom.addWidget(save_btn)
        cancel_btn = QPushButton("取消")
        cancel_btn.setFixedWidth(120)
        cancel_btn.clicked.connect(self.reject)
        bottom.addWidget(cancel_btn)
        body_layout.addLayout(bottom)

        root.addWidget(body)

        # ---- 联动：表达式/位数/字符集任一变化都刷新预览 ----
        self.pattern_edit.textChanged.connect(self._refresh_preview)
        self.seq_system_combo.currentIndexChanged.connect(
            lambda *_: self._on_seq_system_changed())
        self.seq_custom_edit.textChanged.connect(
            lambda *_: self._on_seq_custom_changed())
        if mode == "box":
            self.digits_spin.valueChanged.connect(
                lambda *_: self._on_seq_digits_changed())
        self._load_seq_settings()
        self._refresh_preview()

    # ---- 无边框窗口拖动 ----
    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and event.pos().y() < 44:
            self._drag_pos = event.globalPos() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event) -> None:
        if self._drag_pos is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPos() - self._drag_pos)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_pos = None

    # ---- 保存：校验/写库失败时保留窗口，方便用户就地修改 ----
    def _do_save(self) -> None:
        """先执行外部保存回调，仅在成功后才关闭对话框。

        早期写法是点击保存即 accept()，再由调用方写库；
        一旦写库报错（如名称重复），窗口已经关掉，用户只能重新打开重填。
        """
        if self._on_save is not None:
            try:
                self._on_save(self.values())
            except Exception as exc:
                QMessageBox.warning(self, "保存失败", str(exc))
                return
        self.accept()

    def _insert_token(self, token: str) -> None:
        """在规则表达式的光标位置插入占位符。"""
        edit = self.pattern_edit
        pos = edit.cursorPosition()
        text = edit.text()
        edit.setText(text[:pos] + token + text[pos:])
        edit.setCursorPosition(pos + len(token))
        edit.setFocus()

    # ---- 流水字符集 ----

    def _seq_system(self) -> str:
        return self.seq_system_combo.currentData() or "DIGIT"

    def _seq_custom(self) -> str:
        return self.seq_custom_edit.text().strip()

    def _seq_digits(self) -> int:
        """当前流水位数。

        箱号规则里由「流水位数」控件决定；SN 规则的位数写在表达式里，
        表达式没写 SEQ 时用默认 7。
        """
        if self.mode == "box":
            return max(1, self.digits_spin.value())
        for m in rule_engine.TOKEN_RE.finditer(self.pattern_edit.text()):
            if m.group(1) in ("SEQ", "SEQR"):
                args = rule_engine.parse_token_args(m.group(2))
                if args and args[0].isdigit():
                    return int(args[0])
        return 7

    def _current_seq_token(self) -> str:
        """按当前字符集拼出要插入 / 写回表达式的 SEQ 占位符。"""
        return rule_engine.seq_token(self._seq_digits(), self._seq_system(),
                                     self._seq_custom())

    def _load_seq_settings(self) -> None:
        """打开对话框时，从表达式里回填字符集选择。"""
        system, custom = "DIGIT", ""
        for m in rule_engine.TOKEN_RE.finditer(self.pattern_edit.text()):
            if m.group(1) in ("SEQ", "SEQR"):
                args = rule_engine.parse_token_args(m.group(2))
                _d, _charset, system = rule_engine.resolve_charset(args)
                if system == "CUSTOM" and len(args) > 2:
                    custom = args[2]
                break
        for i in range(self.seq_system_combo.count()):
            if self.seq_system_combo.itemData(i) == system:
                self.seq_system_combo.setCurrentIndex(i)
                break
        self.seq_custom_edit.setText(custom)
        self.seq_custom_edit.setVisible(system == "CUSTOM")

    def _on_seq_system_changed(self) -> None:
        self.seq_custom_edit.setVisible(self._seq_system() == "CUSTOM")
        self._rewrite_seq_token()

    def _on_seq_custom_changed(self) -> None:
        if self._seq_system() == "CUSTOM":
            self._rewrite_seq_token()

    def _on_seq_digits_changed(self) -> None:
        self._rewrite_seq_token()

    def _rewrite_seq_token(self) -> None:
        """把表达式里的 SEQ 占位符改写成当前字符集（表达式没有 SEQ 时不动）。"""
        text = self.pattern_edit.text()
        if not any(m.group(1) in ("SEQ", "SEQR")
                   for m in rule_engine.TOKEN_RE.finditer(text)):
            self._refresh_preview()
            return
        token = self._current_seq_token()
        new_text = rule_engine.TOKEN_RE.sub(
            lambda m: token if m.group(1) in ("SEQ", "SEQR") else m.group(0),
            text)
        if new_text != text:
            self.pattern_edit.setText(new_text)
        else:
            self._refresh_preview()

    # ---- 实时预览 ----

    def _refresh_preview(self) -> None:
        """把预览结果显示在「规则表达式」下方（原来要点按钮才出）。"""
        pattern = self.pattern_edit.text().strip()
        if not pattern:
            self.preview_value.setText("—（填写表达式后自动显示）")
            self.preview_value.setStyleSheet("color:#8A9099;")
            return
        factory = self.db.get_setting("factory_code", "") if self.db else ""
        if self.mode == "box":
            ok, text = rule_engine.preview_box_no(
                pattern, factory=factory or "2", prefix="8001")
        else:
            ok, text = rule_engine.preview_sn(
                pattern, factory=factory or "2", prefix="1234")
        self.preview_value.setText(text)
        self.preview_value.setStyleSheet(
            "color:#1F2329;font-weight:bold;" if ok else "color:#D93025;")

    def values(self):
        return (self.name_edit.text().strip(),
                self.pattern_edit.text().strip(),
                self.digits_spin.value(),
                self.remark_edit.text().strip())


FIELD_HELP = """【三个输入框分别是什么】
1. 字段标识：程序内部用的键名（只能字母/数字/下划线，如 caizhi）。
   它决定这个字段在产品数据里叫什么，不需要和模板一致，新增后不可改。
2. 显示名称（中文）：界面上看到的中文名（如「材质」）。
   它会出现在「产品管理」表格表头、新增/编辑产品的表单里。
3. 模板数据源名：BarTender 模板里「命名数据源」的名字，
   必须与模板里的一字不差（如 cai_zhi），否则打印时传不过去。

【新增一个字段后怎样才算真正用上】
① 先在本对话框填好三项并保存；
② 到「产品管理」新增/编辑产品，就能看到新字段并填写内容；
③ 打开 BarTender 模板，新建一个「命名数据源」，名字填第 3 步的名字，
   并把它绑到标签上的文字/条码对象；
④ 打印时程序会自动把该字段的值传过去。
提示：不确定模板里叫什么名字时，打开 BarTender 的
「数据源名称」对话框复制粘贴，避免手打错。"""


class FieldDialog(QDialog):
    """字段映射编辑对话框。"""

    def __init__(self, label: str = "", datasource: str = "",
                 allow_key: bool = True, fkey: str = "",
                 help_text: str = FIELD_HELP,
                 on_save: Optional[Callable[[tuple], None]] = None,
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("字段映射")
        self.setMinimumWidth(460)
        self._on_save = on_save
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(10)
        self.key_edit = QLineEdit(fkey)
        self.key_edit.setPlaceholderText("如 caizhi（字母/数字/下划线，保存后不可改）")
        self.key_edit.setEnabled(allow_key)
        form.addRow("字段标识", self.key_edit)
        self.label_edit = QLineEdit(label)
        self.label_edit.setPlaceholderText("如 材质（界面上显示的中文名）")
        form.addRow("显示名称（中文）", self.label_edit)
        self.ds_edit = QLineEdit(datasource)
        self.ds_edit.setPlaceholderText("与 BarTender 模板中的命名数据源完全一致")
        form.addRow("模板数据源名", self.ds_edit)
        layout.addLayout(form)

        self.help_box = QPlainTextEdit()
        self.help_box.setObjectName("helpBox")
        self.help_box.setReadOnly(True)
        self.help_box.setFixedHeight(170)   # 快捷插入改成 3 行后压缩说明框，避免窗口过高
        self.help_box.setPlainText(help_text)
        layout.addWidget(self.help_box)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("保存")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        # 不走 accepted -> accept 的默认链路：保存失败时要保留窗口
        buttons.button(QDialogButtonBox.Ok).clicked.connect(self._do_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _do_save(self) -> None:
        """先执行保存回调，仅在成功后关闭对话框。"""
        if self._on_save is not None:
            try:
                self._on_save(self.values())
            except Exception as exc:
                QMessageBox.warning(self, "保存失败", str(exc))
                return
        self.accept()

    def values(self):
        return (self.key_edit.text().strip(),
                self.label_edit.text().strip(),
                self.ds_edit.text().strip())


class SettingsPage(QWidget):
    """设置页。"""

    settings_saved = pyqtSignal()

    def __init__(self, db: DB, parent=None):
        super().__init__(parent)
        self.db = db
        self._latest_update: Optional[dict] = None
        self._build_ui()

    # ================= UI =================

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_box_rules_tab(), "箱号规则")
        self.tabs.addTab(self._build_sn_rules_tab(), "SN 规则")
        self.tabs.addTab(self._build_fields_tab(), "字段映射")
        self.tabs.addTab(self._build_record_columns_tab(), "列表设置")
        self.tabs.addTab(self._build_system_tab(), "系统设置")
        root.addWidget(self.tabs, 1)

    # ---------------- 箱号规则 ----------------

    def _build_box_rules_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 10, 4, 6)
        layout.setSpacing(12)

        head = QHBoxLayout()
        head.addWidget(self._tab_title("箱号规则（可添加 / 修改 / 删除）"))
        head.addStretch(1)
        for text, oid, slot in (("删除", "danger", self._del_box_rule),
                                ("修改", "", self._edit_box_rule),
                                ("+ 新增", "primary", self._add_box_rule)):
            btn = QPushButton(text)
            if oid:
                btn.setObjectName(oid)
            btn.setMinimumWidth(96)
            btn.clicked.connect(slot)
            head.addWidget(btn)
        layout.addLayout(head)

        self.box_rule_table = self._make_rule_table("流水位数")
        self.box_rule_table.itemDoubleClicked.connect(lambda *_: self._edit_box_rule())
        layout.addWidget(self.box_rule_table, 1)
        return page

    def _tab_title(self, text: str) -> QLabel:
        """选项卡标题（加粗加大）。"""
        label = QLabel(text)
        label.setStyleSheet("font-size:16px;font-weight:bold;color:#1F2329;")
        return label

    def _make_rule_table(self, third_header: str) -> QTableWidget:
        """规则列表表格（白底细线、表头居中、选中整行高亮）。"""
        table = QTableWidget(0, 4)
        table.setObjectName("ruleTable")
        table.setHorizontalHeaderLabels(["规则名称", "表达式", third_header, "备注"])
        for col in range(4):
            item = table.horizontalHeaderItem(col)
            if item:
                item.setTextAlignment(Qt.AlignCenter)
        table.verticalHeader().setVisible(False)
        table.setShowGrid(False)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSelectionMode(QTableWidget.SingleSelection)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.verticalHeader().setDefaultSectionSize(36)
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.Fixed)
        header.setSectionResizeMode(2, QHeaderView.Fixed)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        table.setColumnWidth(0, 300)
        table.setColumnWidth(1, 270)
        table.setColumnWidth(2, 110)
        return table

    def _reload_box_rules(self) -> None:
        rules = self.db.list_box_rules()
        self.box_rule_table.setRowCount(0)
        for r in rules:
            row = self.box_rule_table.rowCount()
            self.box_rule_table.insertRow(row)
            values = [r["name"], r["pattern"],
                      rule_engine.box_rule_digits(r["pattern"]),
                      r.get("remark", "")]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setData(Qt.UserRole, r["id"])
                if col in (1, 2):
                    item.setTextAlignment(Qt.AlignCenter)
                self.box_rule_table.setItem(row, col, item)
        if rules:
            self.box_rule_table.selectRow(0)

    def _selected_box_rule(self) -> Optional[Dict]:
        rows = self.box_rule_table.selectionModel().selectedRows()
        if not rows:
            return None
        rid = self.box_rule_table.item(rows[0].row(), 0).data(Qt.UserRole)
        return next((r for r in self.db.list_box_rules() if r["id"] == rid), None)

    def _save_box_rule_values(self, values: tuple, rid: Optional[int] = None) -> None:
        """校验并保存箱号规则（供对话框保存回调使用，异常会保留对话框）。

        Raises:
            ValueError: 校验失败或名称重复时抛出，由对话框提示给用户。
        """
        name, pattern, _digits, remark = values
        if not name:
            raise ValueError("规则名称不能为空")
        if not pattern:
            raise ValueError("规则表达式不能为空")
        self.db.save_box_rule(name, pattern, remark, rid=rid)

    def _add_box_rule(self) -> None:
        dlg = RuleDialog("新增箱号规则", help_text=rule_engine.BOX_RULE_HELP,
                         mode="box", db=self.db,
                         on_save=self._save_box_rule_values, parent=self)
        if dlg.exec_() == QDialog.Accepted:
            self._reload_box_rules()
            self.settings_saved.emit()

    def _edit_box_rule(self) -> None:
        rule = self._selected_box_rule()
        if not rule:
            QMessageBox.information(self, "提示", "请先选择一条规则")
            return
        digits = rule_engine.box_rule_digits(rule["pattern"])
        dlg = RuleDialog("修改箱号规则", rule["name"], rule["pattern"],
                         int(digits) if digits.isdigit() else 5,
                         rule.get("remark", ""), rule_engine.BOX_RULE_HELP,
                         mode="box", db=self.db,
                         on_save=lambda v: self._save_box_rule_values(v, rule["id"]),
                         parent=self)
        if dlg.exec_() == QDialog.Accepted:
            self._reload_box_rules()
            self.settings_saved.emit()

    def _del_box_rule(self) -> None:
        rule = self._selected_box_rule()
        if not rule:
            QMessageBox.information(self, "提示", "请先选择一条规则")
            return
        if QMessageBox.question(self, "确认",
                                f"确定删除箱号规则「{rule['name']}」吗？"
                                ) == QMessageBox.Yes:
            self.db.delete_box_rule(rule["id"])
            self._reload_box_rules()
            self.settings_saved.emit()

    # ---------------- SN 规则 ----------------

    def _build_sn_rules_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 10, 4, 6)
        layout.setSpacing(12)

        head = QHBoxLayout()
        head.addWidget(self._tab_title("SN 规则（可添加 / 修改 / 删除）"))
        head.addStretch(1)
        for text, oid, slot in (("删除", "danger", self._del_sn_rule),
                                ("修改", "", self._edit_sn_rule),
                                ("+ 新增", "primary", self._add_sn_rule)):
            btn = QPushButton(text)
            if oid:
                btn.setObjectName(oid)
            btn.setMinimumWidth(96)
            btn.clicked.connect(slot)
            head.addWidget(btn)
        layout.addLayout(head)

        self.sn_rule_table = self._make_rule_table("总位数")
        self.sn_rule_table.itemDoubleClicked.connect(lambda *_: self._edit_sn_rule())
        layout.addWidget(self.sn_rule_table, 1)
        return page

    def _reload_sn_rules(self) -> None:
        rules = self.db.list_sn_rules()
        self.sn_rule_table.setRowCount(0)
        for r in rules:
            row = self.sn_rule_table.rowCount()
            self.sn_rule_table.insertRow(row)
            total = r.get("total_len", 0)
            values = [r["name"], r["pattern"],
                      total if total else "-", r.get("remark", "")]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setData(Qt.UserRole, r["id"])
                if col in (1, 2):
                    item.setTextAlignment(Qt.AlignCenter)
                self.sn_rule_table.setItem(row, col, item)
        if rules:
            self.sn_rule_table.selectRow(0)

    def _selected_sn_rule(self) -> Optional[Dict]:
        rows = self.sn_rule_table.selectionModel().selectedRows()
        if not rows:
            return None
        rid = self.sn_rule_table.item(rows[0].row(), 0).data(Qt.UserRole)
        return next((r for r in self.db.list_sn_rules() if r["id"] == rid), None)

    def _save_sn_rule_values(self, values: tuple, rid: Optional[int] = None) -> None:
        """校验并保存 SN 规则（供对话框保存回调使用）。

        Raises:
            ValueError: 校验失败或名称重复时抛出，由对话框提示给用户。
        """
        name, pattern, total, remark = values
        if not name:
            raise ValueError("规则名称不能为空")
        if not pattern:
            raise ValueError("规则表达式不能为空")
        self.db.save_sn_rule(name, pattern, total, remark, rid=rid)

    def _add_sn_rule(self) -> None:
        dlg = RuleDialog("新增SN规则", digits=0,
                         help_text=rule_engine.SN_RULE_HELP,
                         mode="sn", db=self.db,
                         on_save=self._save_sn_rule_values, parent=self)
        if dlg.exec_() == QDialog.Accepted:
            self._reload_sn_rules()
            self.settings_saved.emit()

    def _edit_sn_rule(self) -> None:
        rule = self._selected_sn_rule()
        if not rule:
            QMessageBox.information(self, "提示", "请先选择一条规则")
            return
        dlg = RuleDialog("修改SN规则", rule["name"], rule["pattern"],
                         rule.get("total_len", 0), rule.get("remark", ""),
                         rule_engine.SN_RULE_HELP, mode="sn", db=self.db,
                         on_save=lambda v: self._save_sn_rule_values(v, rule["id"]),
                         parent=self)
        if dlg.exec_() == QDialog.Accepted:
            self._reload_sn_rules()
            self.settings_saved.emit()

    def _del_sn_rule(self) -> None:
        rule = self._selected_sn_rule()
        if not rule:
            QMessageBox.information(self, "提示", "请先选择一条规则")
            return
        if QMessageBox.question(self, "确认",
                                f"确定删除 SN 规则「{rule['name']}」吗？"
                                ) == QMessageBox.Yes:
            self.db.delete_sn_rule(rule["id"])
            self._reload_sn_rules()
            self.settings_saved.emit()

    # ---------------- 字段映射 ----------------

    def _build_fields_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        tip = QLabel("产品信息类别与 BarTender 模板数据源名称的对应关系；"
                     "修改后，产品管理 / 打印页面中的名称随之更改。内置字段不可删除。"
                     "「打印」类字段（如箱号）由程序在打印时自动填充，"
                     "只需把数据源名改成模板里对应的名字即可打印出来。")
        tip.setObjectName("sectionTitle")
        tip.setWordWrap(True)
        layout.addWidget(tip)

        self.fields_table = QTableWidget(0, 4)
        self.fields_table.setObjectName("fieldTable")
        self.fields_table.setHorizontalHeaderLabels(
            ["显示名称（中文）", "模板数据源名", "类型", "字段标识"])
        self.fields_table.verticalHeader().setVisible(False)
        self.fields_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.fields_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.fields_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        # 双击直接打开编辑（此前只有下方「编辑」按钮能改）
        self.fields_table.itemDoubleClicked.connect(lambda *_: self._edit_field())
        layout.addWidget(self.fields_table, 1)

        btns = QHBoxLayout()
        btns.addStretch(1)
        for text, slot in (("新增字段", self._add_field),
                           ("编辑", self._edit_field),
                           ("删除", self._del_field)):
            btn = QPushButton(text)
            btn.clicked.connect(slot)
            btns.addWidget(btn)
        layout.addLayout(btns)
        return page

    def _reload_fields(self) -> None:
        fields = self.db.list_fields()
        self.fields_table.setRowCount(0)
        for f in fields:
            row = self.fields_table.rowCount()
            self.fields_table.insertRow(row)
            kind = int(f.get("kind", 0) or 0)
            if kind == KIND_PRINT:
                kind_text = "打印"
            elif f["builtin"]:
                kind_text = "内置"
            else:
                kind_text = "自定义"
            values = [f["label"], f["datasource"], kind_text, f["fkey"]]
            for col, v in enumerate(values):
                item = QTableWidgetItem(str(v))
                item.setData(Qt.UserRole, f["id"])
                self.fields_table.setItem(row, col, item)

    def _selected_field(self) -> Optional[Dict]:
        rows = self.fields_table.selectionModel().selectedRows()
        if not rows:
            return None
        fid = self.fields_table.item(rows[0].row(), 0).data(Qt.UserRole)
        return next((f for f in self.db.list_fields() if f["id"] == fid), None)

    def _save_new_field(self, values: tuple) -> None:
        """校验并新增字段（异常由对话框提示，窗口保持打开）。

        Raises:
            ValueError: 字段为空、标识非法或已存在时抛出。
        """
        fkey, label, ds = values
        if not fkey or not label or not ds:
            raise ValueError("三项均不能为空")
        if not fkey.replace("_", "").isalnum():
            raise ValueError("字段标识仅支持字母数字下划线")
        self.db.add_field(fkey, label, ds)

    def _add_field(self) -> None:
        dlg = FieldDialog(on_save=self._save_new_field, parent=self)
        if dlg.exec_() == QDialog.Accepted:
            self._sync_field_lists()
            self._reload_fields()
            self.settings_saved.emit()

    def _save_edit_field(self, field: Dict, values: tuple) -> None:
        """校验并更新字段（异常由对话框提示，窗口保持打开）。

        Raises:
            ValueError: 名称或数据源名为空时抛出。
        """
        _, label, ds = values
        if not label or not ds:
            raise ValueError("显示名称与数据源名不能为空")
        self.db.update_field(field["id"], label, ds)

    def _edit_field(self) -> None:
        field = self._selected_field()
        if not field:
            QMessageBox.information(self, "提示", "请先选择一条字段")
            return
        dlg = FieldDialog(field["label"], field["datasource"],
                          allow_key=False, fkey=field["fkey"],
                          on_save=lambda v: self._save_edit_field(field, v),
                          parent=self)
        if dlg.exec_() == QDialog.Accepted:
            self._sync_field_lists()
            self._reload_fields()
            self.settings_saved.emit()

    def _del_field(self) -> None:
        field = self._selected_field()
        if not field:
            return
        if QMessageBox.question(self, "确认",
                                f"确定删除字段「{field['label']}」吗？\n"
                                "（已有产品数据中该字段的值将不再显示）"
                                ) != QMessageBox.Yes:
            return
        try:
            self.db.delete_field(field["id"])
        except ValueError as exc:
            QMessageBox.warning(self, "无法删除", str(exc))
            return
        self._reload_fields()
        self.settings_saved.emit()

    def _sync_field_lists(self) -> None:
        """字段增删改后，同步全部列表配置（打印记录 / 产品管理 / 各列表）。

        新增字段进打印记录时默认**不勾选**：记录表列已经很多，
        默认全展开会把表格撑得很宽；需要时到「列表设置」里勾选即可。
        """
        listconfig.sync_with_fields(self.db)
        self._reload_columns()

    # ---------------- 列表设置 ----------------

    def _build_record_columns_tab(self) -> QWidget:
        """列表设置：统一管理程序里所有列表的列顺序与显示。"""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 10, 4, 6)
        layout.setSpacing(10)

        head = QHBoxLayout()
        head.addWidget(self._tab_title("列表设置"))
        head.addStretch(1)
        head.addWidget(QLabel("选择要设置的列表"))
        self.list_selector = QComboBox()
        for key, title, _desc in listconfig.LIST_DEFS:
            self.list_selector.addItem(title, key)
        self.list_selector.setMinimumWidth(180)
        self.list_selector.currentIndexChanged.connect(
            lambda *_: self._reload_columns())
        head.addWidget(self.list_selector)
        layout.addLayout(head)

        self.list_tip = QLabel("")
        self.list_tip.setObjectName("sectionTitle")
        self.list_tip.setWordWrap(True)
        layout.addWidget(self.list_tip)

        self.columns_list = QListWidget()
        # 双击直接切换勾选，操作更快
        self.columns_list.itemDoubleClicked.connect(
            lambda item: item.setCheckState(
                Qt.Unchecked if item.checkState() == Qt.Checked else Qt.Checked))
        layout.addWidget(self.columns_list, 1)

        btns = QHBoxLayout()
        btns.addStretch(1)
        up_btn = QPushButton("上移")
        up_btn.clicked.connect(lambda: self._move_column(-1))
        btns.addWidget(up_btn)
        down_btn = QPushButton("下移")
        down_btn.clicked.connect(lambda: self._move_column(1))
        btns.addWidget(down_btn)
        default_btn = QPushButton("恢复默认")
        default_btn.clicked.connect(self._reset_columns)
        btns.addWidget(default_btn)
        save_btn = QPushButton("保存列表设置")
        save_btn.setObjectName("primary")
        save_btn.clicked.connect(self._save_record_columns)
        btns.addWidget(save_btn)
        layout.addLayout(btns)
        return page

    def _current_list_key(self) -> str:
        return self.list_selector.currentData() or listconfig.LIST_DEFS[0][0]

    def _reload_columns(self) -> None:
        key = self._current_list_key()
        desc = next((d for k, _t, d in listconfig.LIST_DEFS if k == key), "")
        suffix = "（ID 列用于定位产品，始终显示）" if key == "product_columns" else ""
        self.list_tip.setText(desc + suffix)
        cols = listconfig.load(self.db, key)
        self.columns_list.clear()
        for c in cols:
            item = QListWidgetItem(c["label"])
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if c.get("visible", True) else Qt.Unchecked)
            item.setData(Qt.UserRole, c["id"])
            self.columns_list.addItem(item)

    def _move_column(self, delta: int) -> None:
        row = self.columns_list.currentRow()
        target = row + delta
        if row < 0 or target < 0 or target >= self.columns_list.count():
            return
        item = self.columns_list.takeItem(row)
        self.columns_list.insertItem(target, item)
        self.columns_list.setCurrentRow(target)

    def _reset_columns(self) -> None:
        key = self._current_list_key()
        listconfig.reset(self.db, key)
        self._reload_columns()
        self.settings_saved.emit()

    def _save_record_columns(self) -> None:
        key = self._current_list_key()
        cols = []
        for i in range(self.columns_list.count()):
            item = self.columns_list.item(i)
            cols.append({
                "id": item.data(Qt.UserRole),
                "label": item.text(),
                "visible": item.checkState() == Qt.Checked,
            })
        listconfig.save(self.db, key, cols)
        title = listconfig.LIST_TITLES.get(key, key)
        QMessageBox.information(self, "完成", f"「{title}」的列表设置已保存")
        self._reload_columns()
        self.settings_saved.emit()

    # ---------------- 系统设置 ----------------

    def _build_system_tab(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        root = QHBoxLayout()
        outer.addLayout(root, 1)
        root.setSpacing(16)

        # 左列：打印设置（QFrame 才能正确应用 whiteCard 背景样式）
        left_card = QFrame()
        left_card.setObjectName("whiteCard")
        left = QVBoxLayout(left_card)
        left.setContentsMargins(16, 14, 16, 14)
        left.setSpacing(8)
        title = QLabel("打印设置")
        title.setStyleSheet("font-weight:bold;font-size:15px;")
        left.addWidget(title)

        self.printer_label = QLabel("默认打印机")
        left.addWidget(self.printer_label)
        printer_row = QHBoxLayout()
        self.printer_combo = QComboBox()
        self.printer_combo.setEditable(True)
        printer_row.addWidget(self.printer_combo, 1)
        refresh_btn = QPushButton("刷新")
        refresh_btn.clicked.connect(self._refresh_printers)
        printer_row.addWidget(refresh_btn)
        left.addLayout(printer_row)

        left.addWidget(QLabel("模板文件夹"))
        tpl_row = QHBoxLayout()
        self.template_dir_edit = QLineEdit()
        self.template_dir_edit.setPlaceholderText("留空使用 data 目录下的 templates")
        tpl_row.addWidget(self.template_dir_edit, 1)
        tpl_btn = QPushButton("浏览…")
        tpl_btn.clicked.connect(self._browse_template_dir)
        tpl_row.addWidget(tpl_btn)
        left.addLayout(tpl_row)

        # --- 打印记录导出设置：在这里定好，记录页点「导出」就直接按它导出 ---
        export_title = QLabel("打印记录导出")
        export_title.setStyleSheet("font-weight:bold;")
        left.addWidget(export_title)

        left.addWidget(QLabel("导出方式"))
        self.export_mode_combo = QComboBox()
        self.export_mode_combo.addItem("全部数据放在一个 sheet 里", "single")
        self.export_mode_combo.addItem("按打印日期分别存到对应的 sheet", "date")
        self.export_mode_combo.setToolTip(
            "选好后，在「打印记录」页点导出会直接按这里的方式导出，不再弹窗询问")
        left.addWidget(self.export_mode_combo)

        left.addWidget(QLabel("sheet 名称格式（按日期分表时用）"))
        self.sheet_fmt_edit = QLineEdit()
        self.sheet_fmt_edit.setPlaceholderText("留空为 yy.MM.dd，示例 26.10.19")
        self.sheet_fmt_edit.setToolTip(
            "占位符：yyyy=四位年  yy=两位年  MM=月  dd=日\n"
            "例：yy.MM.dd -> 26.10.19；yyyy-MM-dd -> 2026-10-19")
        left.addWidget(self.sheet_fmt_edit)
        self.export_mode_combo.currentIndexChanged.connect(
            self._sync_export_mode)

        left.addWidget(QLabel("工厂代码（用于 {FACTORY} 占位符）"))
        self.factory_edit = QLineEdit()
        left.addWidget(self.factory_edit)

        left.addWidget(QLabel("删除打印记录所需密码"))
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)
        left.addWidget(self.password_edit)

        self.mock_check = QCheckBox("模拟打印模式（未安装 BarTender 时调试用，"
                                    "打印内容写入 data/print_log.txt）")
        left.addWidget(self.mock_check)

        note = QLabel("提示：模板（.btw）中的数据源必须是「命名字符串」，"
                      "名称与「字段映射」一致；打印时程序只在内存中赋值，"
                      "不会保存对模板的任何修改。")
        note.setObjectName("sectionTitle")
        note.setWordWrap(True)
        left.addWidget(note)
        left.addStretch(1)

        left_col = QVBoxLayout()
        left_col.setSpacing(16)
        left_col.addWidget(left_card)
        left_col.addStretch(1)
        root.addLayout(left_col, 3)

        # 右列：数据备份 + 更新设置
        right = QVBoxLayout()
        right.setSpacing(16)

        backup_card = QFrame()
        backup_card.setObjectName("whiteCard")
        backup = QVBoxLayout(backup_card)
        backup.setContentsMargins(16, 14, 16, 14)
        backup.setSpacing(8)
        btitle = QLabel("数据备份")
        btitle.setStyleSheet("font-weight:bold;font-size:15px;")
        backup.addWidget(btitle)

        # 老版本只备主库、漏了打印记录，这里把范围写明，免得再误解
        bdesc = QLabel("备份内容：主库（产品/规则/字段/系统设置）+ 打印记录，"
                       "打包为一个 .zip")
        bdesc.setObjectName("recordHint")
        bdesc.setWordWrap(True)
        backup.addWidget(bdesc)

        auto_row = QHBoxLayout()
        self.auto_backup_check = QCheckBox("开启每日自动备份  时间点")
        auto_row.addWidget(self.auto_backup_check)
        self.backup_time_edit = QLineEdit()
        self.backup_time_edit.setFixedWidth(70)
        self.backup_time_edit.setPlaceholderText("18:00")
        auto_row.addWidget(self.backup_time_edit)
        auto_row.addWidget(QLabel("保留份数"))
        self.backup_keep_spin = QSpinBox()
        self.backup_keep_spin.setRange(1, 30)
        self.backup_keep_spin.setValue(3)
        auto_row.addWidget(self.backup_keep_spin)
        auto_row.addStretch(1)
        backup.addLayout(auto_row)

        backup.addWidget(QLabel("备份目录（留空则使用程序目录 data/backup）"))
        bdir_row = QHBoxLayout()
        self.backup_dir_edit = QLineEdit()
        bdir_row.addWidget(self.backup_dir_edit, 1)
        bdir_btn = QPushButton("浏览…")
        bdir_btn.clicked.connect(self._browse_backup_dir)
        bdir_row.addWidget(bdir_btn)
        backup.addLayout(bdir_row)

        bbtn_row = QHBoxLayout()
        now_btn = QPushButton("立即备份")
        now_btn.setObjectName("primary")
        now_btn.clicked.connect(self._backup_now)
        bbtn_row.addWidget(now_btn)
        restore_btn = QPushButton("从备份恢复…")
        restore_btn.setObjectName("danger")
        restore_btn.clicked.connect(self._restore_backup)
        bbtn_row.addWidget(restore_btn)
        bbtn_row.addStretch(1)
        backup.addLayout(bbtn_row)
        right.addWidget(backup_card)

        update_card = QFrame()
        update_card.setObjectName("whiteCard")
        update = QVBoxLayout(update_card)
        update.setContentsMargins(16, 14, 16, 14)
        update.setSpacing(8)
        utitle = QLabel("更新设置")
        utitle.setStyleSheet("font-weight:bold;font-size:15px;")
        update.addWidget(utitle)

        self.auto_update_check = QCheckBox("启动时自动检查更新（可随时关闭，不影响离线使用）")
        update.addWidget(self.auto_update_check)
        update.addWidget(QLabel("仓库地址（owner/repo 或完整 GitHub 地址，可留空）"))
        repo_row = QHBoxLayout()
        self.repo_edit = QLineEdit()
        repo_row.addWidget(self.repo_edit, 1)
        check_btn = QPushButton("检查更新")
        check_btn.clicked.connect(self._check_update_now)
        repo_row.addWidget(check_btn)
        update.addLayout(repo_row)
        self.update_status = QLabel(f"当前版本 v{VERSION}")
        self.update_status.setObjectName("sectionTitle")
        self.update_status.setWordWrap(True)
        update.addWidget(self.update_status)
        self.download_btn = QPushButton("下载更新")
        self.download_btn.setObjectName("primary")
        self.download_btn.hide()
        self.download_btn.clicked.connect(self._download_update)
        update.addWidget(self.download_btn)
        right.addWidget(update_card)
        right.addStretch(1)
        root.addLayout(right, 2)

        # 底部按钮（直接挂在 page 的布局下，避免中间容器被 GC 回收导致控件失效）
        bottom = QHBoxLayout()
        bottom.addStretch(1)
        save_btn = QPushButton("保存系统设置")
        save_btn.setObjectName("primary")
        save_btn.clicked.connect(self._save_system)
        bottom.addWidget(save_btn)
        reset_btn = QPushButton("恢复默认")
        reset_btn.clicked.connect(self._reset_system)
        bottom.addWidget(reset_btn)
        outer.addLayout(bottom)

        return page

    # ================= 系统设置逻辑 =================

    def _refresh_printers(self) -> None:
        current = self.printer_combo.currentText()
        self.printer_combo.clear()
        self.printer_combo.addItem("")
        for name in list_printers():
            self.printer_combo.addItem(name)
        self.printer_combo.setCurrentText(current)

    def _sync_export_mode(self) -> None:
        """只有「按日期分表」才需要填 sheet 名称格式。"""
        is_date = (self.export_mode_combo.currentData() or "date") == "date"
        self.sheet_fmt_edit.setEnabled(is_date)

    def _browse_template_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择模板文件夹")
        if path:
            self.template_dir_edit.setText(path)

    def _browse_backup_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择备份目录")
        if path:
            self.backup_dir_edit.setText(path)

    def _save_system(self) -> None:
        # 输入框里显示的若是「电脑默认打印机」本身，就存空串：
        # 以后在 Windows 里换了默认打印机，程序仍会自动跟随
        printer_text = self.printer_combo.currentText().strip()
        if printer_text and printer_text == system_default_printer():
            printer_text = ""
        self.db.set_setting("default_printer", printer_text)
        self.db.set_setting("template_dir", self.template_dir_edit.text().strip())
        self.db.set_setting("sheet_name_format",
                            self.sheet_fmt_edit.text().strip() or "yy.MM.dd")
        self.db.set_setting("export_mode",
                            self.export_mode_combo.currentData() or "date")
        self.db.set_setting("factory_code", self.factory_edit.text().strip())
        if self.password_edit.text():
            self.db.set_setting("delete_password", self.password_edit.text())
        self.db.set_setting("bartender_mock", "1" if self.mock_check.isChecked() else "")
        self.db.set_setting("auto_backup", "1" if self.auto_backup_check.isChecked() else "")
        self.db.set_setting("backup_time", self.backup_time_edit.text().strip() or "18:00")
        self.db.set_setting("backup_keep", self.backup_keep_spin.value())
        self.db.set_setting("backup_dir", self.backup_dir_edit.text().strip())
        self.db.set_setting("auto_check_update",
                            "1" if self.auto_update_check.isChecked() else "")
        self.db.set_setting("update_repo", self.repo_edit.text().strip())
        QMessageBox.information(self, "完成", "系统设置已保存")
        self.settings_saved.emit()

    def _reset_system(self) -> None:
        if QMessageBox.question(self, "确认", "恢复系统设置为默认值？") != QMessageBox.Yes:
            return
        from app.core.db import DEFAULT_SETTINGS
        for key, value in DEFAULT_SETTINGS.items():
            if value is not None:
                self.db.set_setting(key, value)
        self.reload()
        QMessageBox.information(self, "完成", "已恢复默认设置")
        self.settings_saved.emit()

    def _backup_now(self) -> None:
        try:
            dest = backup_mod.backup_dir(self.backup_dir_edit.text().strip())
            path = backup_mod.do_backup(dest, self.backup_keep_spin.value())
            QMessageBox.information(self, "完成", f"已备份到：\n{path}")
        except Exception as exc:
            QMessageBox.critical(self, "备份失败", str(exc))

    def _restore_backup(self) -> None:
        start_dir = self.backup_dir_edit.text().strip() or str(backup_mod.backup_dir())
        path, _ = QFileDialog.getOpenFileName(
            self, "选择备份文件", start_dir, "备份文件 (*.zip *.db)")
        if not path:
            return
        confirm = QMessageBox.question(
            self, "确认恢复", "恢复会用备份文件覆盖当前的主库与打印记录"
            "（恢复前会自动留存一份 data/before_restore.zip）。\n确定继续吗？")
        if confirm != QMessageBox.Yes:
            return
        try:
            backup_mod.restore_backup(Path(path))
            QMessageBox.information(self, "完成", "恢复成功，请重启软件使数据生效")
        except Exception as exc:
            QMessageBox.critical(self, "恢复失败", str(exc))

    def _check_update_now(self) -> None:
        self._save_silent()
        repo = self.repo_edit.text().strip()
        if not repo:
            QMessageBox.information(self, "提示", "请先填写仓库地址")
            return
        self.update_status.setText("正在检查更新…")
        from app.ui.main_window import UpdateCheckThread
        self._update_thread = UpdateCheckThread(repo)
        self._update_thread.result.connect(self.show_update_result)
        self._update_thread.start()

    def _save_silent(self) -> None:
        self.db.set_setting("update_repo", self.repo_edit.text().strip())

    def show_update_result(self, info: Optional[dict]) -> None:
        self._latest_update = info
        if info:
            self.update_status.setText(
                f"当前版本 v{VERSION} ｜ 最新版本 {info['version']}（有可用更新）")
            self.download_btn.setVisible(bool(info.get("url")))
        else:
            self.update_status.setText(f"当前版本 v{VERSION} ｜ 已是最新版本")
            self.download_btn.hide()

    def _download_update(self) -> None:
        if not self._latest_update or not self._latest_update.get("url"):
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "保存更新包", f"标签打印_{self._latest_update['version']}.zip",
            "ZIP 压缩包 (*.zip)")
        if not path:
            return
        try:
            updater.download_asset(self._latest_update["url"], Path(path))
            QMessageBox.information(
                self, "完成",
                "更新包已下载。解压后用其中的「标签打印.exe」及全部文件\n"
                "替换程序目录内同名文件即可完成更新（data 目录不受影响）。")
        except Exception as exc:
            QMessageBox.critical(self, "下载失败", str(exc))

    # ================= 总入口 =================

    def reload(self) -> None:
        """进入设置页时刷新全部选项卡。"""
        self._reload_box_rules()
        self._reload_sn_rules()
        self._reload_fields()
        self._reload_columns()
        # 系统设置回显
        self.printer_combo.clear()
        self.printer_combo.addItem("")
        for name in list_printers():
            self.printer_combo.addItem(name)
        self.printer_combo.setCurrentText(self.db.get_setting("default_printer"))
        # 需求：不在标签后加注释，直接把电脑默认打印机显示在输入框里；
        # 设置里没存过就回落到系统默认打印机，显示的就是「当前实际会用哪台」
        configured = self.db.get_setting("default_printer").strip()
        self.printer_combo.setCurrentText(
            configured or system_default_printer())
        self.template_dir_edit.setText(self.db.get_setting("template_dir"))
        self.sheet_fmt_edit.setText(
            self.db.get_setting("sheet_name_format") or "")
        mode = self.db.get_setting("export_mode") or "date"
        idx = self.export_mode_combo.findData(mode)
        self.export_mode_combo.setCurrentIndex(idx if idx >= 0 else 1)
        self._sync_export_mode()
        self.factory_edit.setText(self.db.get_setting("factory_code"))
        self.password_edit.clear()
        self.password_edit.setPlaceholderText("不修改请留空")
        self.mock_check.setChecked(self.db.get_bool("bartender_mock"))
        self.auto_backup_check.setChecked(self.db.get_bool("auto_backup"))
        self.backup_time_edit.setText(self.db.get_setting("backup_time", "18:00"))
        self.backup_keep_spin.setValue(int(self.db.get_setting("backup_keep", 3) or 3))
        self.backup_dir_edit.setText(self.db.get_setting("backup_dir"))
        self.auto_update_check.setChecked(self.db.get_bool("auto_check_update"))
        self.repo_edit.setText(self.db.get_setting("update_repo"))
        if not self._latest_update:
            self.update_status.setText(f"当前版本 v{VERSION}")
