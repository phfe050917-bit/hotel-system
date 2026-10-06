"""
本地数据库配置覆盖文件（模板）。

用法：把本文件复制为 config.local.py 并改成你自己的密码。
config.local.py 不随版本库提交，避免把口令写进代码。

优先级：环境变量 > config.local.py > app/config.py 里的默认值

环境变量方式（推荐，无需创建文件）：
    set HOTEL_DB_PASSWORD=你的密码
    set HOTEL_DB_USER=root
    set HOTEL_DB_HOST=localhost
    set HOTEL_DB_PORT=3306
    set HOTEL_DB_NAME=hotel_booking
"""

DB_OVERRIDES = {
    "host": "localhost",
    "port": 3306,
    "user": "root",
    "password": "123456",          # ← 改成你的 MySQL 密码
    "database": "hotel_booking",
}
