"""
程序主入口。

    python main.py

流程：
    1. 读取配置（环境变量 > config.local.py > 默认值）并连接数据库；
    2. 首次运行或缺少基础数据时，自动执行 sql/*.sql 建库并写入基础数据
       （数据库结构只存在于 sql/ 中，代码里不会再有第二份 DDL）；
    3. 打开登录窗口，按角色进入对应界面。

命令行参数：
    --init-db   强制重新执行 sql/*.sql（会重建数据表，谨慎使用）
    --no-init   跳过自动初始化检查
"""

from __future__ import annotations

import argparse
import io
import sys
import traceback


def _use_utf8_console() -> None:
    """
    让控制台按 UTF-8 输出。

    Windows 默认代码页是 GBK，直接 print 中文/符号会抛 UnicodeEncodeError，
    在最不该崩的地方（比如"数据库连接失败"的提示里）再崩一次。
    """
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is None:
            continue
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            setattr(sys, stream_name, io.TextIOWrapper(
                stream.buffer, encoding="utf-8", errors="replace"))


_use_utf8_console()

import pymysql

from app.bootstrap import DEFAULT_ORDER, bootstrap
from app.config import APP_TITLE, DB_CONFIG
from app.db import Database, DatabaseError


def _bootstrap_if_needed() -> None:
    """无参数启动时：确保数据库存在且基础数据已就绪。"""
    conn = pymysql.connect(
        host=DB_CONFIG["host"], port=int(DB_CONFIG["port"]),
        user=DB_CONFIG["user"], password=DB_CONFIG["password"],
        charset=DB_CONFIG.get("charset", "utf8mb4"), autocommit=False,
    )
    try:
        with conn.cursor() as cursor:
            cursor.execute("SHOW DATABASES LIKE %s", (DB_CONFIG["database"],))
            exists = cursor.fetchone() is not None
        if not exists:
            print(f"未检测到数据库 {DB_CONFIG['database']}，正在自动创建...")
            bootstrap(conn, DEFAULT_ORDER)
            print("✓ 数据库与基础数据已就绪")
        else:
            # 库已存在：只做一次轻量校验，避免每次启动都重建表
            conn.select_db(DB_CONFIG["database"])
            with conn.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM `user`")
                users = cursor.fetchone()[0]
                cursor.execute(
                    "SELECT COUNT(*) FROM information_schema.views "
                    "WHERE table_schema = %s", (DB_CONFIG["database"],))
                views = cursor.fetchone()[0]
            if users == 0 or views == 0:
                print("检测到数据库结构或基础数据不完整，正在补齐...")
                bootstrap(conn, DEFAULT_ORDER)
                print("✓ 数据库结构与基础数据已补齐")
            else:
                print(f"✓ 数据库 {DB_CONFIG['database']} 已就绪"
                      f"（{users} 个账号，{views} 个视图）")
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=APP_TITLE)
    parser.add_argument("--init-db", action="store_true",
                        help="强制重新执行 sql/*.sql（会重建数据表）")
    parser.add_argument("--no-init", action="store_true",
                        help="跳过启动时的数据库检查")
    args = parser.parse_args()

    print("=" * 62)
    print(f"  {APP_TITLE}")
    print(f"  数据库：{DB_CONFIG['database']} @ {DB_CONFIG['host']}:{DB_CONFIG['port']}")
    print("=" * 62)

    # 1. 数据库准备
    if args.init_db:
        try:
            conn = pymysql.connect(
                host=DB_CONFIG["host"], port=int(DB_CONFIG["port"]),
                user=DB_CONFIG["user"], password=DB_CONFIG["password"],
                charset=DB_CONFIG.get("charset", "utf8mb4"), autocommit=False)
        except pymysql.Error as exc:
            print(f"✗ 无法连接 MySQL：{exc}")
            return 2
        try:
            print("正在重新执行 sql/*.sql ...")
            bootstrap(conn, DEFAULT_ORDER)
        finally:
            conn.close()
    elif not args.no_init:
        try:
            _bootstrap_if_needed()
        except pymysql.Error as exc:
            print(f"\n✗ 数据库连接失败：{exc}")
            print("  请检查：1) MySQL 服务是否启动  2) 账号密码是否正确")
            print("  账号密码可在 config.local.py 或环境变量 HOTEL_DB_* 中设置。")
            return 2
        except RuntimeError as exc:
            print(f"\n✗ 数据库初始化失败：{exc}")
            return 3

    # 2. 建立连接
    try:
        db = Database()
    except DatabaseError as exc:
        print(f"\n✗ {exc}")
        return 2

    # 3. 启动界面
    try:
        print("正在启动登录界面...")
        from app.ui.login import LoginWindow
        LoginWindow(db).run()
    except Exception:                                   # noqa: BLE001
        traceback.print_exc()
        return 1
    finally:
        db.close()
        print("数据库连接已关闭，再见 👋")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
