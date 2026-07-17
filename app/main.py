# -*- coding: utf-8 -*-
"""库存核对平台 · FastAPI 入口。

运行:  uvicorn app.main:app --host 0.0.0.0 --port 8061
路由:
  GET  /             看板页面（未登录返回登录页）
  POST /login        登录（表单 u/p）
  GET  /logout       退出
  GET  /api/data     核对数据 JSON（60s 缓存 + ETag + gzip）
  GET  /export.xlsx  Excel 导出（现查现生成，跟随数据缓存）
"""
import os
import time
import asyncio
import urllib.parse
from typing import Optional

from fastapi import FastAPI, Request, Form, Response, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse, JSONResponse
from starlette.middleware.gzip import GZipMiddleware

import secrets

from . import auth, feishu
from .config import settings, TEMPLATE_DIR
from .services import recon, excel, etl_runner, tables, users

MAX_UPLOAD = 100 * 1024 * 1024   # 单文件上限 100MB

app = FastAPI(title='库存核对平台', docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(GZipMiddleware, minimum_size=1024)


def _template(name: str) -> str:
    with open(os.path.join(TEMPLATE_DIR, name), encoding='utf-8') as f:
        return f.read()


def _login_page(err: str = '') -> HTMLResponse:
    feishu_btn = ('<div class="divider">或</div>'
                  '<a class="feishu" href="feishu/login">'
                  '<svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">'
                  '<path d="M4 5h13l-2.5 4H6.5L4 5zm0 6h11l-2.5 4H6.5L4 11zm0 6h9l-2.5 4H6.5L4 17z"/></svg>'
                  '飞书登录</a>') if feishu.enabled() else ''
    html = (_template('login.html')
            .replace('{ERR}', f'<div class="err">{err}</div>' if err else '')
            .replace('{FEISHU}', feishu_btn))
    return HTMLResponse(html, headers={'Cache-Control': 'no-store'})


def _set_session_redirect(to: str = '/', subject: str = ''):
    token = auth.create_session(subject)
    resp = RedirectResponse(to, status_code=302)
    resp.set_cookie(auth.COOKIE_NAME, token, max_age=settings.session_ttl,
                    httponly=True, samesite='lax', path='/')
    return resp


def _current_user_name(request: Request) -> str:
    """当前登录者显示名（操作记录用）：飞书查 users 表姓名；密码登录=用户名；dev='本地开发'。"""
    sub = auth.session_subject(request)
    if not sub:
        return ''
    if sub == 'dev':
        return '本地开发'
    if sub.startswith('ou_'):          # 飞书 open_id
        return users.display_name(sub)
    return sub                          # 账号密码登录：subject 就是用户名


def _is_admin(request: Request) -> bool:
    """管理员=用 SKG 账号密码登录（subject==DASH_USER）或本地开发；飞书用户默认非管理员，
    可在 users 表把 is_admin 置 true 提权。含 DB 查询，异步路由里请用 to_thread 调用。"""
    sub = auth.session_subject(request)
    if sub == 'dev':
        return True
    if not sub:
        return False
    if sub.startswith('ou_'):          # 飞书登录
        u = users.get_by_open_id(sub)
        return bool(u and u.get('is_admin'))
    return sub == settings.username    # 账号密码登录


def _not_modified(request: Request, etag: str):
    return request.headers.get('if-none-match') == etag


# ---------- 页面 ----------

@app.get('/', response_class=HTMLResponse)
@app.get('/index.html', response_class=HTMLResponse)
@app.get('/dashboard', response_class=HTMLResponse)
async def index(request: Request):
    if not auth.is_authed(request):
        return _login_page()
    return HTMLResponse(_template('dashboard.html'),
                        headers={'Cache-Control': 'no-cache'})


@app.post('/login')
async def login(request: Request, u: str = Form(''), p: str = Form('')):
    if auth.verify_credentials(u, p):
        return _set_session_redirect('/', subject=u)
    await asyncio.sleep(1)          # 减缓暴力尝试
    return _login_page('账号或密码不正确')


@app.get('/logout')
async def logout(request: Request):
    auth.destroy_session(request.cookies.get(auth.COOKIE_NAME))
    resp = RedirectResponse('/', status_code=302)
    resp.delete_cookie(auth.COOKIE_NAME, path='/')
    return resp


# ---------- 飞书网页登录 ----------

def _redirect_uri(request: Request) -> str:
    # 优先用配置的固定回调地址（必须与飞书白名单一致）；飞书客户端内打开时 request.base_url
    # 会变（Host/代理不同），动态生成会对不上白名单导致 20029。未配置时才回退动态（本地开发用）。
    if settings.feishu_redirect_uri:
        return settings.feishu_redirect_uri
    return str(request.base_url).rstrip('/') + '/api/feishu/callback'


@app.get('/feishu/login')
async def feishu_login(request: Request):
    if not feishu.enabled():
        return _login_page('未配置飞书登录')
    state = secrets.token_hex(8)
    resp = RedirectResponse(feishu.authorize_url(_redirect_uri(request), state), status_code=302)
    resp.set_cookie('fs_state', state, max_age=600, httponly=True, samesite='lax', path='/')
    return resp


@app.get('/api/feishu/callback')
async def feishu_callback(request: Request, code: str = '', state: str = ''):
    if not code or not state or state != request.cookies.get('fs_state'):
        return _login_page('飞书登录校验失败，请重试')
    try:
        info = await asyncio.to_thread(feishu.exchange_user_info, code, _redirect_uri(request))
    except Exception as e:      # noqa: BLE001
        return _login_page(f'飞书登录失败：{e}')
    user = await asyncio.to_thread(users.upsert_login, info)   # 落库/更新用户
    if user and not user.get('is_active'):
        return _login_page('该账号已被禁用，请联系管理员')
    resp = _set_session_redirect('/', subject=info.get('open_id') or info.get('name') or '')
    resp.delete_cookie('fs_state', path='/')
    return resp


@app.get('/api/me')
async def api_me(request: Request):
    if not auth.is_authed(request):
        return JSONResponse({'error': 'unauthorized'}, status_code=401)
    sub = auth.session_subject(request)
    user = None
    if sub and sub.startswith('ou_'):
        user = await asyncio.to_thread(users.get_by_open_id, sub)
    if not user:                       # 账号密码 / dev / 查不到
        user = {'name': _current_user_name(request), 'source': 'dev' if sub == 'dev' else 'password'}
    user['is_admin'] = await asyncio.to_thread(_is_admin, request)
    return {'ok': True, 'user': user}


# ---------- 用户管理（仅管理员：SKG 账号密码登录）----------

async def _require_admin(request: Request):
    """管理员门禁：未登录 401，非管理员 403，通过返回 None。"""
    if not auth.is_authed(request):
        return JSONResponse({'error': 'unauthorized'}, status_code=401)
    if not await asyncio.to_thread(_is_admin, request):
        return JSONResponse({'error': '需要管理员权限'}, status_code=403)
    return None


@app.get('/api/users')
async def api_users(request: Request):
    if (r := await _require_admin(request)):
        return r
    rows = await asyncio.to_thread(users.list_all)
    return {'ok': True, 'users': rows}


@app.post('/api/users/{open_id}/active')
async def api_user_active(request: Request, open_id: str):
    if (r := await _require_admin(request)):
        return r
    body = await _json_body(request)
    if not isinstance(body, dict) or 'active' not in body:
        return JSONResponse({'error': '缺少 active 参数'}, status_code=400)
    ok = await asyncio.to_thread(users.set_active, open_id, bool(body['active']))
    if not ok:
        return JSONResponse({'error': f'用户 {open_id} 不存在'}, status_code=404)
    return {'ok': True}


# ---------- 数据接口 ----------

@app.get('/api/data')
async def api_data(request: Request):
    if not auth.is_authed(request):
        return Response('{"error":"unauthorized"}', status_code=401,
                        media_type='application/json')
    etag, body = await asyncio.to_thread(recon.get_data)
    if _not_modified(request, etag):
        return Response(status_code=304, headers={'ETag': etag})
    return Response(body, media_type='application/json; charset=utf-8',
                    headers={'ETag': etag, 'Cache-Control': 'no-cache'})


_EXPORT_NAMES = {'recon': '客户门店核对', 'guard': '网点保障'}


@app.get('/export.xlsx')
async def export_xlsx(request: Request, kind: str = 'recon'):
    if not auth.is_authed(request):
        return _login_page()
    if kind not in _EXPORT_NAMES:
        kind = 'recon'
    etag, data = await asyncio.to_thread(excel.get_xlsx, kind)
    etag = 'W/' + etag
    if _not_modified(request, etag):
        return Response(status_code=304, headers={'ETag': etag})
    ts = time.strftime('%Y-%m-%d')
    fname = urllib.parse.quote(f'{_EXPORT_NAMES[kind]}_{ts}.xlsx')
    return Response(
        data,
        media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'ETag': etag, 'Cache-Control': 'no-cache',
                 'Content-Disposition': f"attachment; filename*=UTF-8''{fname}"})


# ---------- 数据上传（京东/美团 API 拿不到，每天用 Excel 更新） ----------

@app.post('/api/upload')
async def upload(request: Request, kind: str = Form(...), file: UploadFile = File(...)):
    if not auth.is_authed(request):
        return JSONResponse({'error': 'unauthorized'}, status_code=401)
    if kind not in etl_runner.UPLOAD_KINDS:
        return JSONResponse({'error': f'未知数据类型 {kind}'}, status_code=400)
    if not (file.filename or '').lower().endswith(('.xlsx', '.xls')):
        return JSONResponse({'error': '只接受 .xlsx / .xls 文件'}, status_code=400)
    content = await file.read()
    if len(content) > MAX_UPLOAD:
        return JSONResponse({'error': '文件超过 100MB 上限'}, status_code=400)
    if len(content) < 1000:
        return JSONResponse({'error': '文件内容异常（过小），请检查后重传'}, status_code=400)
    if etl_runner.status()['state'] == 'running':
        return JSONResponse({'error': '已有入库任务在执行，请稍候'}, status_code=409)
    try:
        await asyncio.to_thread(etl_runner.save_upload, kind, content)
    except RuntimeError as e:
        return JSONResponse({'error': str(e)}, status_code=409)
    if not etl_runner.start_etl(kind, filename=file.filename or '', size=len(content),
                                operator=_current_user_name(request)):
        return JSONResponse({'error': '已有入库任务在执行，请稍候'}, status_code=409)
    return {'ok': True, 'kind': kind, 'size': len(content)}


@app.get('/api/etl/status')
async def etl_status(request: Request):
    if not auth.is_authed(request):
        return JSONResponse({'error': 'unauthorized'}, status_code=401)
    return etl_runner.status()


@app.get('/api/outlet_guard')
async def outlet_guard_detail(request: Request, customer: str, product: str):
    if not auth.is_authed(request):
        return JSONResponse({'error': 'unauthorized'}, status_code=401)
    rows = await asyncio.to_thread(recon.fetch_outlet_detail, customer, product)
    return {'rows': rows}


@app.get('/api/upload/history')
async def upload_history(request: Request):
    if not auth.is_authed(request):
        return JSONResponse({'error': 'unauthorized'}, status_code=401)
    rows = await asyncio.to_thread(etl_runner.history)
    return {'rows': rows}


@app.get('/api/template/{kind}')
async def upload_template(request: Request, kind: str):
    if not auth.is_authed(request):
        return _login_page()
    if kind not in etl_runner.UPLOAD_KINDS:
        return JSONResponse({'error': f'未知数据类型 {kind}'}, status_code=404)
    data = await asyncio.to_thread(etl_runner.build_template, kind)
    label = etl_runner.UPLOAD_KINDS[kind][2].split('（')[0]
    fname = urllib.parse.quote(f'{label}-上传模板.xlsx')
    return Response(
        data,
        media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition': f"attachment; filename*=UTF-8''{fname}"})


# ---------- 门店映射管理（设置 → feishu_store_mapping） ----------

def _auth_json(request: Request) -> Optional[JSONResponse]:
    if not auth.is_authed(request):
        return JSONResponse({'error': 'unauthorized'}, status_code=401)
    return None


async def _json_body(request: Request):
    try:
        return await request.json()
    except Exception:
        return None


def _mgr(key: str):
    """按 key 取表管理器；未知 key 返回 None。"""
    return tables.REGISTRY.get(key)


@app.get('/api/table/{key}')
async def table_list(request: Request, key: str):
    if (r := _auth_json(request)):
        return r
    mgr = _mgr(key)
    if not mgr:
        return JSONResponse({'error': f'未知配置表 {key}'}, status_code=404)
    rows = await asyncio.to_thread(mgr.list_rows)
    return {'schema': mgr.schema(), 'rows': rows, 'total': len(rows)}


@app.post('/api/table/{key}')
async def table_create(request: Request, key: str):
    if (r := _auth_json(request)):
        return r
    mgr = _mgr(key)
    if not mgr:
        return JSONResponse({'error': f'未知配置表 {key}'}, status_code=404)
    fields = await _json_body(request)
    if not isinstance(fields, dict):
        return JSONResponse({'error': '请求体不是有效的 UTF-8 JSON'}, status_code=400)
    try:
        new_id = await asyncio.to_thread(mgr.insert_row, fields)
    except ValueError as e:
        return JSONResponse({'error': str(e)}, status_code=400)
    return {'ok': True, 'id': new_id}


@app.put('/api/table/{key}/{row_id}')
async def table_update(request: Request, key: str, row_id: int):
    if (r := _auth_json(request)):
        return r
    mgr = _mgr(key)
    if not mgr:
        return JSONResponse({'error': f'未知配置表 {key}'}, status_code=404)
    fields = await _json_body(request)
    if not isinstance(fields, dict):
        return JSONResponse({'error': '请求体不是有效的 UTF-8 JSON'}, status_code=400)
    try:
        ok = await asyncio.to_thread(mgr.update_row, row_id, fields)
    except ValueError as e:
        return JSONResponse({'error': str(e)}, status_code=400)
    if not ok:
        return JSONResponse({'error': f'记录 {row_id} 不存在'}, status_code=404)
    return {'ok': True}


@app.delete('/api/table/{key}/{row_id}')
async def table_delete(request: Request, key: str, row_id: int):
    if (r := _auth_json(request)):
        return r
    mgr = _mgr(key)
    if not mgr:
        return JSONResponse({'error': f'未知配置表 {key}'}, status_code=404)
    ok = await asyncio.to_thread(mgr.delete_row, row_id)
    if not ok:
        return JSONResponse({'error': f'记录 {row_id} 不存在'}, status_code=404)
    return {'ok': True}


@app.get('/api/table/{key}/export')
async def table_export(request: Request, key: str):
    if not auth.is_authed(request):
        return _login_page()
    mgr = _mgr(key)
    if not mgr:
        return JSONResponse({'error': f'未知配置表 {key}'}, status_code=404)
    data = await asyncio.to_thread(mgr.export_xlsx)
    fname = urllib.parse.quote(f'{mgr.title}_{time.strftime("%Y-%m-%d")}.xlsx')
    return Response(
        data,
        media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition': f"attachment; filename*=UTF-8''{fname}"})


@app.post('/api/table/{key}/import')
async def table_import(request: Request, key: str, file: UploadFile = File(...)):
    if (r := _auth_json(request)):
        return r
    mgr = _mgr(key)
    if not mgr:
        return JSONResponse({'error': f'未知配置表 {key}'}, status_code=404)
    if not (file.filename or '').lower().endswith(('.xlsx', '.xls')):
        return JSONResponse({'error': '只接受 .xlsx / .xls 文件'}, status_code=400)
    content = await file.read()
    if len(content) > MAX_UPLOAD:
        return JSONResponse({'error': '文件超过 100MB 上限'}, status_code=400)
    operator = _current_user_name(request)
    try:
        result = await asyncio.to_thread(mgr.import_xlsx, content)
    except ValueError as e:
        etl_runner.add_log(f'{mgr.title}导入', file.filename or '', len(content),
                           'error', f'失败: {e}', operator=operator)
        return JSONResponse({'error': str(e)}, status_code=400)
    etl_runner.add_log(f'{mgr.title}导入', file.filename or '', len(content),
                       'success', f"导入 {result['inserted']} 行", operator=operator)
    return {'ok': True, **result}


@app.get('/healthz', response_class=PlainTextResponse)
async def healthz():
    return 'ok'
