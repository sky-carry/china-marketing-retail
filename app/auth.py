# -*- coding: utf-8 -*-
"""登录会话：HMAC 签名令牌 + HttpOnly Cookie。

令牌自包含（过期时间 + 签名），不依赖服务器内存——服务重启/发版后已登录用户
不会掉线。签名密钥由登录密码派生：改密码即全员下线；登出靠清 Cookie。
"""
import time
import hmac
import hashlib
import secrets
from typing import Optional

from fastapi import Request

from .config import settings

COOKIE_NAME = 'dbsess'


def _key() -> bytes:
    return hashlib.sha256(f'dbsess-v1|{settings.password}'.encode('utf-8')).digest()


def _sign(payload: str) -> str:
    return hmac.new(_key(), payload.encode('utf-8'), 'sha256').hexdigest()


def verify_credentials(username: str, password: str) -> bool:
    return (secrets.compare_digest(username, settings.username)
            and secrets.compare_digest(password, settings.password))


def create_session() -> str:
    exp = int(time.time()) + settings.session_ttl
    nonce = secrets.token_hex(8)
    payload = f'{exp}.{nonce}'
    return f'{payload}.{_sign(payload)}'


def destroy_session(token: Optional[str]) -> None:
    """令牌无服务端状态，登出由路由层清 Cookie 完成。"""


def is_authed(request: Request) -> bool:
    token = request.cookies.get(COOKIE_NAME) or ''
    parts = token.rsplit('.', 1)
    if len(parts) != 2:
        return False
    payload, sig = parts
    if not hmac.compare_digest(_sign(payload), sig):
        return False
    try:
        exp = int(payload.split('.', 1)[0])
    except ValueError:
        return False
    return exp > time.time()
