"""Fast SQL statement splitter.

Handles '...' / "..." / `...` quoting, -- and # (MySQL) and /* */ comments,
PostgreSQL $tag$ dollar quoting, MySQL DELIMITER directives and
SQLite/MySQL trigger bodies (BEGIN ... END;). Pure python, linear time.
"""
import re

_TRIGGER = re.compile(r"^\s*CREATE\s+(?:TEMP\s+|TEMPORARY\s+)?(?:DEFINER\s*=\s*\S+\s+)?TRIGGER\b", re.I)
_PROC = re.compile(r"^\s*CREATE\s+(?:DEFINER\s*=\s*\S+\s+)?(?:PROCEDURE|FUNCTION|EVENT)\b", re.I)
_END = re.compile(r"\bEND\s*$", re.I)
_DOLLAR = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)?\$")


def split_sql(sql: str, engine: str = "postgresql"):
    """Yield statements (without trailing delimiter), skipping empty ones."""
    n = len(sql)
    i = 0
    start = 0
    delim = ";"
    buf_parts = []
    hash_comments = engine == "mysql"
    backslash_escapes = engine == "mysql"
    at_line_start = True

    def flush(end):
        nonlocal start
        chunk = "".join(buf_parts) + sql[start:end]
        buf_parts.clear()
        start = end
        return chunk

    while i < n:
        c = sql[i]
        # DELIMITER directive (mysql client syntax) at line start
        if at_line_start and engine == "mysql" and sql.startswith(("DELIMITER", "delimiter"), _skip_ws(sql, i)):
            j = _skip_ws(sql, i)
            eol = sql.find("\n", j)
            eol = n if eol == -1 else eol
            pending = flush(i).strip()
            if pending:
                yield pending
            parts = sql[j:eol].split()
            if len(parts) >= 2:
                delim = parts[1]
            i = eol + 1
            start = i
            at_line_start = True
            continue
        if c == "\n":
            at_line_start = True
            i += 1
            continue
        if c in " \t\r":
            i += 1
            continue
        at_line_start = False
        if c in ("'", '"', "`"):
            i = _skip_quoted(sql, i, c, backslash_escapes and c != "`")
            continue
        if c == "-" and sql.startswith("--", i):
            eol = sql.find("\n", i)
            i = n if eol == -1 else eol
            continue
        if c == "#" and hash_comments:
            eol = sql.find("\n", i)
            i = n if eol == -1 else eol
            continue
        if c == "/" and sql.startswith("/*", i):
            end = sql.find("*/", i + 2)
            i = n if end == -1 else end + 2
            continue
        if c == "$" and engine == "postgresql":
            m = _DOLLAR.match(sql, i)
            if m:
                tag = m.group(0)
                end = sql.find(tag, m.end())
                i = n if end == -1 else end + len(tag)
                continue
        if sql.startswith(delim, i):
            stmt_so_far = "".join(buf_parts) + sql[start:i]
            if delim == ";" and engine in ("sqlite", "mysql") and (_TRIGGER.match(_strip_lead_comments(stmt_so_far)) or (engine == "mysql" and _PROC.match(_strip_lead_comments(stmt_so_far)))):
                body = stmt_so_far.rstrip()
                if re.search(r"\bBEGIN\b", body, re.I) and not _END.search(body):
                    i += 1
                    continue
            stmt = flush(i).strip()
            i += len(delim)
            start = i
            if stmt and _strip_lead_comments(stmt).strip():
                yield stmt
            continue
        i += 1
    tail = flush(n).strip()
    if tail and _strip_lead_comments(tail).strip():
        yield tail


def _skip_ws(s, i):
    while i < len(s) and s[i] in " \t":
        i += 1
    return i


def _skip_quoted(s, i, q, backslash):
    n = len(s)
    i += 1
    while i < n:
        c = s[i]
        if backslash and c == "\\":
            i += 2
            continue
        if c == q:
            if i + 1 < n and s[i + 1] == q:
                i += 2
                continue
            return i + 1
        i += 1
    return n


_LEAD = re.compile(r"^(?:\s+|--[^\n]*(?:\n|$)|#[^\n]*(?:\n|$)|/\*.*?\*/)*", re.S)


def _strip_lead_comments(stmt: str) -> str:
    m = _LEAD.match(stmt)
    return stmt[m.end():] if m else stmt


def first_keyword(stmt: str) -> str:
    s = _strip_lead_comments(stmt)
    # mysql versioned comments /*!40101 SET ... */ are stripped as comments above
    m = re.match(r"\(*\s*([A-Za-z]+)", s)
    return m.group(1).upper() if m else ""


def strip_comments(stmt: str) -> str:
    return _strip_lead_comments(stmt)
