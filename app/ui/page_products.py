# -*- coding: utf-8 -*-
"""产品管理页面（对齐设计稿第 3 页）。

功能：搜索 / 查询 / 清空、新增、编辑、删除、Excel 批量导入导出（中文表头）。
SN 前缀唯一，其余字段可重复；字段由「设置 -> 字段映射」动态决定。
"""

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QComboBox, QDialog, QDialogButtonBox,
                             QFileDialog, QFormLayout, QHBoxLayout,
                             QLabel, QLineEdit, QMessageBox,
                             QPushButton, QTableWidget, QTableWidgetItem,
                             QVBoxLayout, QWidget)

from app.config import resolve_template_dir
from app.core.bartender import template_name
from app.core import excel_io, listconfig
from app.core.db import DB
from app.ui.table_util import freeze_widths

# 这两个字段提供下拉选项（同时允许手动输入）
COMBO_FIELD_KEYS = {"template", "sn_rule", "box_rule"}

# 搜索框宽度约束（窗口缩小时可继续变窄，不写死大宽度）
SEARCH_EDIT_MIN = 120


class ProductDialog(QDialog):
    """产品新增 / 编辑对话框（字段动态生成）。"""

    def __init__(self, db: DB, product: Optional[Dict] = None,
                 on_save: Optional[Callable[[Dict[str, str]], None]] = None,
                 parent=None):
        super().__init__(parent)
        self.db = db
        self.product = product
        self._on_save = on_save
        self.setWindowTitle("编辑产品" if product else "新增产品")
        self.setMinimumWidth(420)
        self.inputs: Dict[str, object] = {}

        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(10)
        # 字段顺序与显隐来自「设置 - 列表设置 - 新建产品弹窗」
        for f in self._form_fields():
            fkey = f["fkey"]
            if fkey in COMBO_FIELD_KEYS:
                editor = QComboBox()
                editor.setEditable(True)
                editor.addItem("")
                for opt in self._options_for(fkey):
                    editor.addItem(opt)
                if fkey == "template":
                    # 模板只填文件名：下拉里也不带后缀，打印时自动补 .btw
                    editor.setPlaceholderText("只填文件名，不用写 .btw")
                    editor.setToolTip("例如模板是 t.btw，这里填 t 即可；"
                                      "写了 .btw 也会自动处理")
                if product:
                    editor.setCurrentText(
                        template_name(str(product.get(fkey, ""))))
            else:
                editor = QLineEdit(str(product.get(fkey, "")) if product else "")
            self.inputs[fkey] = editor
            form.addRow(f["label"], editor)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("保存")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        # 不直接 connect(accept)：保存失败（如 SN 前缀重复）时必须保留窗口，
        # 否则用户只能重新打开对话框重填全部字段
        buttons.button(QDialogButtonBox.Ok).clicked.connect(self._do_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _form_fields(self) -> List[Dict[str, Any]]:
        """按「列表设置 - 新建产品弹窗」的顺序返回要显示的字段。"""
        by_key = {f["fkey"]: f for f in self.db.list_product_fields()}
        fields = []
        for c in listconfig.visible_columns(self.db, "product_form_order"):
            f = by_key.get(listconfig.field_key(c["id"]))
            if f is not None:
                fields.append(f)
        if not fields:
            # 兜底：配置为空（例如全部取消勾选）时至少给出 SN 前缀，
            # 否则产品无法保存（SN 前缀必填）
            f = by_key.get("sn4")
            if f is not None:
                fields.append(f)
        return fields

    def _do_save(self) -> None:
        """先执行保存回调，仅在成功后关闭对话框。

        保存回调抛异常（ValueError 等）时提示错误并保留当前已填内容。
        """
        if self._on_save is not None:
            try:
                self._on_save(self.values())
            except Exception as exc:
                QMessageBox.warning(self, "保存失败", str(exc))
                return
        self.accept()

    def _options_for(self, fkey: str) -> List[str]:
        if fkey == "template":
            from app.core.bartender import template_name
            template_dir = resolve_template_dir(self.db.get_setting("template_dir"))
            try:
                # 下拉里只显示文件名：产品里填的名字不写后缀，
                # 打印时由 template_path() 自动补 .btw
                return sorted({template_name(p.name)
                              for p in Path(template_dir).glob("*.btw")})
            except OSError:
                return []
        if fkey == "sn_rule":
            return [r["name"] for r in self.db.list_sn_rules()]
        if fkey == "box_rule":
            return [r["name"] for r in self.db.list_box_rules()]
        return []

    def values(self) -> Dict[str, str]:
        data = {}
        for fkey, editor in self.inputs.items():
            if isinstance(editor, QComboBox):
                data[fkey] = editor.currentText().strip()
            else:
                data[fkey] = editor.text().strip()
        return data


class ProductsPage(QWidget):
    """产品管理页。"""

    def __init__(self, db: DB, parent=None):
        super().__init__(parent)
        self.db = db
        self._products: List[Dict] = []
        self._columns: List[Dict[str, Any]] = []
        self._width_cache: Dict[str, Any] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        # 工具行
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("搜索"))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("名称 / SN前缀 / 69码（输入即筛选，回车立即刷新）")
        self.search_edit.setMinimumWidth(SEARCH_EDIT_MIN)
        self.search_edit.textChanged.connect(self.reload)
        toolbar.addWidget(self.search_edit, 1)
        clear_btn = QPushButton("清空")
        clear_btn.clicked.connect(self._clear_search)
        toolbar.addWidget(clear_btn)

        add_btn = QPushButton("+ 新增产品")
        add_btn.setObjectName("primary")
        add_btn.clicked.connect(self._add_product)
        toolbar.addWidget(add_btn)
        edit_btn = QPushButton("编辑")
        edit_btn.clicked.connect(self._edit_product)
        toolbar.addWidget(edit_btn)
        del_btn = QPushButton("删除")
        del_btn.setObjectName("danger")
        del_btn.clicked.connect(self._delete_product)
        toolbar.addWidget(del_btn)
        import_btn = QPushButton("Excel 导入")
        import_btn.clicked.connect(self._import_excel)
        toolbar.addWidget(import_btn)
        export_btn = QPushButton("Excel 导出")
        export_btn.clicked.connect(self._export_excel)
        toolbar.addWidget(export_btn)
        root.addLayout(toolbar)

        # 产品表格
        self.table = QTableWidget(0, 1)
        # objectName 用于挂专用样式：默认浅蓝选中底在白底上几乎看不出来，
        # 这里改用强调色实心填充 + 白字，一眼就能分辨选中的是哪一行
        self.table.setObjectName("productTable")
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.ExtendedSelection)
        self.table.itemDoubleClicked.connect(lambda *_: self._edit_product())
        root.addWidget(self.table, 1)

        tip = QLabel("提示：SN 前缀具有唯一性，其余字段可重复；"
                     "产品字段与数据源名称可在「设置 - 字段映射」中自行增删改。")
        tip.setObjectName("sectionTitle")
        root.addWidget(tip)

    # ================= 数据 =================

    def reload(self) -> None:
        keyword = self.search_edit.text().strip()
        self._products = self.db.list_products(keyword)
        self._columns = self._visible_columns()
        headers = [c["label"] for c in self._columns]
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setRowCount(0)
        for p in self._products:
            row = self.table.rowCount()
            self.table.insertRow(row)
            for col, text in enumerate(self._row_values(p)):
                self.table.setItem(row, col, QTableWidgetItem(text))
        # 列宽按「全量产品」量，而不是当前筛选结果：
        # 这样筛选、选中产品时列宽都锁定在最宽的那一版，不会忽长忽短。
        # 只在列结构变化时查一次全量数据，避免每次输入都重查。
        signature = tuple(headers) + ("all-products",)
        measure = None
        if self._width_cache.get("sig") != signature:
            measure = [self._row_values(p) for p in self.db.list_products("")]
        freeze_widths(self.table, self._width_cache, signature=signature,
                      min_width=76, max_width=300, overrides={0: 56},
                      measure_rows=measure)

    def _row_values(self, product: Dict[str, Any]) -> List[str]:
        """按当前列配置取出一个产品的各行文字（列宽测量与填表共用）。"""
        values = []
        for c in self._columns:
            cid = c["id"]
            values.append(str(product["_id"]) if cid == "__id__"
                          else str(product.get(listconfig.field_key(cid), "")))
        return values

    def _visible_columns(self) -> List[Dict[str, Any]]:
        cols = listconfig.visible_columns(self.db, "product_columns")
        # ID 列用于定位产品（编辑/删除靠它取 product_id），必须始终存在
        if not any(c["id"] == "__id__" for c in cols):
            cols = [{"id": "__id__", "label": "ID", "visible": True}] + cols
        return cols

    def _clear_search(self) -> None:
        self.search_edit.clear()
        self.reload()

    def _id_column(self) -> int:
        """返回「ID」列当前的列号（列顺序可被用户调整，不能写死 0）。"""
        for i, c in enumerate(self._columns):
            if c["id"] == "__id__":
                return i
        return 0

    def _selected_ids(self) -> List[int]:
        col = self._id_column()
        ids = set()
        for idx in self.table.selectionModel().selectedRows():
            item = self.table.item(idx.row(), col)
            if item:
                try:
                    ids.add(int(item.text()))
                except ValueError:
                    continue
        return sorted(ids)

    # ================= 操作 =================

    def _add_product(self) -> None:
        """新增产品：保存回调失败时对话框保持打开，方便就地修改 SN 前缀等字段。

        模板名只存文件名：去 .btw 后缀的活儿做在 DB 层
        （`DB._save_product`），这样 Excel 批量导入也一并生效。
        """
        dlg = ProductDialog(self.db, on_save=self.db.add_product, parent=self)
        if dlg.exec_() == QDialog.Accepted:
            self.reload()

    def _edit_product(self) -> None:
        ids = self._selected_ids()
        if len(ids) != 1:
            QMessageBox.information(self, "提示", "请选择一条产品记录进行编辑")
            return
        product = self.db.get_product(ids[0])
        dlg = ProductDialog(
            self.db, product,
            on_save=lambda data: self.db.update_product(ids[0], data),
            parent=self)
        if dlg.exec_() == QDialog.Accepted:
            self.reload()

    def _delete_product(self) -> None:
        ids = self._selected_ids()
        if not ids:
            QMessageBox.information(self, "提示", "请先选择要删除的产品")
            return
        confirm = QMessageBox.question(
            self, "确认删除", f"确定删除选中的 {len(ids)} 个产品吗？")
        if confirm == QMessageBox.Yes:
            self.db.delete_products(ids)
            self.reload()

    def _import_excel(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "导入产品", "", "Excel 文件 (*.xlsx *.xls)")
        if not path:
            return
        try:
            added, updated, errors = excel_io.import_products(
                Path(path), self.db.list_product_fields(), self.db)
        except Exception as exc:
            QMessageBox.critical(self, "导入失败", str(exc))
            return
        msg = f"新增 {added} 条，更新 {updated} 条"
        if errors:
            msg += "\n\n以下行未导入：\n" + "\n".join(errors[:20])
        QMessageBox.information(self, "导入完成", msg)
        self.reload()

    def _export_excel(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "导出产品", "产品信息.xlsx", "Excel 文件 (*.xlsx)")
        if not path:
            return
        try:
            excel_io.export_products(Path(path), self.db.list_product_fields(),
                                     self.db.list_products())
            QMessageBox.information(self, "完成", "产品已导出")
        except Exception as exc:
            QMessageBox.critical(self, "导出失败", str(exc))
