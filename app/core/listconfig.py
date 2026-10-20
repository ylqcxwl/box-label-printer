# -*- coding: utf-8 -*-
"""程序内各列表的「列顺序 / 显示」配置。

统一在这里定义程序里所有可配置的列表，供「设置 - 列表设置」读写，
也供各页面读取自己的列配置。所有配置以 JSON 存在 settings 表的下列键：

    product_columns        产品管理页面表格
    print_product_columns  打印标签页左侧产品列表
    record_columns         打印记录页面表格
    product_form_order     新增 / 编辑产品对话框的字段顺序与显隐

条目的 id 统一规则：
    "__id__"          产品管理表格的「ID」列（不是字段，仅此一处）
    "field:<fkey>"    某个产品字段
    "box_no" / "sn" 等 打印记录的基础列与尾部列（见 db.RECORD_*_COLUMNS）
"""

from typing import Any, Dict, List

from app.core.db import (DB, KIND_PRINT, RECORD_BASE_COLUMNS,
                         RECORD_TAIL_COLUMNS)

# (配置键, 显示名称, 说明)
LIST_DEFS = [
    ("product_columns", "产品管理",
     "产品管理页面表格：勾选要显示的列，用「上移 / 下移」调整顺序。"),
    ("print_product_columns", "打印页产品列表",
     "打印标签页左侧产品列表：勾选要显示的列，用「上移 / 下移」调整顺序。"),
    ("product_form_order", "新建产品弹窗",
     "新增 / 编辑产品对话框中各项的顺序：取消勾选即在该弹窗中隐藏该项。"),
    ("record_columns", "打印记录",
     "打印记录页面表格：勾选要显示的列，用「上移 / 下移」调整顺序。"),
]

LIST_TITLES = {key: title for key, title, _ in LIST_DEFS}

# 打印页产品列表的默认列（沿用历史默认的 6 列）
DEFAULT_PRINT_PRODUCT_COLS = ["mingcheng", "guige", "xinghao",
                              "yanse", "sn4", "code69"]


def _entry(cid: str, label: str, visible: bool = True) -> Dict[str, Any]:
    return {"id": cid, "label": label, "visible": visible}


def defaults(key: str, db: DB) -> List[Dict[str, Any]]:
    """返回某个列表的默认列配置。"""
    fields = db.list_product_fields()          # 打印类字段不属于产品属性
    if key == "record_columns":
        cols = [_entry(cid, label) for cid, label in RECORD_BASE_COLUMNS]
        cols += [_entry("field:" + f["fkey"], f["label"]) for f in fields]
        cols += [_entry(cid, label) for cid, label in RECORD_TAIL_COLUMNS]
        return cols
    if key == "product_columns":
        return ([_entry("__id__", "ID")]
                + [_entry("field:" + f["fkey"], f["label"]) for f in fields])
    if key == "print_product_columns":
        return [_entry("field:" + f["fkey"], f["label"],
                       f["fkey"] in DEFAULT_PRINT_PRODUCT_COLS) for f in fields]
    if key == "product_form_order":
        return [_entry("field:" + f["fkey"], f["label"]) for f in fields]
    return []


def merge_missing(stored: List[Dict[str, Any]],
                  default: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """把「默认值里有、但已存配置里没有」的列补进去。

    ★ 为什么需要：列配置是存进 settings 的 JSON，一旦存过，
      后续程序新增的列（如「箱号序号」）不会自动出现，用户永远看不到。
      这里按默认顺序把缺失项插到它该在的位置，且**不动**用户已有的显隐与排序。

    Args:
        stored: 已保存的列配置
        default: 当前版本的默认列定义

    Returns:
        补齐后的列表；没有缺失时原样返回
    """
    known = {c["id"] for c in stored}
    missing = [c for c in default if c["id"] not in known]
    if not missing:
        return stored
    merged = list(stored)
    for entry in missing:
        idx = next(i for i, d in enumerate(default) if d["id"] == entry["id"])
        # 往前找第一个已存在的列，插到它后面，保持默认的相对顺序
        anchor = None
        for j in range(idx - 1, -1, -1):
            if default[j]["id"] in known:
                anchor = default[j]["id"]
                break
        pos = next((i for i, c in enumerate(merged) if c["id"] == anchor), None)
        merged.append(entry) if pos is None else merged.insert(pos + 1, entry)
        known.add(entry["id"])
    return merged


def load(db: DB, key: str) -> List[Dict[str, Any]]:
    """读取列配置；未保存过则写入并返回默认值。"""
    cols = db.get_json(key)
    if not cols:
        cols = defaults(key, db)
        db.set_json(key, cols)
        return cols
    # 补齐本版本新增、但旧配置里没有的列
    merged = merge_missing(cols, defaults(key, db))
    if len(merged) != len(cols):
        db.set_json(key, merged)
    return merged


def visible_columns(db: DB, key: str) -> List[Dict[str, Any]]:
    """读取并只保留显示的列。"""
    return [c for c in load(db, key) if c.get("visible", True)]


def field_key(cid: str) -> str:
    """从列 id 里取出字段标识（非字段列返回空串）。"""
    return cid[6:] if cid.startswith("field:") else ""


def save(db: DB, key: str, cols: List[Dict[str, Any]]) -> None:
    if key == "product_columns":
        # ID 列用于定位产品（编辑 / 删除要靠它取 product_id），不允许隐藏
        for c in cols:
            if c["id"] == "__id__":
                c["visible"] = True
    db.set_json(key, cols)


def reset(db: DB, key: str) -> List[Dict[str, Any]]:
    """恢复某个列表的默认列配置。"""
    cols = defaults(key, db)
    db.set_json(key, cols)
    return cols


def sync_with_fields(db: DB) -> None:
    """字段映射增删改后，同步全部列表配置。

    - 已删除的字段：从各列表里移除；
    - 新增的字段：补到列表末尾（打印记录里默认不勾选，表格列已经很多）；
    - 显示名称变更：同步更新表头文字。
    """
    fields = {f["fkey"]: f["label"] for f in db.list_product_fields()}
    for key, _title, _desc in LIST_DEFS:
        cols = db.get_json(key)
        if not cols:
            continue           # 还没用过这个列表，等首次打开时按默认生成
        kept: List[Dict[str, Any]] = []
        seen = set()
        for c in cols:
            cid = c["id"]
            fk = field_key(cid)
            if fk:
                if fk not in fields:
                    continue                     # 字段已删
                c["label"] = fields[fk]
            kept.append(c)
            seen.add(cid)
        for f in db.list_product_fields():
            cid = "field:" + f["fkey"]
            if cid in seen:
                continue
            # 打印记录默认不勾选，其余列表默认勾选
            kept.append(_entry(cid, f["label"],
                               visible=(key != "record_columns")))
        db.set_json(key, kept)
