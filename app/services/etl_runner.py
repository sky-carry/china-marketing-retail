# -*- coding: utf-8 -*-
"""ETL 后台运行器：接收看板上传的 Excel，保存到 excel/ 目录后异步执行入库。

同一时间只允许一个 ETL 任务；状态与日志保存在内存里供前端轮询。
"""
import os
import sys
import time
import shutil
import threading
import subprocess
from typing import Optional

from ..config import BASE_DIR
from . import recon

EXCEL_DIR = os.path.join(BASE_DIR, 'excel')

# kind -> (落盘文件名, load_excel --only 的数据源键, 展示名)
UPLOAD_KINDS = {
    'jd_inventory': ('京东门店库存-新.xlsx', 'jd_inventory', '京东门店库存'),
    'meituan_inventory': ('美团门店库存.xlsx', 'meituan_inventory', '美团门店库存'),
    'bojun': ('伯俊线下库存.xlsx', 'bojun', '伯俊线下库存（临时，API 接入后弃用）'),
}

_lock = threading.Lock()
_state = {
    'state': 'idle',          # idle | running | success | error
    'kind': '', 'label': '',
    'started_at': 0.0, 'finished_at': 0.0,
    'log': '',
}


def status() -> dict:
    with _lock:
        s = dict(_state)
    s['running_seconds'] = round(time.time() - s['started_at'], 1) \
        if s['state'] == 'running' else None
    return s


def save_upload(kind: str, content: bytes) -> str:
    """把上传内容写到 excel/ 目录的规范文件名（忽略用户原始文件名，杜绝路径注入）。"""
    fname = UPLOAD_KINDS[kind][0]
    os.makedirs(EXCEL_DIR, exist_ok=True)
    path = os.path.join(EXCEL_DIR, fname)
    tmp = path + '.uploading'
    with open(tmp, 'wb') as f:
        f.write(content)
    if os.path.exists(path):        # 留旧版备份，入库失败时回滚
        shutil.copy2(path, path + '.bak')
    # 原子替换，避免 ETL 读到半个文件。Windows 上目标可能被杀毒/索引/Excel
    # 短暂占用（WinError 5/32），带退避重试
    last_err = None
    for i in range(10):
        try:
            os.replace(tmp, path)
            return path
        except PermissionError as e:
            last_err = e
            time.sleep(0.5 * (i + 1))
    try:
        os.remove(tmp)
    except OSError:
        pass
    raise RuntimeError(
        f'目标文件被占用，无法写入 {fname}（可能被 Excel/WPS 打开，请关闭后重试）'
    ) from last_err


def start_etl(kind: str) -> bool:
    """启动后台 ETL；已有任务在跑时返回 False。"""
    with _lock:
        if _state['state'] == 'running':
            return False
        _state.update(state='running', kind=kind, label=UPLOAD_KINDS[kind][2],
                      started_at=time.time(), finished_at=0.0, log='')
    threading.Thread(target=_run, args=(kind,), daemon=True).start()
    return True


def _run(kind: str):
    only = UPLOAD_KINDS[kind][1]
    env = dict(os.environ, PYTHONIOENCODING='utf-8')
    try:
        proc = subprocess.Popen(
            [sys.executable, os.path.join(BASE_DIR, 'etl', 'load_excel.py'), '--only', only],
            cwd=BASE_DIR, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding='utf-8', errors='replace')
        lines = []
        for line in proc.stdout:
            lines.append(line.rstrip())
            with _lock:
                _state['log'] = '\n'.join(lines[-15:])
        code = proc.wait()
        ok = code == 0
    except Exception as e:      # noqa: BLE001 —— 后台线程必须兜住一切异常
        ok, lines = False, [f'启动 ETL 失败: {e}']
        with _lock:
            _state['log'] = '\n'.join(lines)
    if not ok:                  # 入库失败：把 excel/ 里的文件回滚成上一版，避免留下坏文件
        path = os.path.join(EXCEL_DIR, UPLOAD_KINDS[kind][0])
        bak = path + '.bak'
        if os.path.exists(bak):
            try:
                os.replace(bak, path)
                lines.append('已回滚 excel 目录中的源文件为上一版')
            except OSError as e:
                lines.append(f'源文件回滚失败: {e}')
            with _lock:
                _state['log'] = '\n'.join(lines[-15:])
    with _lock:
        _state.update(state='success' if ok else 'error', finished_at=time.time())
    if ok:
        recon.invalidate()      # 让 /api/data 立即出新数据
