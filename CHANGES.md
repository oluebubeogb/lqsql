# Changelog

## 1.1.0 — 2026-10-31
- **Rebrand: LiteSQL → lqSQL.** The display name is `lqSQL` and the slug is `lqsql`.
  - Renamed in the UI title, sidebar, login, API title, logs and dump headers.
  - The compose service, image and volume are now `lqsql`, `lqsql:1.1.0` and `lqsql-data`. The Dockerfile has OCI labels, and the container user is `lqsql`.
  - The cookie is now `lqsql_session`. The CSRF header is `x-lqsql`. Browser storage keys are now `lqsql-*`.
  - The Coolify variable `SERVICE_FQDN_LQSQL` is used, with `SERVICE_FQDN_LITESQL` still accepted as a fallback.
- **New logo: solid black** (no gradient). It is a black mark in the light theme and a white mark with a black glyph in the dark theme. The favicon follows the OS colour scheme.
- **Docs:** `ROOT_PATH` stays optional; leave it empty for a subdomain. `/lqsql` is just an example path; you pick your own. The `APP_URL` examples use `lqsql.collab.name.ng` and `existing.collab.name.ng/lqsql`.
- **Upgrade note:** existing sessions end once, so sign in again. Old drafts and history in the browser's localStorage do not carry over.


## 1.0.2 — 2026-10-31
- **Optional path hosting** with `ROOT_PATH` (e.g. `/litesql`) for serving on an existing domain: `https://existing.collab.name.ng/litesql`. Empty or unset keeps root/subdomain hosting, the default.
  - `ROOT_PATH` is normalized (leading slash added, trailing slash removed) and validated.
  - The app knows its prefix, and the proxy strip is optional: both `/litesql/api/...` and stripped `/api/...` work. `/litesql` redirects to `/litesql/`.
  - The SPA uses relative assets (Vite `base: './'`). The server injects `<base href="{ROOT_PATH}/">` and `window.__ROOT_PATH__`, and every API, export and download URL uses that prefix.
  - The session cookie is scoped to `Path={ROOT_PATH}` (or `/`).
  - The Dockerfile and compose healthchecks call `{ROOT_PATH}/api/health`, and compose passes `ROOT_PATH`.
  - The README covers path mode and subdomain mode for Coolify, with and without a strip; `.env.example` is updated.
- Smoke-tested with `ROOT_PATH=/litesql` (Postgres) and empty (SQLite):
  - health, the redirect, index injection, assets, favicon, login cookie path, and the API;
  - a browser run through login, browse, terminal and reload.

## 1.0.1 — 2026-10-31
- **Ports / Coolify**: no host port is published any more, and the domain needs no `:port` suffix.
  - The container now listens on `0.0.0.0:${PORT:-80}` (was a fixed 8080). Port 80 is Coolify's default upstream port, so the proxy finds the app automatically. With no published host port there are no clashes with other apps on 8080.
  - Compose: `PORT` env, `expose: ${PORT:-80}`, a port-aware healthcheck, and a `net.ipv4.ip_unprivileged_port_start: 0` sysctl so the non-root user can bind 80.
  - The optional local mapping (commented out) is `${HOST_PORT:-6789}:${PORT:-80}`.
  - The README's Coolify steps were updated to match.

## 1.0.0 — 2026-10-31
First release.

### Features
- Env-configured single-DB admin for PostgreSQL (incl. pgvector), MySQL/MariaDB and SQLite (`DATABASE_URL`, `SQL_TYPE` inferred, `ADMIN_USER`/`ADMIN_PASSWORD`, `APP_URL`, `READ_ONLY`, `IMPORT_MAX_MB`, `QUERY_TIMEOUT_SECONDS`, `PAGE_SIZE_DEFAULT`).
- Login with an HMAC session cookie, SameSite=Lax, a CSRF header and a login lockout.
- Sidebar: schema picker, table search, row counts and views.
- Browse: pagination, sort, typed filters, PK / ctid / rowid row keys, inline edit, insert (value/DEFAULT/NULL), multi-delete with confirm, and a "show generated SQL" toggle.
- Structure tab: columns, types, defaults, indexes, FKs and DDL.
- SQL terminal: multiple statements in one transaction, per-statement timing and row counts, a destructive-SQL confirm, rollback on error, history, run-selection, and CSV export of results.
- Export: a SQL dump (PG schema-qualified with sequences, identity, FKs, views and extensions; MySQL/SQLite portable and unqualified, with triggers) and a table CSV that respects filters.
- Import:
  - CSV: delimiter sniffing, preview, mapping, and create-or-append in a single transaction.
  - `.sql`: a splitter that handles quotes, comments, `$$` blocks, DELIMITER and trigger bodies; streamed progress; stop-on-error; a single transaction.
- Analysis:
  - DB overview: size, cache hit, connections, tables by size, health notes, unused indexes, unindexed FKs, missing PKs, dead rows, pg extensions and vector columns.
  - Per table: null rate, distinct counts, duplicate PKs, index scans and relationships.
- UI: React + Vite (66 KB gzip JS), light and dark themes, soft tinted icon buttons, sized for laptops.
- Docker: a multi-stage image, a single uvicorn worker, a non-root user, a HEALTHCHECK, and Compose with `mem_limit: 256m` and an optional `coolify` network.

### Tested (smoke, 2026-10-31)
| Engine | Version | Browse/filter/sort | Edit/insert/delete | Terminal | Export CSV/SQL | Import CSV/SQL | Analysis | Read-only |
|---|---|---|---|---|---|---|---|---|
| SQLite | 3.x (python) | ✔ | ✔ (incl. rowid) | ✔ | ✔ (dump restores) | ✔ | ✔ | ✔ |
| PostgreSQL + pgvector | 17.5 + 0.8.7 | ✔ (bool/jsonb/date/text[] filters) | ✔ (incl. ctid, vector/jsonb/array binds) | ✔ (vector distance, CONCURRENTLY, rollback) | ✔ (dump → restore into fresh DB, identity continues) | ✔ (new typed table in other schema, append) | ✔ | ✔ |
| MariaDB | 11.4.4 | ✔ | ✔ (JSON, ENUM, decimal) | ✔ (rollback of DML on error) | ✔ (dump incl. view + trigger → restore into other DB) | ✔ | ✔ | (shared code path) |

UI checked in headless Chrome (login, browse, inline edit, structure, analysis, terminal, import preview, export, dark mode, 1280×720).
Not tested: the Docker image build itself (no Docker on the build box; the runtime was verified on Python 3.12 with the pinned requirements) and MySQL 8 (MariaDB only).

### Fixes during development
- PG dump now schema-qualifies sequence defaults and FK targets.
- MySQL/SQLite dumps no longer qualify names with the source DB, which previously made a restore into a different DB touch the source.
- SQLite multi-statement batches are now truly atomic (explicit BEGIN).
- Row estimates prefer `reltuples` over transient `n_live_tup`.
