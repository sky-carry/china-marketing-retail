# 库存核对平台

SKG 即时零售库存核对：**伯俊 ERP 线下库存** vs **京东秒送 / 美团闪购** 线上上翻库存，按客户（经销商公司）→ 门店 → 货号三级核对差异与维护率。需求与口径详见 [docs/库存核对需求.md](docs/库存核对需求.md)。

## 架构

```text
数据源（当前 Excel 导出 / 未来平台 API）
        │  etl/load_excel.py（入库 + 重建核对视图）
        ▼
  PostgreSQL（inventory_check：8 张原始表 + 门店维度层 + 核对视图）
        │  实时查询
        ▼
  FastAPI（app/：登录、/api/data、/export.xlsx）──► 浏览器看板
```

## 目录结构

```text
app/
  main.py           FastAPI 入口与路由
  config.py         配置（环境变量可覆盖：PGHOST/PGPORT/... DASH_USER/DASH_PASSWORD）
  auth.py           登录会话（HttpOnly Cookie，12h）
  db.py             数据库连接
  services/
    recon.py        核对数据组装（/api/data，60s 缓存 + ETag）
    excel.py        Excel 导出（5 sheet，跟随数据版本缓存）
  platforms/        平台 API 客户端骨架（jd / meituan / bojun，待接入）
  templates/        dashboard.html（看板前端）、login.html
etl/load_excel.py   Excel → PostgreSQL（删表重建 + 视图重建 + 记录装载时间）
sql/                01_建表.sql、02_核对视图.sql
excel/              源 Excel（不入 git；京东库存优先读 京东门店库存-新.xlsx）
docs/               需求文档
```

## 本地开发

```powershell
pip install -r requirements.txt
copy .env.example .env                                   # 填入登录账号等敏感配置（.env 不入 git）
python etl\load_excel.py                                 # Excel 入库（本地 PG localhost:5432）
uvicorn app.main:app --host 0.0.0.0 --port 8061          # 启动服务
# 打开 http://localhost:8061/  账号密码见 .env（DASH_USER / DASH_PASSWORD）
```

## 线上部署（已就绪）

- 服务器地址、账号等敏感信息见 `docs/部署信息.local.md`（不入 git），下文以 `<服务器IP>` 占位
- 服务器组件：systemd 服务 `skg-dashboard`（uvicorn）+ Docker 容器 `skg-inventory-db`（PostgreSQL 18，仅 127.0.0.1:5439）
- 项目目录：`/opt/skg-dashboard/`

### 日常数据更新（推荐：看板页面直接上传）

登录看板 → 点右上角「上传数据」→ 选择 Excel 上传，服务端自动入库并刷新页面。支持：

- **京东门店库存**（京东后台导出 .xlsx，格式同 excel/京东门店库存-新.xlsx）
- **美团门店库存**（美团后台导出 .xlsx）
- 伯俊线下库存（临时通道，伯俊 API 接入后弃用）

格式校验：缺少必需列会被拒绝并自动回滚，不影响现有数据；`POST /api/upload` + `GET /api/etl/status`。

低频数据（门店档案、飞书门店映射）仍走命令行：

```powershell
scp "excel\京东门店.xls" root@<服务器IP>:/opt/skg-dashboard/excel/
ssh root@<服务器IP> "cd /opt/skg-dashboard && PGPORT=5439 python3 etl/load_excel.py --only jd_store,feishu"
```

`--only` 可选：bojun / jd_inventory / jd_store / meituan_store / meituan_inventory / feishu，不带则全量。

### 线上发版（代码/页面有改动时）

```powershell
scp -r app etl sql requirements.txt root@<服务器IP>:/opt/skg-dashboard/
ssh root@<服务器IP> "systemctl restart skg-dashboard"
```

服务器运维命令：

```bash
systemctl status|restart skg-dashboard      # 服务
journalctl -u skg-dashboard -n 50           # 日志
docker ps | grep skg-inventory-db           # 数据库容器
```

## Roadmap

- [x] 伯俊 ERP 接口客户端（`app/platforms/bojun.py`，签名/翻页/字段映射已按文档实现并连通测试环境）+ 同步脚本 `etl/sync_bojun.py`（API 拉库存重建伯俊表，替代 Excel；带 `--store` / `--dry-run`）。**待伯俊提供生产地址与 appkey/secret 后即可切换**（填入 `.env`）
- [ ] 平台 API 接入：京东秒送、美团闪购（`app/platforms/` 骨架已就位）
- [ ] 商品主数据（货号 ↔ 条码）：解决剩余 20 个京东编码无法匹配
- [ ] 门店别名维护页面（目前直接往 `store_alias` 表插行）
- [ ] Nginx + HTTPS（当前 HTTP 明文，见下方安全提示）

> 安全提示：HTTP 明文传输，登录口令在公网链路未加密；数据库仅监听服务器本机回环地址。使用范围扩大前建议加 HTTPS。
