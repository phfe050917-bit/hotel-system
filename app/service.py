"""
业务规则层 —— 三端界面共用的唯一业务入口。

原系统把业务规则直接写在 Tkinter 回调里，三端各写一份，导致：
  · 订单汇总逻辑重复三遍，客人端那份还用 BST 排序造成静默丢单；
  · 状态流转没有校验，可以从"待入住"直接跳到"已退房"；
  · 容量校验、日期校验散落在各处，且失败时抛未捕获异常。

本模块把规则集中到一处，界面只负责收集输入与展示结果。
所有校验失败统一抛 BusinessError，由界面转为提示框。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Sequence

from app.db import Database, DatabaseError, Transaction
from app.ids import new_order_id, uniqueness_guard
from app.security import hash_password, needs_rehash, verify_password

# --- 各表主键列名（订单通用操作时用） ---------------------------------
#    原设计覆盖客房/餐饮/健身/SPA/洗衣 5 条业务线；按课程题目
#    （选题19 宾馆客房管理系统）已收敛为客房主线，因此只剩 room 一项。
#    "订单类型 -> (表名, 主键列)" 的映射结构保留：以后要加业务线，
#    只需在这里登记一行，通用操作（查询/流转/取消/支付）无需改动。
_ORDER_TABLE = {
    "room": ("room_order", "order_id"),
}

# 各订单类型可用的状态机：当前状态 -> 允许到达的状态集合
_TRANSITIONS: dict[str, dict[str, set[str]]] = {
    "room": {
        "confirmed":   {"checked_in", "cancelled"},
        "checked_in":  {"checked_out"},
        "checked_out": set(),
        "cancelled":   set(),
    },
}

_STATUS_LABEL = {
    "confirmed": "待确认/待入住", "checked_in": "已入住",
    "checked_out": "已退房", "cancelled": "已取消",
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
    """解析正整数（供"人数/数量"类输入使用），并可限定上限。"""
    try:
        value = int(str(text).strip())
    except (TypeError, ValueError):
        raise BusinessError(f"{field}请填写整数") from None
    if value <= 0:
        raise BusinessError(f"{field}必须大于 0")
    if maximum is not None and value > maximum:
        raise BusinessError(f"{field}不能超过 {maximum}")
    return value


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
                      check_out: date, guest_name: str, guest_phone: str = "",
                      id_card: str = "") -> dict:
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
                "check_out_date, nights, total_price, guest_name, guest_phone, "
                "id_card, status) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'confirmed')",
                (order_id, user_id, room_id, check_in, check_out, nights,
                 float(room["price"]) * nights, guest_name, guest_phone or None,
                 id_card.strip() or None),
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
      · 走状态机，只有"进行中"的订单可取消，已完成的一律拒绝；
      · 已结账的订单必须先办理「结账单退款」，不能直接取消
        （数据库层还有 trg_room_order_before_update 兜底）。
    退回的款项（若已支付）记录一条 refunded 流水。
    """
    if order_type == "room":
        settled = db.query_value(
            "SELECT settlement_no FROM room_order WHERE order_id = %s",
            (order_id,), None)
        if settled:
            raise BusinessError(
                f"该订单已包含在结账单 {settled} 中，不能直接取消。\n"
                f"请先办理「结账单退款」，再按状态机处理订单。")

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


# ---------------------------------------------------------------------
#  敏感操作的密码支持与留痕（题目要求 (4)）
#
#  题目原文：「操作员在密码支持下才可更改房价，房间类型，增加客房」。
#  这里把"密码支持"实现为 Approval：操作员二次输入自己的登录密码，
#  服务层用 security.verify_password 校验（哈希比对，不是明文比较），
#  校验通过才允许改动，并把每个字段的「旧值 → 新值」写进 price_change_log。
# ---------------------------------------------------------------------
@dataclass(frozen=True)
class Approval:
    """敏感操作的密码凭据。"""
    operator_id: int
    operator_name: str
    password: str
    reason: str = ""


# 需要密码支持的表：房价/房型维护在 room_type，增加客房/改房间在 room
AUDITED_TABLES = ("room_type", "room")


def _require_approval(db: Database, table: str, approval: Approval | None) -> None:
    if table not in AUDITED_TABLES:
        return
    if approval is None:
        raise BusinessError(
            "按题目要求，修改房价、房间类型或增加客房必须由操作员在密码支持下进行。\n"
            "请输入当前账号密码后重试。")
    stored = db.query_value("SELECT password_hash FROM `user` WHERE user_id = %s",
                            (approval.operator_id,), None)
    if not stored:
        raise BusinessError("操作员账号不存在")
    if not verify_password(approval.password, stored):
        raise BusinessError("密码校验未通过，操作已被拒绝")


def _same_value(old, new) -> bool:
    """比较库中旧值与界面新值；数值按数值比较，避免 Decimal 与 float 误判为"有改动"。"""
    if old is None and new is None:
        return True
    if old is None or new is None:
        return False
    try:
        return abs(float(old) - float(new)) < 1e-9
    except (TypeError, ValueError):
        return str(old) == str(new)


def _write_audit(tx: Transaction, *, table: str, pk_value, target_label: str,
                 changes: dict, approval: Approval) -> None:
    """changes: {字段名: (旧值, 新值)}；字段名为 '*' 表示新增/删除整条记录。"""
    for field, (old, new) in changes.items():
        tx.execute(
            "INSERT INTO price_change_log (table_name, pk_value, target_label, "
            "field_name, old_value, new_value, reason, operator_id, operator_name) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (table, str(pk_value), (target_label or "")[:100], field,
             None if old is None else str(old)[:100],
             None if new is None else str(new)[:100],
             approval.reason.strip() or None,
             approval.operator_id, approval.operator_name))


def resource_create(db: Database, table: str, values: dict,
                    *, approval: Approval | None = None) -> None:
    spec = _resource_spec(table)
    fields = [f for f in spec["fields"] if f.editable]

    unknown = set(values) - {f.name for f in fields}
    if unknown:
        raise BusinessError(f"存在不可编辑字段：{'、'.join(sorted(unknown))}")

    payload = {f.name: _coerce(f, values.get(f.name)) for f in fields}
    if not any(v is not None for v in payload.values()):
        raise BusinessError("请至少填写一个字段")

    _require_approval(db, table, approval)

    columns = ", ".join(f"`{name}`" for name in payload)
    placeholders = ", ".join(["%s"] * len(payload))
    try:
        if approval is None:
            db.execute(f"INSERT INTO `{table}` ({columns}) VALUES ({placeholders})",
                       list(payload.values()))
            return
        with db.transaction() as tx:
            tx.execute(f"INSERT INTO `{table}` ({columns}) VALUES ({placeholders})",
                       list(payload.values()))
            new_pk = tx.query_value("SELECT LAST_INSERT_ID()", None, None)
            label = payload.get("room_number") or payload.get("type_name") or str(new_pk)
            summary = "新增：" + ", ".join(f"{k}={v}" for k, v in payload.items()
                                           if v is not None)
            _write_audit(tx, table=table, pk_value=new_pk, target_label=str(label),
                         changes={"*": (None, summary)}, approval=approval)
    except DatabaseError as exc:
        raise BusinessError(f"新增失败：{exc}") from exc


def resource_update(db: Database, table: str, pk_value, values: dict,
                    *, approval: Approval | None = None) -> None:
    """
    修改一条基础资源。

    values 只需要给出**要改动的字段**（部分更新）：没出现的字段保持原值。
    这样"只改房价"不会把描述、设施等无关字段一起写成 NULL，
    审计日志里也只会出现真正变化的字段。
    """
    spec = _resource_spec(table)
    fields = {f.name: f for f in spec["fields"] if f.editable}

    unknown = set(values) - set(fields)
    if unknown:
        raise BusinessError(f"存在不可编辑字段：{'、'.join(sorted(unknown))}")
    if not values:
        raise BusinessError("请至少提供一个要改动的字段")

    payload = {name: _coerce(fields[name], values.get(name)) for name in values}
    _require_approval(db, table, approval)

    assignments = ", ".join(f"`{name}`=%s" for name in payload)
    try:
        if approval is None:
            affected = db.execute(
                f"UPDATE `{table}` SET {assignments} WHERE `{spec['pk']}`=%s",
                [*payload.values(), pk_value])
            if affected != 1:
                raise BusinessError("记录不存在，或内容没有变化")
            return

        with db.transaction() as tx:
            before = tx.query_one(
                f"SELECT * FROM `{table}` WHERE `{spec['pk']}`=%s FOR UPDATE",
                (pk_value,))
            if before is None:
                raise BusinessError("记录不存在")

            affected = tx.execute(
                f"UPDATE `{table}` SET {assignments} WHERE `{spec['pk']}`=%s",
                [*payload.values(), pk_value])
            if affected != 1:
                raise BusinessError("内容没有变化，未产生任何改动")

            changes = {name: (before.get(name), new) for name, new in payload.items()
                       if not _same_value(before.get(name), new)}
            if changes:
                label = (before.get("room_number") or before.get("type_name")
                         or str(pk_value))
                _write_audit(tx, table=table, pk_value=pk_value,
                             target_label=str(label), changes=changes,
                             approval=approval)
    except DatabaseError as exc:
        raise BusinessError(f"保存失败：{exc}") from exc


def resource_delete(db: Database, table: str, pk_value,
                    *, approval: Approval | None = None) -> None:
    """
    删除一条基础资源。

    订单类外键为 RESTRICT，因此删除被引用的房型/房间时
    数据库会拒绝，这里把原因翻译成人能读懂的提示。
    """
    spec = _resource_spec(table)
    _require_approval(db, table, approval)

    try:
        if approval is None:
            affected = db.execute(f"DELETE FROM `{table}` WHERE `{spec['pk']}`=%s",
                                  (pk_value,))
        else:
            with db.transaction() as tx:
                before = tx.query_one(
                    f"SELECT * FROM `{table}` WHERE `{spec['pk']}`=%s FOR UPDATE",
                    (pk_value,))
                if before is None:
                    raise BusinessError("记录不存在")
                affected = tx.execute(f"DELETE FROM `{table}` WHERE `{spec['pk']}`=%s",
                                      (pk_value,))
                label = (before.get("room_number") or before.get("type_name")
                         or str(pk_value))
                _write_audit(tx, table=table, pk_value=pk_value,
                             target_label=str(label),
                             changes={"*": (str(before), "删除")},
                             approval=approval)
    except DatabaseError as exc:
        raise BusinessError(
            f"删除失败：该{spec['label']}被其他数据引用，数据库已阻止删除。\n"
            f"（这是外键 RESTRICT 的保护，避免误删历史订单）\n\n{exc}"
        ) from exc
    if affected != 1:
        raise BusinessError("记录不存在")


def list_price_change_logs(db: Database, *, limit: int = 200,
                           table: str = "") -> list[dict]:
    """价格/房型变更审计记录（管理端展示）。"""
    sql = ("SELECT l.log_id, l.table_name, l.pk_value, l.target_label, l.field_name, "
           "       l.old_value, l.new_value, l.reason, l.operator_name, l.changed_at, "
           "       CASE l.table_name WHEN 'room_type' THEN '房型' WHEN 'room' THEN '房间' "
           "            ELSE l.table_name END AS table_label, "
           "       CASE l.field_name WHEN 'price' THEN '房价' "
           "            WHEN 'type_name' THEN '房型名称' WHEN 'max_occupancy' THEN '最大入住' "
           "            WHEN 'room_number' THEN '房间号' WHEN 'floor' THEN '楼层' "
           "            WHEN 'type_id' THEN '房型ID' WHEN 'status' THEN '房间状态' "
           "            WHEN 'facilities' THEN '设施' WHEN 'description' THEN '描述' "
           "            WHEN '*' THEN '整条记录' ELSE l.field_name END AS field_label "
           "FROM price_change_log l WHERE 1 = 1")
    params: list = []
    if table:
        sql += " AND l.table_name = %s"
        params.append(table)
    sql += " ORDER BY l.changed_at DESC, l.log_id DESC LIMIT %s"
    params.append(int(limit))
    return db.query(sql, params)


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
           "CASE p.order_type WHEN 'room' THEN '客房' END AS type_label, "
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
               CASE r.order_type WHEN 'room' THEN '客房' END AS type_label
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


# =====================================================================
#  团体登记 / 团体入住 / 团体结账（题目要求 (1)）
# =====================================================================
GROUP_STATUS_LABEL = {
    "reserved": "已登记", "checked_in": "已入住",
    "checked_out": "已退房", "cancelled": "已取消",
}
SETTLEMENT_STATUS_LABEL = {"settled": "已结账", "refunded": "已退款"}


def _new_no(tx: Transaction, order_type: str, table: str, column: str) -> str:
    """事务内生成唯一单号（毫秒时间戳 + 4 位随机 + 冲突重试）。"""
    def exists(candidate: str) -> bool:
        return bool(tx.query_value(
            f"SELECT COUNT(*) FROM `{table}` WHERE `{column}` = %s", (candidate,), 0))
    return uniqueness_guard(lambda: new_order_id(order_type), exists)


def create_group_booking(db: Database, *, group_name: str, contact_name: str,
                         booker_user_id: int, check_in: date, check_out: date,
                         room_ids: Sequence[int], contact_phone: str = "",
                         id_card: str = "", leader_user_id: int | None = None,
                         remark: str = "") -> dict:
    """
    团体登记：一次为多间房生成同一张团体单下的客房订单。

    校验全部在同一个事务里完成，避免"查完再插"的并发窗口：
      · 团体名称/联系人/日期合法，且同名团体同一天不重复登记；
      · 至少选一间房、不能重复选同一间；
      · 每间房在该日期段内没有冲突订单（SELECT ... FOR UPDATE 复查）。

    金额与晚数仍由数据库触发器按当前房价重算，界面传什么都不影响账目。
    团体单未指定负责人账号时，订单记在 booker_user_id（登记操作员）名下，
    即"前台代客登记"。
    """
    name = (group_name or "").strip()
    contact = (contact_name or "").strip()
    if not name:
        raise BusinessError("请填写团体名称")
    if not contact:
        raise BusinessError("请填写联系人姓名")
    if check_out <= check_in:
        raise BusinessError("离店日期必须晚于入住日期")
    if check_in < date.today():
        raise BusinessError("入住日期不能早于今天")

    rooms = list(dict.fromkeys(int(r) for r in (room_ids or [])))
    if not rooms:
        raise BusinessError("请至少选择一间房间")
    if len(rooms) > 50:
        raise BusinessError("单次团体登记不能超过 50 间房")

    owner = int(leader_user_id or booker_user_id)
    try:
        with db.transaction() as tx:
            if tx.query_value(
                    "SELECT COUNT(*) FROM guest_group "
                    "WHERE group_name = %s AND check_in_date = %s",
                    (name, check_in), 0):
                raise BusinessError(f"团体「{name}」在 {check_in} 已登记过，请换一个名称")

            tx.execute(
                "INSERT INTO guest_group (group_name, contact_name, contact_phone, "
                "id_card, leader_user_id, check_in_date, check_out_date, remark) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (name, contact, contact_phone.strip() or None, id_card.strip() or None,
                 leader_user_id, check_in, check_out, remark.strip() or None))
            group_id = int(tx.query_value(
                "SELECT group_id FROM guest_group "
                "WHERE group_name = %s AND check_in_date = %s", (name, check_in), 0))

            order_ids: list[str] = []
            total_price = 0.0
            nights = 0
            for room_id in rooms:
                conflict = tx.query_one(
                    "SELECT order_id FROM room_order "
                    "WHERE room_id = %s AND status IN ('confirmed','checked_in') "
                    "  AND check_in_date < %s AND check_out_date > %s FOR UPDATE",
                    (room_id, check_out, check_in))
                if conflict:
                    room_no = tx.query_value("SELECT room_number FROM room "
                                             "WHERE room_id = %s", (room_id,), room_id)
                    raise BusinessError(
                        f"房间 {room_no} 在 {check_in} ~ {check_out} 期间已被预订"
                        f"（订单 {conflict['order_id']}），请重新选择房间")

                order_id = _new_no(tx, "room", "room_order", "order_id")
                tx.execute(
                    "INSERT INTO room_order (order_id, user_id, room_id, check_in_date, "
                    "check_out_date, nights, total_price, guest_name, guest_phone, "
                    "id_card, group_id) "
                    "VALUES (%s, %s, %s, %s, %s, 0, 0, %s, %s, %s, %s)",
                    (order_id, owner, room_id, check_in, check_out, contact,
                     contact_phone.strip() or None, id_card.strip() or None, group_id))
                saved = tx.query_one(
                    "SELECT nights, total_price FROM room_order WHERE order_id = %s",
                    (order_id,))
                order_ids.append(order_id)
                total_price += float(saved["total_price"])
                nights = int(saved["nights"])

            return {"group_id": group_id, "order_ids": order_ids, "nights": nights,
                    "room_count": len(order_ids), "total_price": round(total_price, 2)}
    except DatabaseError as exc:
        raise BusinessError(f"团体登记失败：{exc}") from exc


def list_groups(db: Database, *, keyword: str = "", status: str = "") -> list[dict]:
    """团体列表：带房间数、总金额、在住间数与已收款间数（一次查询取回）。"""
    sql = """
        SELECT g.group_id, g.group_name, g.contact_name, g.contact_phone, g.id_card,
               g.check_in_date, g.check_out_date, g.status, g.remark, g.created_at,
               COALESCE(agg.order_count, 0)    AS order_count,
               COALESCE(agg.total_amount, 0)   AS total_amount,
               COALESCE(agg.in_house_count, 0) AS in_house_count,
               COALESCE(agg.room_numbers, '')  AS room_numbers,
               COALESCE(pay.paid_count, 0)     AS paid_count,
               COALESCE(pay.settled_count, 0)  AS settled_count
        FROM guest_group g
        LEFT JOIN (
            SELECT ro.group_id,
                   COUNT(*)                                            AS order_count,
                   SUM(ro.total_price)                                 AS total_amount,
                   SUM(CASE WHEN ro.status = 'checked_in' THEN 1 ELSE 0 END)
                                                                       AS in_house_count,
                   GROUP_CONCAT(r.room_number ORDER BY r.room_number)  AS room_numbers
            FROM room_order ro
            JOIN room r ON r.room_id = ro.room_id
            WHERE ro.status <> 'cancelled'
            GROUP BY ro.group_id
        ) agg ON agg.group_id = g.group_id
        LEFT JOIN (
            -- 用 COUNT(DISTINCT 订单) 而不是 SUM(CASE ...)：一张订单可能先后有
            -- 多条流水（结账 → 退款 → 再结账），直接 SUM 会把同一间房重复计数。
            SELECT ro.group_id,
                   COUNT(DISTINCT CASE WHEN p.status = 'paid'
                                        THEN ro.order_id END)            AS paid_count,
                   COUNT(DISTINCT CASE WHEN ro.settlement_no IS NOT NULL
                                        THEN ro.order_id END)            AS settled_count
            FROM room_order ro
            LEFT JOIN payment p
                   ON p.order_type = 'room' AND p.order_id = ro.order_id
            WHERE ro.status <> 'cancelled'
            GROUP BY ro.group_id
        ) pay ON pay.group_id = g.group_id
        WHERE 1 = 1
    """
    params: list = []
    if keyword:
        sql += (" AND (g.group_name LIKE %s OR g.contact_name LIKE %s "
                "OR g.contact_phone LIKE %s OR g.id_card LIKE %s)")
        params += [f"%{keyword}%"] * 4
    if status and status in GROUP_STATUS_LABEL:
        sql += " AND g.status = %s"
        params.append(status)
    sql += " ORDER BY g.check_in_date DESC, g.group_id DESC"
    rows = db.query(sql, params)
    for row in rows:
        row["status_label"] = GROUP_STATUS_LABEL.get(row["status"], row["status"])
        row["bill_label"] = ("未结账" if not row["settled_count"]
                             else f"已结账 {row['settled_count']} 间")
    return rows


def group_members(db: Database, group_id: int) -> list[dict]:
    """某团体的成员订单明细（带支付与结账状态）。"""
    rows = db.query(
        "SELECT ro.order_id, r.room_number, rt.type_name, ro.guest_name, ro.id_card, "
        "       ro.check_in_date, ro.check_out_date, ro.nights, ro.total_price, "
        "       ro.status AS raw_status, ro.settlement_no, "
        "       CASE ro.status WHEN 'confirmed' THEN '待入住' WHEN 'checked_in' "
        "            THEN '已入住' WHEN 'checked_out' THEN '已退房' ELSE '已取消' END "
        "            AS status_label "
        "FROM room_order ro "
        "JOIN room r ON r.room_id = ro.room_id "
        "JOIN room_type rt ON rt.type_id = r.type_id "
        "WHERE ro.group_id = %s ORDER BY r.room_number, ro.order_id", (group_id,))
    paid = paid_order_map(db)
    for row in rows:
        row["paid_label"] = paid.get(("room", row["order_id"]), "未支付")
        row["settle_label"] = "已结账" if row["settlement_no"] else "未结账"
    return rows


def _advance_group(db: Database, group_id: int, *, target: str) -> int:
    """整团推进状态：所有处于前一状态的订单一起流转，并同步团体状态。"""
    source = "confirmed" if target == "checked_in" else "checked_in"
    action = "入住" if target == "checked_in" else "退房"
    try:
        with db.transaction() as tx:
            group = tx.query_one("SELECT group_id, status FROM guest_group "
                                 "WHERE group_id = %s FOR UPDATE", (group_id,))
            if group is None:
                raise BusinessError("团体单不存在")
            if group["status"] == "cancelled":
                raise BusinessError("该团体单已取消，不能继续办理")

            rows = tx.query("SELECT order_id FROM room_order "
                            "WHERE group_id = %s AND status = %s FOR UPDATE",
                            (group_id, source))
            if not rows:
                need = "待入住" if target == "checked_in" else "已入住"
                raise BusinessError(f"该团体没有可办理「{action}」的房间"
                                    f"（需要处于「{need}」状态的订单）")

            for row in rows:
                tx.execute("UPDATE room_order SET status = %s "
                           "WHERE order_id = %s AND status = %s",
                           (target, row["order_id"], source))

            tx.execute("UPDATE guest_group SET status = %s WHERE group_id = %s",
                       (target, group_id))
            return len(rows)
    except DatabaseError as exc:
        raise BusinessError(f"团体办理{action}失败：{exc}") from exc


def checkin_group(db: Database, group_id: int) -> int:
    """整团办理入住，返回办理的房间数。"""
    return _advance_group(db, group_id, target="checked_in")


def checkout_group(db: Database, group_id: int) -> int:
    """整团办理退房，返回办理的房间数（结账是另一步，见 settle_group）。"""
    return _advance_group(db, group_id, target="checked_out")


def _new_settlement(db: Database, *, order_ids: Sequence[str], group_id: int | None,
                    method: str, operator_id: int | None, remark: str,
                    source_label: str) -> dict:
    """
    结账核心：把若干订单一次结清并生成一张结账单。

    · 已经结过账（settlement_no 非空）的订单会被拒绝，避免一单两结；
    · 已取消的订单不计入账单；
    · 订单若已被客人自助付款，则只计入账单金额、不重复收款；
    · 全程一个事务：锁订单 → 建结账单 → 回填 settlement_no → 逐单登记收款。
    """
    if method not in PAYMENT_METHODS:
        raise BusinessError("请选择有效的结算方式")
    order_ids = list(dict.fromkeys(order_ids))
    if not order_ids:
        raise BusinessError("没有需要结账的订单")

    placeholders = ", ".join(["%s"] * len(order_ids))
    try:
        with db.transaction() as tx:
            rows = tx.query(
                f"SELECT order_id, user_id, total_price, status, settlement_no "
                f"FROM room_order WHERE order_id IN ({placeholders}) FOR UPDATE",
                order_ids)
            if len(rows) != len(order_ids):
                raise BusinessError("部分订单不存在，请刷新后重试")

            payable: list[dict] = []
            owners: set[int] = set()
            for row in rows:
                if row["settlement_no"]:
                    raise BusinessError(
                        f"订单 {row['order_id']} 已在结账单 {row['settlement_no']} 中，"
                        f"请勿重复结账")
                if row["status"] == "cancelled":
                    continue
                payable.append(row)
                owners.add(int(row["user_id"]))
            if not payable:
                raise BusinessError("没有需要结账的订单（订单可能都已取消）")

            total = round(sum(float(r["total_price"]) for r in payable), 2)
            if total <= 0:
                raise BusinessError("结账金额必须大于 0，请检查订单金额")

            payer = sorted(owners)[0]
            settlement_no = _new_no(tx, "settlement", "settlement", "settlement_no")
            tx.execute(
                "INSERT INTO settlement (settlement_no, group_id, user_id, room_count, "
                "total_amount, method, operator_id, remark) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (settlement_no, group_id, payer, len(payable), total, method,
                 operator_id, remark.strip() or None))

            collected = 0.0
            for row in payable:
                tx.execute("UPDATE room_order SET settlement_no = %s WHERE order_id = %s",
                           (settlement_no, row["order_id"]))
                already = tx.query_one(
                    "SELECT payment_id FROM payment WHERE order_type = 'room' "
                    "AND order_id = %s AND status = 'paid'", (row["order_id"],))
                if already:
                    continue                      # 客人已自助付款，不重复收款
                payment_no = _new_no(tx, "payment", "payment", "payment_no")
                tx.execute(
                    "INSERT INTO payment (payment_no, order_id, order_type, user_id, "
                    "amount, method, status) VALUES (%s, %s, 'room', %s, %s, %s, 'paid')",
                    (payment_no, row["order_id"], int(row["user_id"]),
                     float(row["total_price"]), method))
                collected += float(row["total_price"])

            return {"settlement_no": settlement_no, "room_count": len(payable),
                    "total_amount": total, "collected": round(collected, 2),
                    "order_ids": [r["order_id"] for r in payable]}
    except DatabaseError as exc:
        raise BusinessError(f"{source_label}失败：{exc}") from exc


def settle_group(db: Database, *, group_id: int, method: str = "cash",
                 operator_id: int | None = None, remark: str = "") -> dict:
    """团体结账：一次结清整团所有未结账房间，生成一张结账单（题目要求 (1)）。"""
    group = db.query_one("SELECT group_id, status, group_name FROM guest_group "
                         "WHERE group_id = %s", (group_id,))
    if group is None:
        raise BusinessError("团体单不存在")
    if group["status"] == "cancelled":
        raise BusinessError("该团体单已取消，无需结账")

    rows = db.query("SELECT order_id FROM room_order WHERE group_id = %s "
                    "AND status <> 'cancelled' AND settlement_no IS NULL "
                    "ORDER BY order_id", (group_id,))
    if not rows:
        raise BusinessError("该团体没有需要结账的房间（可能已全部结账或已取消）")
    return _new_settlement(db, order_ids=[r["order_id"] for r in rows],
                           group_id=group_id, method=method,
                           operator_id=operator_id, remark=remark,
                           source_label="团体结账")


def settle_order(db: Database, *, order_id: str, method: str = "cash",
                 operator_id: int | None = None, remark: str = "") -> dict:
    """散客结账：一张订单生成一张结账单。"""
    order = db.query_one("SELECT order_id, group_id, status FROM room_order "
                         "WHERE order_id = %s", (order_id,))
    if order is None:
        raise BusinessError("订单不存在")
    if order["status"] == "cancelled":
        raise BusinessError("已取消的订单无需结账")
    return _new_settlement(db, order_ids=[order_id], group_id=order["group_id"],
                           method=method, operator_id=operator_id, remark=remark,
                           source_label="结账")


def list_settlements(db: Database, *, start: date | None = None, end: date | None = None,
                     keyword: str = "", limit: int | None = None) -> list[dict]:
    """结账单列表（题目要求 (5)：结账报表）。"""
    sql = """
        SELECT s.settlement_no, s.group_id, gg.group_name, s.user_id, u.username,
               s.room_count, s.total_amount, s.method,
               CASE s.method WHEN 'cash' THEN '现金' WHEN 'card' THEN '银行卡'
                    WHEN 'wechat' THEN '微信' WHEN 'alipay' THEN '支付宝'
                    WHEN 'room_charge' THEN '挂房账' END AS method_label,
               s.operator_id, op.username AS operator_name,
               s.status, s.settled_at, s.remark,
               CASE WHEN s.group_id IS NULL THEN '散客' ELSE '团体' END AS bill_type
        FROM settlement s
        JOIN `user` u ON u.user_id = s.user_id
        LEFT JOIN `user` op ON op.user_id = s.operator_id
        LEFT JOIN guest_group gg ON gg.group_id = s.group_id
        WHERE 1 = 1
    """
    params: list = []
    if start:
        sql += " AND s.settled_at >= %s"
        params.append(start)
    if end:
        sql += " AND s.settled_at < DATE_ADD(%s, INTERVAL 1 DAY)"
        params.append(end)
    if keyword:
        sql += (" AND (s.settlement_no LIKE %s OR gg.group_name LIKE %s "
                "OR u.username LIKE %s)")
        params += [f"%{keyword}%"] * 3
    sql += " ORDER BY s.settled_at DESC, s.settlement_no DESC"
    if limit:
        sql += " LIMIT %s"
        params.append(int(limit))
    rows = db.query(sql, params)
    for row in rows:
        row["status_label"] = SETTLEMENT_STATUS_LABEL.get(row["status"], row["status"])
    return rows


def settlement_detail(db: Database, settlement_no: str) -> list[dict]:
    """结账单明细（一张账单下的每个房间与其收款流水）。"""
    return db.query(
        "SELECT * FROM v_settlement_detail WHERE settlement_no = %s "
        "ORDER BY room_number, order_id", (settlement_no,))


def order_settlement(db: Database, order_id: str) -> dict | None:
    """某订单所属的结账单（订单详情页展示用）。"""
    return db.query_one(
        "SELECT s.settlement_no, s.total_amount, s.room_count, s.method, s.status, "
        "       s.settled_at, s.remark "
        "FROM settlement s JOIN room_order ro ON ro.settlement_no = s.settlement_no "
        "WHERE ro.order_id = %s", (order_id,))


def refund_settlement(db: Database, *, settlement_no: str,
                      operator_id: int | None = None, reason: str = "") -> dict:
    """
    整单退款。

    把结账单置为已退款、名下收款流水全部置为 refunded，并把成员订单的
    settlement_no 置回 NULL —— 订单回到「未结账」状态，之后才允许按状态机
    取消（数据库层的 trg_room_order_before_update 就是按这个顺序放行的）。
    """
    try:
        with db.transaction() as tx:
            bill = tx.query_one(
                "SELECT settlement_no, status, room_count, total_amount "
                "FROM settlement WHERE settlement_no = %s FOR UPDATE",
                (settlement_no,))
            if bill is None:
                raise BusinessError("结账单不存在")
            if bill["status"] != "settled":
                raise BusinessError("该结账单已是退款状态，无需重复退款")

            order_count = int(tx.query_value(
                "SELECT COUNT(*) FROM room_order WHERE settlement_no = %s",
                (settlement_no,), 0))
            refunded = tx.execute(
                "UPDATE payment SET status = 'refunded' WHERE order_type = 'room' "
                "AND status = 'paid' AND order_id IN ("
                "    SELECT order_id FROM room_order WHERE settlement_no = %s)",
                (settlement_no,))
            tx.execute("UPDATE room_order SET settlement_no = NULL "
                       "WHERE settlement_no = %s", (settlement_no,))
            note = ((reason.strip() + " ") if reason.strip() else "") + "整单退款"
            tx.execute("UPDATE settlement SET status = 'refunded', remark = %s "
                       "WHERE settlement_no = %s", (note[:200], settlement_no))
            return {"settlement_no": settlement_no, "order_count": order_count,
                    "refund_amount": float(bill["total_amount"]),
                    "refunded_payments": int(refunded)}
    except DatabaseError as exc:
        raise BusinessError(f"结账单退款失败：{exc}") from exc


# =====================================================================
#  客人信息多手段查询（题目要求 (3)）
# =====================================================================
def search_guest_profile(db: Database, *, keyword: str = "", name: str = "",
                         phone: str = "", id_card: str = "", room_number: str = "",
                         order_id: str = "", check_in_from: date | None = None,
                         check_in_to: date | None = None,
                         limit: int | None = 300) -> list[dict]:
    """
    多手段查询客人信息，条件之间是「与」关系，可任意组合：

      keyword     —— 用户名 / 真实姓名 / 账号手机号 / 证件号 / 入住人姓名 模糊匹配
      name        —— 客人姓名（账号姓名或入住人姓名）
      phone       —— 手机号（账号手机号或入住人电话）
      id_card     —— 证件号
      room_number —— 房间号（模糊，支持"10"匹配 101/102）
      order_id    —— 订单号（模糊，支持只记得单号片段）
      check_in_from / check_in_to —— 入住日期区间

    数据来自 v_guest_profile：以 user 为主体，所以「没下过单的客人」也查得到。
    """
    sql = "SELECT * FROM v_guest_profile WHERE 1 = 1"
    params: list = []
    if keyword:
        sql += (" AND (username LIKE %s OR real_name LIKE %s OR phone LIKE %s "
                "OR id_card LIKE %s OR guest_name LIKE %s OR guest_phone LIKE %s)")
        params += [f"%{keyword}%"] * 6
    if name:
        sql += " AND (real_name LIKE %s OR guest_name LIKE %s)"
        params += [f"%{name}%"] * 2
    if phone:
        sql += " AND (phone LIKE %s OR guest_phone LIKE %s)"
        params += [f"%{phone}%"] * 2
    if id_card:
        sql += " AND id_card LIKE %s"
        params.append(f"%{id_card}%")
    if room_number:
        sql += " AND room_number LIKE %s"
        params.append(f"%{room_number}%")
    if order_id:
        sql += " AND order_id LIKE %s"
        params.append(f"%{order_id}%")
    if check_in_from:
        sql += " AND check_in_date >= %s"
        params.append(check_in_from)
    if check_in_to:
        sql += " AND check_in_date <= %s"
        params.append(check_in_to)
    # 有订单的排前面，再按入住日期倒序
    sql += " ORDER BY (order_id IS NULL), check_in_date DESC, user_id"
    if limit:
        sql += " LIMIT %s"
        params.append(int(limit))
    return db.query(sql, params)


def guest_orders(db: Database, user_id: int) -> list[dict]:
    """某客人的全部订单（客人查询页双击查看用）。"""
    return db.query(
        "SELECT * FROM v_guest_profile "
        "WHERE user_id = %s AND order_id IS NOT NULL "
        "ORDER BY check_in_date DESC, order_id DESC", (user_id,))
