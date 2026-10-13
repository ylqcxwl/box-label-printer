# -*- coding: utf-8 -*-
"""程序入口。

双击 标签打印.exe 即运行（纯绿色、无需安装、完全离线可用）。
"""

import sys
import traceback
from datetime import datetime
from pathlib import Path

# 兼容直接运行 python app/main.py（把项目根目录加入模块搜索路径）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PyQt5.QtCore import QObject, pyqtSignal
from PyQt5.QtWidgets import QApplication, QMessageBox

from app.config import DATA_DIR, DB_PATH, ensure_dirs
from app.core.db import DB

# 注意：不要在模块层导入 app.ui.style / app.ui.main_window！
# 构建样式表时会用 QPixmap 绘制下拉箭头图标，而在 QApplication 创建之前
# 创建 QPixmap 会触发 Qt 的 qFatal 直接中止进程（无任何提示），
# 事件日志里表现为「Qt5Core.dll 异常 0xc0000409」。
# 因此这两个模块必须在 QApplication 创建之后再导入（见 main()）。

ERROR_LOG = DATA_DIR / "error.log"


class ErrorSignal(QObject):
    """把全局异常转发到主线程弹窗提示（后台线程不能直接操作 UI）。"""
    notify = pyqtSignal(str)


_err_signal = ErrorSignal()


def install_excepthook() -> None:
    """安装全局异常钩子。

    目的：PyQt5 中未捕获异常会触发 qFatal 直接终止进程，界面表现为「点一下就没了」。
    这里改为写入日志并弹窗提示，保证软件不会因单个操作异常而整体退出。
    """

    def handler(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        try:
            ensure_dirs()
            with open(ERROR_LOG, "a", encoding="utf-8") as f:
                f.write(f"\n===== {datetime.now():%Y-%m-%d %H:%M:%S} =====\n{text}\n")
        except Exception:
            pass
        try:
            _err_signal.notify.emit(text)
        except Exception:
            pass

    sys.excepthook = handler


def main() -> int:
    ensure_dirs()
    # 先创建 QApplication，再导入任何会用到 QPixmap / QWidget 的界面模块
    app = QApplication(sys.argv)

    from app.ui.style import QSS          # 内部会用 QPixmap 画下拉箭头
    from app.ui.main_window import MainWindow

    app.setStyleSheet(QSS)
    app.setApplicationName("标签打印")
    app.setOrganizationName("ylqc")

    install_excepthook()
    _err_signal.notify.connect(
        lambda text: QMessageBox.critical(
            None, "程序异常",
            "操作出现错误，已记录到 data/error.log：\n\n"
            + (text.strip().splitlines()[-1] if text.strip() else "未知错误")))

    db = DB(DB_PATH)
    window = MainWindow(db)
    window.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
