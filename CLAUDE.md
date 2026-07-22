# CLAUDE.md

本文件为 Claude Code (claude.ai/code) 在本仓库中工作提供指引。

## 这是什么

SKG 即时零售库存核对平台（inventory reconciliation）：一个 FastAPI Web 应用，把 **伯俊 ERP 线下库存** 与 **京东秒送 / 美团闪购** 线上库存做比对，并核对经销商 **网点 (outlets)** 的备货是否足以覆盖各公司的线下总量（网点保障）。数据目前来自 Excel 导出（平台 API 先留桩，后续接入）。核对规则/口径见 `docs/库存核对需求.md`。

## 常用命令

```bash
# 本地开发
pip install -r requirements.txt
cp .env.example .env                                # 填 DASH_USER/DASH_PASSWORD；本地想跳过登录设 DEV_NO_AUTH=1
python etl/load_excel.py                            # Excel -> PostgreSQL（会 drop 并重建表和视图）；本地 PG 在 :5432
uvicorn app.main:app --host 0.0.0.0 --port 8061     # 打开 http://localhost:8061/

# 只刷新单个数据源（避免全量重跑）
python etl/load_excel.py --only jd_inventory        # bojun / jd_inventory / jd_store / meituan_store / meituan_inventory / meituan_outlet / feishu

# 为「门店地图」tab 给门店/网点地址做地理编码（增量；需 .env 里的 GAODE_KEY）
python etl/geocode.py                               # 只处理还没进 store_geo 的地址；--retry-fail / --dry-run / --limit N
```

**没有测试套件、也没有配 linter**。部署前请自检：
- Python：`python -c "from app import main"`（能抓到 import/语法错误）。
- **前端 JS 内联写在 `dashboard.html` 里** —— Python import 抓不到它的错误。把 `<script>` 块抽出来解析（例如 `node -e "new Function(scriptText)"`），才能抓到诸如重复 `const` 声明这类会在运行时悄悄搞崩整个页面的问题。

## 部署

生产目标是 **newserver**（Ubuntu），项目在 **`/home/code/china-marketing-retail/`**，通过 `ssh-manager` MCP 工具（`newserver`）访问。运行方式：**docker compose** —— 两个容器 `china-marketing-retail-app-1`（uvicorn :8061，`build: .`）+ `china-marketing-retail-db-1`（PostgreSQL 18，发布在 `127.0.0.1:5439`）。没有 nginx —— uvicorn 直接绑 `0.0.0.0:8061`。**app 容器把整个项目目录 bind-mount 到 `/app`**（`volumes: - .:/app`），所以把改过的文件传到 `/home/code/china-marketing-retail/` 就会即时生效 —— 改代码无需重建镜像。

- 把改动的文件上传到 `/home/code/china-marketing-retail/<相同路径>`，然后：
  - **`.py` 改动 → `cd /home/code/china-marketing-retail && docker compose restart app`**（重启 uvicorn；启动时会重新预热内存缓存）。
  - **`dashboard.html` / 模板 → 无需重启** —— 模板每次请求从磁盘读（且目录是 bind-mount 的，编辑即时生效）。
  - **`requirements.txt` 改动 → `docker compose up -d --build app`**（唯一需要重建镜像的情况）。
- app 容器通过 compose 网络以 `PGHOST=db PGPORT=5432` 连数据库（在 `docker-compose.yml` 的 `environment:` 里设置）；`.env`（仍用于读 `DASH_*`/飞书密钥）bind-mount 在 `/app/.env`。**数据库数据存在 external named volume `skg-inventory-pgdata`**（沿用自 compose 之前的独立容器 `skg-inventory-db`，该容器现已停止并设 `restart=no` 作为回滚备份 —— compose 的 db 运行时切勿启动它：同一数据目录跑两个 postgres 会损坏数据）。宿主机侧的 `psql`/手动 ETL 仍可连 `127.0.0.1:5439`。
- 日志：`docker compose logs -f app`。旧的 systemd 单元 `skg-dashboard` 已 **停止并禁用**（保留作回滚；compose 运行时切勿重新 enable —— 会和 8061 端口冲突）。
- `git push` 仅在明确要求时执行；提交/推送不自动进行。提交带 `co-authored-by` trailer。

## 架构

数据流：**Excel → `etl/load_excel.py` → PostgreSQL（原始表 + 维度层 + 核对视图）→ `app/services/recon.py` 组装成一个 JSON payload → 单个 `dashboard.html` 客户端渲染所有 tab。**

- **SQL 视图是所有业务逻辑的唯一真源**（`sql/02_核对视图.sql`、`sql/03_地图视图.sql`）。三个视图驱动一切：
  - `v_recon_detail` —— 门店 × 货号 的核心：每店的伯俊 vs 京东/美团，带 `flag` 状态和差异。所有客户/门店汇总都是对它 `GROUP BY`。
  - `v_outlet_guard` —— 公司 × 平台 × 网点 × 货号：每个经销商网点的线上库存是否 ≥ 该公司该货号的线下总量。网点保障 tab 及其 Excel 全部由它重新分组得到。
  - `v_map_points`（03）—— 每个地图点一行（专卖店在营 / 京东网点启用 / 美团网点营业中），join `store_geo` 取经纬度、join 两张库存表算有货 SKU 数。经 `services/mapdata.py` 供给门店地图 tab。
  - 改视图的列顺序需先 `DROP` 再重跑文件。`load_excel.py` 每次运行都会重建视图（先 02 后 03）。`store_geo`（地理编码缓存，`etl/geocode.py`）和 `store_alias` 是 `CREATE TABLE IF NOT EXISTS` —— 它们在 ETL 重建中会保留。

- **`app/main.py`** 是唯一的路由。关键 endpoint：`/api/data`（整个看板 payload）、`/api/map` + `/api/map/config`（门店地图的点位和高德 JS key）、`/export.xlsx?kind=recon|guard`、`/api/outlet_guard?customer=&platform=&outlet=`（懒加载明细）、`/api/table/{key}`（配置 CRUD）、`/api/upload` + `/api/etl/status`（Excel 入库）、`/api/users` + `/api/me`、飞书 OAuth 回调。

- **`dashboard.html` 是一个自包含的单页**（无构建步骤，纯 vanilla JS）：所有 tab（客户/门店核对、网点保障、未匹配清单、门店地图）、全屏的数据管理配置视图、上传/用户对话框、主题都在这里。加 JS 时当心和已有顶层 `const`/`function` 重名（例如 `rateCell` 已存在；`map*` 前缀被数据管理视图占用 —— 地理地图用 `gm*`）。地图 tab 首次激活时才懒加载高德 AMap 脚本。

- **缓存（两层，都以数据版本为 key）：**
  - `recon.py`：把 `/api/data` 序列化，带 60s TTL + ETag。`recon.invalidate()` 清缓存 *并* 触发已注册的 `on_invalidate` 钩子。
  - `excel.py`：每个 `kind` 的工作簿按 recon 的 ETag 缓存。生成很慢（recon ~3.5s / guard ~7s），所以在启动时和每次 `invalidate()` 时**后台预热**（excel 通过 `recon.on_invalidate` 注册 `warm`，避免反向 import）。这就是为什么生成慢但下载几乎瞬时。
  - 任何数据变更（`etl_runner` 入库后、`tables.py` 配置 CRUD 后）都会调 `recon.invalidate()`，级联到两层缓存。

- **配置表**（`feishu_store_mapping`、`feishu_jd_outlet`、`feishu_meituan_outlet`）通过一个通用的 `TableManager`（`services/tables.py`，`REGISTRY` 以 `mapping`/`jd_outlet`/`mt_outlet` 为 key）在 `/api/table/{key}` 后面在线编辑。前端根据 API 返回的 `schema` 渲染这三张表。

- **鉴权**（`auth.py`）：HMAC 签名的 cookie 令牌（`dbsess`），携带一个 `subject`（飞书 `open_id` / 密码用户名 / `dev`）；密钥由 `DASH_PASSWORD` 派生，所以改密码会让所有人下线。飞书 OAuth 会 upsert 进 `users` 表（`services/users.py`）并检查 `is_active`。**管理员 = 用共享的 SKG 密码登录（subject == `DASH_USER`）或 dev**；飞书用户默认非管理员，除非把 `users.is_admin` 置位。`DEV_NO_AUTH=1` 在本地绕过鉴权。

- **ETL 入库路径**（`services/etl_runner.py`）：上传把文件以规范名写入 `excel/`（带 `.bak` 备份 + Windows 文件锁重试），在后台单次运行线程里跑 `load_excel.py --only <source>`，失败时回滚源文件，并把每次记录进 `upload_log`（带 `operator`）。

## 约定

- **数据库表和列必须有中文 `COMMENT`**（当前全库已 100% 覆盖，新加表/字段时一并写上，含义变了同步改）。注释写在建表语句所在的位置，跟着 DDL 走：
  - ETL 数据表 → `sql/01_建表.sql`；`store_alias` → `sql/02_核对视图.sql`；`store_geo` → `sql/03_地图视图.sql`；视图本身只要求表级 COMMENT。
  - 应用自建表（`users`/`upload_log`/`data_meta`/配置表的 `id` 列）→ 各自 `CREATE TABLE IF NOT EXISTS` 的 Python 代码里紧跟 COMMENT 语句（幂等，重复执行无害）。
  - 只写在 DDL 里、没在现有库上执行过的注释不会自动生效 —— 改完顺手对库执行一遍（或跑一次对应 ETL/代码路径）。

## 坑（Gotchas）

- **沿用已有的 `Optional[...]` 类型写法**（不要 `X | None`）—— 部署目标跑的是较老的 Python，代码库避免 PEP 604 联合类型。
- `load_excel.py --only feishu` 会用飞书 Excel 重建映射表，**覆盖在配置 UI 里做的手工修改** —— 只改网点、且不能动到 `feishu_store_mapping` 时，用 `--only meituan_outlet`（配合在线配置编辑器）。
- 飞书网点（outlets，`feishu_jd_outlet`/`feishu_meituan_outlet`）是经销商级、以 `customer_name` 为键 —— 它们**不是**客户/门店核对 tab 里的专卖店门店。`feishu_jd_outlet.store_status='启用'` 和 `feishu_meituan_outlet.business_status='营业中'` 才是真正的启用状态列（jd_outlet 的 `business_status` 是脏的）。
- 导出文件名是 `<label>_<数据快照时间>`，其中时间戳取 `data_meta` 的 `max(loaded_at)`（数据最后一次入库的时间），不是下载时间。
- **高德 key 有两种互不兼容的类型**：`GAODE_KEY` 必须是「Web服务」（供 `etl/geocode.py` 的 REST 调用用）；地图 tab 需要 `GAODE_JS_KEY`「Web端(JS API)」+ `GAODE_JS_SECRET`（安全密钥）。前端在 `GAODE_JS_KEY` 未设时会回退到 `GAODE_KEY`，若 key 类型不对则会失败。
- `feishu_store_mapping.store_address` 是 `load_feishu()` 从 `excel/专卖店详细信息.xlsx`（B列店仓名称 ↔ 门店名称，AB列地址）合并进来的 —— 它**不是**飞书 Excel 本身的列。匹配不上的门店为 NULL，在配置 UI 里手工维护；ETL 每次 feishu 运行都会打印未匹配清单。
- `store_geo` 以**去空格后的地址文本**为键 —— 在任何地方改了地址就会变成新的缓存 miss；改地址后跑 `python etl/geocode.py` 给新字符串做地理编码（旧行是无害的残留）。
- 敏感配置只存在 `.env` / `docs/部署信息.local.md`（都在 git 忽略）；`excel/` 源文件不提交。
