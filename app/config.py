"""
全局配置。

原系统把 MySQL 的 root 密码硬编码在 main.py 里。现在改为：
  1. 环境变量优先（HOTEL_DB_HOST / HOTEL_DB_USER / HOTEL_DB_PASSWORD / ...）；
  2. 其次读取项目根目录的 config.local.py（该文件加入 .gitignore，不会被提交）；
  3. 最后回退到本地开发的默认值。

这样既保留了课设"双击就能跑"的便利，又不会把口令写进版本库。
"""

from __future__ import annotations

import os

DEFAULTS = {
    "host": "localhost",
    "port": 3306,
    "user": "root",
    "password": "123456",
    "database": "hotel_booking",
    "charset": "utf8mb4",
}

# 环境变量名 -> 配置键
_ENV_KEYS = {
    "HOTEL_DB_HOST": "host",
    "HOTEL_DB_PORT": "port",
    "HOTEL_DB_USER": "user",
    "HOTEL_DB_PASSWORD": "password",
    "HOTEL_DB_NAME": "database",
    "HOTEL_DB_CHARSET": "charset",
}


def _load_local_override() -> dict:
    """读取可选的 config.local.py 覆盖项。"""
    try:
        from config_local import DB_OVERRIDES  # type: ignore
        return dict(DB_OVERRIDES)
    except ImportError:
        return {}


def load_db_config() -> dict:
    """按"环境变量 > config.local.py > 默认值"的优先级组装数据库配置。"""
    config = dict(DEFAULTS)
    config.update(_load_local_override())

    for env_name, key in _ENV_KEYS.items():
        value = os.environ.get(env_name)
        if value:
            config[key] = int(value) if key == "port" else value

    return config


DB_CONFIG = load_db_config()

# 界面相关常量
APP_TITLE = "酒店服务预约管理系统"
WINDOW_SIZE = "1000x680"

# 分页/列表上限，避免一次渲染过多行拖慢 Tkinter
TABLE_MAX_ROWS = 500
