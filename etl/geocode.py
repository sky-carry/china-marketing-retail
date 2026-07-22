# -*- coding: utf-8 -*-
"""门店/网点地址 → 经纬度（高德地理编码），结果缓存进 store_geo 表。

用法:
  python etl/geocode.py                # 增量：只编码 store_geo 里还没有的地址
  python etl/geocode.py --retry-fail   # 连同上次失败的地址一起重试
  python etl/geocode.py --dry-run      # 只统计待编码数量，不调 API
  python etl/geocode.py --limit 100    # 最多编码 100 条（配额紧张时分批跑）

地址来源（与地图看板口径一致，均取有效点位）:
  - 专卖店: feishu_store_mapping.store_address（备注非 闭店/机场店）
  - 京东网点: feishu_jd_outlet（门店状态=启用）
  - 美团网点: feishu_meituan_outlet（营业状态=营业中）

需要 .env 里配置 GAODE_KEY（高德「Web服务」类型 key）。
store_geo 用 CREATE TABLE IF NOT EXISTS，load_excel.py 重建数据表不会清掉它；
地址文本是缓存键，飞书表里改了地址会自动视为新地址补编码。
"""
import sys, os, json, time, argparse
import urllib.parse, urllib.request

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

import psycopg2
from app.config import settings   # 顺带把 .env 读进环境变量

API = 'https://restapi.amap.com/v3/geocode/geo'
# 高德返回的解析级别，越靠前越精确；市/区县级只能落在行政中心，标记为低精度
POOR_LEVELS = {'国家', '省', '市', '区县', '未知'}

DDL = """
CREATE TABLE IF NOT EXISTS store_geo (
  address           text PRIMARY KEY,          -- btrim 后的原始地址（缓存键）
  lng               double precision,
  lat               double precision,
  adcode            text,
  formatted_address text,
  level             text,                      -- 高德解析级别（门牌号/兴趣点/道路…市/区县=低精度）
  status            text NOT NULL,             -- ok / fail
  updated_at        timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE store_geo IS '地址地理编码缓存（高德）：etl/geocode.py 维护，load_excel.py 不会重建此表';
"""

SRC_SQL = """
SELECT a, max(c) FROM (
  SELECT btrim(store_address) a, COALESCE(city, '') c FROM feishu_store_mapping
   WHERE store_address IS NOT NULL AND COALESCE(remark,'') NOT IN ('闭店','机场店')
  UNION ALL
  SELECT btrim(store_address), COALESCE(city, '') FROM feishu_jd_outlet
   WHERE store_status = '启用' AND store_address IS NOT NULL
  UNION ALL
  SELECT btrim(store_address), COALESCE(city, '') FROM feishu_meituan_outlet
   WHERE business_status = '营业中' AND store_address IS NOT NULL
) t WHERE a <> '' GROUP BY a
"""


def geocode_one(key, address, city):
    """单条地理编码；返回 dict(status=ok/fail, ...)。带 city 提示提高准确率。"""
    params = {'key': key, 'address': address, 'output': 'JSON'}
    if city:
        params['city'] = city
    url = API + '?' + urllib.parse.urlencode(params)
    for attempt in (1, 2, 3):
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = json.loads(resp.read().decode('utf-8'))
            break
        except Exception as e:
            if attempt == 3:
                return {'status': 'fail', 'error': f'network: {e}'}
            time.sleep(1.5 * attempt)
    if data.get('status') != '1':
        info = data.get('info', ''), data.get('infocode', '')
        # 10001 key不对 / 10003 配额用尽 / 10021 QPS超限——这些该停下来，不该逐条烧
        return {'status': 'fail', 'error': f'amap: {info}', 'infocode': data.get('infocode', '')}
    geos = data.get('geocodes') or []
    if not geos:
        return {'status': 'fail', 'error': 'no match'}
    g = geos[0]
    try:
        lng, lat = (float(x) for x in g['location'].split(','))
    except (KeyError, ValueError):
        return {'status': 'fail', 'error': 'bad location'}
    return {'status': 'ok', 'lng': lng, 'lat': lat, 'adcode': g.get('adcode') or None,
            'formatted': g.get('formatted_address') or None, 'level': g.get('level') or None}


FATAL_CODES = {'10001', '10002', '10003', '10004', '10005', '10009', '10013', '10044'}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--retry-fail', action='store_true', help='重试之前失败的地址')
    ap.add_argument('--dry-run', action='store_true', help='只统计不调 API')
    ap.add_argument('--limit', type=int, default=0, help='本次最多编码条数（0=不限）')
    ap.add_argument('--qps', type=float, default=3.0, help='每秒请求数上限（默认 3，个人 key 限额）')
    args = ap.parse_args()

    key = os.environ.get('GAODE_KEY', '').strip()
    if not key and not args.dry_run:
        sys.exit('缺少 GAODE_KEY：请在 .env 配置高德「Web服务」key 后重跑')

    conn = psycopg2.connect(**settings.pg_dsn)
    cur = conn.cursor()
    cur.execute(DDL)
    conn.commit()

    cur.execute(SRC_SQL)
    src = cur.fetchall()                       # [(address, city), ...]
    skip_status = ('ok',) if args.retry_fail else ('ok', 'fail')
    cur.execute("SELECT address FROM store_geo WHERE status IN %s", (skip_status,))
    done = {r[0] for r in cur.fetchall()}
    todo = [(a, c) for a, c in src if a not in done]
    print(f'地址总数 {len(src)}，已编码/跳过 {len(src) - len(todo)}，待编码 {len(todo)}')
    if args.limit and len(todo) > args.limit:
        todo = todo[:args.limit]
        print(f'--limit 生效，本次只跑 {len(todo)} 条')
    if args.dry_run or not todo:
        conn.close()
        print('DRY RUN 结束' if args.dry_run else '没有需要编码的地址')
        return

    ok = fail = 0
    interval = 1.0 / max(args.qps, 0.1)
    for i, (addr, city) in enumerate(todo, 1):
        r = geocode_one(key, addr, city)
        if r['status'] == 'ok':
            ok += 1
            cur.execute("""INSERT INTO store_geo (address, lng, lat, adcode, formatted_address, level, status, updated_at)
                           VALUES (%s,%s,%s,%s,%s,%s,'ok',now())
                           ON CONFLICT (address) DO UPDATE SET lng=EXCLUDED.lng, lat=EXCLUDED.lat,
                             adcode=EXCLUDED.adcode, formatted_address=EXCLUDED.formatted_address,
                             level=EXCLUDED.level, status='ok', updated_at=now()""",
                        (addr, r['lng'], r['lat'], r['adcode'], r['formatted'], r['level']))
        else:
            fail += 1
            print(f'  失败: {addr[:50]} -> {r.get("error")}')
            cur.execute("""INSERT INTO store_geo (address, status, updated_at) VALUES (%s,'fail',now())
                           ON CONFLICT (address) DO UPDATE SET status='fail', updated_at=now()""", (addr,))
            if r.get('infocode') in FATAL_CODES:
                conn.commit()
                sys.exit(f'高德返回致命错误（infocode={r["infocode"]}，key 无效或配额用尽），已停止；'
                         f'本次已完成 ok={ok} fail={fail}')
        if i % 50 == 0:
            conn.commit()
            print(f'  进度 {i}/{len(todo)} (ok={ok} fail={fail})')
        time.sleep(interval)
    conn.commit()

    cur.execute("SELECT level, count(*) FROM store_geo WHERE status='ok' GROUP BY 1 ORDER BY 2 DESC")
    levels = cur.fetchall()
    cur.execute("SELECT count(*) FROM store_geo WHERE status='ok' AND (level IS NULL OR level = ANY(%s))",
                (list(POOR_LEVELS),))
    poor = cur.fetchone()[0]
    conn.close()
    print(f'完成: ok={ok} fail={fail}')
    print('解析级别分布:', ', '.join(f'{l or "?"}×{n}' for l, n in levels))
    if poor:
        print(f'注意: {poor} 条只解析到市/区县级（会落在行政中心附近），建议在系统里修正这些地址后 --retry-fail 重跑')


if __name__ == '__main__':
    main()
