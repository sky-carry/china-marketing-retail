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
from .services import recon, excel, etl_runner, mapping

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


def _set_session_redirect(to: str = '/'):
    token = auth.create_session()
    resp = RedirectResponse(to, status_code=302)
    resp.set_cookie(auth.COOKIE_NAME, token, max_age=settings.session_ttl,
                    httponly=True, samesite='lax', path='/')
    return resp


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
        return _set_session_redirect('/')
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
    # base_url 形如 http://120.79.214.225:8061/，回调路径须与飞书后台白名单一致
    return str(request.base_url).rstrip('/') + '/feishu/callback'


@app.get('/feishu/login')
async def feishu_login(request: Request):
    if not feishu.enabled():
        return _login_page('未配置飞书登录')
    state = secrets.token_hex(8)
    resp = RedirectResponse(feishu.authorize_url(_redirect_uri(request), state), status_code=302)
    resp.set_cookie('fs_state', state, max_age=600, httponly=True, samesite='lax', path='/')
    return resp


@app.get('/feishu/callback')
async def feishu_callback(request: Request, code: str = '', state: str = ''):
    if not code or not state or state != request.cookies.get('fs_state'):
        return _login_page('飞书登录校验失败，请重试')
    try:
        info = await asyncio.to_thread(feishu.exchange_user_info, code, _redirect_uri(request))
    except Exception as e:      # noqa: BLE001
        return _login_page(f'飞书登录失败：{e}')
    resp = _set_session_redirect('/')
    resp.delete_cookie('fs_state', path='/')
    return resp


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


@app.get('/export.xlsx')
async def export_xlsx(request: Request):
    if not auth.is_authed(request):
        return _login_page()
    etag, data = await asyncio.to_thread(excel.get_xlsx)
    etag = 'W/' + etag
    if _not_modified(request, etag):
        return Response(status_code=304, headers={'ETag': etag})
    ts = time.strftime('%Y-%m-%d')
    fname = urllib.parse.quote(f'库存核对_{ts}.xlsx')
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
    if not etl_runner.start_etl(kind, filename=file.filename or '', size=len(content)):
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


@app.get('/api/mapping')
async def mapping_list(request: Request):
    if (r := _auth_json(request)):
        return r
    rows = await asyncio.to_thread(mapping.list_rows)
    return {'rows': rows, 'total': len(rows)}


async def _json_body(request: Request):
    try:
        return await request.json()
    except Exception:
        return None


@app.post('/api/mapping')
async def mapping_create(request: Request):
    if (r := _auth_json(request)):
        return r
    fields = await _json_body(request)
    if not isinstance(fields, dict):
        return JSONResponse({'error': '请求体不是有效的 UTF-8 JSON'}, status_code=400)
    try:
        new_id = await asyncio.to_thread(mapping.insert_row, fields)
    except ValueError as e:
        return JSONResponse({'error': str(e)}, status_code=400)
    return {'ok': True, 'id': new_id}


@app.put('/api/mapping/{row_id}')
async def mapping_update(request: Request, row_id: int):
    if (r := _auth_json(request)):
        return r
    fields = await _json_body(request)
    if not isinstance(fields, dict):
        return JSONResponse({'error': '请求体不是有效的 UTF-8 JSON'}, status_code=400)
    try:
        ok = await asyncio.to_thread(mapping.update_row, row_id, fields)
    except ValueError as e:
        return JSONResponse({'error': str(e)}, status_code=400)
    if not ok:
        return JSONResponse({'error': f'记录 {row_id} 不存在'}, status_code=404)
    return {'ok': True}


@app.delete('/api/mapping/{row_id}')
async def mapping_delete(request: Request, row_id: int):
    if (r := _auth_json(request)):
        return r
    ok = await asyncio.to_thread(mapping.delete_row, row_id)
    if not ok:
        return JSONResponse({'error': f'记录 {row_id} 不存在'}, status_code=404)
    return {'ok': True}


@app.get('/api/mapping/export')
async def mapping_export(request: Request):
    if not auth.is_authed(request):
        return _login_page()
    data = await asyncio.to_thread(mapping.export_xlsx)
    fname = urllib.parse.quote(f'门店映射_{time.strftime("%Y-%m-%d")}.xlsx')
    return Response(
        data,
        media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition': f"attachment; filename*=UTF-8''{fname}"})


@app.post('/api/mapping/import')
async def mapping_import(request: Request, file: UploadFile = File(...)):
    if (r := _auth_json(request)):
        return r
    if not (file.filename or '').lower().endswith(('.xlsx', '.xls')):
        return JSONResponse({'error': '只接受 .xlsx / .xls 文件'}, status_code=400)
    content = await file.read()
    if len(content) > MAX_UPLOAD:
        return JSONResponse({'error': '文件超过 100MB 上限'}, status_code=400)
    try:
        result = await asyncio.to_thread(mapping.import_xlsx, content)
    except ValueError as e:
        etl_runner.add_log('门店映射导入', file.filename or '', len(content),
                           'error', f'失败: {e}')
        return JSONResponse({'error': str(e)}, status_code=400)
    etl_runner.add_log('门店映射导入', file.filename or '', len(content),
                       'success', f"导入 {result['inserted']} 行")
    return {'ok': True, **result}


@app.get('/healthz', response_class=PlainTextResponse)
async def healthz():
    return 'ok'
