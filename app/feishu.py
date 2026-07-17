# -*- coding: utf-8 -*-
"""飞书网页登录（网页应用免登，authen/v1 旧版流程）。

流程：/feishu/login 跳转飞书免登授权页 → 用户同意 → 回调 /feishu/callback?code=&state=
     → 用 code 换 user_access_token（先取 app_access_token）→ 得用户信息 → 建立本站会话。

授权端点用的白名单 = 飞书后台「网页应用 → 重定向 URL」，回调地址需加入其中，例如：
     http://120.79.214.225:8061/feishu/callback
"""
import httpx

from .config import settings

AUTHORIZE_URL = 'https://open.feishu.cn/open-apis/authen/v1/index'
APP_TOKEN_URL = 'https://open.feishu.cn/open-apis/auth/v3/app_access_token/internal'
ACCESS_TOKEN_URL = 'https://open.feishu.cn/open-apis/authen/v1/access_token'


def enabled() -> bool:
    return bool(settings.feishu_app_id and settings.feishu_app_secret)


def authorize_url(redirect_uri: str, state: str) -> str:
    import urllib.parse
    q = urllib.parse.urlencode({
        'app_id': settings.feishu_app_id,      # 旧版用 app_id（非 client_id），不需要 response_type
        'redirect_uri': redirect_uri,
        'state': state,
    })
    return f'{AUTHORIZE_URL}?{q}'


def exchange_user_info(code: str, redirect_uri: str = '') -> dict:
    """用授权码换取用户信息，失败抛 RuntimeError。返回 data dict（含 name/open_id 等）。"""
    with httpx.Client(timeout=15) as cli:
        ar = cli.post(APP_TOKEN_URL, json={
            'app_id': settings.feishu_app_id,
            'app_secret': settings.feishu_app_secret,
        }).json()
        aat = ar.get('app_access_token')
        if not aat:
            raise RuntimeError(f"app_access_token 失败: code={ar.get('code')} {ar.get('msg')}")

        dr = cli.post(ACCESS_TOKEN_URL,
                      json={'grant_type': 'authorization_code', 'code': code},
                      headers={'Authorization': f'Bearer {aat}'}).json()
        if dr.get('code') != 0:
            raise RuntimeError(f"换取用户信息失败: {dr.get('msg')}")
        return dr.get('data') or {}
