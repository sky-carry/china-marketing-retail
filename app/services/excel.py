# -*- coding: utf-8 -*-
"""Excel 导出：从核对视图现查现生成工作簿，按数据版本（ETag）缓存。

两个独立导出，各对应看板的一个 Tab：
  kind='recon' 客户/门店核对：客户汇总 + 门店汇总 + 核对明细 + 未匹配门店 + 未匹配商品
  kind='guard' 网点保障：网点保障汇总 + 网点保障明细
"""
import io
import threading
from typing import Tuple

from openpyxl import Workbook

from ..db import get_conn
from . import recon


def _maintain_rate(platform, bojun):
    """维护率：平台 ≥ 伯俊 → 100；否则 平台/伯俊×100；无可比基数 → None"""
    if platform is None or bojun is None:
        return None
    platform, bojun = float(platform), float(bojun)
    if platform >= bojun:
        return 100.0
    if bojun > 0:
        return round(100.0 * platform / bojun, 1)
    return None


# 客户/门店汇总的聚合列，口径与看板树表完全一致：
#   差异 = Σ(平台−伯俊)，仅累计伯俊有记录、且非「平台虚拟库存」的行
#   维护率 = LEAST(100, Σmin(平台,伯俊) ÷ Σ伯俊)，仅伯俊>0 且平台已上翻的行
_AGG_COLS = """
  COALESCE(sum(jd_diff) FILTER (WHERE bojun_qty IS NOT NULL AND flag <> '平台虚拟库存'), 0) AS jd_diff,
  LEAST(100, round(100.0 * sum(LEAST(jd_qty, bojun_qty)) FILTER (WHERE bojun_qty > 0 AND jd_qty IS NOT NULL)
        / NULLIF(sum(bojun_qty) FILTER (WHERE bojun_qty > 0 AND jd_qty IS NOT NULL), 0), 1)) AS jd_rate,
  COALESCE(sum(mt_diff) FILTER (WHERE bojun_qty IS NOT NULL AND flag <> '平台虚拟库存'), 0) AS mt_diff,
  LEAST(100, round(100.0 * sum(LEAST(mt_qty, bojun_qty)) FILTER (WHERE bojun_qty > 0 AND mt_qty IS NOT NULL)
        / NULLIF(sum(bojun_qty) FILTER (WHERE bojun_qty > 0 AND mt_qty IS NOT NULL), 0), 1)) AS mt_rate"""


def _build_recon(sheet):
    """客户/门店核对相关 sheet（与「客户/门店核对」Tab 一致）。"""
    sheet('客户汇总',
          ['客户名称', '门店数', '京东差异', '京东维护率%', '美团差异', '美团维护率%'],
          f"""SELECT customer_name, store_cnt, jd_diff, jd_rate, mt_diff, mt_rate FROM (
                SELECT customer_name, count(DISTINCT store_name) AS store_cnt,{_AGG_COLS}
                FROM v_recon_detail GROUP BY customer_name
              ) t ORDER BY abs(jd_diff) + abs(mt_diff) DESC""")
    sheet('门店汇总',
          ['客户名称', '门店名称', '京东差异', '京东维护率%', '美团差异', '美团维护率%'],
          f"""SELECT customer_name, store_name, jd_diff, jd_rate, mt_diff, mt_rate FROM (
                SELECT customer_name, store_name,{_AGG_COLS}
                FROM v_recon_detail GROUP BY customer_name, store_name
              ) t ORDER BY customer_name, abs(jd_diff) + abs(mt_diff) DESC""")
    sheet('核对明细',
          ['客户名称', '门店名称', '货号', '品名', '伯俊库存', '京东库存', '美团库存',
           '京东差异', '京东维护率%', '美团差异', '美团维护率%', '状态'],
          """SELECT customer_name, store_name, product_code, product_name,
                    bojun_qty, jd_qty, mt_qty, jd_diff, mt_diff, flag
             FROM v_recon_detail ORDER BY customer_name, store_name, product_code""",
          transform=lambda rows: ([r[0], r[1], r[2], r[3], r[4], r[5], r[6],
                                   r[7], _maintain_rate(r[5], r[4]),
                                   r[8], _maintain_rate(r[6], r[4]), r[9]]
                                  for r in rows))
    sheet('未匹配门店',
          ['门店名称', '伯俊店仓名(待修正)', '省份', '城市', '京东ID', '美团ID'],
          """SELECT store_name, bojun_warehouse, province, city, jd_id, meituan_id
             FROM v_store_unmatched ORDER BY province, city, store_name""")
    sheet('未匹配商品',
          ['平台', '平台编码', '商品名称', '条码', '涉及门店', '库存合计'],
          """SELECT platform, platform_code, product_name, barcode, store_cnt, total_qty
             FROM v_product_unmatched ORDER BY platform, store_cnt DESC""")


def _build_guard(sheet):
    """网点保障相关 sheet（与「网点保障」Tab 一致）。"""
    sheet('网点保障汇总',
          ['客户名称', '货号', '品名', '线下伯俊总和', '网点数', '达标网点数',
           '京东网点', '京东达标', '美团网点', '美团达标', '最小网点库存', '最大缺口'],
          """SELECT customer_name, product_code, product_name, offline_qty,
                    outlet_cnt, ok_cnt, jd_cnt, jd_ok, mt_cnt, mt_ok,
                    min_outlet_qty, worst_gap
             FROM v_outlet_guard_summary
             ORDER BY worst_gap, customer_name, product_code""")
    sheet('网点保障明细',
          ['平台', '客户名称', '货号', '品名', '线下总和', '网点名称', '门店编号',
           '平台库存', '缺口', '状态'],
          """SELECT platform, customer_name, product_code, product_name, offline_qty,
                    outlet_name, outlet_code, outlet_qty, gap,
                    CASE WHEN is_ok THEN '达标' ELSE '不足' END
             FROM v_outlet_guard
             ORDER BY customer_name, product_code, platform, COALESCE(outlet_qty, -1)""")


_BUILDERS = {'recon': _build_recon, 'guard': _build_guard}


def build_xlsx(kind: str = 'recon') -> bytes:
    wb = Workbook(write_only=True)
    with get_conn() as conn:
        cur = conn.cursor()

        def sheet(name, headers, sql, transform=None):
            cur.execute(sql)
            rows = cur.fetchall()
            ws = wb.create_sheet(name)
            ws.append(headers)
            for r in (transform(rows) if transform else rows):
                ws.append(list(r))

        _BUILDERS.get(kind, _build_recon)(sheet)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


_lock = threading.Lock()
_cache = {}   # kind -> {'etag', 'bytes'}


def get_xlsx(kind: str = 'recon') -> Tuple[str, bytes]:
    """跟随 /api/data 的数据版本缓存：数据变了才重新生成。每个 kind 独立缓存。"""
    if kind not in _BUILDERS:
        kind = 'recon'
    etag, _ = recon.get_data()
    etag = f'{kind}-{etag}'
    with _lock:
        c = _cache.get(kind)
        if c and c['etag'] == etag and c['bytes']:
            return etag, c['bytes']
    data = build_xlsx(kind)
    with _lock:
        _cache[kind] = {'etag': etag, 'bytes': data}
    return etag, data
