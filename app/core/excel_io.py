# -*- coding: utf-8 -*-
"""Excel 导入导出（中文表头）。

产品表头 = 字段映射表中的中文名；打印记录表头 = 打印记录设置中勾选的中文列名。
"""

import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Tuple

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill

HEADER_FONT = Font(bold=True, color="FFFFFF")
HEADER_FILL = PatternFill("solid", fgColor="0066CC")


def _style_header(ws, ncols: int) -> None:
    for c in range(1, ncols + 1):
        cell = ws.cell(row=1, column=c)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center")


def _display_width(text: str) -> float:
    """按显示宽度估算字符数：中日韩全角字符按 2 个字符宽计算。"""
    total = 0.0
    for ch in str(text):
        total += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return total


def _auto_width(ws, ncols: int, nrows: int) -> None:
    """按表头与全部单元格内容自适应列宽（8~60）。"""
    for c in range(1, ncols + 1):
        widest = _display_width(ws.cell(row=1, column=c).value or "")
        for r in range(2, nrows + 2):
            value = ws.cell(row=r, column=c).value
            if value is None:
                continue
            widest = max(widest, _display_width(value))
        width = min(60, max(8, int(widest) + 4))
        ws.column_dimensions[ws.cell(row=1, column=c).column_letter].width = width


def export_products(path: Path, fields: List[Dict[str, Any]],
                    products: List[Dict[str, Any]]) -> None:
    """导出产品到 Excel（中文表头）。

    Args:
        path: 目标 .xlsx 路径
        fields: 字段映射列表
        products: 产品数据列表
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "产品信息"
    headers = [f["label"] for f in fields]
    ws.append(headers)
    for p in products:
        ws.append([str(p.get(f["fkey"], "")) for f in fields])
    _style_header(ws, len(headers))
    _auto_width(ws, len(headers), len(products))
    wb.save(str(path))


def import_products(path: Path, fields: List[Dict[str, Any]],
                    db) -> Tuple[int, int, List[str]]:
    """从 Excel 批量导入产品（中文表头，按 SN前缀 去重更新）。

    Args:
        path: 源 .xlsx 路径
        fields: 字段映射列表
        db: DB 实例

    Returns:
        (新增数, 更新数, 错误信息列表)
    """
    wb = load_workbook(str(path), read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    wb.close()
    if not rows:
        return 0, 0, ["Excel 内容为空"]

    label_to_key = {f["label"]: f["fkey"] for f in fields}
    header = [str(h).strip() if h is not None else "" for h in rows[0]]
    col_map = {}  # 列号 -> fkey
    for idx, h in enumerate(header):
        if h in label_to_key:
            col_map[idx] = label_to_key[h]
    if not col_map:
        return 0, 0, ["未识别到任何中文表头，请先导出一份模板核对表头"]

    added = updated = 0
    errors: List[str] = []
    for line_no, row in enumerate(rows[1:], start=2):
        data: Dict[str, str] = {}
        for idx, fkey in col_map.items():
            value = row[idx] if idx < len(row) else ""
            if isinstance(value, float) and value.is_integer():
                value = int(value)
            data[fkey] = "" if value is None else str(value).strip()
        if not any(data.values()):
            continue  # 跳过空行
        prefix = data.get("sn4", "")
        if not prefix:
            errors.append(f"第 {line_no} 行：SN前缀为空，已跳过")
            continue
        try:
            existing = db.query("SELECT id FROM products WHERE sn_prefix=?", (prefix,))
            if existing:
                db.update_product(existing[0]["id"], data)
                updated += 1
            else:
                db.add_product(data)
                added += 1
        except ValueError as exc:
            errors.append(f"第 {line_no} 行：{exc}")
    return added, updated, errors


def export_records(path: Path, columns: List[Tuple[str, str]],
                   rows: List[Dict[str, Any]]) -> None:
    """导出打印记录到 Excel（中文表头）。

    Args:
        path: 目标 .xlsx 路径
        columns: [(列id, 中文列名)] 按显示顺序
        rows: 打印记录（snapshot 已解析为 product 字段）
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "打印记录"
    headers = [label for _, label in columns]
    ws.append(headers)
    for r in rows:
        ws.append([str(r.get(cid, "")) for cid, _ in columns])
    _style_header(ws, len(headers))
    _auto_width(ws, len(headers), len(rows))
    wb.save(str(path))
