"""
生成客房订单、团体单与支付流水的演示数据。

用法：python tools/seed_demo_orders.py

设计要点：
  · 订单**不写进 SQL 脚本**，而是通过 app/service.py 创建 —— 这样演示数据
    一定会走过触发器、状态机、金额汇总与事务校验，保证数据自洽；
  · 只生成客房订单（单号 RM 前缀）、结账单（JS 前缀）与支付流水（PY 前缀），
    不再涉及餐饮 / 健身 / SPA / 洗衣等已删除的业务线；
  · 包含一段**团体演示**（3 间房 → 整团入住 → 一张结账单结清），
    对应题目要求 (1) 的"团体登记和团体结账"；
  · 幂等：先用固定前缀检测是否已生成，已存在则跳过（可用 --force 强制重建）；
  · 覆盖各种状态（待入住 / 在住 / 已退房 / 已取消 / 待收款 / 已支付 / 已评价 /
    团体已结账），便于答辩时演示各功能；
  · 所有日期基于"今天"计算，任何时候运行都能看到合理的今日数据。
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

for _stream in ("stdout", "stderr"):
    _s = getattr(sys, _stream, None)
    if _s is not None:
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

from app import service
from app.db import Database, DatabaseError
from app.service import BusinessError

TODAY = date.today()


def _log(message: str) -> None:
    print(f"  {message}")


def _try(description: str, fn, *args, **kwargs):
    """执行一步；失败时打印原因但不中断整体流程。"""
    try:
        result = fn(*args, **kwargs)
        _log(f"✓ {description}")
        return result
    except (BusinessError, DatabaseError) as exc:
        _log(f"– 跳过 {description}：{exc}")
        return None


def seed(db: Database) -> None:
    guest_id = db.query_value("SELECT user_id FROM `user` WHERE username = 'guest01'", None, 0)
    if not guest_id:
        print("✗ 未找到演示账号 guest01，请先执行 python tools/init_db.py")
        return

    # ---------------------------------------------------------------
    # 1. 客房订单：覆盖 待入住 / 在住 / 已退房 / 已取消 / 已支付 / 未支付
    # ---------------------------------------------------------------
    print("\n[1/3] 客房订单")

    # 在住：昨天入住，后天离店（allow_past 供演示/前台查询已入住房间）
    rooms = service.search_available_rooms(db, TODAY - timedelta(days=1),
                                           TODAY + timedelta(days=2),
                                           allow_past=True)
    if rooms:
        order = _try("创建在住订单（101 类房型）", service.create_room_order, db,
                     user_id=guest_id, room_id=rooms[0]["room_id"],
                     check_in=TODAY - timedelta(days=1),
                     check_out=TODAY + timedelta(days=2),
                     guest_name="张三", guest_phone="13800000003")
        if order:
            _try("  办理入住（房间转为在住，由触发器联动）",
                 service.advance_order_status, db, "room", order["order_id"], "checked_in")
            _try("  登记押金/房费收款",
                 service.pay_order, db, order_type="room", order_id=order["order_id"],
                 user_id=guest_id, method="card")

    # 已退房：前 5 天入住，前 2 天离店
    rooms = service.search_available_rooms(db, TODAY - timedelta(days=5),
                                           TODAY - timedelta(days=2),
                                           allow_past=True)
    if rooms:
        order = _try("创建已退房订单", service.create_room_order, db,
                     user_id=guest_id, room_id=rooms[0]["room_id"],
                     check_in=TODAY - timedelta(days=5),
                     check_out=TODAY - timedelta(days=2), guest_name="张三")
        if order:
            _try("  收款", service.pay_order, db, order_type="room",
                 order_id=order["order_id"], user_id=guest_id, method="wechat")
            _try("  办理入住", service.advance_order_status, db, "room",
                 order["order_id"], "checked_in")
            _try("  办理退房（房间转为打扫中）", service.advance_order_status, db,
                 "room", order["order_id"], "checked_out")
            _try("  提交评价", service.submit_review, db, user_id=guest_id,
                 order_id=order["order_id"], order_type="room", rating=5,
                 content="房间干净整洁，前台服务很热情，下次还来。")

    # 今日到店（待入住）：让前台的「入住/退房」工作台有内容可操作
    todays_rooms = service.search_available_rooms(db, TODAY, TODAY + timedelta(days=1))
    if todays_rooms:
        _try("创建今日到店订单（待入住，可在前台办理入住）",
             service.create_room_order, db, user_id=guest_id,
             room_id=todays_rooms[0]["room_id"], check_in=TODAY,
             check_out=TODAY + timedelta(days=1), guest_name="张三",
             guest_phone="13800000003")

    # 待入住：3 天后
    rooms = service.search_available_rooms(db, TODAY + timedelta(days=3),
                                           TODAY + timedelta(days=5))
    if rooms:
        _try("创建待入住订单（未付款，用于演示收款）",
             service.create_room_order, db, user_id=guest_id,
             room_id=rooms[0]["room_id"], check_in=TODAY + timedelta(days=3),
             check_out=TODAY + timedelta(days=5), guest_name="张三")

    # 已取消
    rooms = service.search_available_rooms(db, TODAY + timedelta(days=10),
                                           TODAY + timedelta(days=12))
    if rooms:
        order = _try("创建已取消订单", service.create_room_order, db,
                     user_id=guest_id, room_id=rooms[0]["room_id"],
                     check_in=TODAY + timedelta(days=10),
                     check_out=TODAY + timedelta(days=12), guest_name="张三")
        if order:
            _try("  取消订单", service.cancel_order, db, "room", order["order_id"])

    # ---------------------------------------------------------------
    # 2. 团体登记 → 整团入住 → 团体结账（题目要求 (1)）
    #    「一次登记多间房」和「一张结账单结清多间房」这两件事，
    #    在数据上分别对应 room_order.group_id 与 room_order.settlement_no。
    # ---------------------------------------------------------------
    print("\n[2/3] 团体登记与团体结账")

    booker = db.query_value("SELECT user_id FROM `user` WHERE username = 'reception'",
                            None, 0)
    group_in = TODAY
    group_out = TODAY + timedelta(days=2)
    group_rooms = (service.search_available_rooms(db, group_in, group_out)[:3]
                   if booker else [])
    if len(group_rooms) < 3:
        _log("– 跳过团体演示：未找到前台账号或当天可用房不足 3 间")
    else:
        group = _try("登记 3 间房的团体单「华东区经销商年会」",
                     service.create_group_booking, db,
                     group_name="华东区经销商年会", contact_name="王经理",
                     contact_phone="13900000009", id_card="310101198505051234",
                     booker_user_id=int(booker), leader_user_id=guest_id,
                     check_in=group_in, check_out=group_out,
                     room_ids=[r["room_id"] for r in group_rooms],
                     remark="演示：团体登记 / 整团入住 / 团体结账")
        if group:
            _log(f"    团体单号 {group['group_id']}：{group['room_count']} 间房 · "
                 f"{group['nights']} 晚 · 总额 ¥{group['total_price']:,.2f}")
            _try("  整团办理入住（触发器把房间置为在住）",
                 service.checkin_group, db, group["group_id"])
            bill = _try("  团体结账（一张结账单覆盖 3 间房）",
                        service.settle_group, db, group_id=group["group_id"],
                        method="card", operator_id=int(booker),
                        remark="演示：团体结账")
            if bill:
                _log(f"    结账单号 {bill['settlement_no']}：{bill['room_count']} 间房 · "
                     f"账单 ¥{bill['total_amount']:,.2f} · "
                     f"实收 ¥{bill['collected']:,.2f}")
                _try("  按姓名/手机号/房间号/订单号查询客人信息",
                     service.search_guest_profile, db, keyword="王经理")

    # ---------------------------------------------------------------
    # 3. 再注册一个客人账号，让列表里有多个用户
    # ---------------------------------------------------------------
    print("\n[3/3] 补充演示账号")
    _try("注册演示账号 guest02",
         service.register_guest, db, "guest02", "guest123", "guest123",
         "13800000004", "李四")


def main() -> int:
    parser = argparse.ArgumentParser(description="生成客房订单与支付流水演示数据")
    parser.add_argument("--force", action="store_true",
                        help="即使已有演示订单也继续追加")
    args = parser.parse_args()

    db = Database()
    try:
        existing = db.query_value(
            "SELECT COUNT(*) FROM room_order WHERE guest_name = '张三'", None, 0)
        demo_group = db.query_value(
            "SELECT COUNT(*) FROM guest_group WHERE group_name = '华东区经销商年会'",
            None, 0)
        if (existing or demo_group) and not args.force:
            print(f"检测到已有 {existing} 条演示客房订单、{demo_group} 个演示团体单，跳过。"
                  f"（如需追加请加 --force）")
            return 0

        print("=" * 60)
        print("  生成客房订单 / 团体单 / 结账单 / 支付流水演示数据"
              "（全部通过业务层创建，会走触发器与校验）")
        print("=" * 60)
        seed(db)
        print("\n" + "=" * 60)
        print("✓ 演示数据生成完成。可用 python tools/smoke_test.py 做一次自检。")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
