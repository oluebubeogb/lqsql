"""LiteSQL — a light admin for PostgreSQL / MySQL / SQLite."""
import json
import logging
import os
import time

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, analysis, browse, dump, importer, terminal
from .auth import COOKIE, CSRF_HEADER, Auth
from .browse import UserError
from .config import load
from .db import DB

log = logging.getLogger("litesql")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

settings = load()
db = DB(settings)
auth = Auth(settings)
app = FastAPI(title="LiteSQL", version=__version__, docs_url=None, redoc_url=None, openapi_url=None)
log.info("LiteSQL %s starting · engine=%s · db=%s · read_only=%s · root_path=%s", __version__, settings.engine,
         settings.masked_url, settings.read_only, settings.root_path or "/")
ROOT = settings.root_path            # '' or '/litesql'
COOKIE_PATH = ROOT or "/"

STATIC = os.path.join(os.path.dirname(__file__), "static")
OPEN_PATHS = {"/api/health", "/api/login", "/api/session"}


def _ip(req: Request) -> str:
    fwd = req.headers.get("x-forwarded-for")
    return (fwd.split(",")[0].strip() if fwd else (req.client.host if req.client else "?"))


@app.middleware("http")
async def guard(request: Request, call_next):
    path = request.url.path
    if path.startswith("/api/") and path not in OPEN_PATHS:
        if not auth.verify(request.cookies.get(COOKIE)):
            return JSONResponse({"error": "Not signed in"}, status_code=401)
        if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get(CSRF_HEADER) != "1":
            return JSONResponse({"error": "Missing CSRF header"}, status_code=403)
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    if path.startswith("/api/"):
        resp.headers.setdefault("Cache-Control", "no-store")
    return resp


@app.exception_handler(UserError)
async def _user_error(_req, e: UserError):
    return JSONResponse({"error": str(e)}, status_code=e.status)


@app.exception_handler(LookupError)
async def _lookup(_req, e: LookupError):
    return JSONResponse({"error": str(e) or "Not found"}, status_code=404)


@app.exception_handler(Exception)
async def _any(_req, e: Exception):
    msg = str(getattr(e, "orig", None) or e).split("\n[SQL:")[0].strip()[:1500]
    log.warning("request failed: %s: %s", type(e).__name__, msg[:300])
    return JSONResponse({"error": msg or type(e).__name__}, status_code=500)


# ---------- auth ----------
@app.get("/api/health")
def health(db_check: int = 0):
    out = {"ok": True, "version": __version__, "engine": settings.engine}
    if db_check:
        try:
            with db.engine.connect() as c:
                c.exec_driver_sql("SELECT 1")
            out["db"] = "ok"
        except Exception:
            return JSONResponse({"ok": False, "db": "unreachable"}, status_code=503)
    return out


@app.get("/api/session")
def session(request: Request):
    return {"signed_in": auth.verify(request.cookies.get(COOKIE)), "engine": settings.engine}


@app.post("/api/login")
async def login(request: Request):
    if request.headers.get(CSRF_HEADER) != "1":
        return JSONResponse({"error": "Missing CSRF header"}, status_code=403)
    ip = _ip(request)
    if auth.locked(ip):
        return JSONResponse({"error": "Too many attempts. Try again in a few minutes."}, status_code=429)
    body = await request.json()
    if not auth.check_password(str(body.get("username", "")), str(body.get("password", ""))):
        auth.fail(ip)
        time.sleep(0.4)
        return JSONResponse({"error": "Wrong username or password"}, status_code=401)
    auth.clear(ip)
    resp = JSONResponse({"ok": True})
    secure = settings.cookie_secure or request.headers.get("x-forwarded-proto") == "https" or request.url.scheme == "https"
    resp.set_cookie(COOKIE, auth.issue(), httponly=True, samesite="lax", secure=secure,
                    max_age=settings.session_hours * 3600, path=COOKIE_PATH)
    return resp


@app.post("/api/logout")
def logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(COOKIE, path=COOKIE_PATH)
    return resp


@app.get("/api/me")
def me():
    info = db.server_info()
    return {"user": settings.admin_user, "read_only": settings.read_only, "page_size": settings.page_size_default,
            "import_max_mb": settings.import_max_mb, "query_timeout": settings.query_timeout,
            "max_result_rows": settings.max_result_rows, "app_version": __version__, **info}


# ---------- browse ----------
@app.get("/api/schemas")
def schemas():
    return {"schemas": db.schemas()}


@app.get("/api/tables")
def tables(schema: str):
    return {"tables": db.tables(schema)}


@app.get("/api/table")
def table_meta(schema: str, table: str, refresh: int = 0):
    if refresh:
        db.invalidate()
    return db.table_meta(schema, table)


def _filters(f: str | None):
    if not f:
        return []
    try:
        v = json.loads(f)
        return v if isinstance(v, list) else []
    except ValueError:
        raise UserError("Bad filter")


@app.get("/api/rows")
def rows(schema: str, table: str, page: int = 1, size: int = 0, sort: str | None = None, dir: str = "asc", f: str | None = None):
    return browse.fetch_rows(db, schema, table, page, size or settings.page_size_default, sort, dir, _filters(f))


@app.post("/api/rows")
async def insert(request: Request):
    b = await request.json()
    return browse.insert_row(db, b["schema"], b["table"], b.get("values") or {})


@app.patch("/api/rows")
async def update(request: Request):
    b = await request.json()
    return browse.update_row(db, b["schema"], b["table"], b["key"], b.get("values") or {})


@app.post("/api/rows/delete")
async def delete(request: Request):
    b = await request.json()
    return browse.delete_rows(db, b["schema"], b["table"], b.get("keys") or [])


# ---------- terminal ----------
@app.post("/api/sql")
async def run_sql(request: Request):
    b = await request.json()
    sql = str(b.get("sql") or "")
    if len(sql) > 2_000_000:
        raise UserError("Query too large for the terminal; use Import → SQL file.")
    from starlette.concurrency import run_in_threadpool
    out = await run_in_threadpool(terminal.run, db, sql, bool(b.get("confirm")))
    status = out.pop("status", 200)
    return JSONResponse(out, status_code=status)


# ---------- export ----------
def _ts():
    return time.strftime("%Y%m%d-%H%M%S")


@app.get("/api/export/table.csv")
def export_table_csv(schema: str, table: str, f: str | None = None, sort: str | None = None, dir: str = "asc"):
    gen = dump.table_csv(db, schema, table, _filters(f), sort, dir)
    return StreamingResponse(gen, media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{_safe_name(table)}-{_ts()}.csv"'})


@app.post("/api/export/query.csv")
async def export_query_csv(request: Request):
    b = await request.json()
    sql = str(b.get("sql") or "").strip().rstrip(";")
    stmts = list(terminal.split_sql(sql, db.kind))
    if len(stmts) != 1:
        raise UserError("Export one query at a time.")
    if not terminal.is_read(stmts[0]):
        raise UserError("Only read queries (SELECT/WITH/SHOW…) can be exported.")
    return StreamingResponse(dump.query_csv(db, stmts[0]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="query-{_ts()}.csv"'})


@app.get("/api/export/sql")
def export_sql(schema: str, tables: str, ddl: int = 1, data: int = 1, drop: int = 0):
    names = [t for t in tables.split(",") if t]
    if not names:
        raise UserError("Pick at least one table")
    existing = {t["name"] for t in db.tables(schema)}
    bad = [n for n in names if n not in existing]
    if bad:
        raise UserError("Unknown table(s): " + ", ".join(bad[:5]))
    fname = f"{_safe_name(names[0]) if len(names) == 1 else _safe_name(schema)}-{_ts()}.sql"
    return StreamingResponse(dump.sql_dump(db, schema, names, bool(ddl), bool(data), bool(drop)),
                             media_type="application/sql; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{fname}"'})


def _safe_name(s):
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in s)[:60] or "export"


# ---------- import ----------
async def _read_upload(file: UploadFile) -> bytes:
    cap = settings.import_max_mb * 1024 * 1024
    chunks, size = [], 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        size += len(chunk)
        if size > cap:
            raise UserError(f"File is larger than IMPORT_MAX_MB ({settings.import_max_mb} MB).", 413)
        chunks.append(chunk)
    return b"".join(chunks)


@app.post("/api/import/csv/preview")
async def import_csv_preview(request: Request, file: UploadFile = File(...)):
    cl = int(request.headers.get("content-length") or 0)
    if cl > (settings.import_max_mb + 1) * 1024 * 1024:
        raise UserError(f"File is larger than IMPORT_MAX_MB ({settings.import_max_mb} MB).", 413)
    data = await _read_upload(file)
    return importer.csv_preview(data, file.filename or "import.csv")


@app.post("/api/import/csv/commit")
async def import_csv_commit(request: Request):
    b = await request.json()
    gen = importer.csv_commit(db, b.get("token"), b.get("schema"), b.get("table"), b.get("mapping") or [],
                              bool(b.get("create")), bool(b.get("empty_as_null", True)), bool(b.get("truncate")),
                              b.get("types"))
    return StreamingResponse(gen, media_type="application/x-ndjson")


@app.post("/api/import/sql")
async def import_sql(request: Request, file: UploadFile = File(...), single_tx: str = Form("1"), stop_on_error: str = Form("1")):
    cl = int(request.headers.get("content-length") or 0)
    if cl > (settings.import_max_mb + 1) * 1024 * 1024:
        raise UserError(f"File is larger than IMPORT_MAX_MB ({settings.import_max_mb} MB).", 413)
    data = await _read_upload(file)
    gen = importer.sql_import(db, data, single_tx == "1", stop_on_error == "1")
    return StreamingResponse(gen, media_type="application/x-ndjson")


# ---------- analysis ----------
@app.get("/api/analysis")
def analysis_db():
    return analysis.database(db)


@app.get("/api/analysis/table")
def analysis_table(schema: str, table: str):
    return analysis.table(db, schema, table)


# ---------- SPA ----------
_INDEX_CACHE: dict = {}


def _index_html():
    """index.html with <base href> + window.__ROOT_PATH__ so assets and API calls resolve under ROOT_PATH."""
    idx = os.path.join(STATIC, "index.html")
    if not os.path.exists(idx):
        return None
    mtime = os.path.getmtime(idx)
    if _INDEX_CACHE.get("mtime") != mtime:
        raw = open(idx, encoding="utf-8").read()
        inject = f'<base href="{ROOT}/" /><script>window.__ROOT_PATH__={json.dumps(ROOT)}</script>'
        _INDEX_CACHE.update(mtime=mtime, html=raw.replace("<head>", "<head>" + inject, 1))
    return _INDEX_CACHE["html"]


if os.path.isdir(os.path.join(STATIC, "assets")):
    app.mount("/assets", StaticFiles(directory=os.path.join(STATIC, "assets")), name="assets")


@app.get("/{path:path}")
def spa(path: str):
    if path.startswith("api/"):
        return JSONResponse({"error": "Not found"}, status_code=404)
    f = os.path.join(STATIC, path)
    if path and os.path.isfile(f) and os.path.realpath(f).startswith(os.path.realpath(STATIC)):
        return FileResponse(f)
    html = _index_html()
    if html is not None:
        return HTMLResponse(html, headers={"Cache-Control": "no-cache"})
    return Response("LiteSQL API is running. Build the web UI (web/) to serve it here.", media_type="text/plain")


# ---------- optional path prefix (ROOT_PATH) ----------
class RootPathMiddleware:
    """Serve the app under ROOT_PATH whether or not the proxy strips the prefix.

    /litesql        -> 308 redirect to /litesql/
    /litesql/...    -> routed as /...           (proxy forwards the full path)
    /...            -> routed as-is             (proxy already stripped the prefix)
    """

    def __init__(self, inner, prefix: str):
        self.inner, self.prefix = inner, prefix

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket") and self.prefix:
            path = scope.get("path", "")
            if path == self.prefix:
                qs = scope.get("query_string", b"").decode("latin-1")
                resp = RedirectResponse(self.prefix + "/" + ("?" + qs if qs else ""), status_code=308)
                return await resp(scope, receive, send)
            if path.startswith(self.prefix + "/"):
                scope = dict(scope)
                scope["path"] = path[len(self.prefix):]
                raw = scope.get("raw_path")
                if raw and raw.startswith(self.prefix.encode()):
                    scope["raw_path"] = raw[len(self.prefix):]
        return await self.inner(scope, receive, send)


if ROOT:
    _fastapi_app = app
    app = RootPathMiddleware(_fastapi_app, ROOT)
