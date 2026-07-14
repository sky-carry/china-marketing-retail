# -*- coding: utf-8 -*-
"""京东秒送（到家/小时购）API 客户端 —— 待接入。

TODO:
  - 申请京东到家开放平台应用，获取 app_key / app_secret（配置进 app/config.py）
  - 门店：POST /djapi/... 门店列表接口 → 对齐 jd_store 表字段
  - 库存：商品库存查询接口（按门店分页）→ 对齐 jd_store_inventory 表字段
  - 签名规则与 token 刷新封装在本模块内
"""
from typing import List

from .base import BasePlatformClient


class JDClient(BasePlatformClient):
    name = 'jd'

    def __init__(self, app_key: str = '', app_secret: str = ''):
        self.app_key = app_key
        self.app_secret = app_secret

    def fetch_stores(self) -> List[dict]:
        raise NotImplementedError('京东门店 API 待接入')

    def fetch_inventory(self) -> List[dict]:
        raise NotImplementedError('京东库存 API 待接入')
