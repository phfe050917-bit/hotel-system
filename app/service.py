"""
业务规则层 —— 三端界面共用的唯一业务入口。

原系统把业务规则直接写在 Tkinter 回调里，三端各写一份，导致：
  · 订单汇总逻辑重复三遍，客人端那份还用 BST 排序造成静默丢单；
  · 状态流转没有校验，可以从"等待取衣"直接跳到"已送达"；
  · 容量校验、日期校验散落在各处，且失败时抛未捕获异常。

本模块把规则集中到一处，界面只负责收集输入与展示结果。
所有校验失败统一抛 BusinessError，由界面转为提示框。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Iterable, Sequence

from app.db import Database, DatabaseError, Transaction
from app.ids import new_order_id, uniqueness_guard
from app.security import hash_password, needs_rehash, verify_password

# --- 各表主键列名（多态操作时用） -------------------------------------
_ORDER_TABLE = {
    "room": ("room_order", "order_id"),
    "dining": ("dining_order", "order_id"),
    "fitness": ("fitness_booking", "booking_id"),
    "spa": ("spa_booking", "booking_id"),
    "laundry": ("laundry_order", "order_id"),
}

# 各订单类型可用的状态机：当前状态 -> 允许到达的状态集合
_TRANSITIONS: dict[str, dict[str, set[str]]] = {
    "room": {
        "confirmed":   {"checked_in", "cancelled"},
        "checked_in":  {"checked_out"},
        "checked_out": set(),
        "cancelled":   set(),
    },
    "dining": {
        "confirmed": {"dining", "completed", "cancelled"},
        "dining":    {"completed", "cancelled"},
        "completed": set(),
        "cancelled": set(),
    },
    "fitness": {
        "confirmed": {"completed", "cancelled"},
        "completed": set(),
        "cancelled": set(),
    },
    "spa": {
        "confirmed":   {"in_progress", "completed", "cancelled"},
        "in_progress": {"completed", "cancelled"},
        "completed":   set(),
        "cancelled":   set(),
    },
    "laundry": {
        "pending":    {"picked_up", "cancelled"},
        "picked_up":  {"processing", "delivered", "cancelled"},
        "processing": {"delivered", "cancelled"},
        "delivered":  set(),
        "cancelled":  set(),
    },
}

_STATUS_LABEL = {
    "confirmed": "待确认/待入住", "checked_in": "已入住", "checked_out": "已退房",
    "dining": "用餐中", "completed": "已完成", "cancelled": "已取消",
    "in_progress": "服务中", "pending": "等待取衣", "picked_up": "已取衣",
    "processing": "洗涤中", "delivered": "已送达",
}

FITNESS_SLOTS = ("06:00-08:00", "08:00-10:00", "10:00-12:00",
                 "14:00-16:00", "16:00-18:00", "18:00-20:00", "20:00-22:00")

LAUNDRY_SERVICES = {
    "wash":         ("普通水洗", 25.0, "当日 18:00 前"),
    "dry_clean":    ("普通干洗", 45.0, "次日 12:00 前"),
    "iron":         ("熨烫服务", 20.0, "当日 16:00 前"),
    "express_wash": ("加急水洗", 50.0, "4 小时内"),
    "express_dry":  ("加急干洗", 80.0, "6 小时内"),
}

PAYMENT_METHODS = ("cash", "card", "wechat", "alipay", "room_charge")


class BusinessError(RuntimeError):
    """业务规则校验失败。界面对这类错误只弹提示，不打印堆栈。"""


# =====================================================================
#  输入校验工具
# =====================================================================
def parse_date(text: str, field: str = "日期") -> date:
    """
    解析 YYYY-MM-DD。

    原系统直接 datetime.strptime，用户输入 "2026/5/1" 或误触键盘
    就抛 ValueError 冲进 Tkinter，表现为程序崩溃。这里统一转成
    友好提示。
    """
    if not text or not str(text).strip():
        raise BusinessError(f"请填写{field}")
    raw = str(text).strip().replace("/", "-").replace(".", "-")
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    raise BusinessError(f"{field}格式不正确，应形如 2026-05-10")


def parse_positive_int(text: str, field: str, *, maximum: int | None = None) -> int:
    try:
        value = int(str(text).strip())
    except (TypeError, ValueError):
        raise BusinessError(f"{field}请填写整数") from None
    if value <= 0:
        raise BusinessError(f"{field}必须大于 0")
    if maximum is not None and value > maximum:
        raise BusinessError(f"{field}不能超过 {maximum}")
    return value


def parse_time(text: str, field: str = "时间") -> str:
    """把 HH:MM 规范化为 HH:MM:SS，供 TIME 列使用。"""
    if not text or not str(text).strip():
        raise BusinessError(f"请选择{field}")
    raw = str(text).strip()
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt).strftime("%H:%M:%S")
        except ValueError:
            continue
    raise BusinessError(f"{field}格式不正确，应形如 14:30")


def _to_datetime(value, field: str = "时间") -> datetime | None:
    """把用户选择的取衣时间转换为 DATETIME。'立即取衣' 返回 None。"""
    if not value or value == "立即取衣":
        return None
    parsed = parse_time(value, field)
    return datetime.combine(date.today(), datetime.strptime(parsed, "%H:%M:%S").time())


# =====================================================================
#  登录与账号
# =====================================================================
@dataclass(frozen=True)
class Session:
    """登录成功后传给界面层的会话信息。"""
    user_id: int
    username: str
    real_name: str
    role: str


def authenticate(db: Database, username: str, password: str) -> Session:
    """
    校验账号密码。

    原实现直接拿明文比对。现在取出哈希做常量时间校验；
    同时检查 is_active，被禁用的账号无法登录（配合管理端"禁用/启用"）。
    """
    username = (username or "").strip()
    if not username or not password:
        raise BusinessError("用户名和密码不能为空")

    row = db.query_one(
        "SELECT user_id, username, real_name, role, password_hash, is_active "
        "FROM `user` WHERE username = %s",
        (username,),
    )
    # 用户名不存在与密码错误返回同一提示，避免账号枚举
    if row is None or not verify_password(password, row["password_hash"]):
        raise BusinessError("用户名或密码错误")
    if not row["is_active"]:
        raise BusinessError("该账号已被禁用，请联系管理员")

    # 密码参数升级时自动重算哈希
    if needs_rehash(row["password_hash"]):
        db.execute("UPDATE `user` SET password_hash = %s WHERE user_id = %s",
                   (hash_password(password), row["user_id"]))

    return Session(
        user_id=row["user_id"],
        username=row["username"],
        real_name=row["real_name"] or row["username"],
        role=row["role"],
    )


def register_guest(db: Database, username: str, password: str, password_confirm: str,
                   phone: str = "", real_name: str = "") -> int:
    """注册客人账号，用户名/手机号唯一性由数据库约束兜底。"""
    username = (username or "").strip()
    if not username or not password:
        raise BusinessError("用户名和密码不能为空")
    if len(username) < 3:
        raise BusinessError("用户名至少 3 个字符")
    if len(password) < 6:
        raise BusinessError("密码至少 6 位")
    if password != password_confirm:
        raise BusinessError("两次输入的密码不一致")

    phone = (phone or "").strip() or None
    if phone and not (phone.isdigit() and len(phone) == 11):
        raise BusinessError("手机号应为 11 位数字")

    try:
        with db.transaction() as tx:
            if tx.query_value("SELECT COUNT(*) FROM `user` WHERE username = %s",
                              (username,), 0):
                raise BusinessError("该用户名已被注册，请换一个")
            if phone and tx.query_value("SELECT COUNT(*) FROM `user` WHERE phone = %s",
                                        (phone,), 0):
                raise BusinessError("该手机号已被注册")
            tx.execute(
                "INSERT INTO `user` (username, password_hash, phone, real_name, role) "
                "VALUES (%s, %s, %s, %s, 'guest')",
                (username, hash_password(password), phone, (real_name or "").strip() or None),
            )
            return int(tx.query_value("SELECT LAST_INSERT_ID() AS id", None, 0) or 0)
    except DatabaseError as exc:
        raise BusinessError(f"注册失败：{exc}") from exc


def change_password(db: Database, old_password: str, new_password: str, confirm: str,
                    *, user_id: int | None = None, username: str | None = None) -> None:
    """
    修改密码。

    必须提供原密码并通过校验 —— 登录页入口只要求输入用户名，
    但仍需验证原密码，否则就成了"知道用户名即可改密码"。
    找不到用户时返回与密码错误相同的提示，避免用户名枚举。
    """
    if user_id is None:
        if not username:
            raise BusinessError("请填写用户名")
        row = db.query_one("SELECT user_id FROM `user` WHERE username = %s",
                           (username.strip(),))
        if row is None:
            raise BusinessError("用户名或原密码不正确")
        user_id = row["user_id"]

    row = db.query_one("SELECT password_hash FROM `user` WHERE user_id = %s", (user_id,))
    if row is None or not verify_password(old_password, row["password_hash"]):
        raise BusinessError("用户名或原密码不正确")
    if len(new_password or "") < 6:
        raise BusinessError("新密码至少 6 位")
    if new_password != confirm:
        raise BusinessError("两次输入的新密码不一致")
    db.execute("UPDATE `user` SET password_hash = %s WHERE user_id = %s",
               (hash_password(new_password), user_id))


# =====================================================================
#  客房业务
# =====================================================================
def search_available_rooms(db: Database, check_in: date, check_out: date,
                           type_name: str | None = None, *,
                           allow_past: bool = False) -> list[dict]:
    """
    查询指定日期区间内可预订的房间。

    原实现两个问题：
      1. 只判断 room.status='available'，而该字段几乎从不更新，判断形同虚设；
      2. 返回结果不含 room_id，预订时要靠房间号反查，多一次往返且易错。
    现在改为"与既有订单无日期冲突 + 不在维护中"来判定，
    并直接带出 room_id、type_id、价格。

    allow_past=True 供前台/演示数据使用：需要查询"已入住但尚未离店"的房间，
    此时入住日显然早于今天，不应被拒绝。
    """
    if check_out <= check_in:
        raise BusinessError("离店日期必须晚于入住日期")
    if not allow_past and check_in < date.today():
        raise BusinessError("入住日期不能早于今天")

    sql = """
        SELECT r.room_id, r.room_number, rt.type_id, rt.type_name, rt.price,
               rt.max_occupancy, rt.facilities, r.floor
        FROM room r
        JOIN room_type rt ON rt.type_id = r.type_id
        WHERE r.status <> 'maintenance'
          AND NOT EXISTS (
              SELECT 1 FROM room_order ro
              WHERE ro.room_id = r.room_id
                AND ro.status IN ('confirmed', 'checked_in')
                AND ro.check_in_date < %s
                AND ro.check_out_date > %s
          )
    """
    params: list = [check_out, check_in]
    if type_name and type_name != "全部房型":
        sql += " AND rt.type_name = %s"
        params.append(type_name)
    sql += " ORDER BY rt.price, r.room_number"
    return db.query(sql, params)


def create_room_order(db: Database, *, user_id: int, room_id: int, check_in: date,
                      check_out: date, guest_name: str, guest_phone: str = "") -> dict:
    """
    创建客房订单。

    并发安全：在同一事务内先做冲突复查（SELECT ... FOR UPDATE 锁住该房间的
    有效订单行），再插入。原实现是"界面查到可订 -> 稍后插入"，
    中间任何人插单都会造成同一房间被重复预订。
    总金额与晚数由数据库触发器按当前房价重算，界面无法篡改账目。
    """
    guest_name = (guest_name or "").strip()
    if not guest_name:
        raise BusinessError("请填写入住人姓名")
    if check_out <= check_in:
        raise BusinessError("离店日期必须晚于入住日期")

    try:
        with db.transaction() as tx:
            room = tx.query_one(
                "SELECT r.room_id, r.room_number, r.status, rt.price, rt.max_occupancy "
                "FROM room r JOIN room_type rt ON rt.type_id = r.type_id "
                "WHERE r.room_id = %s FOR UPDATE",
                (room_id,),
            )
            if room is None:
                raise BusinessError("房间不存在")
            if room["status"] == "maintenance":
                raise BusinessError(f"房间 {room['room_number']} 正在维护，暂不可预订")

            conflict = tx.query_one(
                "SELECT order_id FROM room_order "
                "WHERE room_id = %s AND status IN ('confirmed','checked_in') "
                "  AND check_in_date < %s AND check_out_date > %s "
                "LIMIT 1",
                (room_id, check_out, check_in),
            )
            if conflict:
                raise BusinessError(
                    f"房间 {room['room_number']} 在所选日期已被预订"
                    f"（冲突订单 {conflict['order_id']}），请重新查询可用房"
                )

            order_id = uniqueness_guard(
                lambda: new_order_id("room"),
                lambda oid: bool(tx.query_value(
                    "SELECT COUNT(*) FROM room_order WHERE order_id = %s", (oid,), 0)),
            )

            nights = (check_out - check_in).days
            tx.execute(
                "INSERT INTO room_order (order_id, user_id, room_id, check_in_date, "
                "check_out_date, nights, total_price, guest_name, guest_phone, status) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'confirmed')",
                (order_id, user_id, room_id, check_in, check_out, nights,
                 float(room["price"]) * nights, guest_name, guest_phone or None),
            )
            # 触发器已重算金额，这里回读数据库的最终结果用于展示
            saved = tx.query_one(
                "SELECT order_id, nights, total_price, status FROM room_order "
                "WHERE order_id = %s", (order_id,))
            return dict(saved or {"order_id": order_id, "nights": nights,
                                  "total_price": float(room["price"]) * nights,
                                  "status": "confirmed"})
    except DatabaseError as exc:
        raise BusinessError(f"预订失败：{exc}") from exc


def room_calendar(db: Database, room_id: int) -> list[dict]:
    """某房间的占用日历（用于前台查看该房未来的预订情况）。"""
    return db.query(
        "SELECT ro.order_id, ro.check_in_date, ro.check_out_date, ro.guest_name, "
        "       ro.status, u.username "
        "FROM room_order ro JOIN `user` u ON u.user_id = ro.user_id "
        "WHERE ro.room_id = %s AND ro.status IN ('confirmed','checked_in') "
        "ORDER BY ro.check_in_date",
        (room_id,),
    )


# =====================================================================
#  餐饮业务
# =====================================================================
def list_menu(db: Database, restaurant_id: int) -> list[dict]:
    """餐厅菜单，带分类名与分类层级，体现 dish_category 的树形结构。"""
    return db.query(
        "SELECT d.dish_id, d.dish_name, d.price, d.description, d.is_setmeal, "
        "       d.is_available, c.category_name, p.category_name AS parent_category "
        "FROM dish d "
        "LEFT JOIN dish_category c ON c.category_id = d.category_id "
        "LEFT JOIN dish_category p ON p.category_id = c.parent_id "
        "WHERE d.restaurant_id = %s "
        "ORDER BY COALESCE(p.category_id, c.category_id), c.category_id, d.dish_name",
        (restaurant_id,),
    )


def create_dining_order(db: Database, *, user_id: int, restaurant_id: int,
                        dining_date: date, dining_time: str, guest_count: int,
                        items: Sequence[tuple[int, int]] | None = None) -> dict:
    """
    创建餐饮订单，可同时提交菜品明细。

    原实现 total_price 写死 0 且永不更新，管理端"餐饮收入"因此恒为 0。
    现在明细写入后由触发器自动汇总订单金额。
    items: [(dish_id, quantity), ...]
    """
    if dining_date < date.today():
        raise BusinessError("用餐日期不能早于今天")
    if guest_count <= 0:
        raise BusinessError("用餐人数必须大于 0")

    time_value = parse_time(dining_time, "用餐时间")

    try:
        with db.transaction() as tx:
            # 同餐厅同一时间段的座位数上限校验（按 20 桌估算）
            booked = tx.query_value(
                "SELECT COUNT(*) FROM dining_order "
                "WHERE restaurant_id = %s AND dining_date = %s AND dining_time = %s "
                "  AND status <> 'cancelled'",
                (restaurant_id, dining_date, time_value), 0)
            if booked >= 20:
                raise BusinessError("该时段餐位已订满，请选择其他时间")

            table_number = _allocate_table(tx, restaurant_id, dining_date, time_value)

            order_id = uniqueness_guard(
                lambda: new_order_id("dining"),
                lambda oid: bool(tx.query_value(
                    "SELECT COUNT(*) FROM dining_order WHERE order_id = %s", (oid,), 0)),
            )

            tx.execute(
                "INSERT INTO dining_order (order_id, user_id, restaurant_id, table_number, "
                "dining_date, dining_time, guest_count, total_price, status) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, 0, 'confirmed')",
                (order_id, user_id, restaurant_id, table_number,
                 dining_date, time_value, guest_count),
            )

            for dish_id, quantity in (items or []):
                if quantity <= 0:
                    continue
                dish = tx.query_one(
                    "SELECT price, is_available FROM dish WHERE dish_id = %s "
                    "AND restaurant_id = %s", (dish_id, restaurant_id))
                if dish is None:
                    raise BusinessError(f"菜品 {dish_id} 不属于该餐厅")
                if not dish["is_available"]:
                    raise BusinessError("所选菜品已下架")
                tx.execute(
                    "INSERT INTO dining_order_item (order_id, dish_id, quantity, unit_price, subtotal) "
                    "VALUES (%s, %s, %s, %s, 0)",
                    (order_id, dish_id, quantity, dish["price"]),
                )

            saved = tx.query_one(
                "SELECT order_id, table_number, total_price, status FROM dining_order "
                "WHERE order_id = %s", (order_id,))
            return dict(saved)
    except DatabaseError as exc:
        raise BusinessError(f"餐饮预订失败：{exc}") from exc


def _allocate_table(tx: Transaction, restaurant_id: int, dining_date: date,
                    dining_time: str) -> str:
    """
    分配桌号：取该餐厅该时段尚未占用的最小桌号。

    原实现是 f"{restaurant_id}号桌" —— 无论订多少次都是同一张桌子，
    等于没有桌位概念。现在按 1..20 号桌做真实占用检查。
    """
    used = {
        row["table_number"]
        for row in tx.query(
            "SELECT table_number FROM dining_order "
            "WHERE restaurant_id = %s AND dining_date = %s AND dining_time = %s "
            "  AND status <> 'cancelled'",
            (restaurant_id, dining_date, dining_time),
        )
    }
    for number in range(1, 21):
        candidate = f"{number:02d}号桌"
        if candidate not in used:
            return candidate
    raise BusinessError("该时段已无空桌")


def dining_order_items(db: Database, order_id: str) -> list[dict]:
    return db.query(
        "SELECT i.item_id, i.dish_id, d.dish_name, i.quantity, i.unit_price, i.subtotal "
        "FROM dining_order_item i JOIN dish d ON d.dish_id = i.dish_id "
        "WHERE i.order_id = %s ORDER BY i.item_id",
        (order_id,),
    )


# =====================================================================
#  健身业务
# =====================================================================
def fitness_usage(db: Database, booking_date: date) -> list[dict]:
    """某日各设施各时段的使用情况，容量判断与预约使用同一套口径。"""
    rows = db.query(
        "SELECT f.facility_id, f.facility_name, f.capacity, f.location, "
        "       COALESCE(SUM(b.guest_count), 0) AS booked "
        "FROM fitness_facility f "
        "LEFT JOIN fitness_booking b "
        "       ON b.facility_id = f.facility_id "
        "      AND b.booking_date = %s AND b.status = 'confirmed' "
        "WHERE f.status = 'available' "
        "GROUP BY f.facility_id, f.facility_name, f.capacity, f.location "
        "ORDER BY f.facility_id",
        (booking_date,),
    )
    usage: list[dict] = []
    for row in rows:
        for slot in FITNESS_SLOTS:
            usage.append({**row, "time_slot": slot})
    # 逐时段补充已预约人数（单条聚合查询即可，避免 N×M 次往返）
    detail = db.query(
        "SELECT facility_id, time_slot, SUM(guest_count) AS booked "
        "FROM fitness_booking "
        "WHERE booking_date = %s AND status = 'confirmed' "
        "GROUP BY facility_id, time_slot",
        (booking_date,),
    )
    booked_map = {(d["facility_id"], d["time_slot"]): int(d["booked"] or 0) for d in detail}
    for item in usage:
        item["booked"] = booked_map.get((item["facility_id"], item["time_slot"]), 0)
        item["remaining"] = max(0, int(item["capacity"]) - item["booked"])
        item["available"] = item["remaining"] > 0
    return usage


def create_fitness_booking(db: Database, *, user_id: int, facility_id: int,
                           booking_date: date, time_slot: str, guest_count: int) -> dict:
    """
    预约健身设施。

    原实现"先查已约人数、再插入"，两次独立提交之间存在并发窗口，
    多人同时预约会超卖。现在把复查与插入放进同一事务，
    并对该设施该时段的既有预约行加锁。
    """
    if guest_count <= 0:
        raise BusinessError("预约人数必须大于 0")
    if time_slot not in FITNESS_SLOTS:
        raise BusinessError("请选择有效的时间段")

    try:
        with db.transaction() as tx:
            facility = tx.query_one(
                "SELECT facility_id, facility_name, capacity, status "
                "FROM fitness_facility WHERE facility_id = %s FOR UPDATE",
                (facility_id,),
            )
            if facility is None:
                raise BusinessError("设施不存在")
            if facility["status"] != "available":
                raise BusinessError(f"{facility['facility_name']} 正在维护中")

            booked = int(tx.query_value(
                "SELECT COALESCE(SUM(guest_count), 0) FROM fitness_booking "
                "WHERE facility_id = %s AND booking_date = %s AND time_slot = %s "
                "  AND status = 'confirmed'",
                (facility_id, booking_date, time_slot), 0) or 0)

            capacity = int(facility["capacity"])
            if booked + guest_count > capacity:
                raise BusinessError(
                    f"{facility['facility_name']} {booking_date} {time_slot} 仅剩 "
                    f"{max(0, capacity - booked)} 个名额，无法预约 {guest_count} 人"
                )

            booking_id = uniqueness_guard(
                lambda: new_order_id("fitness"),
                lambda bid: bool(tx.query_value(
                    "SELECT COUNT(*) FROM fitness_booking WHERE booking_id = %s", (bid,), 0)),
            )
            tx.execute(
                "INSERT INTO fitness_booking (booking_id, user_id, facility_id, "
                "booking_date, time_slot, guest_count, status) "
                "VALUES (%s, %s, %s, %s, %s, %s, 'confirmed')",
                (booking_id, user_id, facility_id, booking_date, time_slot, guest_count),
            )
            return {"booking_id": booking_id, "remaining":
                    max(0, capacity - booked - guest_count)}
    except DatabaseError as exc:
        raise BusinessError(f"健身预约失败：{exc}") from exc


# =====================================================================
#  SPA 业务
# =====================================================================
def list_technicians(db: Database, service_id: int | None = None) -> list[dict]:
    """
    可用技师列表；给定服务时把擅长该项目的技师排在前面。

    注意：SQL 里的字面量百分号必须写成 %% —— pymysql 使用 %s 作为占位符，
    单个 % 会被当成格式化符号而报 "not enough arguments for format string"。
    """
    if service_id:
        return db.query(
            "SELECT t.tech_id, t.tech_name, t.tech_level, t.rating, t.specialty, t.status "
            "FROM technician t "
            "JOIN spa_service s ON s.service_id = %s "
            "WHERE t.status <> 'off_duty' "
            "ORDER BY (t.specialty LIKE CONCAT('%%', s.service_name, '%%')) DESC, "
            "         t.rating DESC",
            (service_id,),
        )
    return db.query(
        "SELECT tech_id, tech_name, tech_level, rating, specialty, status "
        "FROM technician WHERE status <> 'off_duty' ORDER BY rating DESC"
    )


def create_spa_booking(db: Database, *, user_id: int, service_id: int, tech_id: int,
                       booking_date: date, booking_time: str) -> dict:
    """
    预约 SPA。

    原实现既不检查技师是否已被占用，也完全没用 tech_schedule 表。
    现在：事务内锁定该技师当日排班，占用对应档期，并保证同一技师
    同一时间不会出现两单。
    """
    time_value = parse_time(booking_time, "预约时间")
    if booking_date < date.today():
        raise BusinessError("预约日期不能早于今天")

    try:
        with db.transaction() as tx:
            service = tx.query_one(
                "SELECT service_id, service_name, duration, price FROM spa_service "
                "WHERE service_id = %s FOR UPDATE", (service_id,))
            if service is None:
                raise BusinessError("SPA 服务不存在")

            tech = tx.query_one(
                "SELECT tech_id, tech_name, status FROM technician WHERE tech_id = %s",
                (tech_id,))
            if tech is None:
                raise BusinessError("技师不存在")
            if tech["status"] == "off_duty":
                raise BusinessError(f"技师 {tech['tech_name']} 今日休息")

            # 同一技师同一时刻只能有一单有效预约
            clash = tx.query_one(
                "SELECT booking_id FROM spa_booking "
                "WHERE tech_id = %s AND booking_date = %s AND booking_time = %s "
                "  AND status IN ('confirmed','in_progress') LIMIT 1",
                (tech_id, booking_date, time_value),
            )
            if clash:
                raise BusinessError(
                    f"技师 {tech['tech_name']} 在 {booking_date} {time_value[:5]} "
                    f"已有预约（{clash['booking_id']}），请另选时间或技师"
                )

            booking_id = uniqueness_guard(
                lambda: new_order_id("spa"),
                lambda bid: bool(tx.query_value(
                    "SELECT COUNT(*) FROM spa_booking WHERE booking_id = %s", (bid,), 0)),
            )
            slot = time_value[:5]
            tx.execute(
                "INSERT INTO spa_booking (booking_id, user_id, service_id, tech_id, "
                "booking_date, booking_time, price, status) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, 'confirmed')",
                (booking_id, user_id, service_id, tech_id, booking_date, time_value,
                 service["price"]),
            )
            # 占用排班档期（若该档期未预先排班则自动补一条，保证 tech_schedule 真正被使用）
            tx.execute(
                "INSERT INTO tech_schedule (tech_id, work_date, time_slot, is_booked) "
                "VALUES (%s, %s, %s, 1) "
                "ON DUPLICATE KEY UPDATE is_booked = 1",
                (tech_id, booking_date, slot),
            )
            return {"booking_id": booking_id, "price": float(service["price"]),
                    "tech_name": tech["tech_name"], "service_name": service["service_name"],
                    "duration": service["duration"]}
    except DatabaseError as exc:
        raise BusinessError(f"SPA 预约失败：{exc}") from exc


def tech_availability(db: Database, tech_id: int, booking_date: date) -> list[dict]:
    """某技师某日的档期占用情况，供界面提示可约时段。"""
    return db.query(
        "SELECT time_slot, is_booked, "
        "       CASE WHEN is_booked = 1 THEN '已约' ELSE '空闲' END AS slot_label "
        "FROM tech_schedule WHERE tech_id = %s AND work_date = %s "
        "ORDER BY time_slot",
        (tech_id, booking_date),
    )


# =====================================================================
#  洗衣业务
# =====================================================================
def estimate_laundry(service_type: str, item_count: int) -> dict:
    """洗衣报价（不落库，供界面实时显示）。"""
    if service_type not in LAUNDRY_SERVICES:
        raise BusinessError("请选择洗衣服务类型")
    if item_count <= 0:
        raise BusinessError("衣物数量必须大于 0")
    name, unit_price, eta = LAUNDRY_SERVICES[service_type]
    return {"service_name": name, "unit_price": unit_price,
            "total_price": unit_price * item_count, "eta": eta}


def create_laundry_order(db: Database, *, user_id: int, service_type: str,
                         item_count: int, room_number: str,
                         expected_pickup: str = "立即取衣") -> dict:
    """
    洗衣下单。

    原实现让客人自己手填房间号，无法校验；这里改为校验该用户确实
    有覆盖今天、状态为 confirmed/checked_in 的客房订单，并用订单上的
    房间号落库，杜绝乱填房号。
    """
    if service_type not in LAUNDRY_SERVICES:
        raise BusinessError("请选择洗衣服务类型")
    if item_count <= 0:
        raise BusinessError("衣物数量必须大于 0")

    pickup_at = _to_datetime(expected_pickup, "取衣时间")

    try:
        with db.transaction() as tx:
            stay = tx.query_one(
                "SELECT r.room_number FROM room_order ro "
                "JOIN room r ON r.room_id = ro.room_id "
                "WHERE ro.user_id = %s AND ro.status IN ('confirmed','checked_in') "
                "  AND ro.check_in_date <= CURDATE() AND ro.check_out_date >= CURDATE() "
                "ORDER BY ro.check_in_date DESC LIMIT 1",
                (user_id,),
            )
            if stay is None:
                # 允许显式传入房间号（例如为同行亲友下单），但仍需是系统内真实房间
                if not room_number or not tx.query_value(
                        "SELECT COUNT(*) FROM room WHERE room_number = %s",
                        (room_number,), 0):
                    raise BusinessError(
                        "当前没有在住/待入住的客房订单，且房间号无效。\n"
                        "请先预订客房，或填写系统中真实存在的房间号"
                    )
            else:
                room_number = stay["room_number"]

            unit_price = LAUNDRY_SERVICES[service_type][1]
            order_id = uniqueness_guard(
                lambda: new_order_id("laundry"),
                lambda oid: bool(tx.query_value(
                    "SELECT COUNT(*) FROM laundry_order WHERE order_id = %s", (oid,), 0)),
            )
            tx.execute(
                "INSERT INTO laundry_order (order_id, user_id, service_type, item_count, "
                "unit_price, total_price, room_number, expected_pickup, status) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'pending')",
                (order_id, user_id, service_type, item_count, unit_price,
                 unit_price * item_count, room_number, pickup_at),
            )
            return {"order_id": order_id, "room_number": room_number,
                    "total_price": unit_price * item_count}
    except DatabaseError as exc:
        raise BusinessError(f"洗衣下单失败：{exc}") from exc


def laundry_queue(db: Database, *, user_id: int | None = None,
                  include_finished: bool = False) -> list[dict]:
    """
    洗衣处理队列，按"加急优先 + 同优先级先到先处理"排序。

    原实现两个问题：
      1. 客人端把**全部住客**的洗衣订单（含房间号）都查出来显示，泄露隐私；
      2. 用 PriorityQueue 排序，但堆里比较的是 (priority, dict)，
         同优先级时顺序不稳定，所谓"同优先级按时间先后"并不成立。
    现在：客人端必须传 user_id 只看自己的单；排序交给 SQL 的
    ORDER BY 优先级, created_at，结果确定且可解释。
    """
    sql = """
        SELECT lo.order_id, lo.user_id, u.username, lo.service_type, lo.item_count,
               lo.unit_price, lo.total_price, lo.room_number, lo.expected_pickup,
               lo.pickup_time, lo.delivery_time, lo.status, lo.created_at,
               CASE WHEN lo.service_type IN ('express_wash','express_dry')
                    THEN 1 ELSE 2 END AS priority,
               CASE lo.service_type
                    WHEN 'wash' THEN '普通水洗' WHEN 'dry_clean' THEN '普通干洗'
                    WHEN 'iron' THEN '熨烫服务' WHEN 'express_wash' THEN '加急水洗'
                    WHEN 'express_dry' THEN '加急干洗' END AS service_label,
               CASE lo.status
                    WHEN 'pending' THEN '等待取衣' WHEN 'picked_up' THEN '已取衣'
                    WHEN 'processing' THEN '洗涤中' WHEN 'delivered' THEN '已送达'
                    WHEN 'cancelled' THEN '已取消' END AS status_label
        FROM laundry_order lo
        JOIN `user` u ON u.user_id = lo.user_id
        WHERE 1 = 1
    """
    params: list = []
    if user_id is not None:
        sql += " AND lo.user_id = %s"
        params.append(user_id)
    if not include_finished:
        sql += " AND lo.status <> 'cancelled'"
    sql += " ORDER BY priority, lo.created_at, lo.order_id"
    return db.query(sql, params)


# =====================================================================
#  订单通用操作
# =====================================================================
def list_orders(db: Database, *, user_id: int | None = None,
                order_type: str | None = None, status_category: str | None = None,
                limit: int | None = None) -> list[dict]:
    """
    统一的订单查询入口，底层走 v_all_orders 视图。

    这是对原系统最关键的架构修正：三端不再各自 UNION + CASE + 合并排序，
    客人端的"BST 时间戳排序丢单"问题从此不存在。
    """
    sql = "SELECT * FROM v_all_orders WHERE 1 = 1"
    params: list = []
    if user_id is not None:
        sql += " AND user_id = %s"
        params.append(user_id)
    if order_type and order_type != "all":
        sql += " AND order_type = %s"
        params.append(order_type)
    if status_category and status_category != "全部":
        sql += " AND status_category = %s"
        params.append(status_category)
    sql += " ORDER BY created_at DESC, order_id DESC"
    if limit:
        sql += " LIMIT %s"
        params.append(int(limit))
    return db.query(sql, params)


def get_order(db: Database, order_type: str, order_id: str) -> dict | None:
    return db.query_one(
        "SELECT * FROM v_all_orders WHERE order_type = %s AND order_id = %s",
        (order_type, order_id),
    )


def advance_order_status(db: Database, order_type: str, order_id: str,
                         new_status: str) -> str:
    """
    按状态机推进订单状态，返回中文状态名。

    原实现直接 UPDATE ... SET status=?, 不校验当前状态，
    可以把"等待取衣"直接改成"已送达"，或取消一张已完成的订单。
    现在先读当前状态、查状态机，再用带条件的 UPDATE 落地，
    并以 rowcount 确认确实更新成功（防止并发下的竞态）。
    """
    if order_type not in _ORDER_TABLE:
        raise BusinessError(f"未知订单类型：{order_type}")

    table, id_column = _ORDER_TABLE[order_type]
    machine = _TRANSITIONS[order_type]

    try:
        with db.transaction() as tx:
            row = tx.query_one(
                f"SELECT status FROM {table} WHERE {id_column} = %s FOR UPDATE",
                (order_id,),
            )
            if row is None:
                raise BusinessError("订单不存在")

            current = row["status"]
            allowed = machine.get(current, set())
            if new_status not in allowed:
                raise BusinessError(
                    f"订单当前是「{_STATUS_LABEL.get(current, current)}」，"
                    f"不能变更为「{_STATUS_LABEL.get(new_status, new_status)}」"
                )

            affected = tx.execute(
                f"UPDATE {table} SET status = %s WHERE {id_column} = %s AND status = %s",
                (new_status, order_id, current),
            )
            if affected != 1:
                raise BusinessError("订单状态已被他人修改，请刷新后重试")

            return _STATUS_LABEL.get(new_status, new_status)
    except DatabaseError as exc:
        raise BusinessError(f"状态更新失败：{exc}") from exc


def cancel_order(db: Database, order_type: str, order_id: str,
                 *, actor_role: str = "guest") -> str:
    """
    取消订单。

    原实现允许任何角色取消任何状态的订单，包括已完成的。现在：
      · 走状态机，只有"进行中"的订单可取消；
      · 已退房/已送达/已完成的订单一律拒绝。
    退回的款项（若已支付）记录一条 refunded 流水。
    """
    label = advance_order_status(db, order_type, order_id, "cancelled")

    paid = db.query_one(
        "SELECT payment_id, amount FROM payment "
        "WHERE order_type = %s AND order_id = %s AND status = 'paid'",
        (order_type, order_id),
    )
    if paid:
        db.execute("UPDATE payment SET status = 'refunded' WHERE payment_id = %s",
                   (paid["payment_id"],))
    return label


def order_owner_id(db: Database, order_type: str, order_id: str) -> int | None:
    """
    查询某订单的所属用户。

    前台代客登记收款时需要它来填写 payment.user_id。
    外键约束保证 payment.user_id 必须是真实用户，因此不能随便填。
    """
    if order_type not in _ORDER_TABLE:
        return None
    table, id_column = _ORDER_TABLE[order_type]
    return db.query_value(
        f"SELECT user_id FROM {table} WHERE {id_column} = %s", (order_id,), None)


def order_payment(db: Database, order_type: str, order_id: str) -> dict | None:
    """某订单最新一条支付流水（用于详情页展示）。"""
    return db.query_one(
        "SELECT payment_no, amount, method, status, paid_at FROM payment "
        "WHERE order_type = %s AND order_id = %s ORDER BY payment_id DESC LIMIT 1",
        (order_type, order_id))


def paid_order_map(db: Database) -> dict[tuple[str, str], str]:
    """
    一次性查出所有订单的支付状态，键为 (order_type, order_id)。

    列表页需要给每行标注支付状态，逐行查询会产生 N+1 次往返，
    因此这里统一取回后在内存里匹配。
    """
    result: dict[tuple[str, str], str] = {}
    for row in db.query("SELECT order_type, order_id, status FROM payment"):
        key = (row["order_type"], row["order_id"])
        if row["status"] == "paid":
            result[key] = "已支付"
        elif key not in result:
            result[key] = "已退款"
    return result


def checkin_candidates(db: Database, mode: str = "今天") -> list[dict]:
    """
    入住/退房工作台的数据源。

    mode: 今天 / 明天 / 未来 7 天 / 全部待入住
    只返回仍需处理的订单（待入住或已入住），并带出房间与入住人信息。
    """
    today = date.today()
    where = "ro.status IN ('confirmed','checked_in')"
    params: list = []

    if mode == "今天":
        where += " AND ro.check_in_date <= %s AND ro.check_out_date > %s"
        params += [today, today]
    elif mode == "明天":
        where += " AND ro.check_in_date = %s"
        params.append(today + timedelta(days=1))
    elif mode == "未来 7 天":
        where += " AND ro.check_in_date BETWEEN %s AND %s"
        params += [today, today + timedelta(days=7)]

    return db.query(
        "SELECT ro.order_id, r.room_number, rt.type_name, ro.guest_name, "
        "       ro.guest_phone, ro.check_in_date, ro.check_out_date, ro.nights, "
        "       ro.total_price, ro.status AS raw_status, ro.room_id "
        "FROM room_order ro "
        "JOIN room r ON r.room_id = ro.room_id "
        "JOIN room_type rt ON rt.type_id = r.type_id "
        f"WHERE {where} ORDER BY ro.check_in_date, r.room_number", params)


# =====================================================================
#  基础资源维护（管理端）
#  说明：表名与列名不能参数化，因此这里用**白名单注册表**约束可操作范围，
#  值一律走参数化绑定。所有 SQL 集中在本层，界面不再直接触碰数据库。
# =====================================================================
@dataclass(frozen=True)
class FieldSpec:
    """基础资源的一个字段。"""
    name: str            # 数据库列名
    label: str           # 界面列头
    width: int           # 界面列宽
    kind: str = "text"   # text / int / decimal / bool
    editable: bool = True
    choices: tuple[str, ...] | None = None


RESOURCE_CATALOG: dict[str, dict] = {
    "room_type": {
        "label": "房型", "pk": "type_id",
        "fields": (
            FieldSpec("type_id", "ID", 50, "int", editable=False),
            FieldSpec("type_name", "房型名称", 130),
            FieldSpec("price", "价格/晚", 90, "decimal"),
            FieldSpec("max_occupancy", "最大入住", 80, "int"),
            FieldSpec("facilities", "设施", 220),
            FieldSpec("description", "描述", 240),
        ),
    },
    "room": {
        "label": "房间", "pk": "room_id",
        "fields": (
            FieldSpec("room_id", "ID", 50, "int", editable=False),
            FieldSpec("room_number", "房间号", 80),
            FieldSpec("type_id", "房型ID", 70, "int"),
            FieldSpec("floor", "楼层", 60, "int"),
            FieldSpec("status", "状态", 110, choices=("available", "occupied",
                                                       "cleaning", "maintenance")),
        ),
    },
    "restaurant": {
        "label": "餐厅", "pk": "restaurant_id",
        "fields": (
            FieldSpec("restaurant_id", "ID", 50, "int", editable=False),
            FieldSpec("restaurant_name", "餐厅名称", 140),
            FieldSpec("location", "位置", 130),
            FieldSpec("open_time", "营业时间", 240),
            FieldSpec("description", "描述", 220),
        ),
    },
    "dish": {
        "label": "菜品", "pk": "dish_id",
        "fields": (
            FieldSpec("dish_id", "ID", 50, "int", editable=False),
            FieldSpec("restaurant_id", "餐厅ID", 70, "int"),
            FieldSpec("category_id", "分类ID", 70, "int"),
            FieldSpec("dish_name", "菜名", 140),
            FieldSpec("price", "价格", 80, "decimal"),
            FieldSpec("is_setmeal", "套餐(0/1)", 80, "bool"),
            FieldSpec("is_available", "在售(0/1)", 80, "bool"),
        ),
    },
    "fitness_facility": {
        "label": "健身设施", "pk": "facility_id",
        "fields": (
            FieldSpec("facility_id", "ID", 50, "int", editable=False),
            FieldSpec("facility_name", "设施名称", 120),
            FieldSpec("location", "位置", 110),
            FieldSpec("capacity", "容量", 70, "int"),
            FieldSpec("open_time", "开放时间", 140),
            FieldSpec("status", "状态", 120, choices=("available", "maintenance")),
        ),
    },
    "spa_service": {
        "label": "SPA服务", "pk": "service_id",
        "fields": (
            FieldSpec("service_id", "ID", 50, "int", editable=False),
            FieldSpec("service_name", "服务名称", 150),
            FieldSpec("duration", "时长(分)", 80, "int"),
            FieldSpec("price", "价格", 80, "decimal"),
            FieldSpec("description", "描述", 240),
        ),
    },
    "technician": {
        "label": "技师", "pk": "tech_id",
        "fields": (
            FieldSpec("tech_id", "ID", 50, "int", editable=False),
            FieldSpec("tech_name", "姓名", 90),
            FieldSpec("tech_level", "级别", 80, choices=("普通", "高级", "资深")),
            FieldSpec("specialty", "擅长项目", 200),
            FieldSpec("rating", "评分", 70, "decimal"),
            FieldSpec("status", "状态", 120, choices=("available", "busy", "off_duty")),
        ),
    },
}


def resource_catalog() -> list[dict]:
    """资源类型清单，供界面生成左侧列表与列定义。"""
    return [{"table": table, "label": spec["label"], "pk": spec["pk"],
             "fields": [{"name": f.name, "label": f.label, "width": f.width,
                         "kind": f.kind, "editable": f.editable,
                         "choices": f.choices} for f in spec["fields"]]}
            for table, spec in RESOURCE_CATALOG.items()]


def _resource_spec(table: str) -> dict:
    spec = RESOURCE_CATALOG.get(table)
    if spec is None:
        raise BusinessError(f"不允许操作该数据表：{table}")
    return spec


def _coerce(field: FieldSpec, raw) -> Any:
    """把界面传来的字符串按字段类型转换，并在服务端重新校验。"""
    text = "" if raw is None else str(raw).strip()

    if field.kind == "int":
        if text == "":
            return None
        try:
            return int(text)
        except ValueError:
            raise BusinessError(f"{field.label}必须是整数") from None

    if field.kind == "decimal":
        if text == "":
            return None
        try:
            return float(text)
        except ValueError:
            raise BusinessError(f"{field.label}必须是数字") from None

    if field.kind == "bool":
        if text in ("1", "是", "true", "True"):
            return 1
        if text in ("0", "否", "false", "False", ""):
            return 0
        raise BusinessError(f"{field.label}只能填 0 或 1")

    if field.choices and text not in field.choices:
        raise BusinessError(f"{field.label}只能是：{'/'.join(field.choices)}")

    return text or None


def resource_list(db: Database, table: str) -> list[dict]:
    spec = _resource_spec(table)
    return db.query(f"SELECT * FROM `{table}` ORDER BY `{spec['pk']}`")


def resource_create(db: Database, table: str, values: dict) -> None:
    spec = _resource_spec(table)
    fields = [f for f in spec["fields"] if f.editable]

    unknown = set(values) - {f.name for f in fields}
    if unknown:
        raise BusinessError(f"存在不可编辑字段：{'、'.join(sorted(unknown))}")

    payload = {f.name: _coerce(f, values.get(f.name)) for f in fields}
    if not any(v is not None for v in payload.values()):
        raise BusinessError("请至少填写一个字段")

    columns = ", ".join(f"`{name}`" for name in payload)
    placeholders = ", ".join(["%s"] * len(payload))
    try:
        db.execute(f"INSERT INTO `{table}` ({columns}) VALUES ({placeholders})",
                   list(payload.values()))
    except DatabaseError as exc:
        raise BusinessError(f"新增失败：{exc}") from exc


def resource_update(db: Database, table: str, pk_value, values: dict) -> None:
    spec = _resource_spec(table)
    fields = [f for f in spec["fields"] if f.editable]

    unknown = set(values) - {f.name for f in fields}
    if unknown:
        raise BusinessError(f"存在不可编辑字段：{'、'.join(sorted(unknown))}")

    payload = {f.name: _coerce(f, values.get(f.name)) for f in fields}
    assignments = ", ".join(f"`{name}`=%s" for name in payload)
    try:
        affected = db.execute(
            f"UPDATE `{table}` SET {assignments} WHERE `{spec['pk']}`=%s",
            [*payload.values(), pk_value])
    except DatabaseError as exc:
        raise BusinessError(f"保存失败：{exc}") from exc
    if affected != 1:
        raise BusinessError("记录不存在，或内容没有变化")


def resource_delete(db: Database, table: str, pk_value) -> None:
    """
    删除一条基础资源。

    订单类外键为 RESTRICT，因此删除被引用的房型/房间/菜品时
    数据库会拒绝，这里把原因翻译成人能读懂的提示。
    """
    spec = _resource_spec(table)
    try:
        affected = db.execute(f"DELETE FROM `{table}` WHERE `{spec['pk']}`=%s",
                              (pk_value,))
    except DatabaseError as exc:
        raise BusinessError(
            f"删除失败：该{spec['label']}被其他数据引用，数据库已阻止删除。\n"
            f"（这是外键 RESTRICT 的保护，避免误删历史订单）\n\n{exc}"
        ) from exc
    if affected != 1:
        raise BusinessError("记录不存在")


def schema_object_names(db: Database) -> dict:
    """数据库对象清单（供管理端「关于系统」页展示）。"""
    return {
        "views": db.query(
            "SELECT table_name AS name FROM information_schema.views "
            "WHERE table_schema = DATABASE() ORDER BY table_name"),
        "triggers": db.query(
            "SELECT trigger_name AS name, action_timing AS timing, "
            "       event_object_table AS `table` "
            "FROM information_schema.triggers WHERE trigger_schema = DATABASE() "
            "ORDER BY event_object_table, trigger_name"),
        "tables": db.query(
            "SELECT table_name AS name FROM information_schema.tables "
            "WHERE table_schema = DATABASE() AND table_type = 'BASE TABLE' "
            "ORDER BY table_name"),
    }


def table_row_counts(db: Database) -> list[dict]:
    """每张表的行数（表名来自 information_schema，不是用户输入）。"""
    rows = []
    for item in schema_object_names(db)["tables"]:
        name = item["name"]
        rows.append({"table_name": name,
                     "rows": db.query_value(f"SELECT COUNT(*) FROM `{name}`", None, 0)})
    return rows


def user_order_counts(db: Database) -> dict[int, int]:
    """每个用户的订单数（列表页一次取回，避免逐行查询）。"""
    return {row["user_id"]: int(row["count"])
            for row in db.query(
                "SELECT user_id, COUNT(*) AS count FROM v_all_orders GROUP BY user_id")}


# =====================================================================
#  支付
# =====================================================================
def pay_order(db: Database, *, order_type: str, order_id: str, user_id: int,
              method: str = "cash", amount: float | None = None) -> dict:
    """
    为订单登记一笔支付流水。

    原系统没有支付表，管理端把各订单表的金额按状态求和当作"收入"，
    未收款的订单也被算进收入。现在收入只从 payment 汇总。
    """
    if order_type not in _ORDER_TABLE:
        raise BusinessError(f"未知订单类型：{order_type}")
    if method not in PAYMENT_METHODS:
        raise BusinessError("请选择有效的支付方式")

    table, id_column = _ORDER_TABLE[order_type]
    if order_type in ("fitness",):
        raise BusinessError("健身预约免费，无需支付")

    try:
        with db.transaction() as tx:
            order = tx.query_one(
                f"SELECT * FROM {table} WHERE {id_column} = %s", (order_id,))
            if order is None:
                raise BusinessError("订单不存在")
            if order["user_id"] != user_id:
                raise BusinessError("只能为自己的订单付款")
            if order["status"] == "cancelled":
                raise BusinessError("已取消的订单无需付款")

            existing = tx.query_one(
                "SELECT payment_id FROM payment WHERE order_type = %s AND order_id = %s "
                "AND status = 'paid'", (order_type, order_id))
            if existing:
                raise BusinessError("该订单已支付，请勿重复付款")

            due = float(order.get("total_price") or order.get("price") or 0)
            pay_amount = float(amount) if amount is not None else due
            if pay_amount <= 0:
                raise BusinessError("支付金额必须大于 0")

            payment_no = uniqueness_guard(
                lambda: new_order_id("payment"),
                lambda pno: bool(tx.query_value(
                    "SELECT COUNT(*) FROM payment WHERE payment_no = %s", (pno,), 0)),
            )
            tx.execute(
                "INSERT INTO payment (payment_no, order_id, order_type, user_id, "
                "amount, method, status) VALUES (%s, %s, %s, %s, %s, %s, 'paid')",
                (payment_no, order_id, order_type, user_id, pay_amount, method),
            )
            return {"payment_no": payment_no, "amount": pay_amount}
    except DatabaseError as exc:
        raise BusinessError(f"支付登记失败：{exc}") from exc


def list_payments(db: Database, *, user_id: int | None = None,
                  order_type: str | None = None) -> list[dict]:
    sql = ("SELECT p.*, u.username, "
           "CASE p.order_type WHEN 'room' THEN '客房' WHEN 'dining' THEN '餐饮' "
           "WHEN 'fitness' THEN '健身' WHEN 'spa' THEN 'SPA' WHEN 'laundry' THEN '洗衣' "
           "END AS type_label, "
           "CASE p.method WHEN 'cash' THEN '现金' WHEN 'card' THEN '银行卡' "
           "WHEN 'wechat' THEN '微信' WHEN 'alipay' THEN '支付宝' "
           "WHEN 'room_charge' THEN '挂房账' END AS method_label "
           "FROM payment p JOIN `user` u ON u.user_id = p.user_id WHERE 1 = 1")
    params: list = []
    if user_id is not None:
        sql += " AND p.user_id = %s"
        params.append(user_id)
    if order_type and order_type != "all":
        sql += " AND p.order_type = %s"
        params.append(order_type)
    sql += " ORDER BY p.paid_at DESC, p.payment_id DESC"
    return db.query(sql, params)


# =====================================================================
#  评价
# =====================================================================
def submit_review(db: Database, *, user_id: int, order_id: str, order_type: str,
                  rating: int, content: str) -> None:
    """
    提交评价。

    原实现：无唯一约束（可无限重复评价）、不校验订单归属、
    也不校验订单是否已完成。现在三层防护：
      · 这里校验评分范围、订单存在且已完成；
      · 触发器校验订单归属；
      · uk_review_order 唯一约束兜底重复评价。
    """
    if not 1 <= int(rating) <= 5:
        raise BusinessError("评分必须是 1 到 5 星")
    content = (content or "").strip()
    if not content:
        raise BusinessError("请填写评价内容")

    order = get_order(db, order_type, order_id)
    if order is None:
        raise BusinessError("订单不存在")
    if order["user_id"] != user_id:
        raise BusinessError("只能评价自己的订单")
    if order["status_category"] != "已完成":
        raise BusinessError(f"订单当前是「{order['status_label']}」，完成后才能评价")

    try:
        db.execute(
            "INSERT INTO review (user_id, order_id, order_type, rating, content) "
            "VALUES (%s, %s, %s, %s, %s)",
            (user_id, order_id, order_type, int(rating), content),
        )
    except DatabaseError as exc:
        message = str(exc)
        if "uk_review_order" in message or "Duplicate" in message:
            raise BusinessError("您已评价过该订单") from exc
        raise BusinessError(f"评价提交失败：{exc}") from exc


def list_reviews(db: Database, *, limit: int | None = None) -> list[dict]:
    sql = """
        SELECT r.review_id, r.order_id, r.order_type, r.rating, r.content, r.created_at,
               u.username, u.real_name,
               CASE r.order_type WHEN 'room' THEN '客房' WHEN 'dining' THEN '餐饮'
                    WHEN 'fitness' THEN '健身' WHEN 'spa' THEN 'SPA'
                    WHEN 'laundry' THEN '洗衣' END AS type_label
        FROM review r JOIN `user` u ON u.user_id = r.user_id
        ORDER BY r.created_at DESC, r.review_id DESC
    """
    params: list = []
    if limit:
        sql += " LIMIT %s"
        params.append(int(limit))
    return db.query(sql, params)


# =====================================================================
#  房间状态
# =====================================================================
ROOM_STATUS_LABEL = {
    "available": "空闲", "occupied": "在住",
    "cleaning": "打扫中", "maintenance": "维护中",
}
ROOM_STATUS_CHOICES = ("available", "cleaning", "maintenance")


def list_rooms(db: Database, *, floor: int | None = None, status: str | None = None,
               keyword: str = "") -> list[dict]:
    """房间列表，附带当前有效订单数，状态不再与订单脱节。"""
    sql = "SELECT * FROM v_room_current_state WHERE 1 = 1"
    params: list = []
    if floor:
        sql += " AND floor = %s"
        params.append(floor)
    if status and status in ROOM_STATUS_LABEL:
        sql += " AND room_status = %s"
        params.append(status)
    if keyword:
        sql += " AND room_number LIKE %s"
        params.append(f"%{keyword}%")
    sql += " ORDER BY room_number"
    return db.query(sql, params)


def set_room_status(db: Database, room_id: int, status: str) -> None:
    """
    人工调整房间物理状态。

    只允许 available / cleaning / maintenance：
    'occupied' 由订单触发器自动维护，不允许手工设置，
    否则会出现"没有客人却显示在住"的假数据。
    """
    if status not in ROOM_STATUS_CHOICES:
        raise BusinessError("只能手工设置：空闲 / 打扫中 / 维护中（在住由订单自动维护）")

    if status == "available":
        active = db.query_value(
            "SELECT COUNT(*) FROM room_order WHERE room_id = %s "
            "AND status IN ('confirmed','checked_in') "
            "AND check_in_date <= CURDATE() AND check_out_date > CURDATE()",
            (room_id,), 0)
        if active:
            raise BusinessError("该房间当前有在住/待入住订单，不能置为空闲")

    affected = db.execute("UPDATE room SET status = %s WHERE room_id = %s", (status, room_id))
    if affected != 1:
        raise BusinessError("房间不存在或状态未变化")


# =====================================================================
#  基础数据查询（供界面下拉框与筛选项使用）
# =====================================================================
def room_type_options(db: Database) -> list[dict]:
    return db.query("SELECT type_id, type_name, price, max_occupancy FROM room_type "
                    "ORDER BY price")


def restaurant_options(db: Database) -> list[dict]:
    """餐厅下拉选项（含位置与营业时间，供界面展示）。"""
    return db.query(
        "SELECT restaurant_id, restaurant_name, location, open_time "
        "FROM restaurant ORDER BY restaurant_id")


def spa_service_options(db: Database) -> list[dict]:
    return db.query(
        "SELECT service_id, service_name, price, duration, description "
        "FROM spa_service ORDER BY service_id")


def fitness_facility_options(db: Database, *, only_available: bool = True) -> list[dict]:
    sql = ("SELECT facility_id, facility_name, capacity, location, open_time, status "
           "FROM fitness_facility")
    if only_available:
        sql += " WHERE status = 'available'"
    sql += " ORDER BY facility_id"
    return db.query(sql)


def room_floors(db: Database) -> list[int]:
    """所有楼层号，供前台按楼层筛选。"""
    return [int(row["floor"]) for row in db.query(
        "SELECT DISTINCT floor FROM room WHERE floor IS NOT NULL ORDER BY floor")]



# =====================================================================
#  用户管理（管理员）
# =====================================================================
def list_users(db: Database, *, role: str | None = None, keyword: str = "") -> list[dict]:
    sql = ("SELECT user_id, username, real_name, role, phone, email, is_active, created_at "
           "FROM `user` WHERE 1 = 1")
    params: list = []
    if role and role != "all":
        sql += " AND role = %s"
        params.append(role)
    if keyword:
        sql += " AND (username LIKE %s OR real_name LIKE %s)"
        params.extend([f"%{keyword}%", f"%{keyword}%"])
    sql += " ORDER BY user_id"
    return db.query(sql, params)


def set_user_active(db: Database, user_id: int, active: bool, *,
                    current_user_id: int) -> None:
    """
    启用/禁用账号。

    原实现的按钮叫「禁用/启用」，实际执行的是 DELETE FROM user，
    而且因为外键是 ON DELETE CASCADE，会连带删掉该用户全部订单 —— 
    一次误点就是不可逆的数据丢失。现在改为真正的软禁用。
    """
    if user_id == current_user_id:
        raise BusinessError("不能禁用当前登录的账号")
    affected = db.execute("UPDATE `user` SET is_active = %s WHERE user_id = %s",
                          (1 if active else 0, user_id))
    if affected != 1:
        raise BusinessError("用户不存在")


def create_user(db: Database, *, username: str, password: str, real_name: str,
                role: str, phone: str = "", email: str = "") -> None:
    if role not in ("guest", "receptionist", "admin"):
        raise BusinessError("角色不合法")
    if len(password or "") < 6:
        raise BusinessError("密码至少 6 位")
    try:
        with db.transaction() as tx:
            if tx.query_value("SELECT COUNT(*) FROM `user` WHERE username = %s",
                              (username.strip(),), 0):
                raise BusinessError("用户名已存在")
            tx.execute(
                "INSERT INTO `user` (username, password_hash, real_name, role, phone, email) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (username.strip(), hash_password(password), real_name.strip() or None, role,
                 phone.strip() or None, email.strip() or None),
            )
    except DatabaseError as exc:
        raise BusinessError(f"添加用户失败：{exc}") from exc


def admin_reset_password(db: Database, user_id: int, new_password: str) -> None:
    if len(new_password or "") < 6:
        raise BusinessError("新密码至少 6 位")
    affected = db.execute("UPDATE `user` SET password_hash = %s WHERE user_id = %s",
                          (hash_password(new_password), user_id))
    if affected != 1:
        raise BusinessError("用户不存在")
