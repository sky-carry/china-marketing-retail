# -*- coding: utf-8 -*-
"""飞书网页登录（OAuth 授权码流程）。

流程：/feishu/login 跳转飞书授权页 → 用户同意 → 回调 /feishu/callback?code=&state=
     → 用 code 换 user_access_token → 拉 user_info → 建立本站会话。

需在飞书开发者后台「安全设置 → 重定向 URL」加入回调地址，例如：
     http://120.79.214.225:8061/feishu/callback
"""
import urllib.parse
from typing import Optional

import httpx

from .config import settings

AUTHORIZE_URL = 'https://accounts.feishu.cn/open-apis/authen/v1/authorize'
TOKEN_URL = 'https://open.feishu.cn/open-apis/authen/v2/oauth/token'
USERINFO_URL = 'https://open.feishu.cn/open-apis/authen/v1/user_info'


def enabled() -> bool:
    return bool(settings.feishu_app_id and settings.feishu_app_secret)


def authorize_url(redirect_uri: str, state: str) -> str:
    q = urllib.parse.urlencode({
        'client_id': settings.feishu_app_id,
        'redirect_uri': redirect_uri,
        'state': state,
    })
    return f'{AUTHORIZE_URL}?{q}'


def exchange_user_info(code: str, redirect_uri: str) -> dict:
    """用授权码换取用户信息，失败抛 RuntimeError。返回 user_info dict（name/open_id 等）。"""
    with httpx.Client(timeout=15) as cli:
        tr = cli.post(TOKEN_URL, json={
            'grant_type': 'authorization_code',
            'client_id': settings.feishu_app_id,
            'client_secret': settings.feishu_app_secret,
            'code': code,
            'redirect_uri': redirect_uri,
        })
        td = tr.json()
        token = td.get('access_token')
        if not token:
            raise RuntimeError(f"换取 token 失败: {td.get('error_description') or td.get('error') or td}")

        ur = cli.get(USERINFO_URL, headers={'Authorization': f'Bearer {token}'})
        ud = ur.json()
        if ud.get('code') != 0:
            raise RuntimeError(f"获取用户信息失败: {ud.get('msg')}")
        return ud.get('data') or {}
