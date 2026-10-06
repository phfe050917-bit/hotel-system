"""
统计与看板查询。

原系统管理端的"收入"是把各订单表按状态求和：
    SELECT SUM(total_price) FROM room_order WHERE status IN ('confirmed',...)
未收款的订单也被计入收入，账目不成立；而且这段 SQL 散在界面文件里，
三端各写一份。

现在：
  · 收入一律来自 payment 表的真实流水（v_daily_revenue）；
  · 订单量与状态分布来自 v_all_orders / v_service_stats；
  · 所有查询集中在本模块，界面只负责渲染。
"""

from __future__ import annotations

from datetime import date

from app.db import Database


def overview(db: Database, day: date | None = None) -> dict:
    """首页概览指标：今日各业务预约量、房间使用、注册用户数。"""
    today = day or date.today()

    return {
        "today": today,
        "arrivals": db.query_value(
            "SELECT COUNT(*) FROM room_order "
            "WHERE check_in_date = %s AND status IN ('confirmed','checked_in')",
            (today,), 0),
        "in_house": db.query_value(
            "SELECT COUNT(*) FROM room_order "
            "WHERE status = 'checked_in' AND check_in_date <= %s AND check_out_date > %s",
            (today, today), 0),
        "departures": db.query_value(
            "SELECT COUNT(*) FROM room_order "
            "WHERE check_out_date = %s AND status = 'checked_in'", (today,), 0),
        "dining_today": db.query_value(
            "SELECT COUNT(*) FROM dining_order "
            "WHERE dining_date = %s AND status <> 'cancelled'", (today,), 0),
        "fitness_today": db.query_value(
            "SELECT COUNT(*) FROM fitness_booking "
            "WHERE booking_date = %s AND status = 'confirmed'", (today,), 0),
        "spa_today": db.query_value(
            "SELECT COUNT(*) FROM spa_booking "
            "WHERE booking_date = %s AND status IN ('confirmed','in_progress')", (today,), 0),
        "laundry_active": db.query_value(
            "SELECT COUNT(*) FROM laundry_order "
            "WHERE status IN ('pending','picked_up','processing')", 0),
        "rooms_total": db.query_value("SELECT COUNT(*) FROM room", 0),
        "rooms_available": db.query_value(
            "SELECT COUNT(*) FROM room WHERE status = 'available'", 0),
        "rooms_occupied": db.query_value(
            "SELECT COUNT(*) FROM room WHERE status = 'occupied'", 0),
        "rooms_cleaning": db.query_value(
            "SELECT COUNT(*) FROM room WHERE status = 'cleaning'", 0),
        "rooms_maintenance": db.query_value(
            "SELECT COUNT(*) FROM room WHERE status = 'maintenance'", 0),
        "users_total": db.query_value("SELECT COUNT(*) FROM `user`", 0),
        "pending_payment": db.query_value(
            "SELECT COUNT(*) FROM v_all_orders o "
            "WHERE o.status_category <> '已取消' AND o.total_price > 0 "
            "  AND NOT EXISTS (SELECT 1 FROM payment p "
            "                  WHERE p.order_type = o.order_type "
            "                    AND p.order_id = o.order_id AND p.status = 'paid')",
            0),
    }


def revenue_summary(db: Database, start: date | None = None,
                    end: date | None = None) -> dict:
    """
    营收汇总（只统计已支付的流水）。

    原系统的"总收入"来自订单状态求和，与真实收款不符；
    这里以 payment.status='paid' 为准。
    """
    where = ["status = 'paid'"]
    params: list = []
    if start:
        where.append("paid_at >= %s")
        params.append(start)
    if end:
        where.append("paid_at < DATE_ADD(%s, INTERVAL 1 DAY)")
        params.append(end)

    condition = " AND ".join(where)
    total = float(db.query_value(
        f"SELECT COALESCE(SUM(amount), 0) FROM payment WHERE {condition}", params, 0) or 0)
    refunded = float(db.query_value(
        "SELECT COALESCE(SUM(amount), 0) FROM payment WHERE status = 'refunded'", None, 0) or 0)

    by_type = db.query(
        f"SELECT order_type, "
        f"       CASE order_type WHEN 'room' THEN '客房' WHEN 'dining' THEN '餐饮' "
        f"            WHEN 'fitness' THEN '健身' WHEN 'spa' THEN 'SPA' "
        f"            WHEN 'laundry' THEN '洗衣' END AS type_label, "
        f"       COUNT(*) AS payment_count, COALESCE(SUM(amount), 0) AS amount "
        f"FROM payment WHERE {condition} GROUP BY order_type ORDER BY amount DESC",
        params,
    )

    by_method = db.query(
        f"SELECT method, "
        f"       CASE method WHEN 'cash' THEN '现金' WHEN 'card' THEN '银行卡' "
        f"            WHEN 'wechat' THEN '微信' WHEN 'alipay' THEN '支付宝' "
        f"            WHEN 'room_charge' THEN '挂房账' END AS method_label, "
        f"       COUNT(*) AS payment_count, COALESCE(SUM(amount), 0) AS amount "
        f"FROM payment WHERE {condition} GROUP BY method ORDER BY amount DESC",
        params,
    )

    by_day = db.query(
        f"SELECT DATE(paid_at) AS pay_date, COALESCE(SUM(amount), 0) AS amount, "
        f"       COUNT(*) AS payment_count "
        f"FROM payment WHERE {condition} GROUP BY DATE(paid_at) ORDER BY pay_date DESC LIMIT 30",
        params,
    )

    return {
        "total": total,
        "refunded": refunded,
        "net": total - refunded,
        "by_type": by_type,
        "by_method": by_method,
        "by_day": by_day,
    }


def service_stats(db: Database) -> list[dict]:
    """各业务线的订单量、状态分布与订单金额（来自 v_service_stats 视图）。"""
    return db.query("SELECT * FROM v_service_stats ORDER BY order_count DESC")


def order_status_distribution(db: Database) -> list[dict]:
    return db.query(
        "SELECT type_label, status_category, COUNT(*) AS cnt "
        "FROM v_all_orders GROUP BY type_label, status_category "
        "ORDER BY type_label, status_category"
    )


def room_usage(db: Database) -> list[dict]:
    """按房型统计房间状态分布，用于管理端看板。"""
    return db.query(
        "SELECT rt.type_name, rt.price, COUNT(*) AS room_count, "
        "       SUM(CASE WHEN r.status = 'available' THEN 1 ELSE 0 END) AS available, "
        "       SUM(CASE WHEN r.status = 'occupied' THEN 1 ELSE 0 END) AS occupied, "
        "       SUM(CASE WHEN r.status = 'cleaning' THEN 1 ELSE 0 END) AS cleaning, "
        "       SUM(CASE WHEN r.status = 'maintenance' THEN 1 ELSE 0 END) AS maintenance "
        "FROM room r JOIN room_type rt ON rt.type_id = r.type_id "
        "GROUP BY rt.type_id, rt.type_name, rt.price ORDER BY rt.price"
    )


def top_dishes(db: Database, limit: int = 10) -> list[dict]:
    """菜品销量排行（体现明细表的作用）。"""
    return db.query(
        "SELECT d.dish_name, r.restaurant_name, SUM(i.quantity) AS sold, "
        "       SUM(i.subtotal) AS revenue "
        "FROM dining_order_item i "
        "JOIN dish d ON d.dish_id = i.dish_id "
        "JOIN restaurant r ON r.restaurant_id = d.restaurant_id "
        "GROUP BY d.dish_id, d.dish_name, r.restaurant_name "
        "ORDER BY sold DESC LIMIT %s",
        (int(limit),),
    )


def tech_workload(db: Database) -> list[dict]:
    """技师工作量统计（让 tech_schedule / spa_booking 的数据有意义）。"""
    return db.query(
        "SELECT t.tech_id, t.tech_name, t.tech_level, t.rating, "
        "       COUNT(b.booking_id) AS total_bookings, "
        "       SUM(CASE WHEN b.status = 'completed' THEN 1 ELSE 0 END) AS completed, "
        "       COALESCE(SUM(CASE WHEN b.status <> 'cancelled' THEN b.price ELSE 0 END), 0) "
        "       AS revenue "
        "FROM technician t "
        "LEFT JOIN spa_booking b ON b.tech_id = t.tech_id "
        "GROUP BY t.tech_id, t.tech_name, t.tech_level, t.rating "
        "ORDER BY total_bookings DESC"
    )


def schema_objects(db: Database) -> dict:
    """
    统计数据库对象数量（表/视图/触发器/索引/外键）。

    既可以在管理端"关于"页展示，也方便答辩时直观说明数据库设计
    —— 原系统这三项都是 0。
    """
    name = db.query_value("SELECT DATABASE()", None, "hotel_booking")
    counts = {
        "tables": db.query_value(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema = %s AND table_type = 'BASE TABLE'", (name,), 0),
        "views": db.query_value(
            "SELECT COUNT(*) FROM information_schema.views WHERE table_schema = %s",
            (name,), 0),
        "triggers": db.query_value(
            "SELECT COUNT(*) FROM information_schema.triggers WHERE trigger_schema = %s",
            (name,), 0),
        "indexes": db.query_value(
            "SELECT COUNT(DISTINCT table_name, index_name) FROM information_schema.statistics "
            "WHERE table_schema = %s AND index_name <> 'PRIMARY'", (name,), 0),
        "foreign_keys": db.query_value(
            "SELECT COUNT(*) FROM information_schema.key_column_usage "
            "WHERE table_schema = %s AND referenced_table_name IS NOT NULL", (name,), 0),
        "check_constraints": db.query_value(
            "SELECT COUNT(*) FROM information_schema.check_constraints "
            "WHERE constraint_schema = %s", (name,), 0),
    }
    return counts
