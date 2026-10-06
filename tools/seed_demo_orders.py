"""
生成订单类演示数据。

用法：python tools/seed_demo_orders.py

设计要点：
  · 订单**不写进 SQL 脚本**，而是通过 app/service.py 创建 —— 这样演示数据
    一定会走过触发器、状态机、金额汇总与事务校验，保证数据自洽；
  · 幂等：先用固定前缀检测是否已生成，已存在则跳过（可用 --force 强制重建）；
  · 覆盖各种状态（待入住 / 在住 / 已退房 / 已取消 / 待收款 / 已支付 / 已评价），
    便于答辩时演示各功能；
  · 所有日期基于"今天"计算，任何时候运行都能看到合理的今日数据。
"""

from __future__ import annotations

import argparse
import io
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
    print("\n[1/6] 客房订单")

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
    # 2. 餐饮订单（带菜品明细，验证金额自动汇总）
    # ---------------------------------------------------------------
    print("\n[2/6] 餐饮订单")
    for restaurant_id, hour, count, dish_indexes in (
        (1, "12:00", 2, [0, 2]),
        (1, "18:30", 4, [4, 5, 6]),
        (2, "19:00", 2, [0, 1]),
    ):
        menu = service.list_menu(db, restaurant_id)
        dishes = [d for d in menu if float(d["price"]) > 0]
        if len(dishes) <= max(dish_indexes):
            continue
        items = [(dishes[i]["dish_id"], 1 + i % 2) for i in dish_indexes]
        order = _try(f"创建餐饮订单（餐厅{restaurant_id} {hour}，{len(items)} 道菜）",
                     service.create_dining_order, db, user_id=guest_id,
                     restaurant_id=restaurant_id, dining_date=TODAY,
                     dining_time=hour, guest_count=count, items=items)
        if order and hour == "12:00":
            _try("  标记完成用餐", service.advance_order_status, db, "dining",
                 order["order_id"], "completed")
            _try("  收款", service.pay_order, db, order_type="dining",
                 order_id=order["order_id"], user_id=guest_id, method="alipay")
            _try("  提交评价", service.submit_review, db, user_id=guest_id,
                 order_id=order["order_id"], order_type="dining", rating=4,
                 content="宫保鸡丁味道正宗，上菜速度也快。")

    # ---------------------------------------------------------------
    # 3. 健身预约
    # ---------------------------------------------------------------
    print("\n[3/6] 健身预约")
    facilities = db.query("SELECT facility_id, facility_name, capacity "
                          "FROM fitness_facility WHERE status='available' "
                          "ORDER BY facility_id LIMIT 2")
    for index, facility in enumerate(facilities):
        _try(f"预约 {facility['facility_name']}",
             service.create_fitness_booking, db, user_id=guest_id,
             facility_id=facility["facility_id"], booking_date=TODAY,
             time_slot=service.FITNESS_SLOTS[index], guest_count=1 + index)

    # ---------------------------------------------------------------
    # 4. SPA 预约（同时占用技师排班表）
    # ---------------------------------------------------------------
    print("\n[4/6] SPA 预约")
    services = db.query("SELECT service_id, service_name FROM spa_service "
                        "ORDER BY service_id LIMIT 2")
    for index, spa in enumerate(services):
        techs = service.list_technicians(db, spa["service_id"])
        if not techs:
            continue
        target_tech = techs[index % len(techs)]
        target_date = TODAY + timedelta(days=index)
        taken = {row["time_slot"] for row in service.tech_availability(
            db, target_tech["tech_id"], target_date) if row["is_booked"]}
        slot = next((f"{h:02d}:00" for h in range(9, 21)
                     if f"{h:02d}:00" not in taken), None)
        if slot is None:
            continue
        _try(f"预约 {spa['service_name']}（{target_tech['tech_name']} {slot}）",
             service.create_spa_booking, db, user_id=guest_id,
             service_id=spa["service_id"], tech_id=target_tech["tech_id"],
             booking_date=target_date, booking_time=slot)

    # ---------------------------------------------------------------
    # 5. 洗衣订单（加急与普通各一，验证优先级排序）
    # ---------------------------------------------------------------
    print("\n[5/6] 洗衣订单")
    for service_type, count, pickup in (("wash", 4, "09:00"),
                                        ("express_dry", 2, "立即取衣")):
        order = _try(f"创建洗衣订单（{service_type} × {count}）",
                     service.create_laundry_order, db, user_id=guest_id,
                     service_type=service_type, item_count=count,
                     room_number="", expected_pickup=pickup)
        if order and service_type == "wash":
            _try("  标记已取衣", service.advance_order_status, db, "laundry",
                 order["order_id"], "picked_up")
            _try("  标记洗涤中", service.advance_order_status, db, "laundry",
                 order["order_id"], "processing")

    # ---------------------------------------------------------------
    # 6. 再注册一个客人账号，让列表里有多个用户
    # ---------------------------------------------------------------
    print("\n[6/6] 补充演示账号")
    _try("注册演示账号 guest02",
         service.register_guest, db, "guest02", "guest123", "guest123",
         "13800000004", "李四")


def main() -> int:
    parser = argparse.ArgumentParser(description="生成订单类演示数据")
    parser.add_argument("--force", action="store_true",
                        help="即使已有演示订单也继续追加")
    args = parser.parse_args()

    db = Database()
    try:
        existing = db.query_value(
            "SELECT COUNT(*) FROM room_order WHERE guest_name = '张三'", None, 0)
        if existing and not args.force:
            print(f"检测到已有 {existing} 条演示客房订单，跳过。"
                  f"（如需追加请加 --force）")
            return 0

        print("=" * 60)
        print("  生成订单类演示数据（全部通过业务层创建，会走触发器与校验）")
        print("=" * 60)
        seed(db)
        print("\n" + "=" * 60)
        print("✓ 演示数据生成完成。可用 python tools/smoke_test.py 做一次自检。")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
