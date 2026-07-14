# -*- coding: utf-8 -*-
"""登录会话：内存 token 表 + HttpOnly Cookie。重启服务需重新登录。"""
import time
import secrets
from typing import Optional

from fastapi import Request

from .config import settings

COOKIE_NAME = 'dbsess'
_sessions: dict[str, float] = {}   # token -> 过期时间戳


def verify_credentials(username: str, password: str) -> bool:
    return (secrets.compare_digest(username, settings.username)
            and secrets.compare_digest(password, settings.password))


def create_session() -> str:
    now = time.time()
    for k in [k for k, exp in _sessions.items() if exp < now]:   # 顺手清理过期会话
        _sessions.pop(k, None)
    token = secrets.token_hex(32)
    _sessions[token] = now + settings.session_ttl
    return token


def destroy_session(token: Optional[str]) -> None:
    if token:
        _sessions.pop(token, None)


def is_authed(request: Request) -> bool:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return False
    exp = _sessions.get(token)
    if not exp or exp < time.time():
        _sessions.pop(token, None)
        return False
    return True
