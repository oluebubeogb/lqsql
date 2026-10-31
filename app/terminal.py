"""Raw SQL terminal. Authenticated admin only. One transaction per run."""
import re
import time

from .db import DB, to_json_value
from .sqlsplit import first_keyword, split_sql, strip_comments

READ_KEYWORDS = {"SELECT", "WITH", "EXPLAIN", "SHOW", "DESCRIBE", "DESC", "PRAGMA", "VALUES", "TABLE", "USE", "SET"}
NO_TX = re.compile(r"^\s*(VACUUM|CREATE\s+DATABASE|DROP\s+DATABASE|ALTER\s+SYSTEM|REINDEX\s+DATABASE|CLUSTER)\b|\bCONCURRENTLY\b", re.I)
TX_CONTROL = {"BEGIN", "COMMIT", "ROLLBACK", "START", "END", "SAVEPOINT", "RELEASE"}


def is_read(stmt: str) -> bool:
    kw = first_keyword(stmt)
    if kw not in READ_KEYWORDS:
        return False
    s = strip_comments(stmt).upper()
    if kw == "WITH" and re.search(r"\b(INSERT|UPDATE|DELETE|MERGE)\b", s):
        return False
    if kw == "EXPLAIN" and re.search(r"\bANALY[SZ]E\b", s) and re.search(r"\b(INSERT|UPDATE|DELETE|MERGE)\b", s):
        return False
    if kw == "PRAGMA" and "=" in s:
        return False
    if kw == "SET" and re.search(r"\b(TRANSACTION|SESSION\s+CHARACTERISTICS|STATEMENT_TIMEOUT|DEFAULT_TRANSACTION_READ_ONLY)\b", s):
        return False
    return True


def destructive_reasons(stmt: str) -> list[str]:
    s = re.sub(r"'(?:[^']|'')*'", "''", strip_comments(stmt))
    kw = first_keyword(s)
    up = s.upper()
    r = []
    if kw in ("DROP", "TRUNCATE"):
        r.append(f"{kw} statement")
    elif kw == "ALTER" and re.search(r"\bDROP\b", up):
        r.append("ALTER … DROP")
    elif kw == "DELETE" and not re.search(r"\bWHERE\b", up):
        r.append("DELETE without WHERE")
    elif kw == "UPDATE" and not re.search(r"\bWHERE\b", up):
        r.append("UPDATE without WHERE")
    elif kw in ("GRANT", "REVOKE"):
        r.append(f"{kw} changes permissions")
    return r


def analyze(db: DB, sql: str):
    stmts = list(split_sql(sql, db.kind))
    reasons, blocked = [], []
    for i, s in enumerate(stmts):
        if db.s.read_only and not is_read(s):
            blocked.append(i + 1)
        for why in destructive_reasons(s):
            reasons.append(f"#{i + 1}: {why}")
    return stmts, reasons, blocked


def run(db: DB, sql: str, confirm: bool = False, max_rows: int | None = None):
    max_rows = max_rows or db.s.max_result_rows
    stmts, reasons, blocked = analyze(db, sql)
    if not stmts:
        return {"results": [], "ms": 0}
    if blocked:
        return {"error": f"Read-only mode: statement(s) {', '.join(map(str, blocked))} would write. Only SELECT/SHOW/EXPLAIN-style queries are allowed.",
                "status": 403}
    if reasons and not confirm:
        return {"needs_confirm": True, "reasons": reasons, "status": 409}
    if len(stmts) > 200:
        return {"error": "Too many statements for the terminal (max 200). Use Import → SQL file.", "status": 400}

    raw = db.engine.raw_connection()
    results = []
    t_all = time.perf_counter()
    single_no_tx = len(stmts) == 1 and NO_TX.search(stmts[0])
    driver = raw.driver_connection
    try:
        if db.kind == "postgresql":
            cur = raw.cursor()
            cur.execute(f"SET statement_timeout = {int(db.s.query_timeout * 1000)}")
            cur.close()
            raw.commit()
            if single_no_tx:
                driver.autocommit = True
        elif db.kind == "sqlite":
            raw.commit()
            if not single_no_tx and any(not is_read(x) for x in stmts):
                raw.cursor().execute("BEGIN")  # make DDL+DML atomic too
        with db.deadline():
            for idx, stmt in enumerate(stmts):
                kw = first_keyword(stmt)
                if db.kind == "sqlite" and kw == "BEGIN" and not single_no_tx and raw.driver_connection.in_transaction:
                    results.append({"index": idx + 1, "sql": stmt[:300], "keyword": kw, "rowcount": -1, "ms": 0,
                                    "skipped": "lqSQL wraps each run in one transaction"})
                    continue
                t0 = time.perf_counter()
                cur = raw.cursor()
                try:
                    cur.execute(stmt)
                except Exception as e:
                    try:
                        raw.rollback()
                    except Exception:
                        pass
                    return {"results": results, "error": _msg(e), "failed_index": idx + 1,
                            "failed_sql": stmt[:500], "rolled_back": True,
                            "note": "MySQL commits DDL implicitly, so earlier DDL may persist." if db.kind == "mysql" else None,
                            "ms": round((time.perf_counter() - t_all) * 1000, 1), "status": 400}
                item = {"index": idx + 1, "sql": stmt[:300], "keyword": kw}
                if cur.description:
                    cols = [d[0] for d in cur.description]
                    rows = cur.fetchmany(max_rows + 1)
                    item["columns"] = _dedupe(cols)
                    item["truncated"] = len(rows) > max_rows
                    item["rows"] = [[to_json_value(v) for v in r] for r in rows[:max_rows]]
                    item["rowcount"] = len(item["rows"])
                else:
                    item["rowcount"] = cur.rowcount if cur.rowcount is not None else -1
                item["ms"] = round((time.perf_counter() - t0) * 1000, 1)
                results.append(item)
                cur.close()
        if not single_no_tx:
            raw.commit()
        if any(not is_read(s) for s in stmts):
            db.invalidate()
        return {"results": results, "ms": round((time.perf_counter() - t_all) * 1000, 1)}
    finally:
        try:
            if db.kind == "postgresql" and driver.autocommit:
                driver.autocommit = False
        except Exception:
            pass
        raw.close()


def _dedupe(cols):
    seen, out = {}, []
    for c in cols:
        c = str(c)
        if c in seen:
            seen[c] += 1
            out.append(f"{c}_{seen[c]}")
        else:
            seen[c] = 0
            out.append(c)
    return out


def _msg(e: Exception) -> str:
    m = str(getattr(e, "orig", None) or e)
    if "interrupted" in m.lower() or "canceling statement due to statement timeout" in m.lower() or "max_execution_time" in m.lower():
        return m.strip() + " (query timeout — raise QUERY_TIMEOUT_SECONDS if needed)"
    return m.strip()[:2000]
