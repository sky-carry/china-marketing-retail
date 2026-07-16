# -*- coding: utf-8 -*-
"""Excel 导出：从核对视图现查现生成多 sheet 工作簿，按数据版本（ETag）缓存。"""
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


def build_xlsx() -> bytes:
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

        sheet('客户汇总',
              ['客户名称', '门店数', '明细行', '可核对行', '三方一致', '存在差异', '虚拟库存',
               '未上架', '合格率%', '京东一致率%', '美团一致率%'],
              """SELECT customer_name, store_cnt, row_cnt, checkable_cnt, match_cnt,
                        diff_cnt, virtual_cnt, unlisted_cnt,
                        round(100.0*match_cnt/NULLIF(checkable_cnt,0),1),
                        round(100.0*jd_match/NULLIF(jd_listed,0),1),
                        round(100.0*mt_match/NULLIF(mt_listed,0),1)
                 FROM v_recon_customer_summary ORDER BY diff_cnt DESC""")
        sheet('门店汇总',
              ['客户名称', '门店名称', '品数', '伯俊有', '京东上架', '美团上架', '三方一致',
               '京东差异', '美团差异', '负库存', '仅平台有', '虚拟库存'],
              """SELECT d.customer_name, s.store_name, s.product_cnt, s.bojun_cnt,
                        s.jd_listed, s.mt_listed, s.match_cnt, s.jd_mismatch, s.mt_mismatch,
                        s.negative_cnt, s.platform_only_cnt, s.virtual_stock_cnt
                 FROM v_recon_store_summary s
                 LEFT JOIN (SELECT store_name, max(customer_name) customer_name
                            FROM v_dim_store GROUP BY 1) d USING (store_name)
                 ORDER BY d.customer_name, s.jd_mismatch + s.mt_mismatch DESC""")
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
        sheet('网点保障汇总',
              ['客户名称', '货号', '品名', '线下伯俊总和', '启用网点数', '达标网点数',
               '最小网点库存', '最大缺口'],
              """SELECT customer_name, product_code, product_name, offline_qty,
                        outlet_cnt, ok_cnt, min_outlet_qty, worst_gap
                 FROM v_outlet_guard_summary
                 ORDER BY worst_gap, customer_name, product_code""")
        sheet('未匹配门店',
              ['门店名称', '伯俊店仓名(待修正)', '省份', '城市', '京东ID', '美团ID'],
              """SELECT store_name, bojun_warehouse, province, city, jd_id, meituan_id
                 FROM v_store_unmatched ORDER BY province, city, store_name""")
        sheet('未匹配商品',
              ['平台', '平台编码', '商品名称', '条码', '涉及门店', '库存合计'],
              """SELECT platform, platform_code, product_name, barcode, store_cnt, total_qty
                 FROM v_product_unmatched ORDER BY platform, store_cnt DESC""")

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


_lock = threading.Lock()
_cache = {'etag': '', 'bytes': b''}


def get_xlsx() -> Tuple[str, bytes]:
    """跟随 /api/data 的数据版本缓存：数据变了才重新生成。"""
    etag, _ = recon.get_data()
    with _lock:
        if _cache['etag'] == etag and _cache['bytes']:
            return etag, _cache['bytes']
    data = build_xlsx()
    with _lock:
        _cache.update(etag=etag, bytes=data)
    return etag, data
