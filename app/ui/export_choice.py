# -*- coding: utf-8 -*-
"""导出打印记录前的选择：全部放一个 sheet，还是按打印日期分 sheet。"""

from typing import Optional, Tuple

from PyQt5.QtWidgets import (QComboBox, QDialog, QDialogButtonBox,
                             QHBoxLayout, QLabel, QLineEdit, QVBoxLayout)

# 可选的格式示例，用户也可以自己填
FORMAT_PRESETS = [
    "yy.MM.dd",        # 26.10.19  ← 默认
    "yyyy.MM.dd",      # 2026.10.19
    "yy-MM-dd",        # 26-10-19
    "yyyyMMdd",        # 20261019
    "MM.dd",           # 10.19
]


class ExportChoiceDialog(QDialog):
    """选择打印记录的导出方式。

    Returns:
        (group_by_date, sheet_name_format)；用户取消时返回 None
    """

    def __init__(self, default_format: str = "yy.MM.dd",
                 record_count: int = 0, parent=None):
        super().__init__(parent)
        self.setWindowTitle("导出打印记录")
        self.setFixedWidth(420)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(12)

        root.addWidget(QLabel(f"共 {record_count} 条记录，请选择导出方式："))

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(QLabel("导出方式"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("全部数据放在一个 sheet 里", False)
        self.mode_combo.addItem("按打印日期分别存到对应的 sheet", True)
        self.mode_combo.setCurrentIndex(1)      # 默认按日期分表
        self.mode_combo.currentIndexChanged.connect(self._sync_enabled)
        row.addWidget(self.mode_combo, 1)
        root.addLayout(row)

        fmt_row = QHBoxLayout()
        fmt_row.setSpacing(8)
        fmt_row.addWidget(QLabel("sheet 名称格式"))
        self.format_combo = QComboBox()
        self.format_combo.setEditable(True)
        for preset in FORMAT_PRESETS:
            self.format_combo.addItem(preset)
        self.format_combo.setCurrentText(default_format)
        fmt_row.addWidget(self.format_combo, 1)
        root.addLayout(fmt_row)

        self.tip = QLabel("")
        self.tip.setObjectName("recordHint")
        root.addWidget(self.tip)

        self.preview_label = QLabel("")
        self.preview_label.setObjectName("recordHint")
        root.addWidget(self.preview_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("导出")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.format_combo.currentTextChanged.connect(self._refresh_preview)
        self._sync_enabled()
        self._refresh_preview()      # 构造时不会触发 textChanged，手动刷一次

    def _sync_enabled(self) -> None:
        """只有「按日期分表」时才需要填名称格式。"""
        enabled = bool(self.mode_combo.currentData())
        self.format_combo.setEnabled(enabled)
        self.tip.setText("占位符：yyyy=四位年  yy=两位年  MM=月  dd=日"
                         if enabled else "")

    def _refresh_preview(self) -> None:
        """实时显示按当前格式会得到的 sheet 名，避免导出完才发现格式填错。"""
        from app.core.excel_io import sheet_name_for_date

        try:
            sample = sheet_name_for_date("2026-10-19",
                                         self.format_combo.currentText())
        except Exception as exc:      # 格式乱填也不该崩
            sample = f"（格式有误：{exc}）"
        self.preview_label.setText(f"示例：2026-10-19 → {sample}")

    def result(self) -> Optional[Tuple[bool, str]]:
        """返回 (是否按日期分表, sheet 名称格式)。"""
        return (bool(self.mode_combo.currentData()),
                self.format_combo.currentText().strip() or "yy.MM.dd")
