# -*- coding: utf-8 -*-
"""把五个 Excel + 飞书导出表格入库到 PostgreSQL inventory_check 库。

用法:
  1. (可选) 用 lark-cli 重新导出飞书《即时零售门店上翻明细》为
     excel/_feishu_即时零售门店上翻明细.xlsx
  2. python etl/load_excel.py
数据表会被 DROP 后重建并重建核对视图 (sql/02_核对视图.sql)。
"""
import sys, io, os, re, csv
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import pandas as pd
import psycopg2

PG = dict(
    host=os.environ.get('PGHOST', 'localhost'),
    port=int(os.environ.get('PGPORT', '5432')),
    user=os.environ.get('PGUSER', 'postgres'),
    password=os.environ.get('PGPASSWORD', 'postgres'),
)
DB = os.environ.get('PGDATABASE', 'inventory_check')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def src(name):
    """Excel 优先从 excel/ 目录取，兼容还在根目录的情况"""
    for d in ('excel', ''):
        p = os.path.join(BASE, d, name)
        if os.path.exists(p):
            return p
    raise FileNotFoundError(name)


def src_any(*names):
    """按优先级取第一个存在的文件（用于"-新"版本优先于旧版本）"""
    for n in names:
        try:
            p = src(n)
            print(f'使用源文件: {os.path.relpath(p, BASE)}')
            return p
        except FileNotFoundError:
            pass
    raise FileNotFoundError(names)


# ---------- 1. 建库 ----------
conn = psycopg2.connect(dbname='postgres', **PG)
conn.autocommit = True
cur = conn.cursor()
cur.execute("SELECT 1 FROM pg_database WHERE datname=%s", (DB,))
if not cur.fetchone():
    cur.execute(f"CREATE DATABASE {DB} ENCODING 'UTF8'")
    print(f'created database {DB}')
else:
    print(f'database {DB} already exists, reuse it')
cur.close(); conn.close()

# ---------- 2. 读取源数据 ----------
def dedup_cols(cols):
    seen, out = {}, []
    for c in cols:
        c = str(c).strip()
        if c.startswith('Unnamed:') or c == '' or c == 'nan':
            c = '_blank'
        n = seen.get(c, 0) + 1
        seen[c] = n
        out.append(c if n == 1 else f'{c}_{n}')
    return out

sources = []  # (table_name, comment, dataframe)

df = pd.read_excel(src('伯俊线下库存.xlsx'), sheet_name='download')
sources.append(('bojun_offline_inventory', '伯俊线下库存（伯俊线下库存.xlsx / download）', df))

df = pd.read_excel(src_any('京东门店库存-新.xlsx', '京东门店库存.xlsx'))
sources.append(('jd_store_inventory', '京东门店库存（京东门店库存-新.xlsx，商家商品编号补全版）', df))

df = pd.read_excel(src('京东门店.xls'))
sources.append(('jd_store', '京东门店（京东门店.xls / 门店导出）', df))

df = pd.read_excel(src('美团门店.xlsx'))
sources.append(('meituan_store', '美团门店（美团门店.xlsx / Sheet0）', df))

df = pd.read_excel(src('美团门店库存.xlsx'))
# 第一行是字段说明（"门店对应的唯一ID"等），不是数据，跳过
first = str(df.iloc[0, 0])
if 'ID' in first or '唯一' in first:
    df = df.iloc[1:].reset_index(drop=True)
    print('美团门店库存: 跳过第一行字段说明行')
sources.append(('meituan_store_inventory', '美团门店库存（美团门店库存.xlsx / 商品明细）', df))

FEISHU = src('_feishu_即时零售门店上翻明细.xlsx')
df = pd.read_excel(FEISHU, sheet_name='专卖店')
# 三个重名"营业状态"按平台改名
plat, new_cols = None, []
for c in df.columns:
    c = str(c).strip()
    if c == '京东ID': plat = '京东'
    if c == '美团ID': plat = '美团'
    if c == '饿了么ID': plat = '饿了么'
    new_cols.append(f'{plat}营业状态' if c.startswith('营业状态') and plat else c)
df.columns = new_cols
sources.append(('feishu_store_mapping', '即时零售门店上翻明细-专卖店（飞书文档主表：三平台门店映射）', df))

df = pd.read_excel(FEISHU, sheet_name='京东网点')
sources.append(('feishu_jd_outlet', '即时零售门店上翻明细-京东网点（飞书文档附表）', df))

df = pd.read_excel(FEISHU, sheet_name='各区域对接人明细')
sources.append(('feishu_region_contact', '即时零售门店上翻明细-各区域对接人明细（飞书文档附表）', df))

# ---------- 3. 中文列名 → 英文（与 sql/01_建表.sql 保持一致） ----------
RENAME = {
 'bojun_offline_inventory': {'店仓':'store_warehouse','产品编码':'product_code','款号':'style_no','品名':'product_name',
  '标准价':'standard_price','库存数量':'stock_qty','库存金额':'stock_amount','箱内库存':'boxed_stock',
  '单件在单':'unit_on_order','箱内在单':'boxed_on_order','在单金额':'on_order_amount','在途数量':'in_transit_qty',
  '在途金额':'in_transit_amount','冻结量':'frozen_qty','OMS冻结量':'oms_frozen_qty','预计数量':'expected_qty',
  '预计金额':'expected_amount','追单可配':'reorder_allocatable','可配':'allocatable','ASI':'asi','可用':'available'},
 'jd_store_inventory': {'门店编号':'store_code','门店名称':'store_name','SKU编码':'sku_code','商品名称':'product_name',
  '商家商品编号':'merchant_product_code','条码':'barcode','销售城市':'sales_city','会员价':'member_price',
  '门店价格':'store_price','现货库存':'onhand_stock','实时价':'realtime_price','可用库存':'available_stock',
  '商品状态':'product_status','库存状态':'stock_status','SPU编码':'spu_code','销售属性名称':'sales_attr_name',
  '指导价':'guide_price','京东SKU编码':'jd_sku_code'},
 'jd_store': {'门店编号':'store_code','门店名称':'store_name','商家门店编号':'merchant_store_code',
  '小时购门店编号':'hourly_store_code','商家名称':'merchant_name','商家编号':'merchant_code','所在城市':'city',
  '行政区':'district','营业时间':'business_hours','门店电话':'store_phone','门店手机':'store_mobile',
  '门店地址':'store_address','创建时间':'created_at','更新时间':'updated_at','最后一次操作人':'last_operator',
  '营业状态':'business_status','门店状态':'store_status','小时购营业状态':'hourly_business_status',
  '门店资质':'store_qualification','运力状态（只开通到店团购商家无需关注）':'delivery_capacity_status',
  '秒送门祥链接':'miaosong_store_link','到家门祥链接':'daojia_store_link'},
 'meituan_store': {'门店名称':'store_name','门店ID':'store_id','内部编码':'internal_code','营业状态':'business_status',
  '休息/下线原因':'offline_reason','所在城市':'city','联系电话':'contact_phone','门店地址':'store_address',
  '营业时间':'business_hours','配送方式':'delivery_method'},
 'meituan_store_inventory': {'门店ID':'store_id','门店名称':'store_name','省份/城市':'province_city',
  '商品名称':'product_name','店内码/货号':'internal_sku_code','sku_id':'sku_id','规格名称':'spec_name','库存':'stock_qty'},
 'feishu_store_mapping': {'序号':'seq_no','省份':'province','城市':'city','客户名称':'customer_name',
  '门店名称':'store_name','内部编码':'internal_code','备注':'remark','京东名称':'jd_name','京东ID':'jd_id',
  '京东营业状态':'jd_business_status','美团名称':'meituan_name','美团ID':'meituan_id','美团营业状态':'meituan_business_status',
  '饿了么名称':'eleme_name','饿了么ID':'eleme_id','饿了么营业状态':'eleme_business_status',
  '京东启用状态':'jd_enable_status','验真状态':'verification_status'},
 'feishu_jd_outlet': {'门店编号':'store_code','门店名称':'store_name','视频状态':'video_status','门店性质':'store_type',
  '备注':'remark','经销商':'dealer','商家门店编号':'merchant_store_code','小时购门店编号':'hourly_store_code',
  '所在城市':'city','批次':'batch','行政区':'district','门店地址':'store_address','营业状态':'business_status',
  '门店状态':'store_status','小时购营业状态':'hourly_business_status','_blank':'extra_status',
  '匹配表状态':'match_table_status','验真状态':'verification_status'},
 'feishu_region_contact': {'一级经销商':'primary_dealer','区域':'region','区域经理':'region_manager',
  '即时零售对接人':'instant_retail_contact'},
}

# ---------- 4. 建表 + 装载 ----------
ID_PAT = re.compile(r'(id$|_id|_code|_no$|phone|mobile|barcode|batch|sku)', re.I)

def sql_type(colname, s):
    if ID_PAT.search(colname):
        return 'text'
    if pd.api.types.is_datetime64_any_dtype(s):
        return 'timestamp'
    if pd.api.types.is_integer_dtype(s):
        return 'bigint'
    if pd.api.types.is_float_dtype(s):
        nn = s.dropna()
        if len(nn) and (nn == nn.round()).all() and nn.abs().max() < 9e18:
            return 'bigint'
        return 'double precision'
    return 'text'

conn = psycopg2.connect(dbname=DB, **PG)
cur = conn.cursor()

for table, comment, df in sources:
    df = df.copy()
    df.columns = dedup_cols(df.columns)
    drop = [c for c in df.columns if c.startswith('_blank') and df[c].isna().all()]
    df = df.drop(columns=drop)
    ren = RENAME.get(table, {})
    unknown = [c for c in df.columns if c not in ren]
    if unknown:
        print(f'警告 {table}: 源表出现新列 {unknown}（原样入库，注意同步 sql/01_建表.sql）')
    df.columns = [ren.get(c, c) for c in df.columns]

    types = {c: sql_type(c, df[c]) for c in df.columns}

    def fmt(v, t):
        if pd.isna(v):
            return None
        if t == 'bigint':
            return str(int(v)) if not isinstance(v, str) else v.strip()
        if isinstance(v, float) and v.is_integer():
            return str(int(v))
        return str(v)

    cols_sql = ',\n  '.join(f'"{c}" {types[c]}' for c in df.columns)
    cur.execute(f'DROP TABLE IF EXISTS "{table}" CASCADE')
    cur.execute(f'CREATE TABLE "{table}" (\n  {cols_sql}\n)')
    cur.execute(f'COMMENT ON TABLE "{table}" IS %s', (comment,))
    for zh, en in ren.items():
        if en in df.columns:
            cur.execute(f'COMMENT ON COLUMN "{table}"."{en}" IS %s', (zh,))

    buf = io.StringIO()
    w = csv.writer(buf, lineterminator='\n')
    tl = [types[c] for c in df.columns]
    for row in df.itertuples(index=False, name=None):
        out = []
        for v, t in zip(row, tl):
            try:
                out.append(fmt(v, t))
            except (ValueError, TypeError):
                out.append(None)
        w.writerow(['' if x is None else x for x in out])
    buf.seek(0)
    collist = ','.join(f'"{c}"' for c in df.columns)
    cur.copy_expert(f'COPY "{table}" ({collist}) FROM STDIN WITH (FORMAT csv, NULL \'\')', buf)
    cur.execute(f'SELECT count(*) FROM "{table}"')
    n = cur.fetchone()[0]
    conn.commit()
    print(f'{table}: {n} rows, {len(df.columns)} cols loaded')

# 美团库存数量列转数值
cur.execute('''SELECT count(*) FROM meituan_store_inventory WHERE stock_qty IS NOT NULL AND stock_qty !~ '^-?[0-9]+$' ''')
if cur.fetchone()[0] == 0:
    cur.execute('''ALTER TABLE meituan_store_inventory ALTER COLUMN stock_qty TYPE bigint USING NULLIF(stock_qty,'')::bigint''')
    conn.commit()
    print('meituan_store_inventory.stock_qty 已转为 bigint')

# 记录数据装载时间（看板"数据快照"时间即取自这里）
cur.execute("CREATE TABLE IF NOT EXISTS data_meta (loaded_at timestamptz NOT NULL)")
cur.execute("DELETE FROM data_meta")
cur.execute("INSERT INTO data_meta VALUES (now())")
conn.commit()

# 重建视图（DROP TABLE CASCADE 会把依赖视图一并删掉）
views_sql = os.path.join(BASE, 'sql', '02_核对视图.sql')
if os.path.exists(views_sql):
    cur.execute(open(views_sql, encoding='utf-8').read())
    conn.commit()
    print('核对视图已重建 (sql/02_核对视图.sql)')

cur.close(); conn.close()
print('ALL DONE')
