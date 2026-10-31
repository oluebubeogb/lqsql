"""Database + table analysis: sizes, counts, columns, null rates, indexes, FKs and health notes."""
import os

from sqlalchemy import inspect, text

from .db import DB

DISTINCT_KINDS = {"number", "text", "date", "bool"}


def _safe(c, sql, params=None, default=None, scalar=False):
    try:
        with c.begin_nested() if (c.dialect.name == "postgresql" and c.in_transaction()) else _Null():
            r = c.execute(text(sql), params or {})
            return r.scalar() if scalar else r.mappings().all()
    except Exception:
        return default


class _Null:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def database(db: DB) -> dict:
    out = {"engine": db.kind, "notes": [], "tables": [], "extensions": [], "stats": {}}
    schema_default = None
    with db.engine.connect() as c:
        if db.kind == "postgresql":
            out["stats"]["version"] = c.execute(text("SHOW server_version")).scalar()
            out["stats"]["database"] = c.execute(text("SELECT current_database()")).scalar()
            out["stats"]["size_bytes"] = c.execute(text("SELECT pg_database_size(current_database())")).scalar()
            out["stats"]["connections"] = _safe(c, "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()", scalar=True)
            out["stats"]["max_connections"] = _safe(c, "SHOW max_connections", scalar=True)
            hit = _safe(c, "SELECT round(100.0*sum(blks_hit)/nullif(sum(blks_hit)+sum(blks_read),0),1) FROM pg_stat_database WHERE datname=current_database()", scalar=True)
            out["stats"]["cache_hit_pct"] = float(hit) if hit is not None else None
            out["extensions"] = [dict(r) for r in (_safe(c, "SELECT extname AS name, extversion AS version FROM pg_extension ORDER BY extname") or [])]
            avail = _safe(c, "SELECT name, default_version AS version FROM pg_available_extensions WHERE name IN ('vector','pg_trgm','postgis','pg_stat_statements','uuid-ossp','pgcrypto') AND installed_version IS NULL ORDER BY name") or []
            out["available_extensions"] = [dict(r) for r in avail]
            rows = c.execute(text("""
                SELECT n.nspname AS schema, c.relname AS name, c.reltuples::bigint AS est_rows,
                       pg_total_relation_size(c.oid) AS total_bytes, pg_relation_size(c.oid) AS table_bytes,
                       pg_indexes_size(c.oid) AS index_bytes,
                       s.n_live_tup AS live, s.n_dead_tup AS dead, s.seq_scan, s.idx_scan,
                       s.last_autovacuum, s.last_vacuum, s.last_autoanalyze, s.last_analyze,
                       EXISTS (SELECT 1 FROM pg_index i WHERE i.indrelid=c.oid AND i.indisprimary) AS has_pk
                FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                LEFT JOIN pg_stat_user_tables s ON s.relid=c.oid
                WHERE c.relkind IN ('r','p') AND NOT c.relispartition
                  AND n.nspname NOT IN ('pg_catalog','information_schema') AND n.nspname NOT LIKE 'pg_toast%'
                ORDER BY pg_total_relation_size(c.oid) DESC""")).mappings().all()
            for r in rows:
                rows_n = r["est_rows"] if r["est_rows"] and r["est_rows"] > 0 else r["live"]
                out["tables"].append({"schema": r["schema"], "name": r["name"], "rows": rows_n,
                                      "bytes": r["total_bytes"], "table_bytes": r["table_bytes"], "index_bytes": r["index_bytes"],
                                      "has_pk": r["has_pk"], "dead": r["dead"], "seq_scan": r["seq_scan"], "idx_scan": r["idx_scan"]})
                if not r["has_pk"]:
                    out["notes"].append({"level": "warn", "table": f"{r['schema']}.{r['name']}", "text": "No primary key — edits use ctid; add a PK for safe updates and replication."})
                if r["dead"] and r["live"] and r["dead"] > 1000 and r["dead"] > 0.2 * r["live"]:
                    out["notes"].append({"level": "warn", "table": f"{r['schema']}.{r['name']}", "text": f"{r['dead']:,} dead rows ({round(100 * r['dead'] / max(r['live'], 1))}% of live) — consider VACUUM."})
                if r["seq_scan"] and r["seq_scan"] > 1000 and (r["idx_scan"] or 0) < r["seq_scan"] / 10 and (r["est_rows"] or 0) > 10000:
                    out["notes"].append({"level": "info", "table": f"{r['schema']}.{r['name']}", "text": f"Mostly sequential scans ({r['seq_scan']:,}) on a {r['est_rows']:,}-row table — a missing index?"})
            unused = _safe(c, """
                SELECT s.schemaname AS schema, s.relname AS table, s.indexrelname AS index, pg_relation_size(s.indexrelid) AS bytes
                FROM pg_stat_user_indexes s JOIN pg_index i ON i.indexrelid=s.indexrelid
                WHERE s.idx_scan = 0 AND NOT i.indisunique AND NOT i.indisprimary
                ORDER BY pg_relation_size(s.indexrelid) DESC LIMIT 20""") or []
            out["unused_indexes"] = [dict(r) for r in unused]
            for u in unused:
                if (u["bytes"] or 0) > 1024 * 1024:
                    out["notes"].append({"level": "info", "table": f"{u['schema']}.{u['table']}", "text": f"Index {u['index']} has never been used since stats reset ({_h(u['bytes'])})."})
            fk_noidx = _safe(c, """
                SELECT n.nspname AS schema, cl.relname AS table, co.conname AS fk,
                       (SELECT string_agg(a.attname, ', ') FROM pg_attribute a WHERE a.attrelid=co.conrelid AND a.attnum = ANY(co.conkey)) AS cols
                FROM pg_constraint co JOIN pg_class cl ON cl.oid=co.conrelid JOIN pg_namespace n ON n.oid=cl.relnamespace
                WHERE co.contype='f' AND NOT EXISTS (
                  SELECT 1 FROM pg_index i WHERE i.indrelid=co.conrelid AND (i.indkey::int2[])[0:array_length(co.conkey,1)-1] @> co.conkey)
                LIMIT 30""") or []
            for f in fk_noidx:
                out["notes"].append({"level": "info", "table": f"{f['schema']}.{f['table']}", "text": f"Foreign key {f['fk']} ({f['cols']}) has no supporting index — joins/deletes on the parent may be slow."})
            if "vector" in {e["name"] for e in out["extensions"]}:
                vcols = _safe(c, """SELECT table_schema AS schema, table_name AS table, column_name AS column
                                    FROM information_schema.columns WHERE udt_name IN ('vector','halfvec','sparsevec') LIMIT 50""") or []
                out["vector_columns"] = [dict(r) for r in vcols]
        elif db.kind == "mysql":
            out["stats"]["version"] = c.execute(text("SELECT VERSION()")).scalar()
            schema_default = c.execute(text("SELECT DATABASE()")).scalar()
            out["stats"]["database"] = schema_default
            rows = c.execute(text("""
                SELECT t.TABLE_SCHEMA AS `schema`, t.TABLE_NAME AS name, t.ENGINE AS engine, t.TABLE_ROWS AS est_rows,
                       COALESCE(t.DATA_LENGTH,0) AS table_bytes, COALESCE(t.INDEX_LENGTH,0) AS index_bytes, COALESCE(t.DATA_FREE,0) AS free_bytes,
                       EXISTS (SELECT 1 FROM information_schema.TABLE_CONSTRAINTS k WHERE k.TABLE_SCHEMA=t.TABLE_SCHEMA AND k.TABLE_NAME=t.TABLE_NAME AND k.CONSTRAINT_TYPE='PRIMARY KEY') AS has_pk
                FROM information_schema.TABLES t
                WHERE t.TABLE_TYPE='BASE TABLE' AND t.TABLE_SCHEMA NOT IN ('mysql','information_schema','performance_schema','sys')
                ORDER BY COALESCE(t.DATA_LENGTH,0)+COALESCE(t.INDEX_LENGTH,0) DESC""")).mappings().all()
            total = 0
            for r in rows:
                b = int(r["table_bytes"]) + int(r["index_bytes"])
                total += b
                out["tables"].append({"schema": r["schema"], "name": r["name"], "rows": r["est_rows"], "bytes": b,
                                      "table_bytes": int(r["table_bytes"]), "index_bytes": int(r["index_bytes"]),
                                      "engine": r["engine"], "has_pk": bool(r["has_pk"]), "free_bytes": int(r["free_bytes"])})
                tn = f"{r['schema']}.{r['name']}"
                if not r["has_pk"]:
                    out["notes"].append({"level": "warn", "table": tn, "text": "No primary key — rows can't be edited from the browser; InnoDB also works best with a PK."})
                if r["engine"] and r["engine"].upper() == "MYISAM":
                    out["notes"].append({"level": "info", "table": tn, "text": "MyISAM table — no transactions or FK; consider ALTER TABLE … ENGINE=InnoDB."})
                if int(r["free_bytes"]) > 10 * 1024 * 1024 and int(r["free_bytes"]) > 0.2 * max(b, 1):
                    out["notes"].append({"level": "info", "table": tn, "text": f"{_h(int(r['free_bytes']))} reclaimable — OPTIMIZE TABLE would compact it."})
            out["stats"]["size_bytes"] = total
            out["stats"]["connections"] = _safe(c, "SELECT COUNT(*) FROM information_schema.PROCESSLIST", scalar=True)
            mc = _safe(c, "SHOW VARIABLES LIKE 'max_connections'")
            out["stats"]["max_connections"] = mc[0]["Value"] if mc else None
            unused = _safe(c, "SELECT object_schema AS `schema`, object_name AS `table`, index_name AS `index` FROM sys.schema_unused_indexes LIMIT 20") or []
            out["unused_indexes"] = [dict(r) for r in unused]
        else:
            out["stats"]["version"] = c.execute(text("SELECT sqlite_version()")).scalar()
            path = db.engine.url.database or ""
            out["stats"]["database"] = os.path.basename(path) or ":memory:"
            ps = c.execute(text("PRAGMA page_size")).scalar()
            pc = c.execute(text("PRAGMA page_count")).scalar()
            fl = c.execute(text("PRAGMA freelist_count")).scalar()
            out["stats"]["size_bytes"] = ps * pc
            out["stats"]["free_bytes"] = ps * fl
            out["stats"]["journal_mode"] = c.execute(text("PRAGMA journal_mode")).scalar()
            out["stats"]["foreign_keys"] = bool(c.execute(text("PRAGMA foreign_keys")).scalar())
            if fl and fl * ps > 1024 * 1024 and fl > 0.2 * pc:
                out["notes"].append({"level": "info", "table": None, "text": f"{_h(fl * ps)} of free pages — VACUUM would shrink the file."})
            if out["stats"]["journal_mode"] != "wal":
                out["notes"].append({"level": "info", "table": None, "text": "journal_mode is not WAL — WAL usually gives better concurrency for web apps."})
            sizes = {}
            dbstat = _safe(c, "SELECT name, SUM(pgsize) AS bytes FROM dbstat GROUP BY name") or []
            for r in dbstat:
                sizes[r["name"]] = r["bytes"]
            out["stats"]["dbstat"] = bool(dbstat)
            if (ps * pc) < 200 * 1024 * 1024:
                out["stats"]["quick_check"] = _safe(c, "PRAGMA quick_check", scalar=True)
            tabs = c.execute(text("SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")).all()
            idx_by_table = {}
            for name, tbl in c.execute(text("SELECT name, tbl_name FROM sqlite_master WHERE type='index'")).all():
                idx_by_table.setdefault(tbl, []).append(name)
            for name, sql in tabs:
                qt = db.q(name)
                n = _safe(c, f"SELECT COUNT(*) FROM {qt}", scalar=True)
                cols = c.execute(text(f"PRAGMA table_info({qt})")).all()
                has_pk = any(r[5] for r in cols)
                b = sizes.get(name)
                if b is not None:
                    b += sum(sizes.get(i, 0) for i in idx_by_table.get(name, []))
                out["tables"].append({"schema": "main", "name": name, "rows": n, "bytes": b, "has_pk": has_pk})
                if not has_pk:
                    out["notes"].append({"level": "info", "table": name, "text": "No explicit primary key — edits use the implicit rowid."})
                fks = c.execute(text(f"PRAGMA foreign_key_list({qt})")).all()
                indexed_first = set()
                for iname in idx_by_table.get(name, []):
                    first = c.execute(text(f"PRAGMA index_info({db.q(iname)})")).first()
                    if first:
                        indexed_first.add(first[2])
                pk_first = [r[1] for r in sorted([r for r in cols if r[5]], key=lambda r: r[5])][:1]
                for fk in fks:
                    if fk[3] not in indexed_first and fk[3] not in pk_first:
                        out["notes"].append({"level": "info", "table": name, "text": f"Foreign key column {fk[3]} → {fk[2]} has no index."})
    out["stats"]["tables"] = len(out["tables"])
    known = [t["rows"] for t in out["tables"] if t["rows"] is not None]
    out["stats"]["total_rows"] = sum(int(x) for x in known) if known else None
    out["tables"] = out["tables"][:200]
    return out


def table(db: DB, schema: str, name: str) -> dict:
    meta = db.table_meta(schema, name)
    qt = db.qt(schema, name)
    insp = inspect(db.engine)
    sch = None if db.kind == "sqlite" and schema == "main" else schema
    out = {"schema": schema, "table": name, "view": meta["view"], "columns": [], "indexes": [], "foreign_keys": [],
           "referenced_by": [], "notes": [], "size": {}}
    try:
        out["indexes"] = [{"name": i.get("name"), "columns": [c for c in i.get("column_names") or [] if c], "unique": bool(i.get("unique"))}
                          for i in insp.get_indexes(name, schema=sch)]
    except Exception:
        pass
    try:
        pk = insp.get_pk_constraint(name, schema=sch)
        if pk and pk.get("constrained_columns"):
            out["indexes"].insert(0, {"name": pk.get("name") or "PRIMARY", "columns": pk["constrained_columns"], "unique": True, "primary": True})
    except Exception:
        pass
    try:
        out["foreign_keys"] = [{"name": f.get("name"), "columns": f["constrained_columns"],
                                "ref": f"{(f.get('referred_schema') + '.') if f.get('referred_schema') else ''}{f['referred_table']}",
                                "ref_columns": f["referred_columns"]} for f in insp.get_foreign_keys(name, schema=sch)]
    except Exception:
        pass

    with db.engine.connect() as c:
        if db.kind == "postgresql":
            r = c.execute(text("SELECT pg_total_relation_size(CAST(:q AS regclass)) AS total, pg_relation_size(CAST(:q AS regclass)) AS tbl, "
                               "pg_indexes_size(CAST(:q AS regclass)) AS idx"), {"q": qt}).mappings().first()
            out["size"] = {"total": r["total"], "table": r["tbl"], "indexes": r["idx"]}
            st = _safe(c, "SELECT n_live_tup, n_dead_tup, seq_scan, idx_scan, last_autovacuum, last_autoanalyze FROM pg_stat_user_tables WHERE schemaname=:s AND relname=:t",
                       {"s": schema, "t": name})
            if st:
                out["stats"] = {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in dict(st[0]).items()}
            iu = _safe(c, "SELECT indexrelname AS name, idx_scan AS scans, pg_relation_size(indexrelid) AS bytes FROM pg_stat_user_indexes WHERE schemaname=:s AND relname=:t",
                       {"s": schema, "t": name}) or []
            usage = {x["name"]: x for x in iu}
            for i in out["indexes"]:
                u = usage.get(i["name"])
                if u:
                    i["scans"], i["bytes"] = u["scans"], u["bytes"]
            refs = _safe(c, """SELECT cl.relname AS table, co.conname AS name FROM pg_constraint co JOIN pg_class cl ON cl.oid=co.conrelid
                               WHERE co.contype='f' AND co.confrelid = CAST(:q AS regclass)""", {"q": qt}) or []
            out["referenced_by"] = [dict(x) for x in refs]
        elif db.kind == "mysql":
            r = _safe(c, "SELECT DATA_LENGTH AS tbl, INDEX_LENGTH AS idx, DATA_FREE AS free, ENGINE AS engine, TABLE_COLLATION AS collation FROM information_schema.TABLES WHERE TABLE_SCHEMA=:s AND TABLE_NAME=:t",
                      {"s": schema, "t": name})
            if r:
                r = r[0]
                out["size"] = {"total": int(r["tbl"] or 0) + int(r["idx"] or 0), "table": r["tbl"], "indexes": r["idx"], "free": r["free"]}
                out["stats"] = {"engine": r["engine"], "collation": r["collation"]}
            refs = _safe(c, "SELECT TABLE_NAME AS `table`, CONSTRAINT_NAME AS name FROM information_schema.KEY_COLUMN_USAGE WHERE REFERENCED_TABLE_SCHEMA=:s AND REFERENCED_TABLE_NAME=:t GROUP BY TABLE_NAME, CONSTRAINT_NAME",
                         {"s": schema, "t": name}) or []
            out["referenced_by"] = [dict(x) for x in refs]
        else:
            b = _safe(c, "SELECT SUM(pgsize) FROM dbstat WHERE name=:t", {"t": name}, scalar=True)
            ib = 0
            for i in out["indexes"]:
                if not i.get("primary") and i.get("name"):
                    v = _safe(c, "SELECT SUM(pgsize) FROM dbstat WHERE name=:t", {"t": i["name"]}, scalar=True)
                    i["bytes"] = v
                    ib += v or 0
            if b is not None:
                out["size"] = {"total": b + ib, "table": b, "indexes": ib}

        est = db.estimate(schema, name)
        total, approx = db.count(schema, name, approx_hint=est)
        out["rows"], out["rows_approx"] = total, approx
        sample_n = None
        src = qt
        if total and total > 200_000:
            sample_n = 100_000
            src = f"(SELECT * FROM {qt} LIMIT {sample_n}) s"
        cols = meta["columns"][:80]
        if cols and (total or 0) > 0:
            parts = ["COUNT(*) AS n"] + [f"COUNT({db.q(x['name'])}) AS {db.q('c' + str(i))}" for i, x in enumerate(cols)]
            nn = _safe(c, f"SELECT {', '.join(parts)} FROM {src}")
            dist_cols = [(i, x) for i, x in enumerate(cols) if x["kind"] in DISTINCT_KINDS][:40]
            dd = None
            if dist_cols:
                dparts = [f"COUNT(DISTINCT {db.q(x['name'])}) AS {db.q('d' + str(i))}" for i, x in dist_cols]
                with db.deadline(15):
                    dd = _safe(c, f"SELECT {', '.join(dparts)} FROM {src}")
            if nn:
                n = nn[0]["n"] or 0
                for i, x in enumerate(cols):
                    nonnull = nn[0][f"c{i}"]
                    nulls = n - nonnull
                    item = {**x, "null_count": nulls, "null_pct": round(100 * nulls / n, 1) if n else 0}
                    if dd and f"d{i}" in dd[0]:
                        item["distinct"] = dd[0][f"d{i}"]
                    out["columns"].append(item)
            else:
                out["columns"] = cols
        else:
            out["columns"] = [{**x, "null_count": None, "null_pct": None} for x in cols]
        out["sampled"] = sample_n
        # duplicate key check
        rk = meta.get("row_key")
        pk_cols = rk["columns"] if rk and rk["type"] == "pk" else []
        cand = pk_cols or ([x["name"] for x in meta["columns"] if x["name"].lower() == "id"][:1])
        if cand and not meta["view"] and (total or 0) > 0:
            cl = ", ".join(db.q(x) for x in cand)
            dup = _safe(c, f"SELECT COUNT(*) FROM (SELECT {cl} FROM {src} GROUP BY {cl} HAVING COUNT(*) > 1) d", scalar=True)
            out["duplicate_check"] = {"columns": cand, "duplicates": dup, "is_pk": bool(pk_cols)}
            if dup:
                out["notes"].append({"level": "warn", "text": f"{dup:,} duplicated value(s) in {', '.join(cand)}."})

    if not meta["view"]:
        if not pk_cols:
            out["notes"].append({"level": "warn", "text": "No primary key." + {
                "postgresql": " Edits fall back to ctid.", "sqlite": " Edits fall back to rowid.",
                "mysql": " Row editing is disabled for this table."}[db.kind]})
        for x in out["columns"]:
            if x.get("null_pct") == 100 and (total or 0) > 0:
                out["notes"].append({"level": "info", "text": f"Column {x['name']} is always NULL."})
            elif x.get("distinct") == 1 and (total or 0) > 10:
                out["notes"].append({"level": "info", "text": f"Column {x['name']} has a single distinct non-null value."})
        idx_first = {tuple(i["columns"][:len(f["columns"])]) for f in out["foreign_keys"] for i in out["indexes"]}
        for f in out["foreign_keys"]:
            if tuple(f["columns"]) not in idx_first and db.kind != "mysql":
                out["notes"].append({"level": "info", "text": f"FK {', '.join(f['columns'])} → {f['ref']} has no index."})
        for i in out["indexes"]:
            if i.get("scans") == 0 and not i.get("unique"):
                out["notes"].append({"level": "info", "text": f"Index {i['name']} has 0 scans since stats reset."})
        seen = {}
        for i in out["indexes"]:
            k = tuple(i["columns"])
            if k in seen and k:
                out["notes"].append({"level": "info", "text": f"Index {i['name']} duplicates {seen[k]} ({', '.join(k)})."})
            seen.setdefault(k, i["name"])
    return out


def _h(b):
    b = float(b or 0)
    for u in ("B", "KB", "MB", "GB", "TB"):
        if b < 1024:
            return f"{b:.0f} {u}" if u == "B" else f"{b:.1f} {u}"
        b /= 1024
    return f"{b:.1f} PB"
