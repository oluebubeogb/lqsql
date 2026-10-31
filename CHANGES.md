# Changelog

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
