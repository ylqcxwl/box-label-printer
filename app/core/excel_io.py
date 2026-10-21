# -*- coding: utf-8 -*-
"""Excel 导入导出（中文表头）。

产品表头 = 字段映射表中的中文名；打印记录表头 = 打印记录设置中勾选的中文列名。
"""

import re
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

    # ★ 先把整表解析成数据列表，再一次性批量写库：
    #   原来逐条 add/update_product，每条一次查询 + 一次提交，
    #   实测 500 条要 62 秒；改走 db.bulk_save_products 后降到 1 秒内。
    parsed: List[Dict[str, str]] = []
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
        if not data.get("sn4", ""):
            errors.append(f"第 {line_no} 行：SN前缀为空，已跳过")
            continue
        parsed.append(data)

    if not parsed:
        return 0, 0, errors
    added, updated, bulk_errors = db.bulk_save_products(parsed)
    return added, updated, errors + bulk_errors


def sheet_name_for_date(date_text: str, fmt: str = "yy.MM.dd") -> str:
    """把 "2026-10-19" 这类日期按格式转成工作表名，如 "26.10.19"。

    支持两位/四位年与 . - / _ 分隔：yy / yyyy / MM / dd。
    格式串里不认识的字符原样保留；日期解析不出来时直接返回原字符串。

    Args:
        date_text: 形如 "2026-10-19" 的日期文本（也可能是别的东西）
        fmt: 格式，默认 "yy.MM.dd"；在系统设置里可改

    Returns:
        工作表名（已处理 Excel 的非法字符与 31 字符长度上限）
    """
    text = (date_text or "").strip()
    if not text:
        return "未填日期"
    parts = re.split(r"[-/._]", text)
    year = month = day = ""
    if len(parts) >= 3 and all(p.isdigit() for p in parts[:3]):
        year, month, day = parts[0], parts[1], parts[2]
    elif len(parts) == 1 and len(text) == 8 and text.isdigit():
        year, month, day = text[:4], text[4:6], text[6:]
    if not year:
        return sanitize_sheet_name(text)
    out = (fmt.replace("yyyy", year)
              .replace("YYYY", year)
              .replace("yy", year[-2:])
              .replace("YY", year[-2:])
              .replace("MM", month.zfill(2))
              .replace("dd", day.zfill(2))
              .replace("DD", day.zfill(2)))
    return sanitize_sheet_name(out)


def cell_text(value: Any) -> str:
    """把单元格值转成文本：None 转空串，避免显示成 "None"。"""
    return "" if value is None else str(value)


def sanitize_sheet_name(name: str) -> str:
    """把字符串整理成合法的 Excel 工作表名。

    Excel 限制：不含 : \\ / ? * [ ]，长度 ≤ 31，且不能为空。
    """
    cleaned = re.sub(r"[:\\/?*\[\]]", "-", (name or "").strip())
    cleaned = cleaned[:31] if len(cleaned) > 31 else cleaned
    return cleaned or "Sheet"


def export_records(path: Path, columns: List[Tuple[str, str]],
                   rows: List[Dict[str, Any]], *,
                   group_by_date: bool = False,
                   sheet_name_format: str = "yy.MM.dd",
                   date_column: str = "produce_date") -> Dict[str, int]:
    """导出打印记录到 Excel（中文表头）。

    Args:
        path: 目标 .xlsx 路径
        columns: [(列id, 中文列名)] 按显示顺序
        rows: 打印记录（snapshot 已解析为 product 字段）
        group_by_date: True = 按打印日期分别存到各自的 sheet；
                       False = 全部放在一个 sheet 里
        sheet_name_format: 按日期分组时的工作表名格式，默认 "yy.MM.dd"
        date_column: 取日期用的列 id，默认 produce_date

    Returns:
        {工作表名: 该表行数}，便于调用方回显导出结果
    """
    headers = [label for _, label in columns]
    wb = Workbook()
    wb.remove(wb.active)          # 去掉默认空表，自己按需建

    def fill(ws, data: List[Dict[str, Any]]) -> None:
        ws.append(headers)
        for r in data:
            # 老记录某些列可能是 NULL（如 box_seq），直接 str() 会写出 "None"
            ws.append([cell_text(r.get(cid)) for cid, _ in columns])
        _style_header(ws, len(headers))
        _auto_width(ws, len(headers), len(data))

    result: Dict[str, int] = {}
    if not group_by_date:
        ws = wb.create_sheet("打印记录")
        fill(ws, rows)
        result["打印记录"] = len(rows)
        wb.save(str(path))
        return result

    # 按日期分组，同一天的记录归到同一个 sheet
    groups: Dict[str, List[Dict[str, Any]]] = {}
    raw_date: Dict[str, str] = {}      # 表名 -> 该组第一条记录的原始日期
    for r in rows:
        raw = str(r.get(date_column, "") or "")
        key = sheet_name_for_date(raw, sheet_name_format)
        if key not in groups:
            groups[key] = []
            raw_date[key] = raw
        groups[key].append(r)

    # ★ sheet 从左往右按日期升序（26.10.20、26.10.21、26.10.22…）：
    #   记录默认是倒序查出来的，照原顺序排会导致大日期在左边。
    #   排序用**原始日期**而不是格式化后的表名——表名可能是 "MM.dd"
    #   这类不含年份的格式，拿它排序会乱。日期为空的放最后。
    order = sorted(
        groups,
        key=lambda k: (1 if not raw_date.get(k) else 0,
                       raw_date.get(k, ""), k))

    used: Dict[str, int] = {}
    for key in order:
        # 同格式下不同日期撞名（如格式只写 MM）时加序号区分，避免覆盖
        base = key
        used[base] = used.get(base, 0) + 1
        title = base if used[base] == 1 else f"{base}({used[base]})"
        ws = wb.create_sheet(sanitize_sheet_name(title))
        fill(ws, groups[key])
        result[sanitize_sheet_name(title)] = len(groups[key])
    if not groups:                 # 一条记录都没有时也要有张表
        ws = wb.create_sheet("打印记录")
        fill(ws, [])
        result["打印记录"] = 0
    wb.save(str(path))
    return result
