"""CSV and .sql imports with progress (NDJSON stream)."""
import csv
import io
import json
import os
import re
import tempfile
import time
import uuid

from sqlalchemy import text

from .browse import UserError
from .db import DB
from .sqlsplit import first_keyword, split_sql

TMP = os.path.join(tempfile.gettempdir(), "lqsql-imports")
os.makedirs(TMP, exist_ok=True)
INT_RE = re.compile(r"^[+-]?\d{1,18}$")
NUM_RE = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$")


def _cleanup():
    now = time.time()
    for f in os.listdir(TMP):
        p = os.path.join(TMP, f)
        try:
            if now - os.path.getmtime(p) > 3600:
                os.remove(p)
        except OSError:
            pass


def _decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def csv_preview(data: bytes, filename: str):
    _cleanup()
    txt = _decode(data)
    sample = txt[:65536]
    delim = ","
    try:
        delim = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        if "\t" in sample.split("\n", 1)[0]:
            delim = "\t"
    rows = list(csv.reader(io.StringIO(txt), delimiter=delim))
    rows = [r for r in rows if any(x.strip() for x in r)]
    if not rows:
        raise UserError("The CSV file is empty")
    header = [h.strip() or f"col_{i + 1}" for i, h in enumerate(rows[0])]
    body = rows[1:]
    types = []
    for i in range(len(header)):
        vals = [r[i].strip() for r in body if i < len(r) and r[i].strip() != ""]
        if vals and all(INT_RE.match(v) for v in vals):
            types.append("integer")
        elif vals and all(NUM_RE.match(v) for v in vals):
            types.append("number")
        else:
            types.append("text")
    token = uuid.uuid4().hex
    with open(os.path.join(TMP, token + ".json"), "w", encoding="utf-8") as f:
        json.dump({"header": header, "rows": body, "filename": filename}, f)
    return {"token": token, "header": header, "sample": body[:20], "rows": len(body),
            "delimiter": {"\t": "tab"}.get(delim, delim), "types": types,
            "suggested_table": re.sub(r"[^a-zA-Z0-9_]+", "_", os.path.splitext(filename or "import")[0]).strip("_").lower() or "import"}


def _type_sql(db: DB, t: str) -> str:
    if t == "integer":
        return "BIGINT"
    if t == "number":
        return {"postgresql": "DOUBLE PRECISION", "mysql": "DOUBLE", "sqlite": "REAL"}[db.kind]
    return "TEXT"


def csv_commit(db: DB, token: str, schema: str, table: str, mapping: list[dict], create: bool = False,
               empty_as_null: bool = True, truncate: bool = False, col_types: list[str] | None = None):
    if db.s.read_only:
        raise UserError("Read-only mode is on.", 403)
    if not re.fullmatch(r"[a-f0-9]{32}", token or ""):
        raise UserError("Invalid upload token")
    path = os.path.join(TMP, token + ".json")
    if not os.path.exists(path):
        raise UserError("Upload expired — choose the file again.")
    with open(path, encoding="utf-8") as f:
        payload = json.load(f)
    header, rows = payload["header"], payload["rows"]
    pairs = [(int(m["csv"]), m["column"]) for m in mapping if m.get("column")]
    if not pairs:
        raise UserError("Map at least one column")
    if not table or len(table) > 120:
        raise UserError("Choose a table name")

    def gen():
        t0 = time.time()
        total = len(rows)
        yield json.dumps({"type": "start", "total": total}) + "\n"
        with db.engine.connect() as c:
            try:
                if create:
                    defs = []
                    for idx, name in pairs:
                        t = (col_types or [])[idx] if col_types and idx < len(col_types) else "text"
                        defs.append(f"{db.q(name)} {_type_sql(db, t)}")
                    c.execute(text(f"CREATE TABLE {db.qt(schema, table)} ({', '.join(defs)})"))
                    db.invalidate()
                else:
                    meta = db.table_meta(schema, table)
                    known = {x["name"] for x in meta["columns"]}
                    bad = [n for _, n in pairs if n not in known]
                    if bad:
                        raise UserError("Unknown column(s): " + ", ".join(bad))
                    if truncate:
                        c.execute(text(f"DELETE FROM {db.qt(schema, table)}"))
                cols = ", ".join(db.q(n) for _, n in pairs)
                binds = ", ".join(f":p{i}" for i in range(len(pairs)))
                stmt = text(f"INSERT INTO {db.qt(schema, table)} ({cols}) VALUES ({binds})")
                done = 0
                B = 500
                for start in range(0, total, B):
                    batch = []
                    for r in rows[start:start + B]:
                        d = {}
                        for i, (idx, _) in enumerate(pairs):
                            v = r[idx] if idx < len(r) else ""
                            d[f"p{i}"] = None if (empty_as_null and v == "") else v
                        batch.append(d)
                    try:
                        with db.deadline(max(db.s.query_timeout, 120)):
                            c.execute(stmt, batch)
                    except Exception as e:
                        c.rollback()
                        yield json.dumps({"type": "error", "message": f"Rows {start + 1}–{start + len(batch)}: {_m(e)}",
                                          "rolled_back": True}) + "\n"
                        return
                    done += len(batch)
                    yield json.dumps({"type": "progress", "done": done, "total": total}) + "\n"
                c.commit()
                db.invalidate()
                try:
                    os.remove(path)
                except OSError:
                    pass
                yield json.dumps({"type": "done", "inserted": done, "ms": int((time.time() - t0) * 1000)}) + "\n"
            except UserError as e:
                c.rollback()
                yield json.dumps({"type": "error", "message": str(e)}) + "\n"
            except Exception as e:
                c.rollback()
                yield json.dumps({"type": "error", "message": _m(e), "rolled_back": True}) + "\n"
    return gen()


def sql_import(db: DB, data: bytes, single_tx: bool = True, stop_on_error: bool = True):
    if db.s.read_only:
        raise UserError("Read-only mode is on.", 403)
    sql = _decode(data)
    # drop psql meta-commands (\connect, \restrict ...)
    sql = "\n".join(l for l in sql.splitlines() if not l.lstrip().startswith("\\"))
    stmts = list(split_sql(sql, db.kind))
    for s in stmts[:2000]:
        if re.match(r"^\s*COPY\b.*\bFROM\s+stdin", s, re.I | re.S):
            raise UserError("This dump uses COPY … FROM stdin (pg_dump default). Re-export with `pg_dump --inserts` "
                            "or use lqSQL's SQL export.")

    def gen():
        t0 = time.time()
        total = len(stmts)
        yield json.dumps({"type": "start", "total": total}) + "\n"
        raw = db.engine.raw_connection()
        errors, done, skipped = [], 0, 0
        try:
            if db.kind == "postgresql":
                cur = raw.cursor()
                cur.execute(f"SET statement_timeout = {int(max(db.s.query_timeout, 120) * 1000)}")
                raw.commit()
            if db.kind == "sqlite" and single_tx:
                raw.commit()
                raw.cursor().execute("BEGIN")
            last = time.time()
            for i, s in enumerate(stmts):
                kw = first_keyword(s)
                if single_tx and kw in ("BEGIN", "COMMIT", "START", "END", "ROLLBACK") and re.match(r"^\s*(BEGIN|COMMIT|START\s+TRANSACTION|END|ROLLBACK)\s*(TRANSACTION|WORK)?\s*$", s, re.I):
                    skipped += 1
                    continue
                cur = raw.cursor()
                try:
                    with db.deadline(max(db.s.query_timeout, 120)):
                        cur.execute(s)
                    if not single_tx:
                        raw.commit()
                    done += 1
                except Exception as e:
                    err = {"index": i + 1, "statement": s[:400], "message": _m(e)}
                    if single_tx or stop_on_error:
                        raw.rollback()
                        yield json.dumps({"type": "error", **err, "rolled_back": single_tx,
                                          "executed": done}) + "\n"
                        return
                    raw.rollback()
                    errors.append(err)
                finally:
                    cur.close()
                if time.time() - last > 0.25 or i == total - 1:
                    last = time.time()
                    yield json.dumps({"type": "progress", "done": i + 1, "total": total}) + "\n"
            raw.commit()
            db.invalidate()
            yield json.dumps({"type": "done", "executed": done, "skipped": skipped, "errors": errors[:50],
                              "ms": int((time.time() - t0) * 1000)}) + "\n"
        except Exception as e:
            try:
                raw.rollback()
            except Exception:
                pass
            yield json.dumps({"type": "error", "message": _m(e)}) + "\n"
        finally:
            raw.close()
    return gen()


def _m(e):
    return str(getattr(e, "orig", None) or e).strip().split("\n[SQL:")[0][:1500]
