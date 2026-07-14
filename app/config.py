# -*- coding: utf-8 -*-
"""集中配置：全部支持环境变量覆盖，默认值即本地开发配置。"""
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE_DIR = os.path.join(BASE_DIR, 'app', 'templates')

# 敏感配置放 .env（不入 git，模板见 .env.example）；已有的环境变量优先于 .env
_env_file = os.path.join(BASE_DIR, '.env')
if os.path.exists(_env_file):
    with open(_env_file, encoding='utf-8') as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith('#') and '=' in _line:
                _k, _, _v = _line.partition('=')
                os.environ.setdefault(_k.strip(), _v.strip())


class Settings:
    # 数据库
    pg_host: str = os.getenv('PGHOST', 'localhost')
    pg_port: int = int(os.getenv('PGPORT', '5432'))
    pg_user: str = os.getenv('PGUSER', 'postgres')
    pg_password: str = os.getenv('PGPASSWORD', 'postgres')
    pg_database: str = os.getenv('PGDATABASE', 'inventory_check')

    # 登录
    username: str = os.getenv('DASH_USER', 'admin')
    password: str = os.getenv('DASH_PASSWORD', 'change-me')
    session_ttl: int = int(os.getenv('DASH_SESSION_TTL', str(12 * 3600)))   # 秒

    # 数据缓存
    cache_ttl: int = int(os.getenv('DASH_CACHE_TTL', '60'))                 # 秒

    # 伯俊 ERP 标准接口
    bojun_base_url: str = os.getenv('BOJUN_BASE_URL', '')
    bojun_appkey: str = os.getenv('BOJUN_APPKEY', '')       # 登录用户名
    bojun_secret: str = os.getenv('BOJUN_SECRET', '')       # 签名密钥

    @property
    def pg_dsn(self) -> dict:
        return dict(host=self.pg_host, port=self.pg_port, user=self.pg_user,
                    password=self.pg_password, dbname=self.pg_database)


settings = Settings()
