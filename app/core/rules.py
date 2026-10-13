# -*- coding: utf-8 -*-
"""箱号规则与 SN 规则引擎。

规则 = 固定字符 + 占位符（占位符用大括号包起来），其余字符原样输出。

箱号规则占位符：
    {YYYY}      4 位年，如 2026
    {YY}        2 位年，如 26
    {Y}         1 位年（年份最后一位 0~9），如 6
    {MM}        2 位月，如 05
    {M}         月份替换码：1~9 为数字，10=A，11=B，12=C（{MMM} 为同义写法）
    {DD}        2 位日，如 09
    {PREFIX}    产品的 SN 前缀
    {FACTORY}   工厂代码（设置页填写）
    {BATCH}     批次号（打印页面选择 0-9）
    {SEQ:n}     n 位流水号，如 {SEQ:5} -> 00001
                批次 0（正常生产）从 00001 起；返修批次按 批次 * 10^(n-1) + 流水
                起算，即批次 1 从 10001 起、批次 2 从 20001 起（{SEQR:n} 为同义写法）

SN 规则占位符：
    {PREFIX}    SN 前缀，打印时自动与产品信息核对
    {FACTORY}   工厂代码，取设置页填写值
    {BATCH}     批次，1 位数字，打印时与界面所选批次核对
    {SEQ:n}     序列号，n 位纯数字，位数可变（{SERIAL:n} 为同义写法）
规则可设置总位数 total_len（0 表示不校验）。
"""

import re
from datetime import date
from typing import Tuple

TOKEN_RE = re.compile(r"\{([A-Z]+)(?::(\d+))?\}")

# 共用计数标记：规则中出现该占位符时，使用该规则的所有产品共用一个流水计数器
# （默认按「产品 + 月份 + 批次」单独计数）
SHARED_TOKEN = "{&}"


def is_shared_rule(pattern: str) -> bool:
    """判断箱号规则是否使用共用计数（含 {&} 占位符）。

    Args:
        pattern: 箱号规则表达式

    Returns:
        True 表示使用该规则的产品共同计数，False 表示每个产品单独计数
    """
    return SHARED_TOKEN in (pattern or "")


def strip_shared_token(pattern: str) -> str:
    """移除共用计数标记，得到真正的渲染用表达式。

    `{&}` 只用于声明计数方式，本身不输出任何字符。
    """
    return (pattern or "").replace(SHARED_TOKEN, "")

MONTH_CODES = {
    1: "1", 2: "2", 3: "3", 4: "4", 5: "5", 6: "6",
    7: "7", 8: "8", 9: "9", 10: "A", 11: "B", 12: "C",
}


def month_code(month: int) -> str:
    """月份转月码（1-9 / A / B / C）。"""
    return MONTH_CODES[month]


def render_box_no(pattern: str, *, day: date, seq: int, batch: str,
                  factory: str, prefix: str) -> str:
    """按箱号规则渲染箱号。

    Args:
        pattern: 箱号规则模板，如 "MZXH{PREFIX}{Y}{M}{SEQ:5}{FACTORY}{DD}"
                 含 {&} 时表示共用计数，该标记不参与输出
        day: 生产日期（打印页面选择的日期）
        seq: 当月流水号（从 1 起）
        batch: 批次号（0-9）
        factory: 工厂代码
        prefix: 产品 SN 前缀

    Returns:
        渲染后的箱号字符串
    """
    pattern = strip_shared_token(pattern)
    batch_int = int(batch) if str(batch).isdigit() else 0

    def repl(m: "re.Match[str]") -> str:
        token, digits = m.group(1), m.group(2)
        n = int(digits) if digits else 0
        if token == "YYYY":
            return f"{day.year:04d}"
        if token == "YY":
            return f"{day.year % 100:02d}"
        if token == "Y":
            return str(day.year % 10)
        if token == "MM":
            return f"{day.month:02d}"
        if token in ("M", "MMM"):
            return month_code(day.month)
        if token == "DD":
            return f"{day.day:02d}"
        if token in ("SEQ", "SEQR"):
            # 返修批次按 批次 * 10^(n-1) 起算：批次 0 -> 00001，批次 1 -> 10001
            offset = (batch_int * (10 ** (n - 1))) if n >= 2 else batch_int * (10 ** n)
            value = offset + seq
            return str(value).zfill(n) if n else str(value)
        if token == "FACTORY":
            return factory
        if token == "BATCH":
            return str(batch)
        if token == "PREFIX":
            return prefix
        return m.group(0)  # 未知占位符原样保留

    return TOKEN_RE.sub(repl, pattern)


def validate_sn(pattern: str, sn: str, *, prefix: str, batch: str,
                factory: str, total_len: int = 0) -> Tuple[bool, str]:
    """校验 SN 是否符合规则。

    Args:
        pattern: SN 规则模板，如 "{PREFIX}/{FACTORY}{BATCH}{SERIAL:7}"
        sn: 待校验的 SN
        prefix: 产品的 SN 前缀
        batch: 打印页面选择的批次
        factory: 工厂代码
        total_len: 规则要求的 SN 总位数（0 不限制）

    Returns:
        (是否合法, 错误信息)
    """
    sn = sn.strip()
    if not sn:
        return False, "SN 为空"
    pattern = strip_shared_token(pattern)

    # {PREFIX} 只是规则里可选的一个占位符：
    #   - 写了：按它所在的位置校验（不一定在 SN 最前面）；
    #   - 没写：表示这类 SN 不含产品前缀，不做任何前缀要求。
    uses_prefix = "{PREFIX}" in pattern
    if uses_prefix and not str(prefix or "").strip():
        return False, "规则含 {PREFIX}，但该产品未设置 SN 前缀"

    # {BATCH} 与 {PREFIX} 一样是「可选占位符」：
    #   - 规则里写了 {BATCH}：才按它所在位置校验批次数字；
    #   - 规则里没写：这类 SN 本来就不含批次，录入时不校验批次。
    uses_batch = "{BATCH}" in pattern
    batch_positions = []  # 记录 BATCH 捕获组编号
    regex_parts = []
    pos = 0
    group_no = 0
    for m in TOKEN_RE.finditer(pattern):
        regex_parts.append(re.escape(pattern[pos:m.start()]))
        token, digits = m.group(1), m.group(2)
        n = int(digits) if digits else 0
        if token == "PREFIX":
            regex_parts.append(re.escape(prefix))
        elif token == "FACTORY":
            regex_parts.append(re.escape(factory))
        elif token == "BATCH":
            group_no += 1
            batch_positions.append(group_no)
            regex_parts.append(r"(\d)")
        elif token in ("SEQ", "SERIAL"):
            group_no += 1
            regex_parts.append(r"(\d{1,%d})" % n if n else r"(\d+)")
        else:
            regex_parts.append(re.escape(m.group(0)))
        pos = m.end()
    regex_parts.append(re.escape(pattern[pos:]))
    regex = "^" + "".join(regex_parts) + "$"

    m = re.match(regex, sn)
    if not m:
        return False, f"SN 不符合规则：{pattern}"

    if uses_batch:
        for g in batch_positions:
            if m.group(g) != str(batch):
                return False, (f"批次不符：SN 中批次为 {m.group(g)}，"
                               f"当前选择批次为 {batch}")

    if total_len and len(sn) != total_len:
        return False, f"SN 位数错误：应为 {total_len} 位，实际 {len(sn)} 位"

    # 注意：这里刻意不再做 sn.startswith(prefix) 的强制判断——
    # 含 {PREFIX} 的规则已在上面的正则里按其真实位置校验过；
    # 不含 {PREFIX} 的规则本就允许 SN 里没有前缀。
    return True, ""


BOX_RULE_HELP = """【箱号规则编写说明】
规则 = 固定字符 + 占位符，占位符用大括号包起来。

可用占位符：
{YYYY}   4 位年，如 2026
{YY}     2 位年，如 26
{Y}      1 位年（年份最后一位 0~9），如 6
{MM}     2 位月，如 05
{M}      月份替换码：1~9 为数字，10=A，11=B，12=C
{DD}     2 位日，如 09
{PREFIX} 产品的 SN 前缀
{FACTORY} 工厂代码（设置页填写）
{BATCH}  批次号（打印页选择 0~9）
{SEQ:n}  n 位流水号，如 {SEQ:5} -> 00001
{&}      共用计数标记（不输出字符）：加在规则任意位置后，
         使用本规则的所有产品**共同使用一个流水计数器**，
         不再按产品分开计数

计数规则：
1. 默认每个产品单独计数，每月 1 日清零重新计数；
2. 正常生产（批次 0）与每个返修批次（1~9）单独计数；
3. 返修批次的流水从 批次 * 10^(n-1) 起算：
   批次 1 -> 10001 起，批次 2 -> 20001 起；
4. 打印成功后流水号才递增，打印失败不产生跳号；
5. 规则末尾加 {&} 表示共同计数，例如：
   {YYYY}{MM}{SEQ:5}{&}  -> 该规则下所有产品共用 00001、00002…

常用示例：
{YYYY}{MM}{SEQ:5}                   2026 + 05 + 00001
{YYYY}{MM}{DD}{SEQ:5}               2026 + 05 + 09 + 00001
{YY}{MM}{DD}G{SEQ:5}                26 + 05 + 09 + G + 00001
MZXH{PREFIX}{Y}{M}{SEQ:5}{FACTORY}{DD}
                                    MZXH + 前缀 + 年 1 位 + 月替换码
                                    + 流水 5 位 + 工厂代码 + 日
                                    -> MZXH80019500001211
"""

SN_RULE_HELP = """【SN 规则编写说明】
规则 = 固定字符 + 占位符，占位符用大括号包起来。

可用占位符（都是「可选添加」——写了才校验，不写就不校验）：
{PREFIX}  SN 前缀（可选）：写在哪就校验在哪，不要求必须在 SN 最前面
{FACTORY} 工厂代码（可选）：取设置页填写值
{BATCH}   批次（可选）：1 位数字。写了才与打印页所选批次核对，
          不写表示这类 SN 不含批次，录入时不校验批次
{SEQ:7}   序列号，7 位纯数字，位数可变

固定字符原样输出，例如 "/" "-"。

常用示例：
{PREFIX}/{FACTORY}{BATCH}{SEQ:7}     前缀在前    1234/200010001（总位数 14）
{FACTORY}{BATCH}{PREFIX}{SEQ:7}      前缀在中间  2000100012340
{FACTORY}{BATCH}{SEQ:7}              不含前缀    20001 0000（12 位）
{BATCH}{PREFIX}{SEQ:6}               前缀在批次后
{PREFIX}{SEQ:8}                      不含批次    123400000001
{FACTORY}{SEQ:9}                     不含前缀也不含批次

说明：
1. 录入 SN 时按本规则校验（固定字符、占位符位置、位数都要对得上）；
2. 规则里没有 {PREFIX} 时，不要求 SN 含前缀；
3. 规则里没有 {BATCH} 时，不要求 SN 含批次，也不会比对批次；
4. 总位数填 0 表示不校验总位数。
"""


def box_rule_digits(pattern: str) -> str:
    """提取箱号规则中的流水位数（供列表「流水位数」列显示）。

    Args:
        pattern: 箱号规则表达式

    Returns:
        流水位数（字符串），未使用流水占位符时返回 "-"
    """
    m = re.search(r"\{(?:SEQ|SEQR):(\d+)\}", pattern or "")
    return m.group(1) if m else "-"


def preview_box_no(pattern: str, *, day: date = None, seq: int = 1,
                   batch: str = "0", factory: str = "2",
                   prefix: str = "8001") -> Tuple[bool, str]:
    """渲染箱号示例，供对话框「预览」按钮使用。

    Returns:
        (是否成功, 预览文本或错误信息)
    """
    if not pattern:
        return False, "请先填写规则表达式"
    try:
        return True, render_box_no(pattern, day=day or date.today(), seq=seq,
                                   batch=batch, factory=factory, prefix=prefix)
    except Exception as exc:  # 表达式语法异常
        return False, f"规则有误：{exc}"


def preview_sn(pattern: str, *, factory: str = "2", prefix: str = "1234",
               batch: str = "0") -> Tuple[bool, str]:
    """按 SN 规则生成一个示例 SN，供对话框「预览」按钮使用。

    Returns:
        (是否成功, 示例文本或错误信息)
    """
    if not pattern:
        return False, "请先填写规则表达式"
    try:
        sample = TOKEN_RE.sub(
            lambda m: {
                "PREFIX": prefix,
                "FACTORY": factory,
                "BATCH": str(batch),
            }.get(m.group(1), "0" * (int(m.group(2)) - 1) + "1"
                  if m.group(2) else "1"),
            pattern)
        return True, sample
    except Exception as exc:
        return False, f"规则有误：{exc}"
