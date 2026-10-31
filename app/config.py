"""Environment configuration. Secrets are never logged."""
import hashlib
import os
import sys
from dataclasses import dataclass

from sqlalchemy.engine import make_url


def _bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None or v.strip() == "":
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except ValueError:
        return default


def normalize_url(raw: str, sql_type: str | None) -> tuple[str, str]:
    """Return (sqlalchemy_url, engine) where engine is postgresql|mysql|sqlite."""
    raw = raw.strip()
    low = raw.lower()
    if sql_type:
        t = sql_type.strip().lower()
        t = {"postgres": "postgresql", "pg": "postgresql", "pgvector": "postgresql",
             "mariadb": "mysql", "sqlite3": "sqlite"}.get(t, t)
    elif low.startswith(("postgres://", "postgresql")):
        t = "postgresql"
    elif low.startswith(("mysql", "mariadb")):
        t = "mysql"
    elif low.startswith("sqlite"):
        t = "sqlite"
    elif low.endswith((".db", ".sqlite", ".sqlite3")):
        t = "sqlite"
        raw = "sqlite:///" + raw
    else:
        raise ValueError("Cannot infer SQL_TYPE from DATABASE_URL; set SQL_TYPE=postgresql|mysql|sqlite")
    if t not in ("postgresql", "mysql", "sqlite"):
        raise ValueError("SQL_TYPE must be postgresql, mysql or sqlite")

    if "://" in raw:
        scheme, rest = raw.split("://", 1)
    else:
        scheme, rest = "", raw
    if t == "postgresql":
        url = "postgresql+psycopg://" + rest
    elif t == "mysql":
        url = "mysql+pymysql://" + rest
    else:
        if not raw.lower().startswith("sqlite"):
            url = "sqlite:///" + raw
        else:
            url = "sqlite://" + rest
    return url, t


@dataclass
class Settings:
    database_url: str
    engine: str
    admin_user: str
    admin_password: str
    secret_key: str
    app_url: str
    read_only: bool
    import_max_mb: int
    query_timeout: int
    page_size_default: int
    max_result_rows: int
    session_hours: int
    show_system_schemas: bool
    port: int

    @property
    def masked_url(self) -> str:
        try:
            return make_url(self.database_url).render_as_string(hide_password=True)
        except Exception:
            return "(unparseable)"

    @property
    def cookie_secure(self) -> bool:
        v = os.getenv("COOKIE_SECURE")
        if v is not None and v != "":
            return _bool("COOKIE_SECURE")
        return self.app_url.lower().startswith("https://")


def load() -> Settings:
    errors = []
    raw = os.getenv("DATABASE_URL", "").strip()
    if not raw:
        errors.append("DATABASE_URL is required")
    user = os.getenv("ADMIN_USER", "").strip()
    pw = os.getenv("ADMIN_PASSWORD", "")
    if not user or not pw:
        errors.append("ADMIN_USER and ADMIN_PASSWORD are required (no open access)")
    elif len(pw) < 8:
        errors.append("ADMIN_PASSWORD must be at least 8 characters")
    url, eng = "", ""
    if raw:
        try:
            url, eng = normalize_url(raw, os.getenv("SQL_TYPE") or None)
        except ValueError as e:
            errors.append(str(e))
    if errors:
        for e in errors:
            print(f"[litesql] config error: {e}", file=sys.stderr)
        sys.exit(2)
    secret = os.getenv("SECRET_KEY", "").strip()
    if not secret:
        # stable across restarts, changes when the admin password changes
        secret = hashlib.sha256(("litesql:" + user + ":" + pw + ":" + raw).encode()).hexdigest()
    app_url = (os.getenv("APP_URL") or os.getenv("SERVICE_FQDN_LITESQL") and "https://" + os.getenv("SERVICE_FQDN_LITESQL", "") or "").strip()
    return Settings(
        database_url=url,
        engine=eng,
        admin_user=user,
        admin_password=pw,
        secret_key=secret,
        app_url=app_url,
        read_only=_bool("READ_ONLY", False),
        import_max_mb=max(1, _int("IMPORT_MAX_MB", 25)),
        query_timeout=max(1, _int("QUERY_TIMEOUT_SECONDS", 30)),
        page_size_default=min(500, max(10, _int("PAGE_SIZE_DEFAULT", 50))),
        max_result_rows=min(20000, max(100, _int("MAX_RESULT_ROWS", 1000))),
        session_hours=max(1, _int("SESSION_HOURS", 12)),
        show_system_schemas=_bool("SHOW_SYSTEM_SCHEMAS", False),
        port=_int("PORT", 8080),
    )
