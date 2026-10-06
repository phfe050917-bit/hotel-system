"""
端到端冒烟测试。

用法：python tools/smoke_test.py

覆盖内容：
  A. 数据库对象清单 —— 表/视图/触发器/索引/外键/CHECK 约束是否齐备
  B. 密码哈希 —— 明文不入库、错误密码被拒、禁用账号被拒
  C. 客房业务 —— 金额由触发器重算、日期校验、同日冲突拒绝、状态机流转
  D. 订单汇总 —— 同一秒创建多单不再互相覆盖（原系统丢单 bug 的回归测试）
  E. 洗衣业务 —— 隐私过滤、状态跳转被拒、时间戳自动写入
  F. 餐饮业务 —— 明细写入后订单金额自动汇总
  G. 评价 —— 订单存在性、归属、重复评价三重校验
  H. 并发容量 —— 健身容量不会被超卖（事务内复查）

测试会写入演示数据，但全部在同一个库中，可重复执行。
"""

from __future__ import annotations

import io
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

for _stream in ("stdout", "stderr"):
    _s = getattr(sys, _stream, None)
    if _s is not None:
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

from app.db import Database, DatabaseError
from app import service, stats
from app.security import hash_password, verify_password

PASS, FAIL = [], []


def check(name: str, condition: bool, detail: str = "") -> None:
    (PASS if condition else FAIL).append(name)
    mark = "✓" if condition else "✗"
    print(f"  {mark} {name}" + (f"  [{detail}]" if detail and not condition else ""))


def section(title: str) -> None:
    print(f"\n{'=' * 66}\n  {title}\n{'=' * 66}")


def expect_error(name: str, fn, *args, **kwargs) -> None:
    """断言该操作必须被拒绝。"""
    try:
        fn(*args, **kwargs)
    except (service.BusinessError, DatabaseError) as exc:
        check(name, True)
        print(f"      → 已按预期拒绝：{str(exc)[:90]}")
    else:
        check(name, False, "本应被拒绝，但操作成功了")


def main() -> int:
    db = Database()

    # =================================================================
    section("A. 数据库对象清单")
    # =================================================================
    obj = stats.schema_objects(db)
    print(f"  表={obj['tables']}  视图={obj['views']}  触发器={obj['triggers']}  "
          f"索引={obj['indexes']}  外键={obj['foreign_keys']}  CHECK={obj['check_constraints']}")
    check("数据表数量为 18", obj["tables"] == 18, f"实际 {obj['tables']}")
    check("视图数量为 6", obj["views"] == 6, f"实际 {obj['views']}")
    check("触发器数量为 9", obj["triggers"] == 9, f"实际 {obj['triggers']}")
    check("外键约束 >= 20", obj["foreign_keys"] >= 20, f"实际 {obj['foreign_keys']}")
    check("CHECK 约束 >= 15", obj["check_constraints"] >= 15,
          f"实际 {obj['check_constraints']}")

    # =================================================================
    section("B. 密码安全")
    # =================================================================
    row = db.query_one("SELECT password_hash FROM `user` WHERE username = 'admin'")
    check("库中不含明文密码列 password",
          db.query_value("SELECT COUNT(*) FROM information_schema.columns "
                         "WHERE table_schema = DATABASE() AND table_name = 'user' "
                         "AND column_name = 'password'", None, 0) == 0)
    check("密码以 pbkdf2_sha256 哈希存储",
          row and row["password_hash"].startswith("pbkdf2_sha256$"))
    check("哈希不含明文片段", row and "admin123" not in row["password_hash"])
    check("正确密码校验通过", verify_password("admin123", row["password_hash"]))
    check("错误密码校验失败", not verify_password("admin1234", row["password_hash"]))
    check("相同密码两次哈希不同（加盐生效）",
          hash_password("same") != hash_password("same"))

    session = service.authenticate(db, "admin", "admin123")
    check("admin 登录成功且角色正确", session.role == "admin")
    expect_error("错误密码登录被拒绝", service.authenticate, db, "admin", "wrong")

    # =================================================================
    section("C. 客房业务")
    # =================================================================
    guest = service.authenticate(db, "guest01", "guest123")
    check_in = date.today() + timedelta(days=1)
    check_out = check_in + timedelta(days=3)

    rooms = service.search_available_rooms(db, check_in, check_out)
    check("可订房间查询返回结果", len(rooms) > 0, f"{len(rooms)} 间")
    check("查询结果带 room_id（预订无需反查）", "room_id" in (rooms[0] if rooms else {}))

    expect_error("离店早于入住被拒绝", service.search_available_rooms,
                 db, check_out, check_in)
    expect_error("入住日期早于今天被拒绝", service.search_available_rooms,
                 db, date.today() - timedelta(days=5), check_in)

    target = rooms[0]
    order = service.create_room_order(
        db, user_id=guest.user_id, room_id=target["room_id"],
        check_in=check_in, check_out=check_out,
        guest_name="测试客人张三", guest_phone="13800000003")
    expected = float(target["price"]) * 3
    check("订单金额由触发器按房价重算", abs(float(order["total_price"]) - expected) < 0.01,
          f"{order['total_price']} vs {expected}")
    check("晚数由触发器计算为 3", int(order["nights"]) == 3)

    expect_error("同一房间同期重复预订被拒绝", service.create_room_order,
                 db, user_id=guest.user_id, room_id=target["room_id"],
                 check_in=check_in, check_out=check_out, guest_name="重复客人")

    overlap = service.create_room_order
    expect_error("日期区间重叠的预订被拒绝", overlap,
                 db, user_id=guest.user_id, room_id=target["room_id"],
                 check_in=check_in + timedelta(days=1),
                 check_out=check_out + timedelta(days=2), guest_name="重叠客人")

    # 状态机
    rid = order["order_id"]
    expect_error("待入住订单不能直接退房", service.advance_order_status,
                 db, "room", rid, "checked_out")
    service.advance_order_status(db, "room", rid, "checked_in")
    check("入住后订单状态为 checked_in",
          db.query_value("SELECT status FROM room_order WHERE order_id = %s",
                         (rid,)) == "checked_in")
    service.advance_order_status(db, "room", rid, "checked_out")
    room_status = db.query_value("SELECT status FROM room WHERE room_id = %s",
                                 (target["room_id"],))
    check("退房后房间自动进入打扫中（触发器联动）", room_status == "cleaning",
          f"实际 {room_status}")

    # 取消流程
    order2 = service.create_room_order(
        db, user_id=guest.user_id, room_id=rooms[1]["room_id"],
        check_in=check_in, check_out=check_out, guest_name="待取消客人")
    service.cancel_order(db, "room", order2["order_id"])
    check("订单可被取消",
          db.query_value("SELECT status FROM room_order WHERE order_id = %s",
                         (order2["order_id"],)) == "cancelled")
    expect_error("已取消订单不能再次取消", service.cancel_order,
                 db, "room", order2["order_id"])
    expect_error("已退房订单不能被取消", service.cancel_order, db, "room", rid)

    # 单独构造一个"当前有效订单"的房间来验证空闲置位保护
    active_order = service.create_room_order(
        db, user_id=guest.user_id, room_id=rooms[3]["room_id"],
        check_in=date.today(), check_out=date.today() + timedelta(days=2),
        guest_name="在住客人")
    expect_error("人工把有在住订单的房间置为空闲被拒绝",
                 service.set_room_status, db, rooms[3]["room_id"], "available")
    check("该房间已被触发器自动置为 occupied",
          db.query_value("SELECT status FROM room WHERE room_id = %s",
                         (rooms[3]["room_id"],)) == "occupied")
    service.cancel_order(db, "room", active_order["order_id"])
    check("取消订单后房间自动恢复空闲（触发器联动）",
          db.query_value("SELECT status FROM room WHERE room_id = %s",
                         (rooms[3]["room_id"],)) == "available")
    expect_error("不允许人工设为 occupied", service.set_room_status,
                 db, target["room_id"], "occupied")

    # =================================================================
    section("D. 订单汇总（原丢单 bug 回归测试）")
    # =================================================================
    before = len(service.list_orders(db, user_id=guest.user_id))
    burst = []
    for i in range(5):
        burst.append(service.create_laundry_order(
            db, user_id=guest.user_id, service_type="wash",
            item_count=i + 1, room_number="101")["order_id"])
    after_orders = service.list_orders(db, user_id=guest.user_id)
    check("同一秒连续创建 5 单，列表条数正确增加",
          len(after_orders) == before + 5, f"{before} -> {len(after_orders)}")
    check("5 张新订单全部可见（不再互相覆盖）",
          all(any(o["order_id"] == oid for o in after_orders) for oid in burst))

    same_second = db.query(
        "SELECT created_at, COUNT(*) AS c FROM laundry_order "
        "GROUP BY created_at HAVING c > 1")
    check("确实存在同一秒内的多张订单", len(same_second) > 0,
          "本次未构造出同秒数据，测试强度下降")

    check("视图状态已归一化",
          all(o["status_category"] in ("进行中", "已完成", "已取消")
              for o in after_orders))

    # =================================================================
    section("E. 洗衣业务")
    # =================================================================
    mine = service.laundry_queue(db, user_id=guest.user_id)
    all_q = service.laundry_queue(db)
    check("客人队列只包含自己的订单",
          all(o["user_id"] == guest.user_id for o in mine))
    check("全量队列条数 >= 客人自己的条数（隐私过滤生效）",
          len(all_q) >= len(mine))

    lid = burst[0]
    expect_error("等待取衣不能直接跳到已送达（原系统可跳）",
                 service.advance_order_status, db, "laundry", lid, "delivered")
    service.advance_order_status(db, "laundry", lid, "picked_up")
    picked = db.query_one("SELECT pickup_time, status FROM laundry_order "
                          "WHERE order_id = %s", (lid,))
    check("取衣时自动写入 pickup_time（原设计该列从不写入）",
          picked["pickup_time"] is not None)
    service.advance_order_status(db, "laundry", lid, "processing")
    service.advance_order_status(db, "laundry", lid, "delivered")
    delivered = db.query_one("SELECT delivery_time FROM laundry_order "
                             "WHERE order_id = %s", (lid,))
    check("送达时自动写入 delivery_time", delivered["delivery_time"] is not None)
    expect_error("已送达订单不能回退", service.advance_order_status,
                 db, "laundry", lid, "processing")

    est = service.estimate_laundry("express_wash", 4)
    check("洗衣报价计算正确", abs(est["total_price"] - 200.0) < 0.01)

    # =================================================================
    section("F. 餐饮业务")
    # =================================================================
    menu = service.list_menu(db, 1)
    check("菜单可读取且带分类", len(menu) > 0 and "category_name" in menu[0])
    dishes = [d for d in menu if d["price"] and float(d["price"]) > 0][:3]
    items = [(d["dish_id"], 2) for d in dishes]
    dining = service.create_dining_order(
        db, user_id=guest.user_id, restaurant_id=1,
        dining_date=date.today(), dining_time="12:00",
        guest_count=2, items=items)
    expected_amount = sum(float(d["price"]) * 2 for d in dishes)
    saved_total = float(db.query_value(
        "SELECT total_price FROM dining_order WHERE order_id = %s",
        (dining["order_id"],), 0))
    check("餐饮订单金额由触发器按明细汇总（原系统恒为 0）",
          abs(saved_total - expected_amount) < 0.01,
          f"{saved_total} vs {expected_amount}")
    check("明细行小计已写入",
          db.query_value("SELECT COUNT(*) FROM dining_order_item "
                         "WHERE order_id = %s AND subtotal > 0",
                         (dining["order_id"],), 0) == len(items))
    check("桌号按占用情况分配而非固定值",
          dining["table_number"] not in (None, "1号桌"))

    # =================================================================
    section("G. 评价")
    # =================================================================
    expect_error("未完成订单不能评价", service.submit_review,
                 db, user_id=guest.user_id, order_id=dining["order_id"],
                 order_type="dining", rating=5, content="好")
    service.advance_order_status(db, "dining", dining["order_id"], "completed")
    service.submit_review(db, user_id=guest.user_id, order_id=dining["order_id"],
                          order_type="dining", rating=5, content="味道很好")
    check("已完成订单可评价", True)
    expect_error("同一订单重复评价被拒绝（原系统可无限重复）",
                 service.submit_review, db, user_id=guest.user_id,
                 order_id=dining["order_id"], order_type="dining",
                 rating=4, content="再评一次")
    expect_error("评分越界被拒绝", service.submit_review,
                 db, user_id=guest.user_id, order_id=order2["order_id"],
                 order_type="room", rating=9, content="x")
    expect_error("评价不存在的订单被拒绝（触发器校验）", db.execute,
                 "INSERT INTO review (user_id, order_id, order_type, rating, content) "
                 "VALUES (%s, 'NOT-EXIST-0001', 'room', 5, 'x')", (guest.user_id,))

    # =================================================================
    section("H. 健身容量与并发")
    # =================================================================
    facility = db.query_one("SELECT facility_id, capacity, facility_name "
                            "FROM fitness_facility ORDER BY capacity LIMIT 1")
    cap = int(facility["capacity"])
    leftover = db.query_value(
        "SELECT COALESCE(SUM(guest_count), 0) FROM fitness_booking "
        "WHERE facility_id = %s AND booking_date = %s AND time_slot = %s "
        "  AND status = 'confirmed'",
        (facility["facility_id"], date.today(), "14:00-16:00"), 0)
    room_left = cap - int(leftover)
    if room_left > 0:
        service.create_fitness_booking(
            db, user_id=guest.user_id, facility_id=facility["facility_id"],
            booking_date=date.today(), time_slot="14:00-16:00", guest_count=room_left)
        check("容量内预约成功", True)
        expect_error("超出容量被拒绝（事务内复查生效）",
                     service.create_fitness_booking, db, user_id=guest.user_id,
                     facility_id=facility["facility_id"], booking_date=date.today(),
                     time_slot="14:00-16:00", guest_count=1)

    usage = service.fitness_usage(db, date.today())
    check("设施使用情况含剩余名额字段", "remaining" in (usage[0] if usage else {}))

    # =================================================================
    section("I. SPA 与排班")
    # =================================================================
    services = db.query("SELECT service_id FROM spa_service ORDER BY service_id LIMIT 1")
    techs = service.list_technicians(db, services[0]["service_id"])
    check("技师列表可读取", len(techs) > 0)
    spa_date = date.today() + timedelta(days=2)
    # 从 09:00 起选一个该技师当天尚未被占用的时段，
    # 保证脚本反复执行不会撞上自己上一次留下的预约。
    spa_slot = None
    taken = {row["time_slot"] for row in service.tech_availability(
        db, techs[0]["tech_id"], spa_date) if row["is_booked"]}
    for hour in range(9, 21):
        candidate = f"{hour:02d}:00"
        if candidate not in taken:
            spa_slot = candidate
            break
    check("找到可用 SPA 时段", spa_slot is not None)
    spa = service.create_spa_booking(
        db, user_id=guest.user_id, service_id=services[0]["service_id"],
        tech_id=techs[0]["tech_id"], booking_date=spa_date, booking_time=spa_slot)
    check("SPA 预约成功并带回价格快照", float(spa["price"]) > 0)
    expect_error("同技师同时间重复预约被拒绝（原系统无校验）",
                 service.create_spa_booking, db, user_id=guest.user_id,
                 service_id=services[0]["service_id"],
                 tech_id=techs[0]["tech_id"], booking_date=spa_date,
                 booking_time=spa_slot)
    check("排班表被真正占用（原系统该表零读写）",
          db.query_value("SELECT COUNT(*) FROM tech_schedule "
                         "WHERE tech_id = %s AND work_date = %s AND time_slot = %s "
                         "  AND is_booked = 1",
                         (techs[0]["tech_id"], spa_date, spa_slot), 0) > 0)

    # =================================================================
    section("J. 支付与统计")
    # =================================================================
    revenue_before = stats.revenue_summary(db)["total"]
    pay = service.pay_order(db, order_type="dining", order_id=dining["order_id"],
                            user_id=guest.user_id, method="wechat")
    check("支付流水登记成功", float(pay["amount"]) > 0)
    expect_error("重复支付被拒绝", service.pay_order, db, order_type="dining",
                 order_id=dining["order_id"], user_id=guest.user_id, method="cash")

    revenue = stats.revenue_summary(db)
    check("营收增量等于本次支付金额（营收来自流水而非订单状态求和）",
          abs((revenue["total"] - revenue_before) - float(pay["amount"])) < 0.01,
          f"增量 {revenue['total'] - revenue_before} vs 支付 {pay['amount']}")
    check("营收按类型分组", len(revenue["by_type"]) >= 1)

    ov = stats.overview(db)
    check("概览指标完整", all(k in ov for k in
                              ("arrivals", "in_house", "rooms_total", "pending_payment")))
    check("服务统计视图可读", len(stats.service_stats(db)) >= 4)
    check("菜品销量排行可读", isinstance(stats.top_dishes(db), list))
    check("技师工作量统计可读", len(stats.tech_workload(db)) >= 1)

    # 取消订单应同步退款
    refund_target = service.create_room_order(
        db, user_id=guest.user_id, room_id=rooms[2]["room_id"],
        check_in=check_in, check_out=check_out, guest_name="退款测试")
    service.pay_order(db, order_type="room", order_id=refund_target["order_id"],
                      user_id=guest.user_id, method="card")
    service.cancel_order(db, "room", refund_target["order_id"])
    check("取消已支付订单会生成退款状态",
          db.query_value("SELECT status FROM payment WHERE order_id = %s",
                         (refund_target["order_id"],)) == "refunded")

    # =================================================================
    section("K. 用户管理")
    # =================================================================
    admin = service.authenticate(db, "admin", "admin123")    # 用户名带随机后缀，脚本可反复执行而不会互相冲突
    suffix = f"{int(datetime.now().timestamp() * 1000) % 100000000:08d}"
    temp_username = f"smoke_{suffix}"
    guest2 = service.register_guest(db, temp_username, "pass123456",
                                    "pass123456", "", "冒烟测试用户")
    check("注册新用户成功", guest2 > 0)
    expect_error("重复用户名注册被拒绝", service.register_guest,
                 db, temp_username, "pass123456", "pass123456")
    expect_error("密码过短被拒绝", service.register_guest,
                 db, f"smoke_short_{suffix}", "123", "123")
    expect_error("两次密码不一致被拒绝", service.register_guest,
                 db, f"smoke_mismatch_{suffix}", "pass123456", "pass654321")
    expect_error("非法手机号被拒绝", service.register_guest,
                 db, f"smoke_phone_{suffix}", "pass123456", "pass123456", "123")

    service.set_user_active(db, guest2, False, current_user_id=admin.user_id)
    expect_error("被禁用账号无法登录", service.authenticate,
                 db, temp_username, "pass123456")
    service.set_user_active(db, guest2, True, current_user_id=admin.user_id)
    check("重新启用后可登录",
          service.authenticate(db, temp_username, "pass123456").user_id == guest2)
    expect_error("不能禁用当前登录账号", service.set_user_active,
                 db, admin.user_id, False, current_user_id=admin.user_id)

    # 清理本次冒烟测试创建的账号（参数化查询避免 % 与 pymysql 占位符冲突）
    temp = db.query("SELECT user_id FROM `user` WHERE username LIKE %s", ("smoke\\_%",))
    for row in temp:
        db.execute("DELETE FROM `user` WHERE user_id = %s", (row["user_id"],))
    check("测试账号已清理",
          not db.query("SELECT user_id FROM `user` WHERE username LIKE %s", ("smoke\\_%",)))

    # =================================================================
    section("L. 基础资源维护（界面已无 SQL，全部走 service 层）")
    # =================================================================
    catalog = service.resource_catalog()
    check("资源注册表可读取", len(catalog) >= 7, f"{len(catalog)} 类")
    check("注册表项含字段规格",
          all(spec.get("fields") and spec.get("pk") for spec in catalog))

    # 白名单拦截：不允许操作未登记的表
    expect_error("操作未登记的数据表被拒绝", service.resource_list, db, "mysql.user")
    expect_error("修改主键字段被拒绝", service.resource_create, db, "room_type",
                 {"type_id": 999, "type_name": "非法房型"})

    # 新增 -> 改 -> 删（房型）
    created_id = None
    try:
        service.resource_create(db, "room_type", {
            "type_name": "冒烟测试房型", "price": "123.45",
            "max_occupancy": "2", "facilities": "WiFi", "description": "临时"})
        created_id = db.query_value(
            "SELECT type_id FROM room_type WHERE type_name = '冒烟测试房型'")
        check("新增基础资源成功", bool(created_id))
    except service.BusinessError as exc:
        check("新增基础资源成功", False, str(exc))

    if created_id:
        expect_error("整数列填非数字被拒绝", service.resource_update, db, "room_type",
                     created_id, {"price": "不是数字"})
        service.resource_update(db, "room_type", created_id,
                                {"type_name": "冒烟测试房型2", "price": "200",
                                 "max_occupancy": "3"})
        check("修改基础资源成功",
              db.query_value("SELECT type_name FROM room_type WHERE type_id = %s",
                             (created_id,)) == "冒烟测试房型2")
        service.resource_delete(db, "room_type", created_id)
        check("删除未被引用的资源成功",
              db.query_value("SELECT COUNT(*) FROM room_type WHERE type_id = %s",
                             (created_id,), 0) == 0)

    # 被引用的资源必须删不掉（外键 RESTRICT 保护）
    referenced_room = db.query_value("SELECT room_id FROM room ORDER BY room_id LIMIT 1")
    expect_error("删除有订单引用的房间被数据库拒绝",
                 service.resource_delete, db, "room", referenced_room)

    check("用户订单数统计可读", isinstance(service.user_order_counts(db), dict))
    check("入住候选查询可用（今天）",
          isinstance(service.checkin_candidates(db, "今天"), list))
    check("入住候选查询可用（未来 7 天）",
          isinstance(service.checkin_candidates(db, "未来 7 天"), list))
    check("数据库对象名清单可读",
          set(service.schema_object_names(db)) == {"views", "triggers", "tables"})
    check("各表行数统计可读", len(service.table_row_counts(db)) >= 18)

    db.close()

    # =================================================================
    print(f"\n{'=' * 66}")
    print(f"  通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    if FAIL:
        print("  失败项：")
        for name in FAIL:
            print(f"    ✗ {name}")
    print("=" * 66)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
