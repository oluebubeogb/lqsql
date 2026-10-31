"""Engine setup + per-dialect metadata helpers for PostgreSQL, MySQL/MariaDB and SQLite."""
import base64
import datetime as dt
import decimal
import json
import math
import re
import threading
import time
import uuid
from contextlib import contextmanager

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine

from .config import Settings

PG_SYSTEM = ("pg_catalog", "information_schema", "pg_toast")
MY_SYSTEM = ("information_schema", "mysql", "performance_schema", "sys")

_local = threading.local()


class DB:
    def __init__(self, s: Settings):
        self.s = s
        self.kind = s.engine
        kw = dict(pool_pre_ping=True, future=True)
        if self.kind == "sqlite":
            kw["connect_args"] = {"check_same_thread": False, "timeout": 15}
        else:
            kw.update(pool_size=3, max_overflow=3, pool_recycle=1800, pool_timeout=20)
            if self.kind == "postgresql":
                kw["connect_args"] = {"connect_timeout": 10, "application_name": "litesql"}
            else:
                kw["connect_args"] = {"connect_timeout": 10, "charset": "utf8mb4"}
        self.engine: Engine = create_engine(s.database_url, **kw)
        self._mysql_timeout_var = None
        event.listen(self.engine, "connect", self._on_connect)
        self.prep = self.engine.dialect.identifier_preparer
        self._meta_cache: dict = {}

    # ---------- connection setup ----------
    def _on_connect(self, dbapi_conn, _rec):
        t = self.s.query_timeout
        if self.kind == "postgresql":
            cur = dbapi_conn.cursor()
            cur.execute(f"SET statement_timeout = {int(t * 1000)}")
            cur.execute("SET idle_in_transaction_session_timeout = 300000")
            if self.s.read_only:
                cur.execute("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY")
            cur.close()
            dbapi_conn.commit()
        elif self.kind == "mysql":
            cur = dbapi_conn.cursor()
            for stmt in (f"SET SESSION max_execution_time = {int(t * 1000)}",  # MySQL
                         f"SET SESSION max_statement_time = {int(t)}"):  # MariaDB
                try:
                    cur.execute(stmt)
                    break
                except Exception:
                    pass
            if self.s.read_only:
                try:
                    cur.execute("SET SESSION TRANSACTION READ ONLY")
                except Exception:
                    pass
            cur.close()
        else:
            if self.s.read_only:
                dbapi_conn.execute("PRAGMA query_only = ON")

            def _progress():
                dl = getattr(_local, "deadline", None)
                return 1 if dl and time.monotonic() > dl else 0

            dbapi_conn.set_progress_handler(_progress, 20000)

    @contextmanager
    def deadline(self, seconds: float | None = None):
        """SQLite only: interrupt long statements (PG/MySQL use server-side timeouts)."""
        prev = getattr(_local, "deadline", None)
        _local.deadline = time.monotonic() + (seconds or self.s.query_timeout)
        try:
            yield
        finally:
            _local.deadline = prev

    # ---------- identifiers ----------
    def q(self, name: str) -> str:
        return self.prep.quote_identifier(name)

    def qt(self, schema: str | None, table: str) -> str:
        if self.kind == "sqlite" or not schema:
            if self.kind == "sqlite" and schema and schema != "main":
                return f"{self.q(schema)}.{self.q(table)}"
            return self.q(table)
        return f"{self.q(schema)}.{self.q(table)}"

    def as_text(self, col_sql: str) -> str:
        if self.kind == "postgresql":
            return f"CAST({col_sql} AS text)"
        if self.kind == "mysql":
            return f"CAST({col_sql} AS CHAR)"
        return f"CAST({col_sql} AS TEXT)"

    def like_op(self) -> str:
        return "ILIKE" if self.kind == "postgresql" else "LIKE"

    # ---------- info ----------
    def server_info(self) -> dict:
        with self.engine.connect() as c:
            if self.kind == "postgresql":
                ver = c.execute(text("SHOW server_version")).scalar()
                db = c.execute(text("SELECT current_database()")).scalar()
                default_schema = c.execute(text("SELECT current_schema()")).scalar() or "public"
            elif self.kind == "mysql":
                ver = c.execute(text("SELECT VERSION()")).scalar()
                db = c.execute(text("SELECT DATABASE()")).scalar()
                default_schema = db
            else:
                ver = c.execute(text("SELECT sqlite_version()")).scalar()
                db = (self.engine.url.database or ":memory:").split("/")[-1]
                default_schema = "main"
        return {"engine": self.kind, "version": str(ver), "database": db, "default_schema": default_schema,
                "host": self.engine.url.host or ("file" if self.kind == "sqlite" else None)}

    def schemas(self) -> list[str]:
        with self.engine.connect() as c:
            if self.kind == "postgresql":
                rows = c.execute(text(
                    "SELECT nspname FROM pg_namespace WHERE nspname NOT LIKE 'pg_temp_%' "
                    "AND nspname NOT LIKE 'pg_toast%' ORDER BY nspname")).scalars().all()
                if not self.s.show_system_schemas:
                    rows = [r for r in rows if r not in PG_SYSTEM]
                return rows
            if self.kind == "mysql":
                rows = c.execute(text("SELECT SCHEMA_NAME FROM information_schema.SCHEMATA ORDER BY SCHEMA_NAME")).scalars().all()
                if not self.s.show_system_schemas:
                    rows = [r for r in rows if r.lower() not in MY_SYSTEM]
                return rows
            rows = c.execute(text("PRAGMA database_list")).all()
            return [r[1] for r in rows if r[1] != "temp"]

    def tables(self, schema: str) -> list[dict]:
        out = []
        with self.engine.connect() as c:
            if self.kind == "postgresql":
                rows = c.execute(text("""
                    SELECT c.relname, c.relkind, c.reltuples::bigint, pg_total_relation_size(c.oid)
                    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = :s AND c.relkind IN ('r','p','v','m','f') AND NOT c.relispartition
                    ORDER BY c.relname"""), {"s": schema}).all()
                for name, kind, est, size in rows:
                    out.append({"name": name, "type": "view" if kind in ("v", "m") else "table",
                                "rows": None if est is None or est < 0 else int(est), "approx": True,
                                "bytes": int(size or 0), "materialized": kind == "m"})
            elif self.kind == "mysql":
                rows = c.execute(text("""
                    SELECT TABLE_NAME, TABLE_TYPE, TABLE_ROWS, COALESCE(DATA_LENGTH,0)+COALESCE(INDEX_LENGTH,0)
                    FROM information_schema.TABLES WHERE TABLE_SCHEMA = :s ORDER BY TABLE_NAME"""), {"s": schema}).all()
                for name, typ, est, size in rows:
                    out.append({"name": name, "type": "view" if "VIEW" in (typ or "") else "table",
                                "rows": None if est is None else int(est), "approx": True, "bytes": int(size or 0)})
            else:
                sch = self.q(schema)
                rows = c.execute(text(f"SELECT name, type FROM {sch}.sqlite_master WHERE type IN ('table','view') "
                                      "AND name NOT LIKE 'sqlite_%' ORDER BY name")).all()
                cheap = len(rows) <= 300
                for name, typ in rows:
                    cnt = None
                    if typ == "table" and cheap:
                        try:
                            with self.deadline(2):
                                cnt = c.execute(text(f"SELECT COUNT(*) FROM {self.qt(schema, name)}")).scalar()
                        except Exception:
                            cnt = None
                    out.append({"name": name, "type": typ, "rows": cnt, "approx": False, "bytes": None})
        return out

    # ---------- columns / keys ----------
    def invalidate(self):
        self._meta_cache.clear()

    def table_meta(self, schema: str, table: str) -> dict:
        key = (schema, table)
        hit = self._meta_cache.get(key)
        if hit and hit[0] > time.monotonic():
            return hit[1]
        meta = self._table_meta(schema, table)
        self._meta_cache[key] = (time.monotonic() + 30, meta)
        return meta

    def _table_meta(self, schema: str, table: str) -> dict:
        cols = []
        is_view = False
        row_key = None
        with self.engine.connect() as c:
            if self.kind == "postgresql":
                reg = c.execute(text("SELECT c.oid, c.relkind FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                                     "WHERE n.nspname=:s AND c.relname=:t"), {"s": schema, "t": table}).first()
                if not reg:
                    raise LookupError("table not found")
                oid, relkind = reg
                is_view = relkind in ("v", "m")
                pk = set(c.execute(text("SELECT a.attname FROM pg_index i JOIN pg_attribute a ON a.attrelid=i.indrelid "
                                        "AND a.attnum = ANY(i.indkey) WHERE i.indrelid=:o AND i.indisprimary"), {"o": oid}).scalars().all())
                rows = c.execute(text("""
                    SELECT a.attname, format_type(a.atttypid, a.atttypmod), NOT a.attnotnull,
                           pg_get_expr(d.adbin, d.adrelid), a.attidentity, a.attgenerated
                    FROM pg_attribute a LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum
                    WHERE a.attrelid=:o AND a.attnum>0 AND NOT a.attisdropped ORDER BY a.attnum"""), {"o": oid}).all()
                for name, typ, nullable, default, ident, gen in rows:
                    auto = bool(ident) or (default or "").startswith("nextval(")
                    cols.append(_col(name, typ, nullable, default, name in pk, auto, bool(gen)))
                if not is_view:
                    row_key = {"type": "pk", "columns": [x["name"] for x in cols if x["pk"]]} if pk else {"type": "ctid", "columns": ["__rowid"]}
            elif self.kind == "mysql":
                typ = c.execute(text("SELECT TABLE_TYPE FROM information_schema.TABLES WHERE TABLE_SCHEMA=:s AND TABLE_NAME=:t"),
                                {"s": schema, "t": table}).scalar()
                if typ is None:
                    raise LookupError("table not found")
                is_view = "VIEW" in typ
                rows = c.execute(text("""
                    SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, COLUMN_DEFAULT, EXTRA, COLUMN_KEY
                    FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=:s AND TABLE_NAME=:t ORDER BY ORDINAL_POSITION"""),
                    {"s": schema, "t": table}).all()
                for name, ctype, nullable, default, extra, key in rows:
                    extra = (extra or "").lower()
                    cols.append(_col(name, ctype, nullable == "YES", default, key == "PRI",
                                     "auto_increment" in extra, "generated" in extra))
                pkc = [x["name"] for x in cols if x["pk"]]
                if not is_view:
                    row_key = {"type": "pk", "columns": pkc} if pkc else None
            else:
                sch = self.q(schema)
                info = c.execute(text(f"SELECT type, sql FROM {sch}.sqlite_master WHERE name=:t"), {"t": table}).first()
                if not info:
                    raise LookupError("table not found")
                is_view = info[0] == "view"
                rows = c.execute(text(f"PRAGMA {sch}.table_xinfo({self.q(table)})")).all()
                npk = sum(1 for r in rows if r[5])
                for cid, name, ctype, notnull, default, pk, hidden in rows:
                    auto = bool(pk) and npk == 1 and (ctype or "").upper() == "INTEGER"
                    cols.append(_col(name, ctype or "", not notnull and not pk, default, bool(pk), auto, hidden in (2, 3)))
                pkc = [r[1] for r in sorted([r for r in rows if r[5]], key=lambda r: r[5])]
                without_rowid = "WITHOUT ROWID" in (info[1] or "").upper()
                if not is_view:
                    if pkc:
                        row_key = {"type": "pk", "columns": pkc}
                    elif not without_rowid:
                        row_key = {"type": "rowid", "columns": ["__rowid"]}
        return {"schema": schema, "table": table, "view": is_view, "columns": cols, "row_key": row_key,
                "editable": bool(row_key) and not is_view and not self.s.read_only}

    def count(self, schema, table, where_sql="", params=None, approx_hint=None) -> tuple[int | None, bool]:
        with self.engine.connect() as c:
            if not where_sql and self.kind in ("postgresql", "mysql") and approx_hint is not None and approx_hint > 500_000:
                return approx_hint, True
            try:
                with self.deadline(10):
                    n = c.execute(text(f"SELECT COUNT(*) FROM {self.qt(schema, table)} {where_sql}"), params or {}).scalar()
                return int(n), False
            except Exception:
                return approx_hint, True

    def estimate(self, schema, table) -> int | None:
        with self.engine.connect() as c:
            if self.kind == "postgresql":
                v = c.execute(text("SELECT c.reltuples::bigint FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                                   "WHERE n.nspname=:s AND c.relname=:t"), {"s": schema, "t": table}).scalar()
                return None if v is None or v < 0 else int(v)
            if self.kind == "mysql":
                v = c.execute(text("SELECT TABLE_ROWS FROM information_schema.TABLES WHERE TABLE_SCHEMA=:s AND TABLE_NAME=:t"),
                              {"s": schema, "t": table}).scalar()
                return None if v is None else int(v)
        return None


def _kind(t: str) -> str:
    t = (t or "").lower()
    if t.endswith("[]"):
        return "array"
    if t.startswith("vector") or t.startswith("halfvec") or t.startswith("sparsevec"):
        return "vector"
    if "bool" in t or t == "tinyint(1)":
        return "bool"
    if any(k in t for k in ("int", "serial", "numeric", "decimal", "real", "double", "float", "money")) and "interval" not in t and "point" not in t:
        return "number"
    if "json" in t:
        return "json"
    if any(k in t for k in ("bytea", "blob", "binary")):
        return "binary"
    if t.startswith("timestamp") or t.startswith("date") or t.startswith("time") or t == "year":
        return "date"
    if any(k in t for k in ("char", "text", "uuid", "enum", "citext", "clob", "set(")) or t == "":
        return "text"
    return "other"


def _col(name, typ, nullable, default, pk, auto, generated):
    return {"name": name, "type": typ, "kind": _kind(typ), "nullable": bool(nullable),
            "default": None if default is None else str(default), "pk": bool(pk), "auto": bool(auto),
            "generated": bool(generated)}


# ---------- value serialization ----------
MAX_CELL = 100_000


def to_json_value(v):
    if v is None or isinstance(v, (bool, str)):
        if isinstance(v, str) and len(v) > MAX_CELL:
            return v[:MAX_CELL] + "…"
        return v
    if isinstance(v, int):
        return v if abs(v) < 2**53 else str(v)
    if isinstance(v, float):
        return v if math.isfinite(v) else str(v)
    if isinstance(v, decimal.Decimal):
        return str(v)
    if isinstance(v, (dt.datetime, dt.date, dt.time)):
        return v.isoformat()
    if isinstance(v, dt.timedelta):
        return str(v)
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, (bytes, bytearray, memoryview)):
        b = bytes(v)
        if len(b) <= 64:
            return "\\x" + b.hex()
        return f"\\x{b[:32].hex()}… ({len(b):,} bytes)"
    if isinstance(v, (list, tuple)):
        return [to_json_value(x) for x in v]
    if isinstance(v, dict):
        return {str(k): to_json_value(x) for k, x in v.items()}
    return str(v)


def to_text(v) -> str:
    """CSV cell text."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (bytes, bytearray, memoryview)):
        return "\\x" + bytes(v).hex()
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False, default=str)
    if isinstance(v, (dt.datetime, dt.date, dt.time)):
        return v.isoformat()
    return str(v)


def bind_value(v):
    """Value coming from the UI -> DB-API parameter (strings let the server cast)."""
    if isinstance(v, (dict, list)):
        return json.dumps(v)
    return v


def b64(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")
