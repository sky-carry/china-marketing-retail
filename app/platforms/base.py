# -*- coding: utf-8 -*-
from abc import ABC, abstractmethod
from typing import List


class BasePlatformClient(ABC):
    """平台客户端基类：门店与库存两类数据的拉取接口。

    实现方应处理各平台的鉴权（签名/refresh token）、翻页与限流重试，
    对外返回"与数据库表同构"的行（dict 列表），由 ETL 层负责入库。
    """

    name: str = ''

    @abstractmethod
    def fetch_stores(self) -> List[dict]:
        """拉取门店列表，字段对齐对应的门店表（如 jd_store / meituan_store）。"""

    @abstractmethod
    def fetch_inventory(self) -> List[dict]:
        """拉取门店级商品库存，字段对齐对应的库存表（如 jd_store_inventory）。"""
