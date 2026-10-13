# -*- coding: utf-8 -*-
"""表格列宽工具：让列表在刷新查询结果时保持列宽稳定。"""

from typing import Any, Dict, Optional

from PyQt5.QtGui import QFontMetrics
from PyQt5.QtWidgets import QHeaderView, QTableWidget


def freeze_widths(table: QTableWidget, cache: Dict[str, Any], signature: Any,
                  min_width: int = 70, max_width: int = 340,
                  pad: int = 30, sample: int = 300,
                  overrides: Optional[Dict[int, int]] = None) -> None:
    """按列头 + 内容算一次列宽并固定，之后刷新数据不再改动。

    为什么不用 ResizeToContents：它每次填充数据都会按「当前结果集」重算列宽，
    搜索/筛选一改整张表的列宽就跳，看起来很不稳定。
    这里只在列结构（signature）变化时计算一次，之后按固定像素宽渲染，
    用户仍可手动拖动列宽。

    Args:
        cache: 调用方持有的字典，用于缓存上次的 signature 与列宽
        signature: 列结构标识（如各列表头的元组），变化时才会重算
        min_width / max_width: 单列宽度的下限 / 上限
        pad: 在文字宽度之外额外留出的内边距
        sample: 最多参考前多少行内容（行数多时避免逐行计算拖慢刷新）
        overrides: 指定列的固定宽度，如勾选框列
    """
    overrides = overrides or {}
    header = table.horizontalHeader()
    header.setStretchLastSection(False)
    header.setSectionResizeMode(QHeaderView.Interactive)

    if cache.get("sig") == signature:
        widths = cache.get("widths", [])
        for i, w in enumerate(widths):
            if i < table.columnCount():
                table.setColumnWidth(i, w)
        return

    fm = QFontMetrics(table.font())
    widths = []
    for col in range(table.columnCount()):
        if col in overrides:
            widths.append(overrides[col])
            continue
        head = table.horizontalHeaderItem(col)
        widest = fm.horizontalAdvance(head.text()) if head is not None else 0
        for row in range(min(table.rowCount(), sample)):
            item = table.item(row, col)
            if item is not None:
                widest = max(widest, fm.horizontalAdvance(item.text()))
        widths.append(max(min_width, min(max_width, widest + pad)))

    cache["sig"] = signature
    cache["widths"] = widths
    for i, w in enumerate(widths):
        table.setColumnWidth(i, w)
