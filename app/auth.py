# -*- coding: utf-8 -*-
"""登录会话：HMAC 签名令牌 + HttpOnly Cookie。

令牌自包含（过期时间 + 签名），不依赖服务器内存——服务重启/发版后已登录用户
不会掉线。签名密钥由登录密码派生：改密码即全员下线；登出靠清 Cookie。
"""
import time
import hmac
import base64
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


def _enc(s: str) -> str:
    return base64.urlsafe_b64encode((s or '').encode('utf-8')).decode().rstrip('=')


def _dec(s: str) -> str:
    try:
        return base64.urlsafe_b64decode(s + '=' * (-len(s) % 4)).decode('utf-8')
    except Exception:
        return ''


def verify_credentials(username: str, password: str) -> bool:
    return (secrets.compare_digest(username, settings.username)
            and secrets.compare_digest(password, settings.password))


def create_session(subject: str = '') -> str:
    """subject 记录"当前是谁"（飞书用 open_id，账号密码用用户名，dev 用 'dev'）。"""
    exp = int(time.time()) + settings.session_ttl
    nonce = secrets.token_hex(8)
    payload = f'{exp}.{nonce}.{_enc(subject)}'
    return f'{payload}.{_sign(payload)}'


def destroy_session(token: Optional[str]) -> None:
    """令牌无服务端状态，登出由路由层清 Cookie 完成。"""


def _parse(token: str):
    """校验令牌，返回 (ok, subject)；无效返回 (False, '')。"""
    parts = token.rsplit('.', 1)
    if len(parts) != 2:
        return False, ''
    payload, sig = parts
    if not hmac.compare_digest(_sign(payload), sig):
        return False, ''
    segs = payload.split('.')
    try:
        exp = int(segs[0])
    except (ValueError, IndexError):
        return False, ''
    if exp <= time.time():
        return False, ''
    subject = _dec(segs[2]) if len(segs) >= 3 else ''
    return True, subject


def is_authed(request: Request) -> bool:
    if settings.dev_no_auth:          # 本地开发免登录
        return True
    return _parse(request.cookies.get(COOKIE_NAME) or '')[0]


def session_subject(request: Request) -> str:
    """取当前登录主体（open_id / 用户名 / 'dev'）；未登录或 dev 免登录返回 ''/'dev'。"""
    if settings.dev_no_auth:
        return 'dev'
    return _parse(request.cookies.get(COOKIE_NAME) or '')[1]
