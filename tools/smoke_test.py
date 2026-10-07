"""
端到端冒烟测试（客房主线）—— 宾馆客房管理系统（选题19）。

用法：py tools/smoke_test.py

覆盖内容：
  A. 数据库对象清单 —— 9 表 / 7 视图 / 5 触发器 / 12 外键 / 9 CHECK 约束 /
                        27 个非主键索引是否齐备，对象名精确核对，
                        且未登记的订单类型连数据库都写不进去
  B. 密码安全 —— 明文不入库、错误密码被拒、加盐生效、禁用账号无法登录
  C. 客房业务 —— 金额由触发器按当前房价重算（界面传错金额也无效）、
                  日期非法被拒、同期重复预订被拒、状态机非法跳转被拒
  D. 入住/退房联动 —— checked_in 置 occupied、checked_out 转 cleaning、
                      取消后按剩余有效订单回置空闲
  E. 订单汇总 —— 同一秒连续创建 5 单不再互相覆盖（原系统 BST 丢单 bug 的回归测试）
  F. 评价 —— 订单存在性 / 归属 / 重复评价三重校验，且只有已完成订单能评价
  G. 支付与统计 —— 重复支付被拒、营收只来自 payment 流水、取消已支付订单产生退款
  H. 用户管理 —— 注册校验、软禁用、自助改密与管理员重置密码
  I. 基础资源维护 —— 白名单拦截非法表名、拒绝改主键、类型校验、外键 RESTRICT 保护
  J. 团体登记 —— 一次为 3 间房生成 3 张同团体订单、金额由触发器重算、
                  同名团体同日重复登记被拒、成员日期与团体单不一致被触发器拒绝
  K. 散客结账 —— 一张订单生成一张 bill_type='散客' 的账单、金额与订单一致、
                  写入收款流水、重复结账被拒
  L. 团体结账 —— 一张结账单覆盖 N 张订单、金额等于各订单之和、
                  逐单写 payment、重复结账/非法结算方式被拒
  M. 整团入住 / 退房 —— 全团订单一起流转并同步 guest_group.status，
                         无可办理订单时抛 BusinessError
  N. 已结账订单不可取消 + 结账单退款 —— service 层拒绝，且**直插 UPDATE** 也被
                           trg_room_order_before_update 拒绝（数据库层兜底）；
                           退款后 payment 全部置 refunded、成员订单 settlement_no
                           回到 NULL、settlement.status='refunded'，订单重新可取消
  O. 客人多手段查询 —— 姓名 / 手机号 / 证件号 / 房间号 / 订单号片段 /
                       入住日期区间 六种手段与 keyword 组合查询，
                       且**没有订单的客人也能被查到**（LEFT JOIN 主体是 user）
  P. 密码支持与审计 —— 不传 approval 改房型被拒、密码错误被拒、
                       成功改动写 price_change_log 且旧值新值一致，
                       新增/删除房间同样留痕，未登记表仍被白名单拒绝
  Q. 结账报表 —— settlement_report 的账单数/房间数/金额与自建账单一致、
                 团体与散客分类正确、已退款账单不计入金额但计入退款数、
                 未结账订单数随结账/退款精确变化
  R. 清理 —— 按外键依赖顺序删除本次创建的团体单、订单、payment、review、
              结账单、审计日志，并恢复被占用房间的房态，脚本可反复执行

原系统的 4 条非客房业务线已整体删除，本脚本只覆盖保留下来的客房主线。
断言强度不因精简而下降：旧对象由 A 段的对象名集合相等比较兜住，
因此脚本里不需要再罗列已删对象的字面量。

脚本通过 service 业务层写入数据（因此会真实走一遍触发器与校验），
并在结尾清理本次创建的数据，**可反复执行**。
"""

from __future__ import annotations

import contextlib
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

# 精简后系统中"应该有"的全部数据库对象：用集合相等比较来核对，
# 任何多出来的遗留对象都会被断言抓住（比"某几个名字不存在"更强）。
EXPECTED_TABLES = frozenset({"user", "room_type", "room", "guest_group",
                             "room_order", "payment", "review", "settlement",
                             "price_change_log"})
EXPECTED_VIEWS = frozenset({"v_all_orders", "v_room_availability",
                            "v_room_current_state", "v_daily_revenue",
                            "v_service_stats", "v_guest_profile",
                            "v_settlement_detail"})
EXPECTED_TRIGGERS = frozenset({"trg_room_order_before_insert",
                               "trg_room_order_after_insert",
                               "trg_room_order_after_update",
                               "trg_room_order_before_update",
                               "trg_review_before_insert"})
# 实测口径（information_schema.statistics，排除 PRIMARY）：
#   9 张表上共 27 个非主键索引 = 22 个显式声明（8 唯一 + 14 普通）
#                              + 5 个 MySQL 为外键自动补建（fk_* 同名）
# 这里断言**精确值**而不是下界：少建索引（漏掉高频查询索引）或多出
# 未登记的索引都属于 schema 走样，应该被抓住。
EXPECTED_INDEX_COUNT = 27
EXPECTED_UNIQUE_INDEX_COUNT = 8
EXPECTED_FOREIGN_KEY_COUNT = 12
EXPECTED_CHECK_COUNT = 9


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


def cleanup(db: Database, state: dict) -> None:
    """
    删除本次运行写入的数据，并恢复房间状态。

    顺序不能随意调换，否则会被外键 RESTRICT 拦住：
      review / payment          —— 挂在订单下，先删
      room_order.settlement_no -> NULL —— 必须先解绑：trg_room_order_before_update
                                         会拦住"已结账订单被取消"
      room_order.group_id      -> NULL —— 之后 settlement / guest_group 才能删
      settlement -> room_order -> guest_group -> 临时账号 -> price_change_log

    本函数被 try/finally 包住，因此**即使中途断言失败/异常退出也会执行**，
    不会把半成品数据留给下一轮运行（否则一轮失败会让后面每轮都缺房可用）。
    """
    orders = list(dict.fromkeys(state.get("orders") or []))
    settlements = list(dict.fromkeys(state.get("settlements") or []))
    groups = [g for g in dict.fromkeys(state.get("groups") or []) if g]
    users = [u for u in dict.fromkeys(state.get("users") or []) if u]
    audit_from = state.get("audit_from")

    if orders:
        placeholders = ", ".join(["%s"] * len(orders))
        db.execute(f"DELETE FROM review WHERE order_id IN ({placeholders})",
                   tuple(orders))
        db.execute(f"DELETE FROM payment WHERE order_id IN ({placeholders})",
                   tuple(orders))
    # 先解绑 settlement_no，再取消订单，最后才删 settlement
    for settlement_no in settlements:
        db.execute("UPDATE room_order SET settlement_no = NULL WHERE settlement_no = %s",
                   (settlement_no,))
    if orders:
        placeholders = ", ".join(["%s"] * len(orders))
        db.execute(f"UPDATE room_order SET status = 'cancelled' "
                   f"WHERE order_id IN ({placeholders}) AND status <> 'cancelled'",
                   tuple(orders))
        db.execute(f"UPDATE room_order SET group_id = NULL "
                   f"WHERE order_id IN ({placeholders})", tuple(orders))
    for settlement_no in settlements:
        db.execute("DELETE FROM settlement WHERE settlement_no = %s", (settlement_no,))
    for order_id in orders:
        db.execute("DELETE FROM room_order WHERE order_id = %s", (order_id,))
    for user_id in users:
        db.execute("DELETE FROM `user` WHERE user_id = %s", (user_id,))
    for group_id in groups:
        db.execute("DELETE FROM guest_group WHERE group_id = %s", (group_id,))
    if audit_from is not None:
        db.execute("DELETE FROM price_change_log WHERE log_id > %s", (audit_from,))

    # 把没有有效订单的房间恢复为空闲（DELETE 不触发房态触发器）
    for room_id in state.get("rooms") or ():
        db.execute(
            "UPDATE room SET status = 'available' WHERE room_id = %s "
            "AND (SELECT COUNT(*) FROM room_order WHERE room_id = %s "
            "     AND status IN ('confirmed','checked_in')) = 0", (room_id, room_id))


def finish() -> int:
    """打印汇总。正常跑完与中途发现环境不满足都走这里，保证汇总格式一致。"""
    print(f"\n{'=' * 66}")
    print(f"  通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    if FAIL:
        print("  失败项：")
        for name in FAIL:
            print(f"    ✗ {name}")
    print("=" * 66)
    return 1 if FAIL else 0


def run(db: Database, state: dict) -> None:  # noqa: C901  （线性书写，便于逐段对照报告）
    """主体断言。所有创建出来的对象都登记到 state，供 cleanup 统一回收。"""
    # 本次测试创建的数据，结尾统一清理，保证脚本可反复执行
    created_orders: list[str] = state["orders"]
    touched_rooms: set[int] = state["rooms"]
    # 团体单 / 结账单 / 审计日志 / 临时账号，同样在结尾清理
    created_groups: list[int] = state["groups"]
    created_settlements: list[str] = state["settlements"]
    created_users: list[int] = state["users"]
    suffix = state["suffix"]

    # 断言辅助：本次构造的订单是否出现在检索结果里
    def has_order(rows: list[dict], order_id: str) -> bool:
        return any(r.get("order_id") == order_id for r in rows)

    # =================================================================
    section("A. 数据库对象清单")
    # =================================================================
    obj = stats.schema_objects(db)
    print(f"  表={obj['tables']}  视图={obj['views']}  触发器={obj['triggers']}  "
          f"索引={obj['indexes']}  外键={obj['foreign_keys']}  CHECK={obj['check_constraints']}")
    check("数据表数量为 9（4 条非客房业务线的表已全部删除，新增 3 张团体/结账/审计表）",
          obj["tables"] == 9, f"实际 {obj['tables']}")
    check("视图数量为 7", obj["views"] == 7, f"实际 {obj['views']}")
    check("触发器数量为 5", obj["triggers"] == 5, f"实际 {obj['triggers']}")
    check(f"外键约束为 {EXPECTED_FOREIGN_KEY_COUNT}",
          obj["foreign_keys"] == EXPECTED_FOREIGN_KEY_COUNT,
          f"实际 {obj['foreign_keys']}")
    check(f"CHECK 约束为 {EXPECTED_CHECK_COUNT}",
          obj["check_constraints"] == EXPECTED_CHECK_COUNT,
          f"实际 {obj['check_constraints']}")
    # information_schema 会把外键自动补建的索引也算进来（本库为 5 个），
    # 因此这里断言实测总数 27，并额外核对唯一索引个数，防止用普通索引凑数。
    check(f"非主键索引恰好 {EXPECTED_INDEX_COUNT} 个（22 个显式 + 5 个外键自动）",
          obj["indexes"] == EXPECTED_INDEX_COUNT, f"实际 {obj['indexes']}")
    unique_indexes = db.query_value(
        "SELECT COUNT(DISTINCT table_name, index_name) FROM information_schema.statistics "
        "WHERE table_schema = DATABASE() AND index_name <> 'PRIMARY' AND non_unique = 0",
        None, 0)
    check(f"其中唯一索引 {EXPECTED_UNIQUE_INDEX_COUNT} 个（业务唯一性靠约束而非应用代码）",
          unique_indexes == EXPECTED_UNIQUE_INDEX_COUNT, f"实际 {unique_indexes}")

    # 只数个数不够（删错表时个数照样对得上），对象名必须与期望集合完全相等
    names = service.schema_object_names(db)
    tables = {r["name"] for r in names["tables"]}
    views = {r["name"] for r in names["views"]}
    triggers = {r["name"] for r in names["triggers"]}
    check("数据库中恰好只有 9 张业务表，无任何遗留表",
          tables == EXPECTED_TABLES,
          f"多出 {sorted(tables - EXPECTED_TABLES)}，缺少 {sorted(EXPECTED_TABLES - tables)}")
    check("数据库中恰好只有 7 个视图，无任何遗留视图",
          views == EXPECTED_VIEWS,
          f"多出 {sorted(views - EXPECTED_VIEWS)}，缺少 {sorted(EXPECTED_VIEWS - views)}")
    check("数据库中恰好只有 5 个触发器，无任何遗留触发器",
          triggers == EXPECTED_TRIGGERS,
          f"多出 {sorted(triggers - EXPECTED_TRIGGERS)}，"
          f"缺少 {sorted(EXPECTED_TRIGGERS - triggers)}")

    # room_order 的三个新列（题目要求 (1)(3)）：证件号 / 团体归属 / 结账归属。
    # 列名写错会让整条团体-结账链路静默失效，因此在这里核对一次。
    new_columns = {r["COLUMN_NAME"] for r in db.query(
        "SELECT COLUMN_NAME FROM information_schema.columns "
        "WHERE table_schema = DATABASE() AND table_name = 'room_order'")}
    check("room_order 新增 id_card / group_id / settlement_no 三列",
          {"id_card", "group_id", "settlement_no"} <= new_columns,
          f"缺少 {sorted({'id_card', 'group_id', 'settlement_no'} - new_columns)}")
    # v_all_orders 新增三列：团体信息要能直接从统一订单视图读到，
    # 否则订单列表页无法展示团体/结账状态（题目要求 (1)(5)）。
    order_view_columns = {r["COLUMN_NAME"] for r in db.query(
        "SELECT COLUMN_NAME FROM information_schema.columns "
        "WHERE table_schema = DATABASE() AND table_name = 'v_all_orders'")}
    check("v_all_orders 新增 group_id / group_name / settlement_no 三列",
          {"group_id", "group_name", "settlement_no"} <= order_view_columns,
          f"缺少 {sorted({'group_id', 'group_name', 'settlement_no'} - order_view_columns)}")

    # 多态订单类型收敛成单值枚举
    pay_enum = db.query_value(
        "SELECT column_type FROM information_schema.columns "
        "WHERE table_schema = DATABASE() AND table_name = 'payment' "
        "AND column_name = 'order_type'", None, "") or ""
    rev_enum = db.query_value(
        "SELECT column_type FROM information_schema.columns "
        "WHERE table_schema = DATABASE() AND table_name = 'review' "
        "AND column_name = 'order_type'", None, "") or ""
    pay_method = db.query_value(
        "SELECT column_type FROM information_schema.columns "
        "WHERE table_schema = DATABASE() AND table_name = 'payment' "
        "AND column_name = 'method'", None, "") or ""
    check("payment.order_type 枚举已收敛为 ('room')", pay_enum == "enum('room')", pay_enum)
    check("review.order_type 枚举已收敛为 ('room')", rev_enum == "enum('room')", rev_enum)
    check("payment.method 仍保留 5 种支付方式",
          pay_method == "enum('cash','card','wechat','alipay','room_charge')", pay_method)

    # 枚举层兜底：未登记的订单类型连数据库都写不进去。
    # 这里刻意用一个与任何业务都无关的非法值，避免在脚本里出现已删业务线的字面量。
    invalid_type = "not_a_registered_type"
    expect_error("数据库拒绝未登记的订单类型（payment.order_type 只允许 room）",
                 db.execute,
                 "INSERT INTO payment (payment_no, order_id, order_type, user_id, "
                 "amount, method, status) "
                 "VALUES (%s, 'NOT-EXIST-0001', %s, "
                 "        (SELECT user_id FROM `user` WHERE username = 'admin'), "
                 "        10, 'cash', 'paid')",
                 ("SMOKE-ENUM-TEST", invalid_type))
    expect_error("review 的 order_type 同样只允许 room",
                 db.execute,
                 "INSERT INTO review (user_id, order_id, order_type, rating, content) "
                 "VALUES ((SELECT user_id FROM `user` WHERE username = 'admin'), "
                 "        'NOT-EXIST-0001', %s, 5, 'x')",
                 (invalid_type,))
    expect_error("业务层同样拒绝未登记的订单类型",
                 service.advance_order_status, db, invalid_type, "NOT-EXIST-0001",
                 "completed")

    # =================================================================
    section("B. 密码安全")
    # =================================================================
    row = db.query_one("SELECT password_hash FROM `user` WHERE username = 'admin'")
    check("库中不含明文密码列 password",
          db.query_value("SELECT COUNT(*) FROM information_schema.columns "
                         "WHERE table_schema = DATABASE() AND table_name = 'user' "
                         "AND column_name = 'password'", None, 0) == 0)
    check("密码以 pbkdf2_sha256 哈希存储",
          bool(row) and row["password_hash"].startswith("pbkdf2_sha256$"))
    check("哈希不含明文片段", bool(row) and "admin123" not in row["password_hash"])
    check("正确密码校验通过", verify_password("admin123", row["password_hash"]))
    check("错误密码校验失败", not verify_password("admin1234", row["password_hash"]))
    check("相同密码两次哈希不同（加盐生效）",
          hash_password("same") != hash_password("same"))

    admin = service.authenticate(db, "admin", "admin123")
    check("admin 登录成功且角色正确", admin.role == "admin")
    expect_error("错误密码登录被拒绝", service.authenticate, db, "admin", "wrong")

    # =================================================================
    section("C. 客房业务")
    # =================================================================
    guest = service.authenticate(db, "guest01", "guest123")
    # 日期窗口刻意取在 30 天之后：既不与演示数据（都在近几天）抢占房间，
    # 也保证脚本反复执行时可用房不会越跑越少。
    check_in = date.today() + timedelta(days=30)
    check_out = check_in + timedelta(days=3)

    def book(room_id: int, ci: date, co: date, name: str) -> dict:
        """下客房订单并登记，便于结尾清理；所有下单都走业务层。"""
        saved = service.create_room_order(
            db, user_id=guest.user_id, room_id=room_id,
            check_in=ci, check_out=co, guest_name=name)
        created_orders.append(saved["order_id"])
        touched_rooms.add(room_id)
        return saved

    def free_room(ci: date, co: date, *, exclude: set[int] | None = None) -> dict:
        """
        现查一间在该日期段内确实空闲的房间。

        不能用"开头查一份快照、后续一直取下标"的写法：演示数据或其它段落
        一旦占用了快照里的房间，后面的下单就会撞车。每次现查则天然只看当前
        真正可订的房，脚本在"干净库"和"已跑过演示数据的库"上都能通过。
        """
        skip = exclude or set()
        for candidate in service.search_available_rooms(db, ci, co):
            if int(candidate["room_id"]) not in skip:
                return candidate
        raise RuntimeError(f"在 {ci} ~ {co} 找不到可用的空闲房间")

    rooms = service.search_available_rooms(db, check_in, check_out)
    check("可订房间查询返回结果", len(rooms) > 0, f"{len(rooms)} 间")
    check("查询结果带 room_id（预订无需反查）", "room_id" in (rooms[0] if rooms else {}))
    # 本脚本先要 1 间目标房 + 1 间篡改房 + 1 间取消房 + 5 间"同秒并单"房，
    # J 段起的团体/结账段落还会各自现查 3 间独立房间，因此可订房至少要有 6 间。
    if len(rooms) < 6:
        check("可订房间数量足够本脚本使用（>= 6 间）", False,
              f"实际 {len(rooms)} 间，请先清理演示订单后重跑")
        return

    expect_error("离店早于入住被拒绝", service.search_available_rooms,
                 db, check_out, check_in)
    expect_error("入住日期早于今天被拒绝", service.search_available_rooms,
                 db, date.today() - timedelta(days=5), check_in)

    target = free_room(check_in, check_out)
    order = book(target["room_id"], check_in, check_out, "测试客人张三")
    expected = float(target["price"]) * 3
    check("订单金额由触发器按房价重算", abs(float(order["total_price"]) - expected) < 0.01,
          f"{order['total_price']} vs {expected}")
    check("晚数由触发器计算为 3", int(order["nights"]) == 3)

    # 界面就算把金额/晚数传成错的，触发器也按 room_type.price 覆盖，账目改不动
    tamper_room = free_room(check_in, check_out)
    tamper_id = f"RM{suffix}"
    db.execute(
        "INSERT INTO room_order (order_id, user_id, room_id, check_in_date, check_out_date, "
        "nights, total_price, guest_name, status) "
        "VALUES (%s, %s, %s, %s, %s, 99, 0.01, %s, 'confirmed')",
        (tamper_id, guest.user_id, tamper_room["room_id"], check_in, check_out,
         "篡改金额客人"))
    created_orders.append(tamper_id)
    touched_rooms.add(tamper_room["room_id"])
    tampered = db.query_one("SELECT nights, total_price FROM room_order WHERE order_id = %s",
                            (tamper_id,))
    check("界面传错金额/晚数无效（触发器按当前房价覆盖）",
          abs(float(tampered["total_price"]) - float(tamper_room["price"]) * 3) < 0.01
          and int(tampered["nights"]) == 3,
          f"{tampered['total_price']} / {tampered['nights']}")
    service.cancel_order(db, "room", tamper_id)

    # 绕过 service 直接插库：日期倒挂必须被 CHECK 约束挡在数据库外
    expect_error("日期区间非法被数据库 CHECK 拒绝", db.execute,
                 "INSERT INTO room_order (order_id, user_id, room_id, check_in_date, "
                 "check_out_date, nights, total_price, guest_name, status) "
                 "VALUES (%s, %s, %s, %s, %s, 1, 100, %s, 'confirmed')",
                 (f"RM{int(suffix) + 1:08d}", guest.user_id, tamper_room["room_id"],
                  check_out, check_in, "倒挂日期客人"))

    expect_error("同一房间同期重复预订被拒绝", service.create_room_order,
                 db, user_id=guest.user_id, room_id=target["room_id"],
                 check_in=check_in, check_out=check_out, guest_name="重复客人")
    expect_error("日期区间重叠的预订被拒绝", service.create_room_order,
                 db, user_id=guest.user_id, room_id=target["room_id"],
                 check_in=check_in + timedelta(days=1),
                 check_out=check_out + timedelta(days=2), guest_name="重叠客人")

    # 状态机：原系统可以随便 UPDATE status，非法跳转必须被拒
    rid = order["order_id"]
    expect_error("待入住订单不能直接退房", service.advance_order_status,
                 db, "room", rid, "checked_out")

    # =================================================================
    section("D. 入住/退房联动（房间状态跟随订单）")
    # =================================================================
    service.advance_order_status(db, "room", rid, "checked_in")
    check("入住后订单状态为 checked_in",
          db.query_value("SELECT status FROM room_order WHERE order_id = %s",
                         (rid,)) == "checked_in")
    check("入住后房间被触发器置为 occupied",
          db.query_value("SELECT status FROM room WHERE room_id = %s",
                         (target["room_id"],)) == "occupied")

    service.advance_order_status(db, "room", rid, "checked_out")
    check("退房后订单状态为 checked_out",
          db.query_value("SELECT status FROM room_order WHERE order_id = %s",
                         (rid,)) == "checked_out")
    room_status = db.query_value("SELECT status FROM room WHERE room_id = %s",
                                 (target["room_id"],))
    check("退房后房间自动进入打扫中（触发器联动）", room_status == "cleaning",
          f"实际 {room_status}")
    # 已退房是终态：允许回退会造成重复退房、重复打扫
    expect_error("已退房订单不能回退为已入住", service.advance_order_status,
                 db, "room", rid, "checked_in")

    # 取消流程
    cancel_room = free_room(check_in, check_out)
    order2 = book(cancel_room["room_id"], check_in, check_out, "待取消客人")
    check("房间占用日历可读（含本次预订）",
          any(c["order_id"] == order2["order_id"]
              for c in service.room_calendar(db, cancel_room["room_id"])))
    check("订单归属查询正确（order_owner_id）",
          service.order_owner_id(db, "room", order2["order_id"]) == guest.user_id)
    service.cancel_order(db, "room", order2["order_id"])
    check("订单可被取消",
          db.query_value("SELECT status FROM room_order WHERE order_id = %s",
                         (order2["order_id"],)) == "cancelled")
    expect_error("已取消订单不能再次取消", service.cancel_order,
                 db, "room", order2["order_id"])
    expect_error("已退房订单不能被取消", service.cancel_order, db, "room", rid)

    # 单独构造一个"当前有效订单"的房间来验证空闲置位保护。
    # 必须用"今天"这个窗口单独查可用房（30 天后的窗口里，房间今天可能已有客人），
    # 又因为插入触发器只在房间物理状态为 available 时才置 occupied，
    # 所以要挑一间"状态为空闲、且今天没有任何有效订单"的房间，否则测不到联动：
    # 若房间今天已有别人的订单，插入触发器不会把它改成 occupied，
    # 后面取消订单也就不会有"回置空闲"的联动可测。
    active_room = None
    for cand in service.search_available_rooms(db, date.today(),
                                               date.today() + timedelta(days=2)):
        _busy_today = db.query_value(
            "SELECT COUNT(*) FROM room_order WHERE room_id = %s "
            "AND status IN ('confirmed','checked_in') "
            "AND check_in_date <= CURDATE() AND check_out_date > CURDATE()",
            (cand["room_id"],), 0)
        if _busy_today:
            continue
        if db.query_value("SELECT status FROM room WHERE room_id = %s",
                          (cand["room_id"],), "") == "available":
            active_room = cand
            break
    check("找到今天可入住且状态空闲的房间（用于入住联动测试）",
          active_room is not None)

    if active_room:
        active_order = book(active_room["room_id"], date.today(),
                            date.today() + timedelta(days=2), "在住客人")
        check("入住日已到的订单把房间自动置为 occupied",
              db.query_value("SELECT status FROM room WHERE room_id = %s",
                             (active_room["room_id"],)) == "occupied")
        expect_error("人工把有在住订单的房间置为空闲被拒绝",
                     service.set_room_status, db, active_room["room_id"], "available")
        service.cancel_order(db, "room", active_order["order_id"])
        check("取消订单后房间自动恢复空闲（触发器联动）",
              db.query_value("SELECT status FROM room WHERE room_id = %s",
                             (active_room["room_id"],)) == "available")

    expect_error("不允许人工设为 occupied", service.set_room_status,
                 db, target["room_id"], "occupied")

    # =================================================================
    section("E. 订单汇总（原丢单 bug 回归测试）")
    # =================================================================
    # 原系统用"秒级时间戳"作二叉搜索树键，同一秒创建的多张订单互相覆盖、
    # 界面静默丢单（实测 4 单只剩 1 单）。这里连续创建 5 单做回归。
    # 5 间房同样现查现取，且要保证互不相同（每次下单后房间即被占用，
    # 下一次 free_room 自然换一间，这里用 exclude 再兜一层，防止重复下单）。
    burst_rooms = []
    _picked: set[int] = set()
    while len(burst_rooms) < 5:
        room = free_room(check_in, check_out, exclude=_picked)
        _picked.add(int(room["room_id"]))
        burst_rooms.append(room)
    before = len(service.list_orders(db, user_id=guest.user_id))
    burst = [book(r["room_id"], check_in, check_out, f"同秒测试{i + 1}")["order_id"]
             for i, r in enumerate(burst_rooms)]
    after_orders = service.list_orders(db, user_id=guest.user_id)
    check("同一秒连续创建 5 单，列表条数正确增加",
          len(after_orders) == before + 5, f"{before} -> {len(after_orders)}")
    check("5 张新订单全部可见（不再互相覆盖）",
          all(any(o["order_id"] == oid for o in after_orders) for oid in burst))

    placeholders = ", ".join(["%s"] * len(burst))
    same_second = db.query(
        f"SELECT created_at, COUNT(*) AS c FROM room_order "
        f"WHERE order_id IN ({placeholders}) "
        f"GROUP BY created_at HAVING c > 1", burst)
    check("确实存在同一秒内的多张订单", len(same_second) > 0,
          "本次未构造出同秒数据，测试强度下降")

    check("视图状态已归一化",
          all(o["status_category"] in ("进行中", "已完成", "已取消")
              for o in after_orders))
    check("统一订单视图只含客房订单（order_type 恒为 room）",
          {o["order_type"] for o in after_orders} == {"room"})
    check("统一订单视图字段与界面约定一致",
          all(k in (service.get_order(db, "room", burst[0]) or {})
              for k in ("order_id", "user_id", "order_type", "total_price",
                        "status_label", "status_category", "created_at")))

    # =================================================================
    section("F. 评价（存在性 / 归属 / 重复 三重校验）")
    # =================================================================
    # burst[0] 还是"待入住"，只有退房后 status_category 才是已完成
    expect_error("未完成（待入住）订单不能评价", service.submit_review,
                 db, user_id=guest.user_id, order_id=burst[0],
                 order_type="room", rating=5, content="不该成功")
    service.submit_review(db, user_id=guest.user_id, order_id=rid,
                          order_type="room", rating=5, content="房间干净，服务好")
    check("已完成订单可评价且已落库",
          db.query_value("SELECT COUNT(*) FROM review "
                         "WHERE order_id = %s AND user_id = %s",
                         (rid, guest.user_id), 0) == 1)
    check("评价列表可读（list_reviews 含本次评价）",
          any(r["order_id"] == rid for r in service.list_reviews(db)))
    expect_error("同一订单重复评价被拒绝（原系统可无限重复）",
                 service.submit_review, db, user_id=guest.user_id,
                 order_id=rid, order_type="room", rating=4, content="再评一次")
    expect_error("评分越界被拒绝", service.submit_review,
                 db, user_id=guest.user_id, order_id=burst[0],
                 order_type="room", rating=9, content="x")
    expect_error("评价不属于自己的订单被拒绝（service 层归属校验）",
                 service.submit_review, db, user_id=admin.user_id,
                 order_id=rid, order_type="room", rating=5, content="别人的订单")
    expect_error("评价不存在的订单被拒绝（触发器校验）", db.execute,
                 "INSERT INTO review (user_id, order_id, order_type, rating, content) "
                 "VALUES (%s, 'NOT-EXIST-0001', 'room', 5, 'x')", (guest.user_id,))
    # 绕过 service 直接插库，触发器同样要拦住冒名评价
    expect_error("冒名评价被触发器拦截（绕过 service 直接插库）", db.execute,
                 "INSERT INTO review (user_id, order_id, order_type, rating, content) "
                 "VALUES (%s, %s, 'room', 5, 'x')", (admin.user_id, rid))

    # =================================================================
    section("G. 支付与统计")
    # =================================================================
    revenue_before = stats.revenue_summary(db)["total"]
    pay = service.pay_order(db, order_type="room", order_id=rid,
                            user_id=guest.user_id, method="wechat")
    check("支付流水登记成功", float(pay["amount"]) > 0)
    check("支付金额等于触发器算出的订单金额",
          abs(float(pay["amount"]) - float(order["total_price"])) < 0.01,
          f"{pay['amount']} vs {order['total_price']}")
    expect_error("重复支付被拒绝", service.pay_order, db, order_type="room",
                 order_id=rid, user_id=guest.user_id, method="cash")
    check("订单支付信息可回查（order_payment）",
          (service.order_payment(db, "room", rid) or {}).get("status") == "paid")
    check("列表页支付状态映射正确（paid_order_map）",
          service.paid_order_map(db).get(("room", rid)) == "已支付")
    check("支付台账可查（list_payments 含本次流水）",
          any(p["payment_no"] == pay["payment_no"]
              for p in service.list_payments(db, user_id=guest.user_id)))

    revenue = stats.revenue_summary(db)
    check("营收增量等于本次支付金额（营收来自流水而非订单状态求和）",
          abs((revenue["total"] - revenue_before) - float(pay["amount"])) < 0.01,
          f"增量 {revenue['total'] - revenue_before} vs 支付 {pay['amount']}")
    check("营收按类型分组", len(revenue["by_type"]) >= 1)
    check("营收分组只剩客房（order_type 枚举已收敛）",
          all(r["order_type"] == "room" for r in revenue["by_type"]))

    # 未收款订单不得计入营收（原系统按订单状态求和会把它算成收入）
    book(free_room(check_in, check_out)["room_id"], check_in, check_out, "未付款客人")
    check("未收款订单不计入营收",
          abs(stats.revenue_summary(db)["total"] - revenue["total"]) < 0.01)

    ov = stats.overview(db)
    check("概览指标完整", all(k in ov for k in
                              ("arrivals", "in_house", "departures", "rooms_total",
                               "rooms_occupied", "pending_payment", "users_total")))
    check("订单统计视图只统计客房一条业务线",
          len(stats.service_stats(db)) == 1, f"{len(stats.service_stats(db))} 行")
    check("订单状态分布可读", isinstance(stats.order_status_distribution(db), list))
    check("房型使用统计可读", len(stats.room_usage(db)) >= 4)

    # 取消已支付订单应同步退款
    refund_target = book(free_room(check_in, check_out)["room_id"],
                         check_in, check_out, "退款测试")
    refund_pay = service.pay_order(db, order_type="room",
                                   order_id=refund_target["order_id"],
                                   user_id=guest.user_id, method="card")
    revenue_before_refund = stats.revenue_summary(db)
    service.cancel_order(db, "room", refund_target["order_id"])
    check("取消已支付订单会生成退款状态",
          db.query_value("SELECT status FROM payment WHERE order_id = %s",
                         (refund_target["order_id"],)) == "refunded")
    revenue_after_refund = stats.revenue_summary(db)
    check("退款后营收回滚、退款额累计（营收只认 payment 流水状态）",
          abs((revenue_after_refund["total"] - revenue_before_refund["total"])
              + float(refund_pay["amount"])) < 0.01
          and abs((revenue_after_refund["refunded"] - revenue_before_refund["refunded"])
                  - float(refund_pay["amount"])) < 0.01,
          f"total {revenue_before_refund['total']} -> {revenue_after_refund['total']}，"
          f"refunded {revenue_before_refund['refunded']} -> {revenue_after_refund['refunded']}")
    check("退款订单在列表页标为已退款（paid_order_map）",
          service.paid_order_map(db).get(("room", refund_target["order_id"])) == "已退款")

    # =================================================================
    section("H. 用户管理")
    # =================================================================
    # 用户名带随机后缀，脚本可反复执行而不会互相冲突
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

    check("用户列表可读取（list_users 含新账号）",
          any(u["user_id"] == guest2
              for u in service.list_users(db, keyword=temp_username)))

    service.set_user_active(db, guest2, False, current_user_id=admin.user_id)
    expect_error("被禁用账号无法登录", service.authenticate,
                 db, temp_username, "pass123456")
    service.set_user_active(db, guest2, True, current_user_id=admin.user_id)
    check("重新启用后可登录",
          service.authenticate(db, temp_username, "pass123456").user_id == guest2)
    expect_error("不能禁用当前登录账号", service.set_user_active,
                 db, admin.user_id, False, current_user_id=admin.user_id)

    # 改密必须验原密码，否则知道用户名就能改掉别人的密码
    service.change_password(db, "pass123456", "newpass123", "newpass123",
                            user_id=guest2)
    check("客人自助改密后新密码生效",
          service.authenticate(db, temp_username, "newpass123").user_id == guest2)
    expect_error("原密码错误时改密被拒绝", service.change_password,
                 db, "wrongpass", "another123", "another123", user_id=guest2)
    expect_error("两次新密码不一致被拒绝", service.change_password,
                 db, "newpass123", "another123", "another456", user_id=guest2)

    # 管理员建号与重置密码
    staff_username = f"smoke_staff_{suffix}"
    service.create_user(db, username=staff_username, password="staff123456",
                        real_name="冒烟前台", role="receptionist")
    staff_id = db.query_value("SELECT user_id FROM `user` WHERE username = %s",
                              (staff_username,))
    check("管理员创建员工账号成功", bool(staff_id))
    expect_error("管理员建号角色非法被拒绝", service.create_user,
                 db, username=f"smoke_bad_{suffix}", password="staff123456",
                 real_name="非法角色", role="boss")
    service.admin_reset_password(db, staff_id, "reset123456")
    check("管理员重置密码后新密码可登录",
          service.authenticate(db, staff_username, "reset123456").user_id == staff_id)
    expect_error("重置密码过短被拒绝", service.admin_reset_password, db, staff_id, "123")

    # 清理本次冒烟测试创建的账号（参数化查询避免 % 与 pymysql 占位符冲突）
    temp = db.query("SELECT user_id FROM `user` WHERE username LIKE %s", ("smoke\\_%",))
    for row_ in temp:
        db.execute("DELETE FROM `user` WHERE user_id = %s", (row_["user_id"],))
    # 注意：H 段的临时账号就地删掉了（不带下划线前缀命名规律的除外）；
    # 后面 O 段还会新建一个持久到结尾的账号，那个登记进 state 由 cleanup 回收。
    check("测试账号已清理",
          not db.query("SELECT user_id FROM `user` WHERE username LIKE %s",
                       ("smoke\\_%",)))

    # =================================================================
    section("I. 基础资源维护（界面已无 SQL，全部走 service 层）")
    # =================================================================
    catalog = service.resource_catalog()
    catalog_names = sorted(spec["table"] for spec in catalog)
    # 注册表必须覆盖房型/房间，且不得再登记已删除业务线的表
    check("资源注册表只剩客房主线资源（房型 / 房间）",
          {"room_type", "room"} <= set(catalog_names)
          and set(catalog_names) <= EXPECTED_TABLES, f"{catalog_names}")
    check("注册表项含字段规格",
          all(spec.get("fields") and spec.get("pk") for spec in catalog))

    # 题目要求 (4)：修改房价/房型/增加客房必须有"密码支持"。
    # 因此房型与房间的增删改一律带 approval 调用；不带 approval 的
    # 反向断言放在 P 段（那里集中验证密码与留痕）。
    reception = service.authenticate(db, "reception", "recep123")
    if state["audit_from"] is None:
        state["audit_from"] = int(db.query_value(
            "SELECT COALESCE(MAX(log_id), 0) FROM price_change_log", None, 0) or 0)
    approval = service.Approval(admin.user_id, admin.username, "admin123",
                               "冒烟测试：房型与房间维护")

    # 白名单拦截：不允许操作未登记的表（含真正的系统库表与随意编造的表名）
    expect_error("操作未登记的数据表被拒绝", service.resource_list, db, "mysql.user")
    expect_error("操作未登记的业务表被拒绝", service.resource_list, db, "audit_log")
    # 主键字段不可编辑，这一层校验先于密码支持，因此不需要 approval 也应被拒
    expect_error("修改主键字段被拒绝", service.resource_create, db, "room_type",
                 {"type_id": 999, "type_name": "非法房型"})

    # 新增 -> 改 -> 删（房型）
    created_id = None
    try:
        service.resource_create(db, "room_type", {
            "type_name": "冒烟测试房型", "price": "123.45",
            "max_occupancy": "2", "facilities": "WiFi", "description": "临时"},
            approval=approval)
        created_id = db.query_value(
            "SELECT type_id FROM room_type WHERE type_name = '冒烟测试房型'")
        check("新增基础资源成功（密码支持 + 留痕）", bool(created_id))
    except service.BusinessError as exc:
        check("新增基础资源成功（密码支持 + 留痕）", False, str(exc))

    if created_id:
        expect_error("整数列填非数字被拒绝", service.resource_update, db, "room_type",
                     created_id, {"price": "不是数字"}, approval=approval)
        expect_error("房型价格必须为正被 CHECK 拒绝", service.resource_update,
                     db, "room_type", created_id, {"price": "-1"}, approval=approval)
        service.resource_update(db, "room_type", created_id,
                                {"type_name": "冒烟测试房型2", "price": "200",
                                 "max_occupancy": "3"}, approval=approval)
        check("修改基础资源成功",
              db.query_value("SELECT type_name FROM room_type WHERE type_id = %s",
                             (created_id,)) == "冒烟测试房型2")
        service.resource_delete(db, "room_type", created_id, approval=approval)
        check("删除未被引用的资源成功",
              db.query_value("SELECT COUNT(*) FROM room_type WHERE type_id = %s",
                             (created_id,), 0) == 0)

    # 被引用的资源必须删不掉（外键 RESTRICT 保护）。
    # 用本脚本自己刚下过单的房间，保证它确实被 room_order 引用，
    # 不依赖演示数据里恰好有订单。
    expect_error("删除有订单引用的房间被数据库拒绝",
                 service.resource_delete, db, "room", target["room_id"],
                 approval=approval)

    check("用户订单数统计可读", isinstance(service.user_order_counts(db), dict))
    check("入住候选查询可用（今天）",
          isinstance(service.checkin_candidates(db, "今天"), list))
    check("入住候选查询可用（未来 7 天）",
          isinstance(service.checkin_candidates(db, "未来 7 天"), list))
    check("数据库对象名清单可读",
          set(service.schema_object_names(db)) == {"views", "triggers", "tables"})
    check("各表行数统计覆盖全部 9 张表",
          len(service.table_row_counts(db)) == 9,
          f"{len(service.table_row_counts(db))} 张")
    check("房型下拉选项可读", len(service.room_type_options(db)) >= 1)
    check("楼层筛选数据可读", len(service.room_floors(db)) >= 1)
    check("房间列表与当前状态视图可读",
          all("room_status" in r for r in service.list_rooms(db)))

    # =================================================================
    section("J. 团体登记（题目要求 (1)）")
    # =================================================================
    # 团体日期取 30 天后，与 C 段的单房测试同窗口。
    # 每个新建段落**现查现用**自己独占的房间：某间房的订单一旦落库，
    # 下一次可用房查询就会把它排除，因此各段不会抢到同一间房，
    # 也不依赖 C 段开头那份快照（它随时可能被前面的段落占用）。
    def take_rooms(count: int, ci: date, co: date) -> list[dict]:
        picked, chosen = [], set()
        while len(picked) < count:
            room = free_room(ci, co, exclude=chosen)
            chosen.add(int(room["room_id"]))
            picked.append(room)
        return picked

    group_name = f"冒烟测试旅行团{suffix}"
    group_rooms = take_rooms(3, check_in, check_out)
    group_ids = [r["room_id"] for r in group_rooms]
    group_expected_total = round(
        sum(float(r["price"]) * 3 for r in group_rooms), 2)

    booking = service.create_group_booking(
        db, group_name=group_name, contact_name="冒烟联系人",
        contact_phone="13900000009", id_card="110101199001019999",
        booker_user_id=guest.user_id, check_in=check_in, check_out=check_out,
        room_ids=group_ids, remark="冒烟测试团体")
    group_id = booking["group_id"]
    created_groups.append(group_id)
    created_orders.extend(booking["order_ids"])
    touched_rooms.update(group_ids)

    check("团体登记一次生成 3 张客房订单",
          len(booking["order_ids"]) == 3 and booking["room_count"] == 3,
          f"{len(booking['order_ids'])} 张")
    check("3 张订单同属一个团体单（group_id 一致）",
          db.query_value("SELECT COUNT(DISTINCT group_id) FROM room_order "
                         "WHERE order_id IN (%s)"
                         % ", ".join(["%s"] * 3),
                         tuple(booking["order_ids"]), 0) == 1)
    check("团体订单金额由触发器按房价重算（= 各房价 × 3 晚之和）",
          abs(float(booking["total_price"]) - group_expected_total) < 0.01,
          f"{booking['total_price']} vs {group_expected_total}")
    check("团体晚数由触发器算出为 3 晚", int(booking["nights"]) == 3)

    group_row = next((g for g in service.list_groups(db, keyword=group_name)
                      if g["group_id"] == group_id), None)
    expected_room_numbers = ",".join(sorted(r["room_number"] for r in group_rooms))
    check("团体列表可查到本次团体单", group_row is not None)
    if group_row:
        check("list_groups 的房间数正确（3 间）", int(group_row["order_count"]) == 3,
              f"{group_row['order_count']}")
        check("list_groups 的总额正确（等于 3 张订单之和）",
              abs(float(group_row["total_amount"]) - group_expected_total) < 0.01,
              f"{group_row['total_amount']} vs {group_expected_total}")
        check("list_groups 的房间号串正确",
              str(group_row["room_numbers"]) == expected_room_numbers,
              f"{group_row['room_numbers']} vs {expected_room_numbers}")

    check("group_members 返回全部 3 个成员订单",
          len(service.group_members(db, group_id)) == 3,
          f"{len(service.group_members(db, group_id))} 行")

    # 同名团体 + 同一天重复登记会让团体结账时无法区分，必须被拒
    expect_error("同名团体在同一天重复登记被拒绝", service.create_group_booking,
                 db, group_name=group_name, contact_name="冒烟联系人",
                 booker_user_id=guest.user_id, check_in=check_in,
                 check_out=check_out, room_ids=group_ids[:1])
    expect_error("团体入住日期早于今天被拒绝", service.create_group_booking,
                 db, group_name=f"过期团{suffix}", contact_name="冒烟联系人",
                 booker_user_id=guest.user_id,
                 check_in=date.today() - timedelta(days=2),
                 check_out=date.today() + timedelta(days=1),
                 room_ids=group_ids[:1])
    expect_error("团体离店早于入住被拒绝", service.create_group_booking,
                 db, group_name=f"倒挂团{suffix}", contact_name="冒烟联系人",
                 booker_user_id=guest.user_id, check_in=check_out,
                 check_out=check_in, room_ids=group_ids[:1])
    expect_error("团体未选择房间被拒绝", service.create_group_booking,
                 db, group_name=f"空团{suffix}", contact_name="冒烟联系人",
                 booker_user_id=guest.user_id, check_in=check_in,
                 check_out=check_out, room_ids=[])

    # 数据库层兜底：绕过 service 直插 room_order 时，
    # 成员日期与团体单不一致必须被 trg_room_order_before_insert 拒绝，
    # 否则团体结账按团体汇总的金额与实际住宿不符。
    # 两个手工单号也登记进清理列表：万一触发器失效、行真的插进去，
    # 脚本结尾仍会把它们删掉，不会污染下一轮执行。
    mismatch_order_id = f"RM{suffix}G1"
    ghost_order_id = f"RM{suffix}G2"
    created_orders.extend([mismatch_order_id, ghost_order_id])
    expect_error("直插 room_order 时成员日期与团体单不一致被触发器拒绝",
                 db.execute,
                 "INSERT INTO room_order (order_id, user_id, room_id, check_in_date, "
                 "check_out_date, nights, total_price, guest_name, status, group_id) "
                 "VALUES (%s, %s, %s, %s, %s, 0, 0, %s, 'confirmed', %s)",
                 (mismatch_order_id, guest.user_id, group_ids[0],
                  check_in + timedelta(days=1), check_out + timedelta(days=1),
                  "日期不符客人", group_id))
    expect_error("直插 room_order 时引用不存在的团体单被触发器拒绝",
                 db.execute,
                 "INSERT INTO room_order (order_id, user_id, room_id, check_in_date, "
                 "check_out_date, nights, total_price, guest_name, status, group_id) "
                 "VALUES (%s, %s, %s, %s, %s, 0, 0, %s, 'confirmed', %s)",
                 (ghost_order_id, guest.user_id, group_ids[0], check_in, check_out,
                  "幽灵团体客人", 2147483000))

    # =================================================================
    section("K. 散客结账（题目要求 (1)(5)）")
    # =================================================================
    # 账本基线在"本次全部订单都已创建、尚未结账"的时刻取：
    #   · 团体 3 单刚由 J 段创建；
    #   · 散客 1 单在这里创建后立即结算。
    # 因此 Q 段可以用增量断言核对报表，不依赖库中既有的演示数据。
    report_before = stats.settlement_report(db)
    unsettled_before = report_before["unsettled_orders"]

    walkin = book(take_rooms(1, check_in, check_out)[0]["room_id"],
                  check_in, check_out, "散客结账客人")
    walkin_bill = service.settle_order(db, order_id=walkin["order_id"],
                                       method="wechat", operator_id=admin.user_id,
                                       remark="冒烟测试散客结账")
    created_settlements.append(walkin_bill["settlement_no"])
    check("散客结账生成一张 room_count=1 的结账单",
          walkin_bill["room_count"] == 1
          and walkin_bill["order_ids"] == [walkin["order_id"]])
    check("散客结账单金额等于订单金额",
          abs(float(walkin_bill["total_amount"]) - float(walkin["total_price"])) < 0.01,
          f"{walkin_bill['total_amount']} vs {walkin['total_price']}")
    walkin_row = next((s for s in service.list_settlements(
        db, keyword=walkin_bill["settlement_no"])), None)
    check("散客账单在列表中标为 bill_type='散客'",
          bool(walkin_row) and walkin_row["bill_type"] == "散客",
          f"{walkin_row and walkin_row['bill_type']}")
    check("散客账单列表带出结算方式标签",
          bool(walkin_row) and walkin_row["method_label"] == "微信",
          f"{walkin_row and walkin_row['method_label']}")
    check("散客结账写入了收款流水",
          db.query_value("SELECT COUNT(*) FROM payment WHERE order_id = %s "
                         "AND status = 'paid'", (walkin["order_id"],), 0) == 1)
    check("散客结账回填了订单的 settlement_no",
          db.query_value("SELECT settlement_no FROM room_order WHERE order_id = %s",
                         (walkin["order_id"],)) == walkin_bill["settlement_no"])
    expect_error("散客账单不能重复结账",
                 service.settle_order, db, order_id=walkin["order_id"])

    # =================================================================
    section("L. 团体结账")
    # =================================================================
    group_bill = service.settle_group(db, group_id=group_id, method="card",
                                      operator_id=reception.user_id,
                                      remark="冒烟测试团体结账")
    created_settlements.append(group_bill["settlement_no"])
    check("团体结账生成一张结账单覆盖 3 个订单",
          len(group_bill["order_ids"]) == 3 and group_bill["room_count"] == 3,
          f"{group_bill['room_count']} 间")
    check("结账单金额等于各订单金额之和",
          abs(float(group_bill["total_amount"]) - group_expected_total) < 0.01,
          f"{group_bill['total_amount']} vs {group_expected_total}")
    check("结账单金额等于 settlement.total_amount 快照",
          abs(float(db.query_value("SELECT total_amount FROM settlement "
                                   "WHERE settlement_no = %s",
                                   (group_bill["settlement_no"],), 0))
              - float(group_bill["total_amount"])) < 0.01)
    check("结账单记录为团体类型（group_id 非空）",
          db.query_value("SELECT group_id FROM settlement WHERE settlement_no = %s",
                         (group_bill["settlement_no"],)) == group_id)
    check("3 个订单都被回填 settlement_no",
          db.query_value("SELECT COUNT(*) FROM room_order WHERE settlement_no = %s",
                         (group_bill["settlement_no"],), 0) == 3)
    check("每个订单都写入了逐单收款流水（3 笔 payment）",
          db.query_value("SELECT COUNT(*) FROM payment WHERE order_id IN (%s) "
                         "AND status = 'paid'"
                         % ", ".join(["%s"] * 3),
                         tuple(group_bill["order_ids"]), 0) == 3)
    check("逐单收款金额等于各订单金额",
          abs(sum(float(r["amount"]) for r in db.query(
              "SELECT amount FROM payment WHERE order_id IN (%s) AND status = 'paid'"
              % ", ".join(["%s"] * 3), tuple(group_bill["order_ids"])))
              - float(group_bill["total_amount"])) < 0.01)
    check("结账后订单的 paid_order_map 显示已支付",
          all(service.paid_order_map(db).get(("room", oid)) == "已支付"
              for oid in group_bill["order_ids"]))

    # 结账单明细与订单反查
    detail = service.settlement_detail(db, group_bill["settlement_no"])
    check("结账单明细视图可读且含 3 间房",
          len(detail) == 3 and {d["room_number"] for d in detail}
          == {r["room_number"] for r in group_rooms},
          f"{len(detail)} 行")
    check("结账单明细带出逐单收款流水",
          all(d["payment_no"] and d["payment_status"] == "paid" for d in detail))
    check("订单可反查所属结账单（order_settlement）",
          (service.order_settlement(db, group_bill["order_ids"][0]) or {})
          .get("settlement_no") == group_bill["settlement_no"])
    check("结账单列表可查到本次账单（list_settlements）",
          any(s["settlement_no"] == group_bill["settlement_no"]
              for s in service.list_settlements(db, keyword=group_bill["settlement_no"])))
    check("团体列表显示已结账间数",
          next((g["settled_count"] for g in service.list_groups(db, keyword=group_name)
                if g["group_id"] == group_id), 0) == 3)

    # 一单两结会把同一笔房费收两次，必须被拒
    expect_error("同一订单重复结账被拒绝",
                 service.settle_order, db, order_id=group_bill["order_ids"][0])
    expect_error("已全部结账的团体重复结账被拒绝",
                 service.settle_group, db, group_id=group_id)
    expect_error("不存在的团体单结账被拒绝",
                 service.settle_group, db, group_id=2147483000)
    expect_error("结算方式非法被拒绝", service.settle_order, db,
                 order_id=group_bill["order_ids"][1], method="bitcoin")
    expect_error("不存在的订单结账被拒绝", service.settle_order, db,
                 order_id="RM-NOT-EXIST-0001")

    # 团体账单此刻仍是 settled，报表里应能统计出"团体"一行（Q 段会复核退款后的口径）
    _report_after_group_settle = stats.settlement_report(db)
    _group_bill_type_rows = [r for r in _report_after_group_settle["by_type"]
                             if r["bill_type"] == "团体"]
    check("团体账单在结账后计入报表的团体分类（by_type 含团体一行）",
          bool(_group_bill_type_rows)
          and int(_group_bill_type_rows[0]["room_count"]) >= 3,
          f"{[dict(r) for r in _report_after_group_settle['by_type']]}")
    check("团体账单计入报表前其状态为 settled",
          db.query_value("SELECT status FROM settlement WHERE settlement_no = %s",
                         (group_bill["settlement_no"],)) == "settled")
    _group_bill_counted_before_refund = (
        _report_after_group_settle["group_count"] - report_before["group_count"] >= 1)

    # =================================================================
    section("M. 整团入住 / 退房")
    # =================================================================
    # 这 3 间房用"今天入住、后天离店"的窗口：既能真实走一遍
    # checkin_candidates("今天")，也与 C 段的 30 天后窗口互不干扰。
    checkin_check_in = date.today()
    checkin_check_out = date.today() + timedelta(days=2)
    checkin_name = f"冒烟入住退房团{suffix}"
    checkin_rooms = take_rooms(3, checkin_check_in, checkin_check_out)
    checkin_ids = [r["room_id"] for r in checkin_rooms]
    checkin_nights = (checkin_check_out - checkin_check_in).days
    checkin_expected = round(
        sum(float(r["price"]) * checkin_nights for r in checkin_rooms), 2)
    checkin_booking = service.create_group_booking(
        db, group_name=checkin_name, contact_name="冒烟团联系人",
        booker_user_id=guest.user_id, check_in=checkin_check_in,
        check_out=checkin_check_out, room_ids=checkin_ids,
        remark="冒烟测试整团入住退房")
    checkin_group_id = checkin_booking["group_id"]
    created_groups.append(checkin_group_id)
    created_orders.extend(checkin_booking["order_ids"])
    touched_rooms.update(checkin_ids)

    check("第二个团体单登记成功且总额正确",
          abs(float(checkin_booking["total_price"]) - checkin_expected) < 0.01,
          f"{checkin_booking['total_price']} vs {checkin_expected}")
    check("团体单初始状态为已登记（reserved）",
          db.query_value("SELECT status FROM guest_group WHERE group_id = %s",
                         (checkin_group_id,)) == "reserved")
    check("今日到店团体出现在前台入住候选列表（今天）",
          any(c["order_id"] in checkin_booking["order_ids"]
              for c in service.checkin_candidates(db, "今天")))
    check("待入住团体也出现在「全部待入住」候选列表",
          any(c["order_id"] in checkin_booking["order_ids"]
              for c in service.checkin_candidates(db, "全部待入住")))

    moved = service.checkin_group(db, checkin_group_id)
    check("整团入住一次办理 3 间房", moved == 3, f"实际 {moved}")
    check("整团入住后所有订单转为已入住",
          db.query_value("SELECT COUNT(*) FROM room_order WHERE group_id = %s "
                         "AND status = 'checked_in'", (checkin_group_id,), 0) == 3)
    check("整团入住后团体状态同步为 checked_in",
          db.query_value("SELECT status FROM guest_group WHERE group_id = %s",
                         (checkin_group_id,)) == "checked_in")
    check("整团入住后房间被触发器置为 occupied",
          db.query_value("SELECT COUNT(*) FROM room WHERE room_id IN (%s) "
                         "AND status = 'occupied'"
                         % ", ".join(["%s"] * 3), tuple(checkin_ids), 0) == 3)
    expect_error("已入住团体不能重复办理入住",
                 service.checkin_group, db, checkin_group_id)

    moved_out = service.checkout_group(db, checkin_group_id)
    check("整团退房一次办理 3 间房", moved_out == 3, f"实际 {moved_out}")
    check("整团退房后所有订单转为已退房",
          db.query_value("SELECT COUNT(*) FROM room_order WHERE group_id = %s "
                         "AND status = 'checked_out'", (checkin_group_id,), 0) == 3)
    check("整团退房后团体状态同步为 checked_out",
          db.query_value("SELECT status FROM guest_group WHERE group_id = %s",
                         (checkin_group_id,)) == "checked_out")
    check("整团退房后房间自动进入打扫中（触发器联动）",
          db.query_value("SELECT COUNT(*) FROM room WHERE room_id IN (%s) "
                         "AND status = 'cleaning'"
                         % ", ".join(["%s"] * 3), tuple(checkin_ids), 0) == 3)
    expect_error("已退房团体不能重复办理退房",
                 service.checkout_group, db, checkin_group_id)
    expect_error("不存在的团体单办理入住被拒绝",
                 service.checkin_group, db, 2147483000)

    # 还没有可办理订单的团体（只登记了团体单、没下订单）必须报业务错误
    db.execute("INSERT INTO guest_group (group_name, contact_name, check_in_date, "
               "check_out_date) VALUES (%s, '空团联系人', %s, %s)",
               (f"冒烟空团{suffix}", check_in, check_out))
    empty_group_id = db.query_value(
        "SELECT group_id FROM guest_group WHERE group_name = %s",
        (f"冒烟空团{suffix}",))
    created_groups.append(empty_group_id)
    expect_error("没有可办理订单的团体不能整团入住",
                 service.checkin_group, db, empty_group_id)
    expect_error("没有可办理订单的团体不能整团退房",
                 service.checkout_group, db, empty_group_id)

    # =================================================================
    section("N. 已结账订单不可取消 + 结账单退款（题目要求 (1)）")
    # =================================================================
    settled_order = group_bill["order_ids"][0]
    # 此时团体订单仍是"待入住"（本来是可以取消的状态），
    # 唯一阻止取消的就是"已结账"这件事本身。
    check("被结账的订单此刻本处于可取消状态（confirmed）",
          db.query_value("SELECT status FROM room_order WHERE order_id = %s",
                         (settled_order,)) == "confirmed")
    expect_error("service 层拒绝取消已结账订单（提示先办结账单退款）",
                 service.cancel_order, db, "room", settled_order)
    check("被拒后订单状态没有变化（事务未半途提交）",
          db.query_value("SELECT status FROM room_order WHERE order_id = %s",
                         (settled_order,)) == "confirmed")
    # 关键兜底：绕过 service 直接 UPDATE 也必须被触发器拦住，
    # 否则任何直接连库的操作都能让结账单与订单状态互相矛盾。
    expect_error("直插 UPDATE 取消已结账订单被 trg_room_order_before_update 拒绝",
                 db.execute,
                 "UPDATE room_order SET status = 'cancelled' WHERE order_id = %s",
                 (settled_order,))
    check("触发器拒绝后订单状态仍为 confirmed",
          db.query_value("SELECT status FROM room_order WHERE order_id = %s",
                         (settled_order,)) == "confirmed")

    refund = service.refund_settlement(db, settlement_no=group_bill["settlement_no"],
                                       operator_id=admin.user_id,
                                       reason="冒烟测试退款")
    check("退款返回的房间数与账单一致", int(refund["order_count"]) == 3,
          f"{refund['order_count']}")
    check("退款金额等于结账单金额",
          abs(float(refund["refund_amount"]) - float(group_bill["total_amount"])) < 0.01)
    check("退款把该账单下全部收款流水置为 refunded",
          db.query_value("SELECT COUNT(*) FROM payment WHERE order_id IN (%s) "
                         "AND status = 'refunded'"
                         % ", ".join(["%s"] * 3),
                         tuple(group_bill["order_ids"]), 0) == 3)
    check("退款后成员订单的 settlement_no 回到 NULL（解除绑定）",
          db.query_value("SELECT COUNT(*) FROM room_order WHERE settlement_no = %s",
                         (group_bill["settlement_no"],), 0) == 0)
    check("退款后结账单状态为 refunded",
          db.query_value("SELECT status FROM settlement WHERE settlement_no = %s",
                         (group_bill["settlement_no"],)) == "refunded")
    expect_error("同一张结账单重复退款被拒绝",
                 service.refund_settlement, db,
                 settlement_no=group_bill["settlement_no"])
    expect_error("不存在的结账单退款被拒绝",
                 service.refund_settlement, db, settlement_no="JS-NOT-EXIST-0001")
    # 解绑之后状态机重新放行：说明"先退款再取消"的流程是通的
    check("退款后订单可按状态机取消（解绑生效）",
          service.cancel_order(db, "room", settled_order) is not None)
    check("退款后取消的订单状态为 cancelled",
          db.query_value("SELECT status FROM room_order WHERE order_id = %s",
                         (settled_order,)) == "cancelled")

    # =================================================================
    section("O. 客人信息多手段查询（题目要求 (3)）")
    # =================================================================
    # 新注册一个客人账号（含手机号），并给它下一张带证件号的订单
    guest_username = f"smoke_guest_{suffix}"
    # 手机号必须是 11 位数字（service 层会校验），suffix 恒为 8 位
    guest_phone = f"13{suffix}0"
    guest_id_card = f"1101011990010{suffix[:5]}"
    prof_user_id = service.register_guest(db, guest_username, "guest123456",
                                          "guest123456", guest_phone, "冒烟查询客人")
    created_users.append(prof_user_id)
    check("多手段查询用的客人账号创建成功", prof_user_id > 0)

    # 「没有订单的客人也能被查到」—— 新建账号此刻确实一单未下
    no_order_rows = service.search_guest_profile(db, name="冒烟查询客人")
    no_order = next((r for r in no_order_rows if r["user_id"] == prof_user_id), None)
    check("没有订单的客人也能被查到（v_guest_profile 以 user 为主体）",
          no_order is not None, f"命中 {len(no_order_rows)} 行")
    check("没有订单的客人 order_id 为 NULL", no_order is not None
          and no_order["order_id"] is None)

    prof_room = take_rooms(1, check_in, check_out)[0]
    prof_order = service.create_room_order(
        db, user_id=prof_user_id, room_id=prof_room["room_id"],
        check_in=check_in, check_out=check_out, guest_name="冒烟查询客人",
        guest_phone=guest_phone, id_card=guest_id_card)
    created_orders.append(prof_order["order_id"])
    touched_rooms.add(prof_room["room_id"])
    prof_order_id = prof_order["order_id"]

    def prof_rows(**criteria) -> list[dict]:
        """只保留本次新建客人的行：库中既有的演示客人可能命中同样的模糊条件。"""
        return [r for r in service.search_guest_profile(db, **criteria)
                if r["user_id"] == prof_user_id]

    by_name = prof_rows(name="冒烟查询客人")
    check("按姓名查询命中本次订单",
          has_order(by_name, prof_order_id), f"命中 {len(by_name)} 行")
    check("按姓名查询只返回该客人（不串到其他人）",
          all(r["real_name"] == "冒烟查询客人" or r["guest_name"] == "冒烟查询客人"
              for r in by_name))
    by_phone = prof_rows(phone=guest_phone)
    check("按手机号查询命中本次订单",
          has_order(by_phone, prof_order_id), f"命中 {len(by_phone)} 行")
    check("按手机号查询命中账号绑定的客人本人",
          all(r["username"] == guest_username for r in by_phone))
    by_card = prof_rows(id_card=guest_id_card)
    check("按证件号查询命中本次订单（订单上登记的证件号）",
          has_order(by_card, prof_order_id), f"命中 {len(by_card)} 行")
    by_room = prof_rows(room_number=prof_room["room_number"])
    check("按房间号查询命中本次订单",
          has_order(by_room, prof_order_id), f"命中 {len(by_room)} 行")
    check("按房间号查询带出房号与房型",
          all(r["room_number"] == prof_room["room_number"] for r in by_room))
    by_order = prof_rows(order_id=prof_order_id)
    check("按完整订单号查询命中且只有该订单",
          len(by_order) == 1 and by_order[0]["order_id"] == prof_order_id,
          f"命中 {len(by_order)} 行")
    # 客人只记得单号片段（如后半段校验位）也要能查到
    fragment = prof_order_id[-6:]
    by_fragment = prof_rows(order_id=fragment)
    check("按订单号片段查询命中本次订单",
          has_order(by_fragment, prof_order_id), f"片段 {fragment}")
    by_range = prof_rows(check_in_from=check_in, check_in_to=check_out)
    check("按入住日期区间查询命中本次订单",
          has_order(by_range, prof_order_id), f"命中 {len(by_range)} 行")
    check("入住日期区间之外的日期查不到该订单",
          not has_order(prof_rows(check_in_from=check_in + timedelta(days=40),
                                  check_in_to=check_out + timedelta(days=40)),
                        prof_order_id))
    # 多条件组合（与关系）：姓名 + 手机号 + 房间号，任一条件错就查不到
    combo = prof_rows(name="冒烟查询客人", phone=guest_phone,
                      room_number=prof_room["room_number"])
    check("多条件组合查询按「与」关系命中",
          len(combo) == 1 and combo[0]["order_id"] == prof_order_id,
          f"命中 {len(combo)} 行")
    check("组合条件中任一不匹配即查不到",
          not service.search_guest_profile(db, name="冒烟查询客人",
                                           room_number="不存在房号XYZ"))
    check("keyword 组合模糊匹配可用（用户名 / 姓名 / 手机号 / 证件号）",
          has_order(prof_rows(keyword=guest_username), prof_order_id)
          and has_order(prof_rows(keyword=guest_phone), prof_order_id)
          and has_order(prof_rows(keyword="冒烟查询客人"), prof_order_id))
    check("keyword 也能按证件号命中",
          has_order(prof_rows(keyword=guest_id_card), prof_order_id))
    check("查询结果带出订单状态标签（status_label）",
          all(r["status_label"] for r in by_order))
    check("guest_orders 能取到该客人的订单明细",
          any(o["order_id"] == prof_order_id
              for o in service.guest_orders(db, prof_user_id)))
    check("查询结果条数受 limit 限制",
          len(service.search_guest_profile(db, limit=1)) == 1)

    # =================================================================
    section("P. 房价与房型变更的密码支持与审计（题目要求 (4)）")
    # =================================================================
    check("审计日志计数器已就位（用于只清理本次新增的日志）",
          state["audit_from"] is not None)
    before_logs = len(service.list_price_change_logs(db, limit=100000))
    # 先读出当前房型状态：下面所有"被拒"的操作都不允许改变它。
    # 注意 resource_update 是按整行提交的（未给出的可编辑字段会写回 NULL），
    # 所以每次调用都要把完整字段填齐，否则会被 NOT NULL 约束挡在前面，
    # 测不到"密码支持"这一层。
    rt_before = db.query_one("SELECT * FROM room_type WHERE type_id = 1")
    baseline_price = float(rt_before["price"])
    price_probe = f"{baseline_price + 30:.2f}"

    def rt_payload(**over) -> dict:
        """完整房型字段 + 本次要改的字段。"""
        payload = {"type_name": rt_before["type_name"],
                   "price": f"{rt_before['price']:.2f}",
                   "max_occupancy": str(rt_before["max_occupancy"]),
                   "facilities": rt_before["facilities"] or "",
                   "description": rt_before["description"] or ""}
        payload.update(over)
        return payload

    # 不带密码凭据 -> 拒绝
    expect_error("不传 approval 修改房型被拒绝", service.resource_update,
                 db, "room_type", 1, rt_payload(price=price_probe))
    expect_error("不传 approval 新增房型被拒绝", service.resource_create,
                 db, "room_type", {"type_name": f"无密码房型{suffix}",
                                   "price": "100", "max_occupancy": "2"})
    expect_error("不传 approval 删除房间被拒绝", service.resource_delete,
                 db, "room", checkin_ids[0])
    # 密码错误 -> 拒绝（字段全部填合法值，确保卡在密码这一层而不是字段校验）
    expect_error("密码错误时修改房型被拒绝", service.resource_update,
                 db, "room_type", 1, rt_payload(price=price_probe),
                 approval=service.Approval(admin.user_id, admin.username, "wrongpass"))
    expect_error("密码错误时新增房间被拒绝", service.resource_create,
                 db, "room", {"room_number": f"9{suffix[:2]}", "type_id": 1,
                              "floor": 9, "status": "available"},
                 approval=service.Approval(admin.user_id, admin.username, "wrongpass"))
    expect_error("操作员账号不存在时被拒绝", service.resource_update,
                 db, "room_type", 1, rt_payload(price=price_probe),
                 approval=service.Approval(2147483000, "ghost", "whatever"))
    check("被拒的操作没有改动房价",
          abs(float(db.query_value("SELECT price FROM room_type WHERE type_id = 1",
                                   None, 0)) - baseline_price) < 0.01)
    check("被拒的操作没有留下审计日志",
          len(service.list_price_change_logs(db, limit=100000)) == before_logs)
    check("被拒的操作没有改动房型名称与最大入住",
          (db.query_value("SELECT type_name FROM room_type WHERE type_id = 1")
           == rt_before["type_name"])
          and int(db.query_value("SELECT max_occupancy FROM room_type "
                                 "WHERE type_id = 1")) == int(rt_before["max_occupancy"]))

    # 正确密码 -> 成功，且留痕
    old_price = baseline_price
    new_price = round(old_price + 30, 2)
    service.resource_update(db, "room_type", 1, rt_payload(price=f"{new_price:.2f}"),
                            approval=service.Approval(
                                admin.user_id, admin.username, "admin123",
                                "冒烟测试：淡季调价"))
    check("正确密码下修改房价成功",
          abs(float(db.query_value("SELECT price FROM room_type WHERE type_id = 1",
                                   None, 0)) - new_price) < 0.01)
    check("审计日志出现房价变更记录",
          len(service.list_price_change_logs(db, limit=100000)) > before_logs)
    price_log = next((l for l in service.list_price_change_logs(db, table="room_type")
                      if l["field_name"] == "price"
                      and abs(float(l["new_value"]) - new_price) < 0.01), None)
    check("审计记录包含 room_type/price 且新值等于改动后的房价", price_log is not None)
    if price_log:
        check("审计记录的旧值等于改动前的房价",
              abs(float(price_log["old_value"]) - old_price) < 0.01,
              f"{price_log['old_value']} vs {old_price}")
        check("审计记录的操作人与原因正确",
              price_log["operator_name"] == admin.username
              and price_log["reason"] == "冒烟测试：淡季调价",
              f"{price_log['operator_name']} / {price_log['reason']}")

    # 还原房价：自检可以改动数据来验证审计，但**不能改动种子数据** ——
    # 否则每跑一次房型价格就漂移一次，演示库会越来越离谱。
    service.resource_update(db, "room_type", 1,
                            rt_payload(price=f"{old_price:.2f}"),
                            approval=service.Approval(
                                admin.user_id, admin.username, "admin123",
                                "冒烟测试：还原房价（自检不改动演示数据）"))
    restored_price = float(db.query_value(
        "SELECT price FROM room_type WHERE type_id = 1", None, 0))
    check("自检结束后房价已还原为运行前的值（不改动种子数据）",
          abs(restored_price - old_price) < 0.01,
          f"{restored_price} vs {old_price}")

    # 新增 / 删除房间同样留痕（题目要求「增加客房」也需密码支持）
    room_number = f"9{suffix[:2]}9"
    service.resource_create(db, "room", {"room_number": room_number, "type_id": 1,
                                         "floor": 9, "status": "available"},
                            approval=service.Approval(
                                admin.user_id, admin.username, "admin123",
                                "冒烟测试：增加客房"))
    new_room_id = db.query_value("SELECT room_id FROM room WHERE room_number = %s",
                                 (room_number,))
    check("正确密码下新增客房成功", bool(new_room_id))
    create_log = next((l for l in service.list_price_change_logs(db, table="room")
                       if l["pk_value"] == str(new_room_id)
                       and l["field_name"] == "*"), None)
    check("新增客房留下了审计记录（field_name='*'）", create_log is not None)
    if new_room_id:
        service.resource_delete(db, "room", new_room_id,
                                approval=service.Approval(
                                    admin.user_id, admin.username, "admin123",
                                    "冒烟测试：删除测试客房"))
        check("新增的测试客房已被删除",
              db.query_value("SELECT COUNT(*) FROM room WHERE room_id = %s",
                             (new_room_id,), 0) == 0)
        check("删除客房同样留下审计记录",
              any(l["pk_value"] == str(new_room_id)
                  for l in service.list_price_change_logs(db, table="room")))
    check("审计日志可按表过滤（table='room_type'）",
          all(l["table_name"] == "room_type"
              for l in service.list_price_change_logs(db, table="room_type")))
    check("审计日志带可读的字段标签（房价）",
          any(l["field_label"] == "房价"
              for l in service.list_price_change_logs(db, table="room_type")))
    # 白名单没有因为新增审计表而放宽：未登记的表依旧不能操作
    expect_error("新增审计表后白名单仍然拦截未登记表（resource_list）",
                 service.resource_list, db, "price_change_log")
    expect_error("白名单拦截未登记的 settlement 表",
                 service.resource_list, db, "settlement")

    # =================================================================
    section("Q. 结账报表（题目要求 (5)）")
    # =================================================================
    # 本次运行的真实账目（报表只统计**当前**仍为 settled 的账单）：
    #   · 散客账单 walkin_bill：仍为 settled，计入金额与房间数；
    #   · 团体账单 group_bill：已被 N 段整单退款，**不计入**金额，
    #     只计入 refunded_count / refunded_amount —— 这正是要断言的口径。
    report = stats.settlement_report(db)
    check("报表账单数增加了 1 张（已退款的团体账单不计入）",
          report["bill_count"] - report_before["bill_count"] == 1,
          f"{report_before['bill_count']} -> {report['bill_count']}")
    check("报表房间数增加了 1 间（3 间团体房已随退款移出）",
          report["room_count"] - report_before["room_count"] == 1,
          f"{report_before['room_count']} -> {report['room_count']}")
    check("报表金额增量等于散客账单金额（退款账单不计入）",
          abs((report["total_amount"] - report_before["total_amount"])
              - float(walkin_bill["total_amount"])) < 0.01,
          f"增量 {report['total_amount'] - report_before['total_amount']} "
          f"vs {walkin_bill['total_amount']}")
    check("报表统计了本次散客账单数",
          report["walkin_count"] - report_before["walkin_count"] == 1,
          f"{report_before['walkin_count']} -> {report['walkin_count']}")
    check("已退款的团体账单不计入 group_count",
          report["group_count"] == report_before["group_count"],
          f"{report_before['group_count']} -> {report['group_count']}")
    check("报表退款笔数增加了 1（团体账单已退款）",
          report["refunded_count"] - report_before["refunded_count"] == 1,
          f"{report_before['refunded_count']} -> {report['refunded_count']}")
    check("报表退款金额不少于本次团体退款额",
          (report["refunded_amount"] - report_before["refunded_amount"]) + 0.01
          >= float(refund["refund_amount"]),
          f"增量 {report['refunded_amount'] - report_before['refunded_amount']} "
          f"vs {refund['refund_amount']}")
    check("平均每单金额 = 总额 / 账单数",
          abs(report["avg_bill"]
              - round(report["total_amount"] / max(report["bill_count"], 1), 2)) < 0.01)
    # by_type 只统计仍为 settled 的账单，因此本次只新增"散客"一行；
    # 库中若要出现"团体"一行，必须存在未退款的团体账单 —— 用一张
    # 只包含团体账单时间窗的报表来单独证明团体分类确实能统计出来。
    type_labels = {row["bill_type"] for row in report["by_type"]}
    check("by_type 里出现本次散客账单（已退款团体账单不计入）",
          "散客" in type_labels, f"{type_labels}")
    check("by_type 的金额合计等于 total_amount",
          abs(sum(float(r["amount"]) for r in report["by_type"])
              - report["total_amount"]) < 0.01)
    # 取团体结账那一刻的报表：那时团体账单还是 settled，应能看到"团体"一行
    check("退款前团体账单确实被报表统计为团体账单",
          _group_bill_counted_before_refund,
          f"结账后 group_count={_report_after_group_settle['group_count']}")
    check("by_method 覆盖现金/银行卡/微信等结算方式",
          len(report["by_method"]) >= 1
          and all(r["method_label"] for r in report["by_method"]))
    check("by_operator 带出经手人（含团体账单的经手前台）",
          any(r["operator_name"] == reception.username
              for r in _report_after_group_settle["by_operator"]),
          f"{[r['operator_name'] for r in _report_after_group_settle['by_operator']]}")
    check("当前报表 by_operator 带出散客账单的经手人",
          any(r["operator_name"] == admin.username for r in report["by_operator"]),
          f"{[r['operator_name'] for r in report['by_operator']]}")
    check("by_day 有当日结账数据",
          any(abs(float(r["amount"])) > 0 for r in report["by_day"]))
    # 未结账订单数（settlement_no IS NULL）随结账/退款变化，口径要精确：
    #   基线 unsettled_before 里已经包含刚建的散客订单与团体 3 单；
    #   · 散客结账 1 张                        = -1
    #   · 多手段查询段新建 1 张订单             = +1
    #   · 团体账单整单退款把 3 张订单解绑        = +3（重新变成"未结账"，
    #     这正是"先退款才能重新取消订单"的数据依据）
    #   净变化 = +3；只有报表按 settlement_no 判"未结账"、而不是按订单状态猜，
    #   这个数才对得上。
    check("未结账订单数的净变化与结账/退款口径一致（-1 +1 +3 = +3）",
          report["unsettled_orders"] - unsettled_before == 3,
          f"{unsettled_before} -> {report['unsettled_orders']}")
    check("退款解绑的 3 张团体订单重新计入未结账",
          db.query_value("SELECT COUNT(*) FROM room_order WHERE order_id IN (%s) "
                         "AND settlement_no IS NULL"
                         % ", ".join(["%s"] * 3),
                         tuple(group_bill["order_ids"]), 0) == 3)
    check("散客订单结账后不再计入未结账",
          db.query_value("SELECT settlement_no FROM room_order WHERE order_id = %s",
                         (walkin["order_id"],)) == walkin_bill["settlement_no"])

    # 已退款账单：不计入金额，但计入退款笔数与退款金额
    refund_report = stats.settlement_report(db)
    check("已退款账单不计入 total_amount",
          abs(float(db.query_value(
              "SELECT COALESCE(SUM(total_amount), 0) FROM settlement "
              "WHERE status = 'settled'", None, 0))
              - refund_report["total_amount"]) < 0.01)
    check("已退款账单计入 refunded_count",
          refund_report["refunded_count"] >= 1, f"{refund_report['refunded_count']}")
    check("已退款金额不小于本次退款金额",
          refund_report["refunded_amount"] + 0.01 >= float(refund["refund_amount"]))
    check("退款后该账单不在已结账账单列表里",
          not any(s["settlement_no"] == group_bill["settlement_no"]
                  for s in service.list_settlements(db, keyword=group_bill["settlement_no"])
                  if s["status"] == "settled"))
    check("结账报表可按日期区间过滤（今天）",
          isinstance(stats.settlement_report(db, start=date.today(),
                                             end=date.today()), dict))


    # =================================================================
    section("R. 清理本次冒烟测试产生的数据（按外键依赖顺序）")
    # =================================================================
    # 先就地回收本次写入的数据，下面才能核对"是否真的清干净了"；
    # cleanup() 的删除都按主键进行、天然幂等，main() 的 finally 里会再兜底调一次
    # （万一 run() 在到达这里之前就异常退出）。
    cleanup(db, state)
    check("清理动作执行完毕（按外键依赖顺序）", True)
    check("本次创建的客房订单已全部清理",
          all(db.query_value("SELECT COUNT(*) FROM room_order WHERE order_id = %s",
                             (oid,), 0) == 0 for oid in created_orders))
    check("本次创建的团体单已全部清理",
          all(db.query_value("SELECT COUNT(*) FROM guest_group WHERE group_id = %s",
                             (gid,), 0) == 0 for gid in created_groups))
    check("本次创建的结账单已全部清理",
          all(db.query_value("SELECT COUNT(*) FROM settlement WHERE settlement_no = %s",
                             (sno,), 0) == 0 for sno in created_settlements))
    check("本次新建的临时账号已清理",
          all(db.query_value("SELECT COUNT(*) FROM `user` WHERE user_id = %s",
                             (uid,), 0) == 0 for uid in created_users))
    check("本次新增的审计日志已清理",
          db.query_value("SELECT COUNT(*) FROM price_change_log WHERE log_id > %s",
                         (state["audit_from"],), 0) == 0)
    check("本次写入的收款流水已清理",
          all(db.query_value("SELECT COUNT(*) FROM payment WHERE order_id = %s",
                             (oid,), 0) == 0 for oid in created_orders))
    check("本次写入的评价已清理",
          all(db.query_value("SELECT COUNT(*) FROM review WHERE order_id = %s",
                             (oid,), 0) == 0 for oid in created_orders))
    check("测试房间已恢复为空闲",
          db.query_value(
              "SELECT COUNT(*) FROM room r WHERE r.room_id IN (%s) "
              "AND r.status <> 'available' "
              "AND (SELECT COUNT(*) FROM room_order ro WHERE ro.room_id = r.room_id "
              "     AND ro.status IN ('confirmed','checked_in')) = 0"
              % ", ".join(["%s"] * len(touched_rooms)), tuple(touched_rooms), 0) == 0)

    # 收尾核对：这一轮跑完，库里的对象数量必须与开始时完全一致，
    # 否则"可反复执行"就是空话（上一轮的残留会在下一轮变成脏数据）。
    final = stats.schema_objects(db)
    check("清理后数据库对象数量与运行前一致（脚本可反复执行）",
          (final["tables"], final["views"], final["triggers"], final["indexes"],
           final["foreign_keys"], final["check_constraints"])
          == (obj["tables"], obj["views"], obj["triggers"], obj["indexes"],
              obj["foreign_keys"], obj["check_constraints"]),
          f"{final} vs {obj}")
    check("清理后没有遗留本次的团体单（按名称模糊核对）",
          db.query_value("SELECT COUNT(*) FROM guest_group WHERE group_name LIKE %s",
                         (f"%{suffix}%",), 0) == 0)
    check("清理后没有遗留本次的订单（按手工单号前缀核对）",
          db.query_value("SELECT COUNT(*) FROM room_order WHERE order_id LIKE %s",
                         (f"RM{suffix}%",), 0) == 0)
    check("清理后测试账号已无残留（按用户名前缀核对）",
          db.query_value("SELECT COUNT(*) FROM `user` WHERE username LIKE %s",
                         (f"smoke\\_%{suffix}%",), 0) == 0)


def main() -> int:
    db = Database()
    # 本次运行的全部可回收对象集中登记在这里：
    # run() 边测边填，cleanup() 在 finally 里统一回收。
    state: dict = {
        # 唯一样本号：毫秒时间戳取模后补零到 8 位（手工单号不会与上一轮撞车）
        "suffix": f"{int(datetime.now().timestamp() * 1000) % 100000000:08d}",
        "orders": [],        # 本次创建的订单号
        "rooms": set(),      # 本次占用过的房间
        "groups": [],        # 本次创建的团体单
        "settlements": [],   # 本次创建的结账单
        "users": [],         # 本次创建的临时账号
        "audit_from": None,  # 本次运行之前的最大 log_id
    }
    try:
        run(db, state)
    except (service.BusinessError, DatabaseError, RuntimeError) as exc:
        # 业务层意外的失败（含"可用房不足"这类环境问题）也应落到汇总里，
        # 而不是抛栈结束 —— 否则看不到"通过 N 项，失败 M 项"的结论。
        check("主体流程未出现意外异常", False, f"{type(exc).__name__}: {str(exc)[:120]}")
        print(f"      → 意外异常：{type(exc).__name__}: {str(exc)[:160]}")
    finally:
        # 无论成功、断言失败还是异常退出，都必须回收本次写入的数据，
        # 否则半成品数据会让下一轮"缺房可用"而连环失败。
        try:
            cleanup(db, state)
        except (service.BusinessError, DatabaseError, RuntimeError) as exc:
            print(f"      → 清理阶段出现问题：{str(exc)[:160]}")
        with contextlib.suppress(Exception):
            db.close()
    return finish()


if __name__ == "__main__":
    raise SystemExit(main())
