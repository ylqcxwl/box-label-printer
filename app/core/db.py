# -*- coding: utf-8 -*-
"""SQLite 数据层。

表结构：
    settings      键值配置
    fields        产品字段映射（中文名 <-> 模板数据源名，可增删改）
    products      产品信息（data 为 JSON，键为字段 fkey；sn_prefix 唯一）
    box_rules     箱号规则
    sn_rules      SN 规则
    box_counters  箱号流水计数（按 产品 + 月份 + 批次 独立计数，每月清零）
    drafts        当前箱未打印的 SN 暂存（防软件中途关闭丢失）
    print_records 打印记录（含产品快照 JSON）
    sn_archive    已打印 SN 存档（数据追溯：禁止重复录入）
"""

import json
import sqlite3
import threading
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core import rules
from app.core.records import RecordStore

# 字段类别
KIND_PRODUCT = 0    # 产品字段：在产品管理 / 打印页产品详情中出现，可随产品录入
KIND_PRINT = 1      # 打印字段：打印时才由程序自动填充（如箱号），不属产品属性

# 内置字段：(fkey, 中文名, 模板数据源名, 类别)
BUILTIN_FIELDS = [
    ("mingcheng", "名称", "mingcheng", KIND_PRODUCT),
    ("guige", "规格", "guige", KIND_PRODUCT),
    ("xinghao", "型号", "xinghao", KIND_PRODUCT),
    ("yanse", "颜色", "yanse", KIND_PRODUCT),
    ("sn4", "SN前缀", "SN4", KIND_PRODUCT),
    ("sku", "SKU", "SKU", KIND_PRODUCT),
    ("code69", "69码", "code69", KIND_PRODUCT),
    ("shuliang", "数量", "shuliang", KIND_PRODUCT),
    ("zhongliang", "重量", "zhongliang", KIND_PRODUCT),
    ("template", "打印模板", "template", KIND_PRODUCT),
    ("sn_rule", "SN规则", "sn_rule", KIND_PRODUCT),
    ("box_rule", "箱号规则", "box_rule", KIND_PRODUCT),
    # 打印时自动填充：数据源名可改，用于把箱号映射到模板里任意命名的数据源
    ("xianghao", "箱号", "xianghao", KIND_PRINT),
]

# 打印记录可选列（产品字段列在此基础上动态追加）
RECORD_BASE_COLUMNS = [
    ("box_no", "箱号"),
    ("seq_in_box", "箱内序号"),
]
RECORD_TAIL_COLUMNS = [
    ("sn", "SN"),
    ("batch", "批次"),
    ("produce_date", "生产日期"),
    ("print_date", "打印日期"),
]

DEFAULT_BOX_RULES = [
    ("年+月+流水", "{YYYY}{MM}{SEQ:5}", "2026 + 05 + 00001"),
    ("年+月+日+流水", "{YYYY}{MM}{DD}{SEQ:5}", "2026 + 05 + 09 + 00001"),
    ("年2位+月+日+替换码+流水", "{YY}{MM}{DD}G{SEQ:5}", "26 + 05 + 09 + G + 00001"),
    ("CB通用规则", "MZXH{PREFIX}{Y}{M}{SEQ:5}{FACTORY}{DD}",
     "MZXH + 前缀 + 年1位 + 月替换码 + 流水5位 + 工厂代码 + 日"),
]

DEFAULT_SN_RULES = [
    ("CB流水号", "{PREFIX}/{FACTORY}{BATCH}{SEQ:7}", 14, "示例 1234/200010001"),
    ("13位SN", "{PREFIX}{FACTORY}{BATCH}{SEQ:7}", 13, "示例 123420001000"),
    ("12位SN", "{PREFIX}{BATCH}{SEQ:6}", 12, "示例 12340001000 位数不足时请按实际调整"),
    ("14位SN（前缀/工厂+批次+7位流水）", "{PREFIX}/{FACTORY}{BATCH}{SEQ:7}", 14,
     "示例 1234/200010001"),
    ("13位SN（前缀+工厂+批次+7位流水）", "{PREFIX}{FACTORY}{BATCH}{SEQ:7}", 13,
     "示例 123420001000"),
    ("12位SN（前缀+批次+6位流水）", "{PREFIX}{BATCH}{SEQ:6}", 12,
     "示例 12340001000 位数不足时请按实际调整"),
]

# 老版本默认规则 -> 新命名（升级时自动改名并同步产品引用）
BOX_RULE_MIGRATION = {
    "年月流水": "年+月+流水",
    "年月日流水": "年+月+日+流水",
    "短年代码流水": "年2位+月+日+替换码+流水",
}
SN_RULE_MIGRATION = {"标准SN规则": "CB流水号"}

# 各默认规则的历史表达式：命中说明该条仍是出厂默认值，可安全升级为新写法
# （用户自行改过的规则不在其中，不会被覆盖）
BOX_RULE_LEGACY_PATTERNS = {
    "年+月+流水": {"{YYYY}{MM}{SEQ:5}"},
    "年+月+日+流水": {"{YYYY}{MM}{DD}{SEQ:5}"},
    "年2位+月+日+替换码+流水": {"{YY}{MM}{DD}G{SEQ:5}"},
    "CB通用规则": {"MZXH{PREFIX}{Y}{MMM}{SEQR:5}{FACTORY}{DD}",
                   "MZXH{PREFIX}{Y}{M}{SEQ:5}{FACTORY}{DD}"},
}
SN_RULE_LEGACY_PATTERNS = {
    "CB流水号": {"{PREFIX}/{FACTORY}{BATCH}{SERIAL:7}",
                 "{PREFIX}/{FACTORY}{BATCH}{SEQ:7}"},
}

DEFAULT_SETTINGS: Dict[str, Any] = {
    "factory_code": "2",
    "default_printer": "",
    "template_dir": "",            # 空 = 程序根目录
    "delete_password": "123456",
    "auto_backup": False,
    "backup_time": "18:00",
    "backup_keep": 3,
    "backup_dir": "",              # 空 = data/backup
    "auto_check_update": False,
    "update_repo": "",             # owner/repo，可留空
    "last_backup_date": "",
    "record_columns": None,        # None = 首次由字段表生成
    "bartender_mock": False,       # True = 无 BarTender 环境时模拟打印
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS fields (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fkey TEXT UNIQUE NOT NULL,
    label TEXT NOT NULL,
    datasource TEXT NOT NULL,
    builtin INTEGER DEFAULT 0,
    sort INTEGER DEFAULT 0,
    kind INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sn_prefix TEXT UNIQUE NOT NULL,
    data TEXT NOT NULL,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS box_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    pattern TEXT NOT NULL,
    remark TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS sn_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    pattern TEXT NOT NULL,
    total_len INTEGER DEFAULT 0,
    remark TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS box_counters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL,
    month TEXT NOT NULL,
    batch TEXT NOT NULL,
    value INTEGER DEFAULT 0,
    UNIQUE(product_id, month, batch)
);
CREATE TABLE IF NOT EXISTS drafts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL,
    batch TEXT NOT NULL,
    produce_date TEXT NOT NULL,
    sn TEXT NOT NULL,
    seq INTEGER NOT NULL
);
"""
# 说明：print_records / sn_archive 已迁到 data/records/records_YYYY.db
#（见 app/core/records.py）。旧库里若仍存在这两张表，启动时会自动搬迁。


class DB:
    """SQLite 封装（线程安全，单例使用）。"""

    def __init__(self, path: Path, records_dir: Optional[Path] = None):
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()
        from app.config import RECORDS_DIR
        self.records = RecordStore(records_dir or RECORDS_DIR)
        self._upgrade_fields()
        self._init_defaults()
        self._migrate_records_out()

    # ---------------- 基础 ----------------

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            return cur

    def query(self, sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def close(self) -> None:
        self.records.close()
        with self._lock:
            self._conn.close()

    # ---------------- 配置 ----------------

    def get_setting(self, key: str, default: Any = "") -> Any:
        rows = self.query("SELECT value FROM settings WHERE key=?", (key,))
        if not rows:
            return DEFAULT_SETTINGS.get(key, default)
        return rows[0]["value"]

    def set_setting(self, key: str, value: Any) -> None:
        self.execute(
            "INSERT INTO settings(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, "" if value is None else str(value)),
        )

    def get_json(self, key: str, default: Any = None) -> Any:
        raw = self.get_setting(key, "")
        if not raw:
            return default
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            return default

    def set_json(self, key: str, obj: Any) -> None:
        self.set_setting(key, json.dumps(obj, ensure_ascii=False))

    def get_bool(self, key: str) -> bool:
        return str(self.get_setting(key, "")).lower() in ("1", "true", "yes", "on")

    # ---------------- 初始化默认数据 ----------------

    def _upgrade_fields(self) -> None:
        """补齐 fields 表的 kind 列，并补上后加的内置字段（如箱号）。

        老版本库没有 kind 列，也没有箱号字段；这里做一次幂等升级，
        保证升级上来的用户也能在「字段映射」里看到并映射箱号。
        """
        cols = [r["name"] for r in
                self.query("PRAGMA table_info(fields)")]
        if "kind" not in cols:
            self.execute("ALTER TABLE fields ADD COLUMN kind INTEGER DEFAULT 0")
        for i, (fkey, label, ds, kind) in enumerate(BUILTIN_FIELDS):
            if self.field_by_key(fkey):
                continue
            max_sort = self.query("SELECT COALESCE(MAX(sort),0) AS m FROM fields")[0]["m"]
            self.execute(
                "INSERT INTO fields(fkey,label,datasource,builtin,sort,kind) "
                "VALUES(?,?,?,?,?,?)",
                (fkey, label, ds, 1, max_sort + 1 + i, kind))

    def _init_defaults(self) -> None:
        if not self.list_fields():
            for i, (fkey, label, ds, kind) in enumerate(BUILTIN_FIELDS):
                self.execute(
                    "INSERT INTO fields(fkey,label,datasource,builtin,sort,kind) "
                    "VALUES(?,?,?,?,?,?)",
                    (fkey, label, ds, 1, i, kind),
                )
        self._migrate_rule_names()
        self._upgrade_default_rules()
        for name, pattern, remark in DEFAULT_BOX_RULES:
            if not self.query("SELECT 1 FROM box_rules WHERE name=?", (name,)):
                self.execute(
                    "INSERT INTO box_rules(name,pattern,remark) VALUES(?,?,?)",
                    (name, pattern, remark),
                )
        for name, pattern, total_len, remark in DEFAULT_SN_RULES:
            if not self.query("SELECT 1 FROM sn_rules WHERE name=?", (name,)):
                self.execute(
                    "INSERT INTO sn_rules(name,pattern,total_len,remark) VALUES(?,?,?,?)",
                    (name, pattern, total_len, remark),
                )
        for key, value in DEFAULT_SETTINGS.items():
            if value is None:
                continue
            if not self.query("SELECT 1 FROM settings WHERE key=?", (key,)):
                self.set_setting(key, value)

    def _migrate_records_out(self) -> None:
        """把旧版本主库里的 print_records / sn_archive 搬迁到按年分文件。

        仅在老库里确实留有这两张表且非空时执行一次；搬迁完成后删掉旧表，
        主库从此只放配置与产品数据。
        """
        tables = {r["name"] for r in
                  self.query("SELECT name FROM sqlite_master WHERE type='table'")}
        if "print_records" not in tables:
            return
        rows = self.query("SELECT * FROM print_records ORDER BY id")
        if not rows:
            self.execute("DROP TABLE IF EXISTS print_records")
            self.execute("DROP TABLE IF EXISTS sn_archive")
            return
        moved = self.records.import_rows(rows)
        self.execute("DROP TABLE IF EXISTS print_records")
        self.execute("DROP TABLE IF EXISTS sn_archive")
        # 记录一次迁移痕迹，便于排查
        self.set_setting("records_migrated", f"{moved}@{datetime.now():%Y-%m-%d %H:%M}")

    def _migrate_rule_names(self) -> None:
        """把老版本默认规则重命名为新命名，并同步产品的规则引用。

        目的：升级后老用户已有的产品配置不会因规则改名而失效。
        """
        for old, new in BOX_RULE_MIGRATION.items():
            rows = self.query("SELECT id FROM box_rules WHERE name=?", (old,))
            if not rows:
                continue
            if self.query("SELECT 1 FROM box_rules WHERE name=?", (new,)):
                self.execute("DELETE FROM box_rules WHERE id=?", (rows[0]["id"],))
            else:
                self.execute("UPDATE box_rules SET name=? WHERE id=?",
                             (new, rows[0]["id"]))
            self._rename_product_rule(old, new, "box_rule")
        for old, new in SN_RULE_MIGRATION.items():
            rows = self.query("SELECT id FROM sn_rules WHERE name=?", (old,))
            if not rows:
                continue
            if self.query("SELECT 1 FROM sn_rules WHERE name=?", (new,)):
                self.execute("DELETE FROM sn_rules WHERE id=?", (rows[0]["id"],))
            else:
                self.execute("UPDATE sn_rules SET name=? WHERE id=?",
                             (new, rows[0]["id"]))
            self._rename_product_rule(old, new, "sn_rule")

    def _upgrade_default_rules(self) -> None:
        """把出厂默认规则的内容升级到当前版本写法。

        仅在表达式仍为历史默认值（或已是新默认值）时更新，
        用户自行改过的规则保持原样，不会被覆盖。
        """
        # 备注是否仍为出厂旧文案（SQLite 的 LIKE 对中文前缀不可靠，故在 Python 侧判断）
        def is_legacy_remark(text: str) -> bool:
            return not text or text.startswith("示例：") or text.startswith("示例 ")

        for name, pattern, remark in DEFAULT_BOX_RULES:
            rows = self.query(
                "SELECT id, pattern, remark FROM box_rules WHERE name=?", (name,))
            if not rows:
                continue
            cur = rows[0]
            if cur["pattern"] not in BOX_RULE_LEGACY_PATTERNS.get(name, set()) | {pattern}:
                continue  # 用户自定义规则，保持原样
            if cur["pattern"] != pattern or is_legacy_remark(cur.get("remark", "")):
                self.execute("UPDATE box_rules SET pattern=?, remark=? WHERE id=?",
                             (pattern, remark, cur["id"]))
        for name, pattern, total_len, remark in DEFAULT_SN_RULES:
            rows = self.query(
                "SELECT id, pattern, remark FROM sn_rules WHERE name=?", (name,))
            if not rows:
                continue
            cur = rows[0]
            if cur["pattern"] not in SN_RULE_LEGACY_PATTERNS.get(name, set()) | {pattern}:
                continue
            if cur["pattern"] != pattern or is_legacy_remark(cur.get("remark", "")):
                self.execute(
                    "UPDATE sn_rules SET pattern=?, total_len=?, remark=? WHERE id=?",
                    (pattern, total_len, remark, cur["id"]))

    def _rename_product_rule(self, old: str, new: str, field_key: str) -> None:
        """更新产品 data JSON 中引用的规则名称。"""
        import json as _json
        for row in self.query("SELECT id, data FROM products"):
            data = _json.loads(row["data"])
            if data.get(field_key) == old:
                data[field_key] = new
                self.execute("UPDATE products SET data=? WHERE id=?",
                             (_json.dumps(data, ensure_ascii=False), row["id"]))

    # ---------------- 字段映射 ----------------

    def list_fields(self) -> List[Dict[str, Any]]:
        """全部字段（含打印时自动填充的字段，如箱号）。"""
        return self.query("SELECT * FROM fields ORDER BY sort, id")

    def list_product_fields(self) -> List[Dict[str, Any]]:
        """仅产品字段：用于产品表格、新增/编辑产品、Excel 导入导出。

        打印字段（箱号等）由程序在打印时自动填充，不属于产品属性，
        不能出现在产品录入界面里。
        """
        return self.query(
            "SELECT * FROM fields WHERE COALESCE(kind,0)=? ORDER BY sort, id",
            (KIND_PRODUCT,))

    def list_print_fields(self) -> List[Dict[str, Any]]:
        """打印时自动填充的字段（数据源名可改，用于对接模板）。"""
        return self.query(
            "SELECT * FROM fields WHERE COALESCE(kind,0)=? ORDER BY sort, id",
            (KIND_PRINT,))

    def field_by_key(self, fkey: str) -> Optional[Dict[str, Any]]:
        rows = self.query("SELECT * FROM fields WHERE fkey=?", (fkey,))
        return rows[0] if rows else None

    def add_field(self, fkey: str, label: str, datasource: str,
                  kind: int = KIND_PRODUCT) -> None:
        if self.field_by_key(fkey):
            raise ValueError(f"字段标识 {fkey} 已存在")
        max_sort = self.query("SELECT COALESCE(MAX(sort),0) AS m FROM fields")[0]["m"]
        self.execute(
            "INSERT INTO fields(fkey,label,datasource,builtin,sort,kind) "
            "VALUES(?,?,?,0,?,?)",
            (fkey, label, datasource, max_sort + 1, kind),
        )

    def update_field(self, fid: int, label: str, datasource: str) -> None:
        self.execute("UPDATE fields SET label=?, datasource=? WHERE id=?",
                     (label, datasource, fid))

    def delete_field(self, fid: int) -> None:
        row = self.query("SELECT builtin FROM fields WHERE id=?", (fid,))
        if row and row[0]["builtin"]:
            raise ValueError("内置字段不可删除")
        self.execute("DELETE FROM fields WHERE id=?", (fid,))

    # ---------------- 产品 ----------------

    def list_products(self, keyword: str = "") -> List[Dict[str, Any]]:
        rows = self.query("SELECT * FROM products ORDER BY id")
        result = []
        for r in rows:
            data = json.loads(r["data"])
            data["_id"] = r["id"]
            if keyword:
                kw = keyword.lower()
                hay = " ".join(str(v) for v in data.values()).lower()
                if kw not in hay:
                    continue
            result.append(data)
        return result

    def get_product(self, pid: int) -> Optional[Dict[str, Any]]:
        rows = self.query("SELECT * FROM products WHERE id=?", (pid,))
        if not rows:
            return None
        data = json.loads(rows[0]["data"])
        data["_id"] = rows[0]["id"]
        return data

    def _save_product(self, data: Dict[str, Any]) -> Dict[str, Any]:
        clean = {k: v for k, v in data.items() if not k.startswith("_")}
        return clean

    def add_product(self, data: Dict[str, Any]) -> int:
        clean = self._save_product(data)
        prefix = str(clean.get("sn4", "")).strip()
        if not prefix:
            raise ValueError("SN前缀不能为空")
        if self.query("SELECT 1 FROM products WHERE sn_prefix=?", (prefix,)):
            raise ValueError(f"SN前缀 {prefix} 已存在（SN前缀必须唯一）")
        cur = self.execute(
            "INSERT INTO products(sn_prefix,data,created_at) VALUES(?,?,?)",
            (prefix, json.dumps(clean, ensure_ascii=False),
             datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        )
        return cur.lastrowid

    def update_product(self, pid: int, data: Dict[str, Any]) -> None:
        clean = self._save_product(data)
        prefix = str(clean.get("sn4", "")).strip()
        if not prefix:
            raise ValueError("SN前缀不能为空")
        dup = self.query("SELECT id FROM products WHERE sn_prefix=? AND id<>?",
                         (prefix, pid))
        if dup:
            raise ValueError(f"SN前缀 {prefix} 已被其他产品使用")
        self.execute("UPDATE products SET sn_prefix=?, data=? WHERE id=?",
                     (prefix, json.dumps(clean, ensure_ascii=False), pid))

    def delete_products(self, ids: List[int]) -> None:
        for pid in ids:
            self.execute("DELETE FROM products WHERE id=?", (pid,))

    # ---------------- 规则 ----------------

    def list_box_rules(self) -> List[Dict[str, Any]]:
        return self.query("SELECT * FROM box_rules ORDER BY id")

    def list_sn_rules(self) -> List[Dict[str, Any]]:
        return self.query("SELECT * FROM sn_rules ORDER BY id")

    def _check_rule_name(self, table: str, name: str,
                         rid: Optional[int]) -> None:
        """校验规则名称唯一性。

        Raises:
            ValueError: 名称已被其他规则占用时抛出（提示语给用户看，
                比直接抛 sqlite 的 UNIQUE 约束错误友好）。
        """
        sql = f"SELECT id FROM {table} WHERE name=?"
        for row in self.query(sql, (name,)):
            if rid is None or int(row["id"]) != int(rid):
                raise ValueError(f"规则名称「{name}」已存在，请换一个名称")

    def save_box_rule(self, name: str, pattern: str, remark: str = "",
                      rid: Optional[int] = None) -> None:
        """新增或更新箱号规则。

        Raises:
            ValueError: 名称为空或重名。
        """
        if not name:
            raise ValueError("规则名称不能为空")
        self._check_rule_name("box_rules", name, rid)
        if rid:
            self.execute("UPDATE box_rules SET name=?,pattern=?,remark=? WHERE id=?",
                         (name, pattern, remark, rid))
        else:
            self.execute("INSERT INTO box_rules(name,pattern,remark) VALUES(?,?,?)",
                         (name, pattern, remark))

    def save_sn_rule(self, name: str, pattern: str, total_len: int = 0,
                     remark: str = "", rid: Optional[int] = None) -> None:
        """新增或更新 SN 规则。

        Raises:
            ValueError: 名称为空或重名。
        """
        if not name:
            raise ValueError("规则名称不能为空")
        self._check_rule_name("sn_rules", name, rid)
        if rid:
            self.execute(
                "UPDATE sn_rules SET name=?,pattern=?,total_len=?,remark=? WHERE id=?",
                (name, pattern, total_len, remark, rid))
        else:
            self.execute(
                "INSERT INTO sn_rules(name,pattern,total_len,remark) VALUES(?,?,?,?)",
                (name, pattern, total_len, remark))

    def delete_box_rule(self, rid: int) -> None:
        self.execute("DELETE FROM box_rules WHERE id=?", (rid,))

    def delete_sn_rule(self, rid: int) -> None:
        self.execute("DELETE FROM sn_rules WHERE id=?", (rid,))

    def get_box_rule(self, name: str) -> Optional[Dict[str, Any]]:
        rows = self.query("SELECT * FROM box_rules WHERE name=?", (name,))
        return rows[0] if rows else None

    def get_sn_rule(self, name: str) -> Optional[Dict[str, Any]]:
        rows = self.query("SELECT * FROM sn_rules WHERE name=?", (name,))
        return rows[0] if rows else None

    # ---------------- 箱号计数 ----------------

    def box_counter_scope(self, product: Dict[str, Any]) -> int:
        """返回箱号流水的计数作用域。

        默认按产品各自计数（作用域 = 产品 ID，次月自动清零）；
        若产品的箱号规则含 {&} 占位符，则使用该规则的所有产品共同计数，
        此时作用域取规则 ID 的负数（负号用于与产品 ID 命名空间区分，避免撞号）。

        Args:
            product: 产品数据字典（含 _id 与 box_rule）

        Returns:
            计数作用域整数
        """
        rule = self.get_box_rule(str(product.get("box_rule", "")))
        if rule and rules.is_shared_rule(rule.get("pattern", "")):
            return -int(rule["id"])
        return int(product["_id"])

    def scope_products(self, product: Dict[str, Any]) -> List[int]:
        """返回与给定产品共用同一计数器的所有产品 ID。"""
        rule = self.get_box_rule(str(product.get("box_rule", "")))
        if not rule or not rules.is_shared_rule(rule.get("pattern", "")):
            return [int(product["_id"])]
        ids = []
        for row in self.query("SELECT id, data FROM products"):
            if json.loads(row["data"]).get("box_rule") == rule["name"]:
                ids.append(int(row["id"]))
        return ids or [int(product["_id"])]

    def peek_counter(self, scope: int, month: str, batch: str) -> int:
        """返回下一箱的流水号（不递增）。

        Args:
            scope: 计数作用域（见 box_counter_scope）
        """
        rows = self.query(
            "SELECT value FROM box_counters WHERE product_id=? AND month=? AND batch=?",
            (scope, month, batch))
        return (rows[0]["value"] + 1) if rows else 1

    def commit_counter(self, scope: int, month: str, batch: str, value: int) -> None:
        """打印成功后提交流水号（仅成功才递增，失败不产生跳号）。"""
        self.execute(
            "INSERT INTO box_counters(product_id,month,batch,value) VALUES(?,?,?,?) "
            "ON CONFLICT(product_id,month,batch) DO UPDATE SET value=excluded.value",
            (scope, month, batch, value))

    # ---------------- 暂存（当前箱 SN 列表） ----------------

    def list_drafts(self, product_id: int, batch: str, produce_date: str) -> List[Dict[str, Any]]:
        return self.query(
            "SELECT * FROM drafts WHERE product_id=? AND batch=? AND produce_date=? "
            "ORDER BY seq",
            (product_id, batch, produce_date))

    def add_draft(self, product_id: int, batch: str, produce_date: str,
                  sn: str, seq: int) -> None:
        self.execute(
            "INSERT INTO drafts(product_id,batch,produce_date,sn,seq) VALUES(?,?,?,?,?)",
            (product_id, batch, produce_date, sn, seq))

    def remove_drafts(self, ids: List[int]) -> None:
        for did in ids:
            self.execute("DELETE FROM drafts WHERE id=?", (did,))

    def resequence_drafts(self, product_id: int, batch: str, produce_date: str) -> None:
        rows = self.list_drafts(product_id, batch, produce_date)
        for i, r in enumerate(rows, start=1):
            self.execute("UPDATE drafts SET seq=? WHERE id=?", (i, r["id"]))

    def clear_drafts(self, product_id: int, batch: str, produce_date: str) -> None:
        self.execute(
            "DELETE FROM drafts WHERE product_id=? AND batch=? AND produce_date=?",
            (product_id, batch, produce_date))

    def clear_product_drafts(self, product_id: int) -> int:
        """清空某产品全部未打印 SN（更换产品时调用）。

        SN 与产品强绑定：旧产品录了一半的 SN 若留着，很容易被误打进另一个
        产品的标签里，因此切换产品时一律清空，切回来也需重新录入。

        Returns:
            被清空的条数
        """
        rows = self.query("SELECT COUNT(*) AS c FROM drafts WHERE product_id=?",
                          (product_id,))
        n = int(rows[0]["c"]) if rows else 0
        if n:
            self.execute("DELETE FROM drafts WHERE product_id=?", (product_id,))
        return n

    # ---------------- 打印记录（按年分文件，见 app/core/records.py） ----------------

    def sn_exists(self, sn: str) -> bool:
        return self.records.sn_exists(sn)

    def add_record(self, box_no: str, seq_in_box: int, product_id: int,
                   snapshot: Dict[str, Any], sn: str, batch: str,
                   produce_date: str, box_seq: Optional[int] = None) -> int:
        """写入一条打印记录。

        Args:
            box_seq: 该箱的流水号（删除记录后用于回退计数器，可为 None）
        """
        return self.records.add(
            datetime.now().year, box_no, seq_in_box, product_id, snapshot, sn,
            batch, produce_date, datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            box_seq)

    def query_records(self, sn: str = "", box_no: str = "",
                      date_from: str = "", date_to: str = "") -> List[Dict[str, Any]]:
        return self.records.query(sn=sn, box_no=box_no,
                                  date_from=date_from, date_to=date_to)

    def records_by_box(self, box_no: str) -> List[Dict[str, Any]]:
        return self.records.by_box(box_no)

    def delete_records(self, ids: List[int]) -> None:
        """删除记录，并按「现存最大流水」回退箱号计数器。

        需求：删掉末尾那箱后，重新打印应沿用被删的箱号（1/2/3/4 删 4 -> 再打还是 4）；
        删掉中间的箱号则继续往后（删 3 -> 再打是 5）。
        实现方式：删除后把计数器改成「剩余记录里最大的箱流水号」，
        下一个箱号自然就是 最大+1，同时把空出来的末尾号让出来复用。
        """
        if not ids:
            return
        # 先取回待删记录，用于定位受影响的（产品 / 批次 / 月份）
        targets = [r for r in self.records.query() if r["id"] in set(ids)]
        self.records.delete(ids)
        seen = set()
        for r in targets:
            pid = r.get("product_id")
            batch = str(r.get("batch", ""))
            month = str(r.get("produce_date", ""))[:7]
            if not pid or not month:
                continue
            key = (pid, batch, month)
            if key in seen:
                continue
            seen.add(key)
            self.recompute_box_counter(int(pid), batch, month)

    def recompute_box_counter(self, product_id: int, batch: str,
                              month: str) -> None:
        """把箱号计数器回退到「现存记录的最大流水号」。

        Args:
            product_id: 任一受影响的产品 ID（共用计数时会自动扩到同规则产品）
            batch: 批次
            month: 生产月份（yyyy-MM）
        """
        product = self.get_product(product_id)
        if product is None:
            return
        ids = self.scope_products(product)
        max_seq = self.records.max_seq(ids, batch, month)
        if max_seq is None:
            # 有流水号未知的历史记录，无法安全判断，保持计数器不动
            return
        scope = self.box_counter_scope(product)
        self.commit_counter(scope, month, batch, max_seq)

    def today_boxes(self, product: Dict[str, Any], batch: str) -> int:
        """当天当前批次的装箱件数（按箱号去重）。

        共用计数的规则统计该规则下所有产品当天的箱数，普通规则只统计本产品。

        Args:
            product: 产品数据字典
            batch: 批次号
        """
        today = date.today().strftime("%Y-%m-%d")
        return self.records.count_boxes(self.scope_products(product), batch, today)
