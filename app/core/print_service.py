# -*- coding: utf-8 -*-
"""常驻打印服务：所有 BarTender 调用固定在同一个线程里串行执行。

★ 为什么需要它（这是「手动打印偶尔报错、再点一次又好了」的根因）：
  BarTender 是通过 COM 调用的，而 **COM 对象有线程亲和性**——
  它只能在创建它的那个线程里使用。
  原来的写法是「每次打印 new 一个 QThread」，而 BarTender 连接对象
  缓存在 BarTender 实例上被跨线程复用：
    第 1 次：线程 A 建连接 -> 打印成功
    第 2 次：线程 B 复用属于线程 A 的连接 -> 访问 app.Formats 抛异常
             -> 报错「打印失败：BarTenderApplication.Formats」
    第 3 次：上次失败时把连接置空了，线程 C 重新建连接 -> 又成功
  于是就出现「时好时坏、重新点一次又能打」的规律。

  这里改成**一个常驻线程 + 任务队列**：
  连接只建一次、之后所有打印都在同一线程里执行，
  既不会有跨线程问题，也不用每次重启 BarTender（更快）。
"""

import queue
from pathlib import Path
from typing import Any, Dict, Optional

from PyQt5.QtCore import QThread, pyqtSignal


class PrintService(QThread):
    """常驻打印线程。

    Signals:
        done(int, str, object): (任务号, 箱号, 调用方附带的数据)
        failed(int, str):       (任务号, 错误信息)
    """

    done = pyqtSignal(int, str, object)
    failed = pyqtSignal(int, str)

    def __init__(self, bartender, parent=None):
        super().__init__(parent)
        self._bt = bartender
        self._queue: "queue.Queue[Optional[tuple]]" = queue.Queue()
        self._next_id = 0

    def submit(self, template: Path, data: Dict[str, str],
               printer: str, box_no: str,
               tag: Any = None) -> int:
        """提交一个打印任务，返回任务号（用于区分回调）。

        Args:
            template: .btw 模板路径
            data: 命名数据源字典
            printer: 打印机名（空串表示用模板默认）
            box_no: 箱号（回调里带回去）
            tag: 调用方自定义的附带数据（如 SN 列表），原样回传

        Returns:
            任务号
        """
        # ★ 第一次提交时才真正启动线程：
        #   页面一构造就 start 的话，只是点开界面（或跑测试）也会留一个
        #   阻塞在队列上的线程，进程退出时容易卡住。
        if not self.isRunning():
            self.start()
        self._next_id += 1
        self._queue.put((self._next_id, template, data, printer, box_no, tag))
        return self._next_id

    def stop(self, wait_ms: int = 3000) -> None:
        """停止服务线程（放一个哨兵让它退出循环）。"""
        self._queue.put(None)
        self.wait(wait_ms)

    def run(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:      # 停止哨兵
                break
            task_id, template, data, printer, box_no, tag = item
            try:
                self._bt.print_label(template, data, printer or None,
                                     copies=1)
                self.done.emit(task_id, box_no, tag)
            except Exception as exc:      # noqa: BLE001 打印失败一律回传界面
                self.failed.emit(task_id, str(exc))
