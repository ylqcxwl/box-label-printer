# -*- coding: utf-8 -*-
"""打印记录存储：按年分文件，支持跨年查询。

为什么分文件：
    打印记录是唯一会无限增长的数据（每箱若干条 SN），全部塞进主库会让
    label_printer.db 越来越臃肿，备份体积大、查询也变慢。改为
    ``data/records/records_YYYY.db`` 每年一个库：
      - 单文件只装一年的数据，体积可控；
      - 查询按年份剪枝：给了日期范围就只扫涉及的年份文件；
      - 跨年查询由本模块合并多个年份文件的结果，界面层无感知。

记录 ID 编码：
    各年份文件的主键都是本地自增 ID，跨文件会撞号。对外统一暴露
    ``年份 * 10_000_000 + 本地ID`` 的全局 ID（int 型，UI 层无需改动），
    删除时再反解回（年份, 本地ID）。单年记录数远小于 1000 万，不会溢出。
"""

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

# 全局 ID 编码基数（每年最多 10_000_000 条本地记录）
ID_STRIDE = 10_000_000

YEAR_SCHEMA = """
CREATE TABLE IF NOT EXISTS print_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    box_no TEXT NOT NULL,
    seq_in_box INTEGER NOT NULL,
    product_id INTEGER,
    snapshot TEXT,
    sn TEXT,
    batch TEXT,
    produce_date TEXT,
    print_date TEXT,
    box_seq INTEGER
);
CREATE TABLE IF NOT EXISTS sn_archive (
    sn TEXT PRIMARY KEY,
    record_id INTEGER
);
CREATE INDEX IF NOT EXISTS idx_records_box ON print_records(box_no);
CREATE INDEX IF NOT EXISTS idx_records_date ON print_records(print_date);
CREATE INDEX IF NOT EXISTS idx_records_sn ON print_records(sn);
"""


def encode_id(year: int, local_id: int) -> int:
    """把（年份, 本地ID）编码为全局 ID。"""
    return int(year) * ID_STRIDE + int(local_id)


def decode_id(rid: int) -> Tuple[int, int]:
    """把全局 ID 反解为（年份, 本地ID）。"""
    rid = int(rid)
    return rid // ID_STRIDE, rid % ID_STRIDE


class RecordStore:
    """按年分文件的打印记录仓库（线程安全）。"""

    def __init__(self, directory: Path):
        self._dir = Path(directory)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conns: Dict[int, sqlite3.Connection] = {}

    # ---------------- 底层 ----------------

    def _path(self, year: int) -> Path:
        return self._dir / f"records_{year}.db"

    def _conn(self, year: int) -> sqlite3.Connection:
        with self._lock:
            conn = self._conns.get(year)
            if conn is None:
                conn = sqlite3.connect(str(self._path(year)),
                                       check_same_thread=False)
                conn.row_factory = sqlite3.Row
                conn.executescript(YEAR_SCHEMA)
                conn.commit()
                self._conns[year] = conn
            return conn

    def years(self) -> List[int]:
        """返回已存在记录文件的年份（升序）。"""
        out = []
        for p in self._dir.glob("records_*.db"):
            try:
                out.append(int(p.stem.split("_")[1]))
            except (IndexError, ValueError):
                continue
        return sorted(out)

    def close(self) -> None:
        with self._lock:
            for conn in self._conns.values():
                try:
                    conn.close()
                except Exception:
                    pass
            self._conns.clear()

    # ---------------- 写入 ----------------

    def add(self, year: int, box_no: str, seq_in_box: int, product_id: int,
            snapshot: Dict[str, Any], sn: str, batch: str, produce_date: str,
            print_date: str, box_seq: Optional[int] = None) -> int:
        """写入一条打印记录，返回全局 ID。"""
        conn = self._conn(year)
        with self._lock:
            cur = conn.execute(
                "INSERT INTO print_records(box_no,seq_in_box,product_id,snapshot,"
                "sn,batch,produce_date,print_date,box_seq) VALUES(?,?,?,?,?,?,?,?,?)",
                (box_no, seq_in_box, product_id,
                 json.dumps(snapshot, ensure_ascii=False), sn, batch,
                 produce_date, print_date, box_seq))
            local = int(cur.lastrowid)
            conn.commit()
            if sn:
                conn.execute(
                    "INSERT INTO sn_archive(sn,record_id) VALUES(?,?) "
                    "ON CONFLICT(sn) DO NOTHING", (sn, local))
                conn.commit()
        return encode_id(year, local)

    # ---------------- 查询 ----------------

    @staticmethod
    def _years_for_range(date_from: str, date_to: str,
                         all_years: Sequence[int]) -> List[int]:
        """按日期范围剪枝出需要扫描的年份；无日期条件时扫描全部。"""
        if not all_years:
            return []
        if not date_from and not date_to:
            return list(all_years)
        lo = int(date_from[:4]) if date_from else min(all_years)
        hi = int(date_to[:4]) if date_to else max(all_years)
        return [y for y in all_years if lo <= y <= hi]

    def _run(self, year: int, sql: str, params: tuple) -> List[Dict[str, Any]]:
        conn = self._conn(year)
        with self._lock:
            rows = conn.execute(sql, params).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["id"] = encode_id(year, int(r["id"]))
            d["_year"] = year
            # 打印时间拆成两列：print_date 只留日期、print_time 单独存时间。
            # 需求是记录页「打印日期」只显示日期、具体时间另起一列。
            # 放在这里派生，界面和导出都不用再做字符串截取。
            raw = str(d.get("print_date") or "")
            d["print_date"] = raw[:10]                 # 2026-10-16
            d["print_time"] = raw[11:19] if len(raw) > 10 else ""   # 09:43:50
            out.append(d)
        return out

    def query(self, sn: str = "", box_no: str = "", date_from: str = "",
              date_to: str = "", years: Optional[Sequence[int]] = None
              ) -> List[Dict[str, Any]]:
        """跨年查询打印记录。

        Args:
            sn: SN 模糊匹配
            box_no: 箱号模糊匹配
            date_from / date_to: 打印日期范围（yyyy-MM-dd）
            years: 限定年份；None 时按日期范围自动剪枝

        Returns:
            按打印时间倒序排列的记录列表（id 为全局 ID）
        """
        all_years = list(years) if years else self.years()
        scan = self._years_for_range(date_from, date_to, all_years)
        sql = "SELECT * FROM print_records WHERE 1=1"
        params: List[Any] = []
        if sn:
            sql += " AND sn LIKE ?"
            params.append(f"%{sn}%")
        if box_no:
            sql += " AND box_no LIKE ?"
            params.append(f"%{box_no}%")
        if date_from:
            sql += " AND print_date >= ?"
            params.append(f"{date_from} 00:00:00")
        if date_to:
            sql += " AND print_date <= ?"
            params.append(f"{date_to} 23:59:59")

        rows: List[Dict[str, Any]] = []
        for y in scan:
            rows.extend(self._run(y, sql, tuple(params)))
        rows.sort(key=lambda r: (r.get("print_date", ""), r["id"]), reverse=True)
        return rows

    def by_box(self, box_no: str,
               years: Optional[Sequence[int]] = None) -> List[Dict[str, Any]]:
        """按箱号取整箱记录（跨年，按箱内序号升序）。"""
        scan = list(years) if years else self.years()
        rows: List[Dict[str, Any]] = []
        for y in scan:
            rows.extend(self._run(
                y, "SELECT * FROM print_records WHERE box_no=? "
                   "ORDER BY seq_in_box", (box_no,)))
        return rows

    def max_seq(self, product_ids: Sequence[int], batch: str,
                month: str) -> Optional[int]:
        """返回给定产品/批次/月份下现存记录的最大箱流水号。

        Returns:
            最大流水号（无记录时返回 0）；若存在流水号未知的历史记录
            （box_seq 为 NULL，无法安全回退计数器）则返回 None。
        """
        if not product_ids:
            return 0
        holders = ",".join("?" * len(product_ids))
        base = (f"FROM print_records WHERE product_id IN ({holders}) "
                f"AND batch=? AND produce_date LIKE ?")
        args: List[Any] = list(product_ids) + [batch, f"{month}%"]
        best = 0
        for y in self.years():
            conn = self._conn(y)
            with self._lock:
                unknown = conn.execute(
                    f"SELECT COUNT(*) AS c {base} AND box_seq IS NULL",
                    tuple(args)).fetchone()["c"]
                if unknown:
                    return None
                row = conn.execute(
                    f"SELECT COALESCE(MAX(box_seq),0) AS m {base}",
                    tuple(args)).fetchone()
            best = max(best, int(row["m"] or 0))
        return best

    def count_boxes(self, product_ids: Sequence[int], batch: str,
                    day: str) -> int:
        """统计当天（print_date 前缀匹配）某批次的装箱件数（按箱号去重）。"""
        if not product_ids:
            return 0
        holders = ",".join("?" * len(product_ids))
        year = int(day[:4])
        boxes = set()
        for y in {year, year + 1, year - 1} & set(self.years()):
            conn = self._conn(y)
            with self._lock:
                rows = conn.execute(
                    f"SELECT DISTINCT box_no FROM print_records "
                    f"WHERE product_id IN ({holders}) AND batch=? "
                    f"AND print_date LIKE ?",
                    tuple(list(product_ids) + [batch, f"{day}%"])).fetchall()
            boxes.update(r["box_no"] for r in rows)
        return len(boxes)

    def sn_exists(self, sn: str) -> bool:
        """判断 SN 是否已存档（跨年）。"""
        for y in self.years():
            conn = self._conn(y)
            with self._lock:
                row = conn.execute(
                    "SELECT 1 FROM sn_archive WHERE sn=?", (sn,)).fetchone()
            if row:
                return True
        return False

    # ---------------- 删除 ----------------

    def delete(self, ids: Sequence[int]) -> List[Tuple[int, int]]:
        """按全局 ID 批量删除记录，返回被删的（年份, 本地ID）列表。"""
        grouped: Dict[int, List[int]] = {}
        for rid in ids:
            year, local = decode_id(rid)
            grouped.setdefault(year, []).append(local)
        removed: List[Tuple[int, int]] = []
        for year, locals_ in grouped.items():
            conn = self._conn(year)
            holders = ",".join("?" * len(locals_))
            with self._lock:
                conn.execute(
                    f"DELETE FROM sn_archive WHERE record_id IN ({holders})",
                    tuple(locals_))
                conn.execute(
                    f"DELETE FROM print_records WHERE id IN ({holders})",
                    tuple(locals_))
                conn.commit()
            removed.extend((year, i) for i in locals_)
        return removed

    # ---------------- 迁移 ----------------

    def import_rows(self, rows: Sequence[Dict[str, Any]]) -> int:
        """把旧主库里的记录搬迁进来（一次性迁移用）。

        Args:
            rows: 旧记录字典，需含 print_date（决定归属年份）

        Returns:
            成功导入条数
        """
        count = 0
        for r in rows:
            print_date = str(r.get("print_date") or "")
            year = int(print_date[:4]) if print_date[:4].isdigit() else 0
            if not year:
                continue
            self.add(year, r.get("box_no", ""), int(r.get("seq_in_box", 0) or 0),
                     r.get("product_id"),
                     json.loads(r["snapshot"]) if r.get("snapshot") else {},
                     r.get("sn", ""), r.get("batch", ""),
                     r.get("produce_date", ""), print_date, None)
            count += 1
        return count
