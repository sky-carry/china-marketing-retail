# -*- coding: utf-8 -*-
"""数据库访问：轻量连接工厂（查询频率低，无需连接池；要上量时换 psycopg_pool）。"""
from contextlib import contextmanager

import psycopg2

from .config import settings


@contextmanager
def get_conn():
    conn = psycopg2.connect(**settings.pg_dsn)
    try:
        yield conn
    finally:
        conn.close()


def query(sql: str, params=None) -> list:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        return cur.fetchall()
