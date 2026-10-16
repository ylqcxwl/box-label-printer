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
                批次 0（正常生产）从 00001 起；返修批次按 批次 * 进制^(n-1) + 流水
                起算，即批次 1 从 10001 起、批次 2 从 20001 起（{SEQR:n} 为同义写法）
    {SEQ:n:系统}  指定流水号使用的字符集（见下方 SEQ_CHARSETS）：
                {SEQ:5:DIGIT}   纯数字        00001、00002…00009、00010
                {SEQ:5:ALPHA}   字母(区分大小写) AAAAA、AAAAB…AAAAZ、AAAAa
                {SEQ:5:ALNUM}   数字+字母      00001、00002…0000A
                {SEQ:5:HEX}     16 进制        00000、00001…00009、0000A…0000F、00010
                {SEQ:5:CUSTOM:XY} 自定义序列   X 之后是 Y，再往后 XX、XY…
                省略「系统」时默认 DIGIT（纯数字），与老规则完全兼容。

SN 规则占位符：
    {PREFIX}    SN 前缀，打印时自动与产品信息核对
    {FACTORY}   工厂代码，取设置页填写值
    {BATCH}     批次，1 位数字，打印时与界面所选批次核对
    {SEQ:n}     序列号，n 位，位数可变（{SERIAL:n} 为同义写法）
                同样支持 {SEQ:n:系统} 指定字符集，写法与箱号一致
规则可设置总位数 total_len（0 表示不校验）。
"""

import re
from datetime import date
from typing import List, Optional, Tuple

# 占位符：{标记名} 或 {标记名:参数} 或 {标记名:参数:参数…}
TOKEN_RE = re.compile(r"\{([A-Z]+)((?::[^}]*)?)\}")

# 共用计数标记：规则中出现该占位符时，使用该规则的所有产品共用一个流水计数器
# （默认按「产品 + 月份 + 批次」单独计数）
SHARED_TOKEN = "{&}"

# 流水号的可用字符集。
#
# ★ 两个关键约定（改这里前先看清楚）：
#   1. 纯数字集 DIGIT 保持「流水 1 -> 1」的历史行为，老规则产生的箱号不会变；
#   2. 其它字符集没有「1」这个字符，采用「第 n 个流水 = 字符集第 n 个字符」，
#      即字母集第 1 个是 A、16 进制第 1 个是 0，符合直觉。
SEQ_CHARSETS = {
    "DIGIT": "0123456789",
    "ALPHA": "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
    "ALNUM": "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
    "HEX": "0123456789ABCDEF",
}

# 界面下拉框用：[(代码, 显示名, 说明)]
SEQ_SYSTEM_CHOICES = [
    ("DIGIT", "纯数字", "0-9，如 00001、00002"),
    ("ALPHA", "字母（区分大小写）", "A-Z a-z，如 AAAAA、AAAAB"),
    ("ALNUM", "数字 + 字母（区分大小写）", "0-9 A-Z a-z，如 00001、0000A"),
    ("HEX", "16 进制（区分大小写）", "0-9 A-F，如 00009、0000A、00010"),
    ("CUSTOM", "自定义序列", "自己指定字符顺序，按顺序进位"),
]

CUSTOM_MAX_CHARS = 64      # 自定义序列的最大字符数（够用且避免误填一长串）



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


def parse_token_args(group: str) -> List[str]:
    """把占位符冒号后的部分拆成参数列表。

    Args:
        group: 形如 ""、":5"、":5:ALPHA"、":5:CUSTOM:ABCD" 的字符串

    Returns:
        参数列表，如 []、["5"]、["5", "ALPHA"]、["5", "CUSTOM", "ABCD"]
    """
    if not group:
        return []
    return [p for p in group.lstrip(":").split(":")]


def dedup_chars(text: str) -> str:
    """去除重复字符并保持原有顺序（自定义序列要求每个字符只出现一次）。"""
    seen, ordered = set(), []
    for ch in text or "":
        if ch not in seen:
            seen.add(ch)
            ordered.append(ch)
    return "".join(ordered)


def resolve_charset(args: List[str]) -> Tuple[int, str, str]:
    """从 SEQ 占位符的参数里解出「位数 + 字符集 + 系统代码」。

    Args:
        args: parse_token_args 的结果，如 ["5"]、["5", "ALPHA"]、
              ["5", "CUSTOM", "XYZ"]

    Returns:
        (位数, 字符集字符串, 系统代码)，无法识别时回退到纯数字

    Raises:
        无（参数非法时静默回退，避免一条规则写错就整页报错）
    """
    digits = int(args[0]) if args and args[0].isdigit() else 0
    system = (args[1] if len(args) > 1 else "DIGIT").upper()
    if system == "CUSTOM":
        custom = dedup_chars(args[2] if len(args) > 2 else "")
        if len(custom) >= 2:
            return digits, custom, "CUSTOM"
        return digits, SEQ_CHARSETS["DIGIT"], "DIGIT"
    if system in SEQ_CHARSETS:
        return digits, SEQ_CHARSETS[system], system
    return digits, SEQ_CHARSETS["DIGIT"], "DIGIT"


def seq_token(digits: int, system: str = "DIGIT", custom: str = "") -> str:
    """拼出 SEQ 占位符文本（供界面「快捷插入」与保存规则时使用）。

    Args:
        digits: 流水位数
        system: DIGIT / ALPHA / ALNUM / HEX / CUSTOM
        custom: 自定义字符集（仅 system=CUSTOM 时使用）

    Returns:
        形如 "{SEQ:5}"、"{SEQ:5:ALPHA}"、"{SEQ:5:CUSTOM:ABC}"
    """
    if system in ("", "DIGIT"):
        return "{%s:%d}" % ("SEQ", digits)
    if system == "CUSTOM":
        return "{SEQ:%d:CUSTOM:%s}" % (digits, dedup_chars(custom))
    return "{SEQ:%d:%s}" % (digits, system.upper())


def encode_seq(value: int, digits: int, charset: str) -> str:
    """把流水数值按字符集转成 N 进制字符串，用字符集首字符左补位。

    例（charset="0123456789"）：1 -> "00001"，10 -> "00010"
    例（charset="ABCDEFG..."）：1 -> "AAAAB"，26 -> "AAAAZ"
    """
    base = len(charset)
    if base < 2:
        return str(value).zfill(digits) if digits else str(value)
    if value <= 0:
        return charset[0] * digits if digits else charset[0]
    out = []
    while value > 0:
        value, rem = divmod(value, base)
        out.append(charset[rem])
    text = "".join(reversed(out))
    return text.rjust(digits, charset[0]) if digits else text


def seq_value(seq: int, batch_int: int, digits: int, charset: str) -> int:
    """算出流水号要编码的数值（含返修批次的起始偏移）。

    偏移量随进制走：批次 1 的起点是 进制^(位数-1)。

    起始值分两种情况（记住这条就能推所有字符集的结果）：
      * 字符集以 "0" 开头（纯数字 / 数字+字母 / 16 进制）：
        沿用「第 1 个流水就是 1」的历史习惯 -> 00001、00009、0000A、00010
      * 字符集不以 "0" 开头（纯字母 / 自定义）：
        没有「1」这个字符，改成「第 n 个流水 = 字符集第 n 个字符」
        -> 字母集第 1 个是 A（AAAAA），自定义集第 1 个是你填的首字符
    """
    base = len(charset)
    power = base ** (digits - 1) if digits >= 2 else base ** max(digits, 1)
    offset = batch_int * power
    step = seq if charset.startswith("0") else seq - 1
    return offset + step


def charset_class(charset: str) -> str:
    """把字符集转成正则字符类的内容（用于校验 SN 中的流水段）。"""
    return "".join(re.escape(ch) for ch in charset)


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
        token = m.group(1)
        args = parse_token_args(m.group(2))
        n = int(args[0]) if args and args[0].isdigit() else 0
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
            digits, charset, _system = resolve_charset(args)
            value = seq_value(seq, batch_int, digits, charset)
            return encode_seq(value, digits, charset)
        if token == "FACTORY":
            return factory
        if token == "BATCH":
            return str(batch)
        if token == "PREFIX":
            return prefix
        return m.group(0)  # 未知占位符原样保留

    return TOKEN_RE.sub(repl, pattern)


def validate_sn(pattern: str, sn: str, *, prefix: str, batch: str,
                factory: str, total_len: int = 0,
                day: Optional[date] = None) -> Tuple[bool, str]:
    """校验 SN 是否符合规则。

    Args:
        pattern: SN 规则模板，如 "{PREFIX}/{FACTORY}{BATCH}{SERIAL:7}"
        sn: 待校验的 SN
        prefix: 产品的 SN 前缀
        batch: 打印页面选择的批次
        factory: 工厂代码
        total_len: 规则要求的 SN 总位数（0 不限制）
        day: 生产日期。规则里写了年月日占位符时，按这个日期核对；
            留空则用今天（老规则没有日期占位符，不受影响）

    Returns:
        (是否合法, 错误信息)
    """
    sn = sn.strip()
    if not sn:
        return False, "SN 为空"
    pattern = strip_shared_token(pattern)
    day = day or date.today()

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
        token = m.group(1)
        args = parse_token_args(m.group(2))
        n = int(args[0]) if args and args[0].isdigit() else 0
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
            # 流水段的字符类来自所选字符集：纯数字 [0-9]、字母 [A-Za-z]、
            # 16 进制 [0-9A-F]、自定义集则按用户填的字符逐个转义
            _digits, charset, _system = resolve_charset(args)
            cls = charset_class(charset)
            regex_parts.append("([%s]{1,%d})" % (cls, n) if n
                               else "([%s]+)" % cls)
        elif token == "YYYY":
            # 年月日占位符和 {BATCH} 一样是「可选添加」：
            # 规则里写了就按打印页所选日期逐字核对
            regex_parts.append(re.escape("%04d" % day.year))
        elif token == "YY":
            regex_parts.append(re.escape("%02d" % (day.year % 100)))
        elif token == "Y":
            regex_parts.append(re.escape(str(day.year % 10)))
        elif token == "MM":
            regex_parts.append(re.escape("%02d" % day.month))
        elif token in ("M", "MMM"):
            regex_parts.append(re.escape(month_code(day.month)))
        elif token == "DD":
            regex_parts.append(re.escape("%02d" % day.day))
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

流水号的字符集（在「流水字符集」里选，也可手写）：
  {SEQ:5}            纯数字 0-9     00001、00002 … 00009、00010
  {SEQ:5:DIGIT}      同上（显式写法）
  {SEQ:5:ALPHA}      字母（区分大小写）AAAAA、AAAAB … AAAAAZ、AAAAAa
  {SEQ:5:ALNUM}      数字+字母（区分大小写）00001 … 0000A … 0000z
  {SEQ:5:HEX}        16 进制（区分大小写）00000 … 0000A … 0000F、00010
  {SEQ:5:CUSTOM:XY}  自定义序列：按你给的字符顺序进位，
                     第 1 个是 XXXXX，之后 XXXXY、XXXYX …
  说明：字符集以 0 开头（纯数字 / 数字+字母 / 16 进制）时，
       第 1 个流水就是 1（00001、00009、0000A、00010）；
       不以 0 开头（纯字母 / 自定义）时，第 1 个流水等于
       字符集的第 1 个字符（字母集 -> A，自定义 -> 你填的首字符）。

计数规则：
1. 默认每个产品单独计数，每月 1 日清零重新计数；
2. 正常生产（批次 0）与每个返修批次（1~9）单独计数；
3. 返修批次的流水从 批次 * 进制^(n-1) 起算（纯数字即 10^(n-1)）：
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
{YYYY}    4 位年，如 2026（与箱号规则相同的那套年月日占位符）
{YY}      2 位年，如 26
{Y}       1 位年（年份最后一位 0~9），如 6
{MM}      2 位月，如 05
{M}       月份替换码：1~9 为数字，10=A，11=B，12=C
{DD}      2 位日，如 09
{SEQ:7}   序列号，7 位，位数可变

流水号的字符集（在「流水字符集」里选，也可手写）：
  {SEQ:7}            纯数字 0-9
  {SEQ:7:ALPHA}      字母（区分大小写）A-Z a-z
  {SEQ:7:ALNUM}      数字 + 字母（区分大小写）0-9 A-Z a-z
  {SEQ:7:HEX}        16 进制（区分大小写）0-9 A-F
  {SEQ:7:CUSTOM:XY}  自定义序列，按你给的字符顺序进位

固定字符原样输出，例如 "/" "-"。
说明：年月日占位符与 {BATCH} 一样是「可选添加」——写了才按打印页所选
      生产日期核对，不写就不校验日期。

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
    for m in TOKEN_RE.finditer(pattern or ""):
        if m.group(1) in ("SEQ", "SEQR"):
            args = parse_token_args(m.group(2))
            return args[0] if args and args[0].isdigit() else "-"
    return "-"


def box_rule_charset_label(pattern: str) -> str:
    """提取箱号规则里流水号使用的字符集名称（供列表展示）。

    Returns:
        如「纯数字」「字母（区分大小写）」「自定义(ABC)」；未用流水占位符时返回 "-"
    """
    for m in TOKEN_RE.finditer(pattern or ""):
        if m.group(1) not in ("SEQ", "SEQR"):
            continue
        args = parse_token_args(m.group(2))
        _digits, charset, system = resolve_charset(args)
        if system == "CUSTOM":
            return "自定义(" + charset + ")"
        for code, label, _desc in SEQ_SYSTEM_CHOICES:
            if code == system:
                return label.split("（")[0]
        return "纯数字"
    return "-"


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
               batch: str = "0", day: Optional[date] = None) -> Tuple[bool, str]:
    """按 SN 规则生成一个示例 SN，供对话框实时预览使用。

    Returns:
        (是否成功, 示例文本或错误信息)
    """
    if not pattern:
        return False, "请先填写规则表达式"
    day = day or date.today()
    try:
        def repl(m: "re.Match[str]") -> str:
            token = m.group(1)
            args = parse_token_args(m.group(2))
            if token == "PREFIX":
                return prefix
            if token == "FACTORY":
                return factory
            if token == "BATCH":
                return str(batch)
            if token == "YYYY":
                return "%04d" % day.year
            if token == "YY":
                return "%02d" % (day.year % 100)
            if token == "Y":
                return str(day.year % 10)
            if token == "MM":
                return "%02d" % day.month
            if token in ("M", "MMM"):
                return month_code(day.month)
            if token == "DD":
                return "%02d" % day.day
            if token in ("SEQ", "SERIAL"):
                digits, charset, _system = resolve_charset(args)
                return encode_seq(seq_value(1, 0, digits, charset),
                                  digits, charset)
            return m.group(0)

        return True, TOKEN_RE.sub(repl, pattern)
    except Exception as exc:
        return False, f"规则有误：{exc}"
