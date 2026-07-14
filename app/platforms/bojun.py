# -*- coding: utf-8 -*-
"""伯俊 ERP 标准接口客户端。

文档: https://s.apifox.cn/c4659e5d-71a8-42e0-aa37-aea13f79be7c
鉴权: 请求头携带 appkey/method/timestamp/format/uniqstr/sign，
      sign = MD5( secret + "appkey=..&format=..&method=..&timestamp=..&uniqstr=.." + secret ) 的 32 位大写
      （五个系统参数按字母序拼接；算法已用文档示例校验通过）

已接入:
  storage_query()   库存查询 /bos/standard/storage/storage.query（分页）
  fetch_inventory() 拉全量库存，返回与 bojun_offline_inventory 表对齐的行

凭证通过环境变量 BOJUN_APPKEY / BOJUN_SECRET 提供（见 app/config.py）。
"""
import time
import uuid
import hashlib
from typing import List, Optional

import httpx

from ..config import settings
from .base import BasePlatformClient

STORAGE_QUERY_PATH = '/bos/standard/storage/storage.query'
# 签名头里的 method：文档示例用的是 "/product/product.create" 形态（模块/接口名，带前导斜杠）。
# 若实际验签失败（错误码 10103），依次尝试 METHOD_CANDIDATES 里的其它形态。
METHOD_CANDIDATES = ('/storage/storage.query',
                     'bos/standard/storage/storage.query',
                     STORAGE_QUERY_PATH)


class BojunError(RuntimeError):
    def __init__(self, code, msg):
        super().__init__(f'伯俊接口错误 code={code}: {msg}')
        self.code = code


class BojunClient(BasePlatformClient):
    name = 'bojun'

    def __init__(self, base_url: str = '', appkey: str = '', secret: str = '',
                 method_style: int = 0, timeout: float = 60.0):
        self.base_url = (base_url or settings.bojun_base_url).rstrip('/')
        self.appkey = appkey or settings.bojun_appkey
        self.secret = secret or settings.bojun_secret
        self.method = METHOD_CANDIDATES[method_style]
        self.timeout = timeout

    # ---- 鉴权 ----
    def _headers(self, method: str) -> dict:
        ts = str(int(time.time()))                     # 十位时间戳
        uniq = str(uuid.uuid4())
        params = {'appkey': self.appkey, 'format': 'json',
                  'method': method, 'timestamp': ts, 'uniqstr': uniq}
        plain = '&'.join(f'{k}={params[k]}' for k in sorted(params))
        sign = hashlib.md5((self.secret + plain + self.secret).encode('utf-8')) \
                      .hexdigest().upper()
        return {'Content-Type': 'application/json', 'appkey': self.appkey,
                'method': method, 'timestamp': ts, 'format': 'json',
                'uniqstr': uniq, 'sign': sign}

    def _post(self, path: str, method: str, body: dict) -> dict:
        resp = httpx.post(self.base_url + path, json=body,
                          headers=self._headers(method), timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        if data.get('code') != 200:
            raise BojunError(data.get('code'), data.get('msg'))
        return data.get('data') or {}

    # ---- 库存查询 ----
    def storage_query(self, page: int = 1, page_size: int = 1000,
                      store_name: str = '', product_code: str = '',
                      barcode: str = '', start_time: str = '',
                      end_time: str = '') -> dict:
        """单页库存查询，返回 data 对象（current/pageSize/total/totalPage/records）。"""
        body = {'mProductName': product_code, 'mProductaliasNo': barcode,
                'cStoreName': store_name, 'current': page, 'pageSize': page_size,
                'startTime': start_time, 'endTime': end_time}
        return self._post(STORAGE_QUERY_PATH, self.method, body)

    def fetch_inventory(self, store_name: str = '',
                        page_size: int = 1000,
                        max_pages: Optional[int] = None) -> List[dict]:
        """翻页拉取库存，返回与 bojun_offline_inventory 表列对齐的 dict 列表。"""
        rows, page = [], 1
        while True:
            data = self.storage_query(page=page, page_size=page_size,
                                      store_name=store_name)
            records = data.get('records') or []
            for r in records:
                # 实际返回字段为 cstoreCode/mproductName 这种小写前缀形态，与文档的
                # cStoreCode/mProductName 大小写不一致，两种都兼容
                rows.append({
                    'store_code': r.get('cstoreCode') or r.get('cStoreCode'),
                    'store_warehouse': r.get('cstoreName') or r.get('cStoreName'),
                    'product_code': r.get('mproductName') or r.get('mProductName'),      # 款号
                    'barcode': r.get('mproductaliasNo') or r.get('mProductaliasNo'),     # 条码
                    'stock_qty': _num(r.get('qty')),
                    'unit_on_order': _num(r.get('qtypreout')),
                    'in_transit_qty': _num(r.get('qtyprein')),
                    'frozen_qty': _num(r.get('qtyFreeze')),
                    'oms_frozen_qty': _num(r.get('qtyOms')),
                    'expected_qty': _num(r.get('qtyvalid')),
                    'reorder_allocatable': _num(r.get('qtyconsign')),
                    'allocatable': _num(r.get('qtycan')),
                })
            total_page = int(data.get('totalPage') or 0)
            if not records or page >= total_page:
                break
            page += 1
            if max_pages and page > max_pages:
                break
        return rows

    def fetch_stores(self) -> List[dict]:
        raise NotImplementedError('伯俊侧无独立门店接口，店仓信息随库存记录返回')


def _num(v):
    """接口里数量字段有的是字符串有的是整数，统一转 int；空/非法返回 None。"""
    if v is None or v == '':
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None
