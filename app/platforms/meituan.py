# -*- coding: utf-8 -*-
"""美团闪购 API 客户端 —— 待接入。

TODO:
  - 申请美团闪购开放平台（歪马/牵牛花）应用，获取 appAuthToken
  - 门店：门店列表接口 → 对齐 meituan_store 表字段
  - 库存：retail/sku 库存查询接口（按门店分页）→ 对齐 meituan_store_inventory 表字段
"""
from typing import List

from .base import BasePlatformClient


class MeituanClient(BasePlatformClient):
    name = 'meituan'

    def __init__(self, app_id: str = '', app_secret: str = ''):
        self.app_id = app_id
        self.app_secret = app_secret

    def fetch_stores(self) -> List[dict]:
        raise NotImplementedError('美团门店 API 待接入')

    def fetch_inventory(self) -> List[dict]:
        raise NotImplementedError('美团库存 API 待接入')
