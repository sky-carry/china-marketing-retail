# -*- coding: utf-8 -*-
"""核对数据服务：从核对视图组装看板 /api/data 的 payload，并做带 ETag 的时效缓存。

payload 结构（与前端 dashboard.html 约定）:
  meta:       { generated_at, flags, inactive }
  detail:     [[客户, 门店, 货号, 品名, 伯俊, 京东, 美团, 京差, 美差, flag_idx], ...]
  unStores:   门店未匹配清单
  unProducts: 商品未匹配清单
"""
import json
import time
import gzip
import hashlib
import datetime
import threading
from typing import Optional, Tuple

import psycopg2

from ..config import settings
from ..db import get_conn

FLAGS = ['存在差异', '伯俊负库存', '仅平台有货(伯俊无此品)', '平台均未上架', '平台虚拟库存', '三方一致']
FLAG_IDX = {f: i for i, f in enumerate(FLAGS)}


def _int(v):
    return None if v is None else int(v)


def fetch_payload() -> dict:
    with get_conn() as conn:
        cur = conn.cursor()

        cur.execute("""
            SELECT customer_name, store_name, product_code, product_name,
                   bojun_qty, jd_qty, mt_qty, jd_diff, mt_diff, flag
            FROM v_recon_detail
            ORDER BY customer_name, store_name, product_code""")
        detail = [[r[0], r[1], r[2], r[3], _int(r[4]), _int(r[5]), _int(r[6]),
                   _int(r[7]), _int(r[8]), FLAG_IDX[r[9]]] for r in cur.fetchall()]

        cur.execute("""
            SELECT store_name, bojun_warehouse, province, city, jd_id, meituan_id
            FROM v_store_unmatched ORDER BY province, city, store_name""")
        un_stores = [list(r) for r in cur.fetchall()]

        cur.execute("""
            SELECT platform, platform_code, product_name, barcode, store_cnt, total_qty
            FROM v_product_unmatched ORDER BY platform, store_cnt DESC""")
        un_products = [[r[0], r[1], r[2], r[3], int(r[4]), _int(r[5])] for r in cur.fetchall()]

        cur.execute("SELECT count(*) FROM v_dim_store WHERE NOT is_active")
        inactive = cur.fetchone()[0]

        try:
            cur.execute("SELECT max(loaded_at) FROM data_meta")
            loaded_at = cur.fetchone()[0]
        except psycopg2.Error:
            conn.rollback()
            loaded_at = None

    ts = (loaded_at or datetime.datetime.now()).strftime('%Y-%m-%d %H:%M')
    return {'meta': {'generated_at': ts, 'flags': FLAGS, 'inactive': inactive},
            'detail': detail, 'unStores': un_stores, 'unProducts': un_products}


# ---- 缓存层：payload 序列化结果 + ETag，跟随 cache_ttl 失效 ----
_lock = threading.Lock()
_cache = {'ts': 0.0, 'body': b'', 'etag': ''}


def invalidate() -> None:
    """数据入库后调用，使缓存立即失效。"""
    with _lock:
        _cache.update(ts=0.0, body=b'', etag='')


def get_data() -> Tuple[str, bytes]:
    """返回 (etag, json_bytes)。60 秒内命中缓存，避免每次请求都全量查库。"""
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
