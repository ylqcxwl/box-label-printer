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


class BarTender:
    """BarTender COM 封装。mock=True 时不调用 BarTender，仅写打印日志。"""

    def __init__(self, mock: bool = False):
        self.mock = mock
        self._app = None

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
            for key, value in data.items():
                try:
                    fmt.SetNamedSubStringValue(str(key), "" if value is None else str(value))
                except Exception:
                    pass  # 模板中不存在该数据源时跳过
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
