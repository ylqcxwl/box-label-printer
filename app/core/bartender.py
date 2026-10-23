# -*- coding: utf-8 -*-
"""BarTender 打印封装（兼容 BarTender 10.0 及以上，COM 方式调用）。

原则：软件绝不修改模板（.btw）的任何样式及数据——
模板以只读方式打开，命名数据源仅在内存中赋值，打印完成后
以「不保存更改」方式关闭。
"""

from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from app.config import PRINT_LOG

# BarTender BtSaveOptions 枚举值（务必与官方一致，写错会「保存」模板）：
#   btPromptSave       = 0  关闭时提示是否保存
#   btDoNotSaveChanges = 1  不保存任何修改  ← 我们要的
#   btSaveChanges      = 2  保存全部修改    ← 会把打印时的改动写回 .btw！
#
# 曾在这里误用 2（以为 2 = 不保存），导致每次打印都会把内存里的数据源赋值、
# 打印机切换等改动写回模板文件。现统一用下面的常量，杜绝再写错。
BT_DO_NOT_SAVE = 1


class PrintError(Exception):
    """打印失败。"""


def list_printers() -> List[str]:
    """枚举本机可用打印机（默认打印机排在首位）。"""
    try:
        import win32print
        flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
        names = [p[2] for p in win32print.EnumPrinters(flags)]
        try:
            default = win32print.GetDefaultPrinter()
            if default in names:
                names.remove(default)
                names.insert(0, default)
        except Exception:
            pass
        return names
    except Exception:
        return []


def system_default_printer() -> str:
    """取 Windows 的默认打印机名。

    Returns:
        打印机名；读取失败（无 win32print、未设置默认打印机等）时返回空串
    """
    try:
        import win32print
        return win32print.GetDefaultPrinter() or ""
    except Exception:
        return ""


def template_name(name: str) -> str:
    """把产品里填的模板名统一成「不带 .btw 后缀」的形式。

    需求：产品管理里只填文件名即可，不必连后缀一起写。
    已经填了 .btw 的旧数据照样能识别（这里只是去掉后缀，不是再加一层）。

    Args:
        name: 产品里的模板名，如 "t"、"t.btw"、"T.BTW"

    Returns:
        去掉 .btw 后缀的名字；原值为空时返回空串
    """
    text = (name or "").strip()
    if not text:
        return ""
    return text[:-4] if text.lower().endswith(".btw") else text


def template_path(template_dir: Path, name: str) -> Path:
    """按模板目录 + 模板名拼出 .btw 文件的完整路径。

    只填文件名的产品（如 "t"）在这里补齐 .btw；
    旧数据里已经带 .btw 的不会变成 .btw.btw。

    Returns:
        .btw 文件完整路径；模板名为空时返回空路径（调用方会先判空，
        这里兜一层避免拼出 ".btw" 这种奇怪文件名）
    """
    base = template_name(name)
    return Path(template_dir) / (base + ".btw") if base else Path()


def resolve_printer(configured: str) -> str:
    """确定实际使用的打印机。

    需求：设置页没填 / 没改过时，直接跟随「电脑的默认打印机」，
    这样用户换了系统默认打印机，程序自动跟着变，不用再去设置里改一遍。

    Args:
        configured: 设置页「默认打印机」里存的值，可为空

    Returns:
        实际要用的打印机名；都取不到时返回空串（交给 BarTender 自己决定）
    """
    name = (configured or "").strip()
    return name or system_default_printer()


class BarTender:
    """BarTender COM 封装。mock=True 时不调用 BarTender，仅写打印日志。"""

    def __init__(self, mock: bool = False):
        self.mock = mock
        self._app = None
        # 上一次打印时模板里不存在的数据源名（用于排查「某字段打不出来」）
        self._last_missing: List[str] = []

    @staticmethod
    def available() -> bool:
        """检测本机是否安装 BarTender。"""
        try:
            import pythoncom
            import win32com.client
            pythoncom.CoInitialize()
            app = win32com.client.DispatchEx("BarTender.Application")
            app.Quit(BT_DO_NOT_SAVE)
            return True
        except Exception:
            return False

    def _ensure_app(self):
        if self._app is not None:
            return self._app
        import pythoncom
        import win32com.client
        pythoncom.CoInitialize()
        self._app = win32com.client.DispatchEx("BarTender.Application")
        self._app.Visible = False
        return self._app

    def print_label(self, template_path: Path, data: Dict[str, str],
                    printer: Optional[str] = None, copies: int = 1) -> None:
        """打印一张外箱标签。

        Args:
            template_path: .btw 模板完整路径
            data: 命名数据源字典，如 {"mingcheng": "...", "1": "SN1", ...}
            printer: 指定打印机名称（None 使用 BarTender 模板默认）
            copies: 打印份数

        Raises:
            PrintError: 模板不存在或打印失败
        """
        if not template_path.exists():
            raise PrintError(f"打印模板不存在：{template_path}")

        if self.mock:
            self._mock_print(template_path, data, printer, copies)
            return

        fmt = None
        try:
            app = self._ensure_app()
            # Formats.Open(路径, 是否关闭默认空白文档, 打印机)
            # 打印机在打开时就指定，避免再赋值 fmt.Printer 把文档标成「已修改」
            fmt = app.Formats.Open(str(template_path), True, printer or "")
            # 份数为 1 时不动 PrintSetup：改打印设置同样会把文档标成已修改
            if copies and copies != 1:
                try:
                    fmt.PrintSetup.IdenticalCopiesOfLabel = copies
                except Exception:
                    pass  # 老版本 BarTender 部分属性不可写，忽略
            # 仅在内存中给命名数据源赋值，模板文件保持不变
            # 空值保持空串：改坏之前的打印页就是用空串填多余位、结果正确
            missing: List[str] = []
            for key, value in data.items():
                try:
                    fmt.SetNamedSubStringValue(
                        str(key), "" if value is None else str(value))
                except Exception:
                    # 模板里没有这个数据源（字段映射没配到）时跳过，
                    # 记录下来便于排查「某个字段怎么打不出来」
                    missing.append(str(key))
            self._last_missing = missing
            fmt.PrintOut(False, False)
        except PrintError:
            raise
        except Exception as exc:  # COM 异常统一转换
            self._app = None  # BarTender 进程异常时重置连接
            raise PrintError(f"打印失败：{exc}") from exc
        finally:
            if fmt is not None:
                try:
                    # btDoNotSaveChanges：绝不把任何改动写回模板文件
                    fmt.Close(BT_DO_NOT_SAVE)
                except Exception:
                    pass

    def _mock_print(self, template_path: Path, data: Dict[str, str],
                    printer: Optional[str], copies: int) -> None:
        """模拟打印：写入打印日志，便于无 BarTender 环境下调试。"""
        lines = [
            "=" * 60,
            f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"模板: {template_path}",
            f"打印机: {printer or '(模板默认)'}  份数: {copies}",
        ]
        lines += [f"  {k} = {v}" for k, v in sorted(data.items())]
        with open(PRINT_LOG, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    def quit(self) -> None:
        """释放 BarTender 进程（程序退出时调用，不留后台进程）。"""
        if self._app is not None:
            try:
                self._app.Quit(BT_DO_NOT_SAVE)
            except Exception:
                pass
            self._app = None
