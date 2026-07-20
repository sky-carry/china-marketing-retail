# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

SKG 即时零售库存核对平台 (inventory reconciliation): a FastAPI web app that compares **伯俊 ERP 线下库存** against **京东秒送 / 美团闪购** online inventory, and checks whether dealer **网点 (outlets)** stock enough to cover each company's offline total (网点保障). Data comes from Excel exports today (platform APIs are stubbed for later). Reconciliation rules/口径 live in `docs/库存核对需求.md`.

## Commands

```bash
# Local dev
pip install -r requirements.txt
cp .env.example .env                                # fill DASH_USER/DASH_PASSWORD; set DEV_NO_AUTH=1 to skip login locally
python etl/load_excel.py                            # Excel -> PostgreSQL (drops+rebuilds tables AND views); local PG on :5432
uvicorn app.main:app --host 0.0.0.0 --port 8061     # open http://localhost:8061/

# Refresh a single data source (avoids re-running everything)
python etl/load_excel.py --only jd_inventory        # bojun / jd_inventory / jd_store / meituan_store / meituan_inventory / meituan_outlet / feishu
```

There is **no test suite and no linter** configured. Validate before deploying:
- Python: `python -c "from app import main"` (catches import/syntax errors).
- **Frontend JS lives inline in `dashboard.html`** — a Python import will NOT catch its errors. Extract the `<script>` blocks and parse them (e.g. `node -e "new Function(scriptText)"`) to catch things like duplicate `const` declarations, which otherwise silently break the whole page at runtime.

## Deploy

Production target is **newserver** (Ubuntu), project at **`/home/code/`**, reached via the `ssh-manager` MCP tools (`newserver`). Runtime: systemd service `skg-dashboard` (uvicorn :8061) + Docker PostgreSQL 18 container `skg-inventory-db` (127.0.0.1:**5439**, env `PGPORT=5439`).

- Upload changed files to `/home/code/<same path>`, then:
  - **`.py` change → `systemctl restart skg-dashboard`** (also clears and re-warms the in-memory caches).
  - **`dashboard.html` / templates → no restart needed** — templates are read from disk per request.
- The DB env vars are inline in the systemd unit (`PGHOST=127.0.0.1 PGPORT=5439 PGUSER=postgres PGPASSWORD=postgres PGDATABASE=inventory_check`); an ad-hoc `python3` on the server without them hits the wrong port and fails auth.
- `git push` only when explicitly asked; commits/pushes are not automatic. `co-authored-by` trailer is used on commits.

## Architecture

Data flow: **Excel → `etl/load_excel.py` → PostgreSQL (raw tables + dimension layer + reconciliation views) → `app/services/recon.py` assembles one JSON payload → single `dashboard.html` renders every tab client-side.**

- **The SQL views are the source of truth for all business logic** (`sql/02_核对视图.sql`). Two views drive everything:
  - `v_recon_detail` — 门店 × 货号 core: 伯俊 vs 京东/美团 per store, with `flag` states and diffs. All customer/store summaries are `GROUP BY` over it.
  - `v_outlet_guard` — 公司 × 平台 × 网点 × 货号: whether each dealer outlet's online stock ≥ the company's offline total for that product. The 网点保障 tab and its Excel derive entirely from this by re-grouping.
  - Changing a view's column order requires `DROP` before re-running the file. `load_excel.py` rebuilds views on every run.

- **`app/main.py`** is the only router. Key endpoints: `/api/data` (whole dashboard payload), `/export.xlsx?kind=recon|guard`, `/api/outlet_guard?customer=&platform=&outlet=` (lazy detail), `/api/table/{key}` (config CRUD), `/api/upload` + `/api/etl/status` (Excel ingest), `/api/users` + `/api/me`, feishu OAuth callback.

- **`dashboard.html` is a single self-contained page** (no build step, vanilla JS): all tabs (客户/门店核对, 网点保障, 未匹配清单), the full-screen 数据管理 config view, upload/user dialogs, and theming live here. When adding JS, watch for name collisions with existing top-level `const`/`function` (e.g. `rateCell` already exists).

- **Caching (two layers, both keyed to a data version):**
  - `recon.py`: serializes `/api/data` with a 60s TTL + ETag. `recon.invalidate()` clears it *and* fires registered `on_invalidate` hooks.
  - `excel.py`: caches each `kind`'s workbook against the recon ETag. Generation is slow (~3.5s recon / ~7s guard), so it is **warmed in the background** at startup and on every `invalidate()` (excel registers `warm` via `recon.on_invalidate`, avoiding a reverse import). This is why downloads are near-instant despite slow generation.
  - Any data mutation (`etl_runner` after ingest, `tables.py` after config CRUD) calls `recon.invalidate()`, which cascades to both caches.

- **Config tables** (`feishu_store_mapping`, `feishu_jd_outlet`, `feishu_meituan_outlet`) are edited online through one generic `TableManager` (`services/tables.py`, `REGISTRY` keyed `mapping`/`jd_outlet`/`mt_outlet`) behind `/api/table/{key}`. The frontend renders all three from the API-returned `schema`.

- **Auth** (`auth.py`): HMAC-signed cookie token (`dbsess`) carrying a `subject` (feishu `open_id` / password username / `dev`); key derived from `DASH_PASSWORD` so changing it logs everyone out. Feishu OAuth upserts into the `users` table (`services/users.py`) and checks `is_active`. **Admin = logged in via the shared SKG password (subject == `DASH_USER`) or dev**; feishu users are non-admin unless `users.is_admin` is set. `DEV_NO_AUTH=1` bypasses auth locally.

- **ETL ingest path** (`services/etl_runner.py`): upload writes the file to `excel/` under a canonical name (with `.bak` backup + Windows file-lock retry), runs `load_excel.py --only <source>` in a background single-run thread, rolls back the source file on failure, and records每次 into `upload_log` (with `operator`).

## Gotchas

- **Match the existing `Optional[...]` typing style** (not `X | None`) — the deploy target runs an older Python and the codebase avoids PEP 604 unions.
- `load_excel.py --only feishu` rebuilds the mapping table from the Feishu Excel and **overwrites manual edits made in the config UI** — use `--only meituan_outlet` (and the online config editor) for outlet-only changes that must not touch `feishu_store_mapping`.
- Feishu 网点 (outlets, `feishu_jd_outlet`/`feishu_meituan_outlet`) are dealer-level and keyed to `customer_name` — they are NOT the 专卖店 stores of the 客户/门店核对 tab. `feishu_jd_outlet.store_status='启用'` and `feishu_meituan_outlet.business_status='营业中'` are the real active-status columns (jd_outlet's `business_status` is dirty).
- The exported filename is `<label>_<data-snapshot-time>` where the timestamp is `max(loaded_at)` from `data_meta` (when data was last ingested), not the download time.
- Sensitive config lives only in `.env` / `docs/部署信息.local.md` (both git-ignored); `excel/` source files are not committed.
