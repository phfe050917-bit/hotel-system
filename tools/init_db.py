"""
数据库初始化工具。

用法：
    python tools/init_db.py            # 建库 + 建表 + 视图 + 触发器 + 基础数据
    python tools/init_db.py --schema   # 只执行 01_schema.sql（不动视图和触发器）

说明：
    脚本会重建 hotel_booking 库中的表结构（01_schema.sql 使用 DROP TABLE
    IF EXISTS），因此**会清空该库的既有数据**。原库如需保留请先备份：

        mysqldump -u root -p hotel_booking > backup.sql
"""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

# 允许从项目根目录直接运行本脚本
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _use_utf8_console() -> None:
    """
    让控制台按 UTF-8 输出。

    Windows 默认代码页是 GBK，直接 print 中文与 ✓/✗ 会抛 UnicodeEncodeError，
    甚至让初始化脚本在"最后一步报错"时崩掉。这里主动切换编码，
    并把无法编码的字符降级替换而不是抛异常。
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
from app.config import DB_CONFIG


def main() -> int:
    parser = argparse.ArgumentParser(description="初始化 hotel_booking 数据库")
    parser.add_argument("--schema", action="store_true",
                        help="只执行 01_schema.sql（建表），跳过视图/触发器/基础数据")
    parser.add_argument("--yes", "-y", action="store_true",
                        help="跳过确认提示（用于脚本化调用）")
    args = parser.parse_args()

    files = ("01_schema.sql",) if args.schema else DEFAULT_ORDER

    print("=" * 64)
    print(f"  目标数据库 : {DB_CONFIG['database']} @ {DB_CONFIG['host']}:{DB_CONFIG['port']}")
    print(f"  执行脚本   : {', '.join(files)}")
    print("=" * 64)

    if not args.yes:
        print("⚠  01_schema.sql 会重建所有数据表，库中现有数据将被清空。")
        answer = input("   确认继续？输入 yes 继续：").strip().lower()
        if answer != "yes":
            print("已取消。")
            return 1

    try:
        connection = pymysql.connect(
            host=DB_CONFIG["host"], port=int(DB_CONFIG["port"]),
            user=DB_CONFIG["user"], password=DB_CONFIG["password"],
            charset=DB_CONFIG.get("charset", "utf8mb4"), autocommit=False,
        )
    except pymysql.Error as exc:
        print(f"✗ 无法连接 MySQL：{exc}")
        print("  请确认 MySQL 服务已启动，并检查 config.local.py 或环境变量中的账号密码。")
        return 2

    try:
        bootstrap(connection, files)
    except (RuntimeError, FileNotFoundError) as exc:
        print(f"✗ 初始化失败：{exc}")
        return 3
    finally:
        connection.close()

    print("-" * 64)
    print("✓ 数据库初始化完成。")
    print("  演示账号：admin/admin123  reception/recep123  guest01/guest123")
    print("  可选：python tools/seed_demo_orders.py  生成订单类演示数据")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
