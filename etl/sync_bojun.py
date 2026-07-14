# -*- coding: utf-8 -*-
"""从伯俊 ERP 标准接口拉取库存，替换 bojun_offline_inventory 表（替代 Excel 导入）。

用法:
  BOJUN_APPKEY=xxx BOJUN_SECRET=yyy python etl/sync_bojun.py [--store 店仓名] [--dry-run]

  --store    只拉某个店仓（调试用），默认全量
  --dry-run  只拉数并打印统计，不写库

与 etl/load_excel.py 的关系：两者都会重建 bojun_offline_inventory，谁后跑以谁为准；
其余 7 张表仍由 load_excel.py 维护。API 版多了 barcode（条码）和 store_code（店仓编号）
两列，条码可用于打通京东侧未匹配的自有编码。API 不提供品名/价格类字段，这些列置空，
核对视图会自动回退用平台侧品名展示。
"""
import io
import csv
import sys
import os
import argparse

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2

from app.config import settings, BASE_DIR
from app.platforms.bojun import BojunClient, BojunError

COLUMNS = [   # (列名, 类型, 中文注释)
    ('store_code', 'text', '店仓编号（API cStoreCode）'),
    ('store_warehouse', 'text', '店仓名称（API cStoreName）'),
    ('product_code', 'text', '款号/产品编码（API mProductName）'),
    ('barcode', 'text', '条码（API mProductaliasNo，可用于对齐京东自有编码）'),
    ('product_name', 'text', '品名（API 不提供，置空，看板回退平台侧品名）'),
    ('stock_qty', 'bigint', '库存数量（API qty）'),
    ('unit_on_order', 'bigint', '单件在单（API qtypreout）'),
    ('in_transit_qty', 'bigint', '在途数量（API qtyprein）'),
    ('frozen_qty', 'bigint', '冻结量（API qtyFreeze）'),
    ('oms_frozen_qty', 'bigint', 'OMS冻结量（API qtyOms）'),
    ('expected_qty', 'bigint', '预计数量（API qtyvalid）'),
    ('reorder_allocatable', 'bigint', '追单可配（API qtyconsign）'),
    ('allocatable', 'bigint', '可配（API qtycan）'),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--store', default='', help='只拉某个店仓（默认全量）')
    ap.add_argument('--dry-run', action='store_true', help='只拉数不写库')
    args = ap.parse_args()

    if not settings.bojun_appkey or not settings.bojun_secret:
        sys.exit('缺少凭证：请设置环境变量 BOJUN_APPKEY / BOJUN_SECRET')

    client = BojunClient()
    print(f'拉取伯俊库存: {settings.bojun_base_url} (appkey={settings.bojun_appkey})'
          + (f', 店仓={args.store}' if args.store else ', 全量'))
    try:
        rows = client.fetch_inventory(store_name=args.store)
    except BojunError as e:
        if getattr(e, 'code', None) == 10103:
            sys.exit(f'{e}\n提示: 验签失败，可尝试调整 method 形态 '
                     f'(BojunClient(method_style=1/2))')
        raise
    print(f'共 {len(rows)} 条记录, '
          f'{len({r["store_warehouse"] for r in rows})} 个店仓, '
          f'{len({r["product_code"] for r in rows})} 个款号')

    if args.dry_run:
        for r in rows[:5]:
            print(' ', r)
        return

    conn = psycopg2.connect(dbname=settings.pg_database, **{
        k: v for k, v in settings.pg_dsn.items() if k != 'dbname'})
    cur = conn.cursor()
    cols_sql = ',\n  '.join(f'"{c}" {t}' for c, t, _ in COLUMNS)
    cur.execute('DROP TABLE IF EXISTS bojun_offline_inventory CASCADE')
    cur.execute(f'CREATE TABLE bojun_offline_inventory (\n  {cols_sql}\n)')
    cur.execute("COMMENT ON TABLE bojun_offline_inventory IS "
                "'伯俊线下库存（来源: 伯俊标准接口 storage.query）'")
    for c, _, comment in COLUMNS:
        cur.execute(f'COMMENT ON COLUMN bojun_offline_inventory."{c}" IS %s', (comment,))

    buf = io.StringIO()
    w = csv.writer(buf, lineterminator='\n')
    names = [c for c, _, _ in COLUMNS]
    for r in rows:
        w.writerow(['' if r.get(c) is None else r.get(c) for c in names])
    buf.seek(0)
    collist = ','.join(f'"{c}"' for c in names)
    cur.copy_expert(
        f'COPY bojun_offline_inventory ({collist}) FROM STDIN WITH (FORMAT csv, NULL \'\')', buf)

    # 重建核对视图（DROP CASCADE 把依赖视图删了）并记录装载时间
    views_sql = os.path.join(BASE_DIR, 'sql', '02_核对视图.sql')
    cur.execute(open(views_sql, encoding='utf-8').read())
    cur.execute("CREATE TABLE IF NOT EXISTS data_meta (loaded_at timestamptz NOT NULL)")
    cur.execute("DELETE FROM data_meta")
    cur.execute("INSERT INTO data_meta VALUES (now())")
    conn.commit()

    cur.execute('SELECT count(*) FROM bojun_offline_inventory')
    print(f'入库完成: bojun_offline_inventory {cur.fetchone()[0]} 行, 核对视图已重建')
    cur.close(); conn.close()


if __name__ == '__main__':
    main()
