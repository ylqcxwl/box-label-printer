# -*- coding: utf-8 -*-
"""组装交给 BarTender 的标签数据。

★ 为什么单独抽出来：
  原来「打印」和「重打印」各自组装一遍数据，两处代码一旦走偏，
  就会出现「正常打印是对的、重打印却是模板里的默认值」这种怪现象
  （重打印不走产品当前数据，而是走记录里存的快照，稍有遗漏
  BarTender 就会保留模板自带的值）。
  现在两边都调 build_label_data，保证任何时候两者完全一致。
"""

from typing import Any, Dict, List, Optional

from app.core.db import KIND_PRINT


def build_label_data(db, source: Dict[str, Any], box_no: str,
                     sns: List[str], total: Optional[int] = None
                     ) -> Dict[str, str]:
    """组装一张外箱标签要用的数据（数据源名 -> 值）。

    Args:
        db: DB 实例（用于读字段映射）
        source: 产品数据。打印时传当前产品，重打印时传记录里的 snapshot
        box_no: 箱号
        sns: 本箱的 SN 列表（按箱内序号升序）
        total: 标签上要填的 SN 位数；不传则按实际 SN 条数。
               打印不满箱时会按实际数量，重打印按箱内实际记录数。

    Returns:
        {模板数据源名: 值}；SN 位的键是 "1" / "2" / …
    """
    data: Dict[str, str] = {}
    # 产品字段：按「字段映射」里配的数据源名写值
    for f in db.list_fields():
        # 打印字段（箱号等）由程序自动填充，不从产品数据里取
        if int(f.get("kind", 0) or 0) == KIND_PRINT:
            continue
        data[f["datasource"]] = str(source.get(f["fkey"], ""))
    # 箱号：写进「字段映射」里配置的数据源名（默认 xianghao），
    # 模板里叫什么名字就填什么，箱号才打得出来
    for f in db.list_print_fields():
        if f["fkey"] == "xianghao":
            data[f["datasource"]] = box_no
    # SN 位：模板里第 1~N 个 SN 分别叫 "1" "2" …
    pad_to = total if total else len(sns)
    for i in range(pad_to):
        data[str(i + 1)] = sns[i] if i < len(sns) else ""
    return data
