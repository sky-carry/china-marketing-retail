# -*- coding: utf-8 -*-
"""门店地图看板数据服务：从 v_map_points 组装 /api/map 的 payload（带 ETag 缓存）。

payload 结构（与前端 dashboard.html 地图 Tab 约定）:
  meta:   { generated_at, total, located }
  points: [[类型idx, 名称, 客户/经销商, 省份, 城市, 地址, lng, lat, 京东SKU, 美团SKU], ...]
          类型idx: 0=专卖店 1=京东网点 2=美团网点；lng/lat 为 null 表示未定位。
数据变化（ETL/配置修改）经 recon.invalidate() 级联清此缓存；geocode.py 离线补点后按 TTL 自然刷新。
"""
import json
import time
import hashlib
import datetime
import threading
from typing import Tuple

import psycopg2

from ..config import settings
from ..db import get_conn
from . import recon

POINT_TYPES = ['专卖店', '京东网点', '美团网点']


def _num(v):
    return None if v is None else (float(v) if isinstance(v, float) else int(v))


def fetch_payload() -> dict:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT point_type, platform, name, customer_name, province, city, address,
                   lng, lat, jd_sku_cnt, mt_sku_cnt
            FROM v_map_points
            ORDER BY point_type, platform, customer_name, name""")
        points = []
        for r in cur.fetchall():
            tidx = 0 if r[0] == '专卖店' else (1 if r[1] == '京东' else 2)
            points.append([tidx, r[2], r[3], r[4], r[5], r[6],
                           _num(r[7]), _num(r[8]), _num(r[9]), _num(r[10])])
        try:
            cur.execute("SELECT max(loaded_at) FROM data_meta")
            loaded_at = cur.fetchone()[0]
        except psycopg2.Error:
            conn.rollback()
            loaded_at = None
    ts = (loaded_at or datetime.datetime.now()).strftime('%Y-%m-%d %H:%M')
    located = sum(1 for p in points if p[6] is not None)
    return {'meta': {'generated_at': ts, 'types': POINT_TYPES,
                     'total': len(points), 'located': located},
            'points': points}


# ---- 缓存层：与 recon 相同的 TTL + ETag 模式 ----
_lock = threading.Lock()
_cache = {'ts': 0.0, 'body': b'', 'etag': ''}


def invalidate() -> None:
    with _lock:
        _cache.update(ts=0.0, body=b'', etag='')


recon.on_invalidate(invalidate)   # 数据入库/配置修改后跟随失效


def get_data() -> Tuple[str, bytes]:
    now = time.time()
    with _lock:
        if _cache['body'] and now - _cache['ts'] <= settings.cache_ttl:
            return _cache['etag'], _cache['body']
    body = json.dumps(fetch_payload(), ensure_ascii=False,
                      separators=(',', ':')).encode('utf-8')
    etag = '"' + hashlib.md5(body).hexdigest()[:20] + '"'
    with _lock:
        _cache.update(ts=now, body=body, etag=etag)
    return etag, body
