"""Table browsing + row edits (parameterized, primary-key aware)."""
import time

from sqlalchemy import text

from .db import DB, bind_value, to_json_value

OPS = {"eq", "neq", "contains", "starts", "gt", "lt", "gte", "lte", "null", "notnull"}


class UserError(Exception):
    def __init__(self, msg, status=400):
        super().__init__(msg)
        self.status = status


def _colmap(meta):
    return {c["name"]: c for c in meta["columns"]}


def build_where(db: DB, meta, filters):
    cols = _colmap(meta)
    parts, params = [], {}
    for i, f in enumerate(filters or []):
        name, op, val = f.get("column"), f.get("op", "eq"), f.get("value")
        if name not in cols:
            raise UserError(f"Unknown column: {name}")
        if op not in OPS:
            raise UserError(f"Unknown filter: {op}")
        col = db.q(name)
        kind = cols[name]["kind"]
        textual = kind in ("json", "vector", "binary", "other", "array")
        p = f"f{i}"
        if op == "null":
            parts.append(f"{col} IS NULL")
            continue
        if op == "notnull":
            parts.append(f"{col} IS NOT NULL")
            continue
        if val is None:
            val = ""
        if op in ("contains", "starts"):
            params[p] = (f"%{_esc_like(str(val))}%" if op == "contains" else f"{_esc_like(str(val))}%")
            esc = " ESCAPE '!'"
            parts.append(f"{db.as_text(col)} {db.like_op()} :{p}{esc}")
            continue
        sym = {"eq": "=", "neq": "<>", "gt": ">", "lt": "<", "gte": ">=", "lte": "<="}[op]
        params[p] = str(val)
        lhs = db.as_text(col) if textual else col
        if db.kind == "postgresql" and kind == "bool":
            lhs = db.as_text(col)
            params[p] = {"1": "true", "0": "false", "t": "true", "f": "false"}.get(str(val).lower(), str(val).lower())
        parts.append(f"{lhs} {sym} :{p}")
    return (" WHERE " + " AND ".join(parts)) if parts else "", params


def _esc_like(s: str) -> str:
    return s.replace("!", "!!").replace("%", "!%").replace("_", "!_")


def select_list(db: DB, meta) -> str:
    items = []
    rk = meta.get("row_key")
    if rk and rk["type"] == "ctid":
        items.append('CAST(ctid AS text) AS "__rowid"')
    elif rk and rk["type"] == "rowid":
        items.append('rowid AS "__rowid"')
    for c in meta["columns"]:
        q = db.q(c["name"])
        if db.kind == "postgresql" and c["kind"] in ("array", "vector", "other"):
            items.append(f"CAST({q} AS text) AS {q}")
        else:
            items.append(q)
    return ", ".join(items)


def fetch_rows(db: DB, schema, table, page=1, size=50, sort=None, direction="asc", filters=None):
    meta = db.table_meta(schema, table)
    cols = _colmap(meta)
    size = max(1, min(int(size), 1000))
    page = max(1, int(page))
    where, params = build_where(db, meta, filters)
    order = ""
    if sort:
        if sort not in cols:
            raise UserError(f"Unknown sort column: {sort}")
        d = "DESC" if str(direction).lower() == "desc" else "ASC"
        order = f" ORDER BY {db.q(sort)} {d}"
    elif meta["row_key"] and meta["row_key"]["type"] == "pk":
        order = " ORDER BY " + ", ".join(db.q(c) for c in meta["row_key"]["columns"])
    sql = f"SELECT {select_list(db, meta)} FROM {db.qt(schema, table)}{where}{order} LIMIT {size} OFFSET {(page - 1) * size}"
    t0 = time.perf_counter()
    with db.engine.connect() as c, db.deadline():
        res = c.execute(text(sql), params)
        names = list(res.keys())
        rows = [[to_json_value(v) for v in r] for r in res.fetchall()]
    ms = round((time.perf_counter() - t0) * 1000, 1)
    est = db.estimate(schema, table)
    total, approx = db.count(schema, table, where, params, est)
    return {"meta": meta, "columns": names, "rows": rows, "page": page, "size": size,
            "total": total, "approx": approx, "ms": ms, "sql": sql}


def _key_where(db: DB, meta, key: dict, params: dict, prefix="k"):
    rk = meta.get("row_key")
    if not rk:
        raise UserError("This table has no primary key, so rows cannot be edited safely.")
    parts = []
    for i, cname in enumerate(rk["columns"]):
        if cname not in key:
            raise UserError(f"Missing key column {cname}")
        p = f"{prefix}{i}"
        params[p] = None if key[cname] is None else str(key[cname])
        if rk["type"] == "ctid":
            parts.append(f"ctid = CAST(:{p} AS tid)")
        elif rk["type"] == "rowid":
            parts.append(f"rowid = :{p}")
        else:
            parts.append(f"{db.q(cname)} = :{p}" if params[p] is not None else f"{db.q(cname)} IS NULL")
            if params[p] is None:
                params.pop(p)
    return " AND ".join(parts)


def _check_writable(db: DB, meta):
    if db.s.read_only:
        raise UserError("Read-only mode is on (READ_ONLY=true).", 403)
    if meta["view"]:
        raise UserError("Views are read-only here.", 400)


def update_row(db: DB, schema, table, key: dict, values: dict):
    meta = db.table_meta(schema, table)
    _check_writable(db, meta)
    cols = _colmap(meta)
    if not values:
        raise UserError("Nothing to update")
    params, sets = {}, []
    for i, (k, v) in enumerate(values.items()):
        if k not in cols:
            raise UserError(f"Unknown column {k}")
        p = f"v{i}"
        params[p] = bind_value(v)
        sets.append(f"{db.q(k)} = :{p}")
    where = _key_where(db, meta, key, params)
    sql = f"UPDATE {db.qt(schema, table)} SET {', '.join(sets)} WHERE {where}"
    with db.engine.connect() as c, db.deadline():
        n = c.execute(text(sql), params).rowcount
        if n > 1:
            c.rollback()
            raise UserError(f"Key matched {n} rows; nothing changed.", 409)
        c.commit()
    return {"updated": n}


def insert_row(db: DB, schema, table, values: dict):
    meta = db.table_meta(schema, table)
    _check_writable(db, meta)
    cols = _colmap(meta)
    names, binds, params = [], [], {}
    for i, (k, v) in enumerate((values or {}).items()):
        if k not in cols:
            raise UserError(f"Unknown column {k}")
        names.append(db.q(k))
        binds.append(f":v{i}")
        params[f"v{i}"] = bind_value(v)
    qt = db.qt(schema, table)
    if names:
        sql = f"INSERT INTO {qt} ({', '.join(names)}) VALUES ({', '.join(binds)})"
    else:
        sql = f"INSERT INTO {qt} DEFAULT VALUES" if db.kind != "mysql" else f"INSERT INTO {qt} () VALUES ()"
    with db.engine.connect() as c, db.deadline():
        c.execute(text(sql), params)
        c.commit()
    return {"inserted": 1}


def delete_rows(db: DB, schema, table, keys: list[dict]):
    meta = db.table_meta(schema, table)
    _check_writable(db, meta)
    if not keys:
        raise UserError("No rows selected")
    if len(keys) > 1000:
        raise UserError("Delete at most 1000 rows at a time")
    total = 0
    with db.engine.connect() as c, db.deadline():
        for key in keys:
            params = {}
            where = _key_where(db, meta, key, params)
            n = c.execute(text(f"DELETE FROM {db.qt(schema, table)} WHERE {where}"), params).rowcount
            if n > 1:
                c.rollback()
                raise UserError(f"A key matched {n} rows; nothing was deleted.", 409)
            total += n
        c.commit()
    return {"deleted": total}
