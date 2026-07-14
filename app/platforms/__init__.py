# -*- coding: utf-8 -*-
"""平台 API 客户端：后续用各平台开放接口直接拉门店/库存数据，替代 Excel 导入。

约定：每个平台一个模块，实现 BasePlatformClient 的两个方法，
返回与现有数据库表同构的行列表，ETL 层即可无缝切换数据来源（Excel → API）。
"""
from .base import BasePlatformClient

__all__ = ['BasePlatformClient']
