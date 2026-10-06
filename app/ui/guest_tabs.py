"""
客人端各标签页。

每个标签页只做三件事：读取输入、调用 app.service、渲染结果。
所有校验与写库都发生在 service 层，界面层不再出现任何 SQL。
"""

from __future__ import annotations

import tkinter as tk
from datetime import date, datetime, timedelta
from tkinter import ttk
from typing import Callable

from app import service
from app.service import BusinessError
from app.ui.widgets import (
    CS, FONT, DataTable, DateField, DetailDialog, LabeledCombo, LabeledEntry,
    RoundedButton, TimeCombo, ToolbarCombo, info, warn,
)

ORDERS_TABLE = [
    ("order_id", "订单号", 190),
    ("type_label", "类型", 60),
    ("detail", "详情", 250),
    ("created_at", "下单时间", 140),
    ("total_price", "金额", 80),
    ("status_label", "状态", 90),
]

PAY_METHODS = {"现金": "cash", "银行卡": "card", "微信": "wechat",
               "支付宝": "alipay", "挂房账": "room_charge"}


def _fmt_time(value) -> str:
    return str(value).split(".")[0] if value else ""


def _fmt_money(value) -> str:
    try:
        return f"¥{float(value or 0):,.2f}"
    except (TypeError, ValueError):
        return "¥0.00"


def parse_date_input(field: DateField, name: str) -> date:
    """把日期输入框转成 date，格式非法时给出明确提示。"""
    try:
        return field.value()
    except ValueError:
        raise BusinessError(f"{name}格式不正确，请使用 2026-05-10 这样的格式，"
                            f"或点击旁边的日期按钮") from None


class GuestTab(tk.Frame):
    """客人端标签页基类。"""

    def __init__(self, parent, window):
        super().__init__(parent, bg=CS.BG_MAIN)
        self.app = window              # GuestWindow
        self.db = window.db
        self.session = window.session

    # 左栏 / 右栏的通用布局
    def make_layout(self, left_width: int = 250) -> tuple[tk.Frame, tk.Frame]:
        left = tk.Frame(self, bg=CS.BG_WHITE, width=left_width,
                        highlightbackground=CS.BORDER, highlightthickness=1)
        left.pack(side="left", fill="y", padx=(10, 6), pady=10)
        left.pack_propagate(False)

        right = tk.Frame(self, bg=CS.BG_MAIN)
        right.pack(side="left", fill="both", expand=True, padx=(6, 10), pady=10)
        return left, right

    def on_show(self) -> None:
        """切换到本页时调用，子类按需覆盖。"""


# =====================================================================
#  客房预订
# =====================================================================
class RoomTab(GuestTab):
    """客房查询与预订。"""

    def __init__(self, parent, window):
        super().__init__(parent, window)

        left, right = self.make_layout(260)

        tk.Label(left, text="客房查询", font=(FONT, 14, "bold"), bg=CS.BG_WHITE,
                 fg=CS.TEXT_PRIMARY).pack(pady=(14, 12))

        form = tk.Frame(left, bg=CS.BG_WHITE)
        form.pack(fill="x", padx=16)

        self.check_in = DateField(form, "入住日期", date.today())
        self.check_in.pack(fill="x")
        self.check_out = DateField(form, "离店日期", date.today() + timedelta(days=1))
        self.check_out.pack(fill="x")

        type_names = ["全部房型"] + [t["type_name"] for t in service.room_type_options(self.db)]
        self.type_combo = LabeledCombo(form, "房型偏好", type_names, width=22)
        self.type_combo.pack(fill="x")

        RoundedButton(form, text="🔍 查询可用客房", width=200, height=36, radius=8,
                      command=self.search).pack(pady=(6, 14))

        tk.Label(form, text="入住人信息", font=(FONT, 10, "bold"), bg=CS.BG_WHITE,
                 fg=CS.TEXT_PRIMARY).pack(anchor="w", pady=(6, 4))
        self.guest_name = LabeledEntry(form, "入住人姓名", initial=self.session.real_name)
        self.guest_name.pack(fill="x")
        self.guest_phone = LabeledEntry(form, "联系电话（选填）")
        self.guest_phone.pack(fill="x")

        RoundedButton(form, text="📅 确认预订", width=200, height=38, radius=8,
                      color=CS.SUCCESS, hover_color=CS.SUCCESS_DARK,
                      command=self.book).pack(pady=(6, 16))

        tk.Label(right, text="可用客房列表（选中一行后点击左侧「确认预订」）",
                 font=(FONT, 12, "bold"), bg=CS.BG_MAIN,
                 fg=CS.TEXT_PRIMARY).pack(anchor="w", pady=(0, 6))

        self.table = DataTable(right, [
            ("room_number", "房间号", 90),
            ("type_name", "房型", 130),
            ("price", "价格/晚", 100),
            ("floor", "楼层", 70),
            ("max_occupancy", "可住人数", 90),
            ("facilities", "设施", 300),
        ], height=18)
        self.table.pack(fill="both", expand=True)

        self.search()

    def on_show(self) -> None:
        self.search()

    def search(self) -> None:
        def action() -> None:
            check_in = parse_date_input(self.check_in, "入住日期")
            check_out = parse_date_input(self.check_out, "离店日期")
            rooms = service.search_available_rooms(
                self.db, check_in, check_out, self.type_combo.get())
            self.table.set_rows(rooms, formatter=lambda r: (
                r["room_number"], r["type_name"], _fmt_money(r["price"]),
                f"{r['floor']}楼", f"{r['max_occupancy']}人", r["facilities"] or "-",
            ))
            self.app.status.show(f"查询到 {len(rooms)} 间可预订客房", "success")

        self.app.run_guarded(action)

    def book(self) -> None:
        room = self.table.selected()
        if room is None:
            warn("提示", "请先在右侧列表中选择一个房间", parent=self.app.window)
            return

        def action() -> None:
            check_in = parse_date_input(self.check_in, "入住日期")
            check_out = parse_date_input(self.check_out, "离店日期")
            order = service.create_room_order(
                self.db, user_id=self.session.user_id, room_id=room["room_id"],
                check_in=check_in, check_out=check_out,
                guest_name=self.guest_name.get(), guest_phone=self.guest_phone.get())

            info("预订成功",
                 f"订单号：{order['order_id']}\n"
                 f"房间号：{room['room_number']}（{room['type_name']}）\n"
                 f"入住 {check_in} → 离店 {check_out}，共 {order['nights']} 晚\n"
                 f"总金额：{_fmt_money(order['total_price'])}（由数据库按当前房价计算）",
                 parent=self.app.window)
            self.search()
            self.app.notify_order_changed()

        self.app.run_guarded(
            action,
            confirm_text=f"确认预订 {room['room_number']}（{room['type_name']}）？")


# =====================================================================
#  餐饮预约
# =====================================================================
class DiningTab(GuestTab):
    """餐厅预约 + 菜品明细下单（原系统没有明细，金额恒为 0）。"""

    def __init__(self, parent, window):
        super().__init__(parent, window)
        self._cart: dict[int, dict] = {}

        left, right = self.make_layout(270)

        tk.Label(left, text="餐厅预约", font=(FONT, 14, "bold"), bg=CS.BG_WHITE,
                 fg=CS.TEXT_PRIMARY).pack(pady=(14, 12))

        form = tk.Frame(left, bg=CS.BG_WHITE)
        form.pack(fill="x", padx=16)

        restaurants = service.restaurant_options(self.db)
        self._restaurant_map = {r["restaurant_name"]: r for r in restaurants}

        self.rest_combo = LabeledCombo(
            form, "选择餐厅", list(self._restaurant_map), width=24)
        self.rest_combo.pack(fill="x")
        self.rest_combo.combo.bind("<<ComboboxSelected>>",
                                   lambda _e: self.load_menu())

        self.location_label = tk.Label(form, text="", font=(FONT, 9), bg=CS.BG_WHITE,
                                       fg=CS.TEXT_SECONDARY, anchor="w", wraplength=220)
        self.location_label.pack(fill="x")

        self.dining_date = DateField(form, "用餐日期", date.today())
        self.dining_date.pack(fill="x")
        self.dining_time = TimeCombo(
            form, "用餐时间",
            ["11:30", "12:00", "12:30", "13:00", "17:30", "18:00", "18:30", "19:00", "19:30"])
        self.dining_time.pack(fill="x")
        self.guest_count = LabeledEntry(form, "用餐人数", initial="2")
        self.guest_count.pack(fill="x")

        tk.Label(form, text="已选菜品", font=(FONT, 10, "bold"), bg=CS.BG_WHITE,
                 fg=CS.TEXT_PRIMARY).pack(anchor="w", pady=(8, 2))

        self.cart_table = DataTable(form, [
            ("dish_name", "菜品", 120),
            ("quantity", "数量", 50),
            ("subtotal", "小计", 80),
        ], height=5)
        self.cart_table.pack(fill="both", expand=True)

        self.total_var = tk.StringVar(value="合计：¥0.00")
        tk.Label(form, textvariable=self.total_var, font=(FONT, 11, "bold"),
                 bg=CS.BG_WHITE, fg=CS.DANGER).pack(anchor="e", pady=(4, 0))

        cart_buttons = tk.Frame(form, bg=CS.BG_WHITE)
        cart_buttons.pack(fill="x", pady=(4, 0))
        RoundedButton(cart_buttons, text="移除选中", width=90, height=28, radius=6,
                      color=CS.NEUTRAL, hover_color=CS.NEUTRAL_DARK,
                      font=(FONT, 9, "bold"),
                      command=self.remove_from_cart).pack(side="left")
        RoundedButton(cart_buttons, text="清空", width=70, height=28, radius=6,
                      color=CS.NEUTRAL, hover_color=CS.NEUTRAL_DARK,
                      font=(FONT, 9, "bold"),
                      command=self.clear_cart).pack(side="left", padx=6)

        RoundedButton(form, text="🍽 提交预订", width=200, height=38, radius=8,
                      color=CS.SUCCESS, hover_color=CS.SUCCESS_DARK,
                      command=self.book).pack(pady=(8, 16))

        # 右栏：菜单
        header = tk.Frame(right, bg=CS.BG_MAIN)
        header.pack(fill="x")
        tk.Label(header, text="餐厅菜单", font=(FONT, 12, "bold"), bg=CS.BG_MAIN,
                 fg=CS.TEXT_PRIMARY).pack(side="left", pady=(0, 6))
        tk.Label(header, text="（选中菜品后填写数量，点「加入订单」）",
                 font=(FONT, 9), bg=CS.BG_MAIN, fg=CS.TEXT_SECONDARY).pack(side="left",
                                                                            padx=6)

        add_bar = tk.Frame(right, bg=CS.BG_MAIN)
        add_bar.pack(fill="x", pady=(0, 6))
        tk.Label(add_bar, text="数量：", font=(FONT, 10), bg=CS.BG_MAIN).pack(side="left")
        self.qty_entry = tk.Entry(add_bar, font=(FONT, 10), width=5, bd=1, relief="solid")
        self.qty_entry.insert(0, "1")
        self.qty_entry.pack(side="left")
        RoundedButton(add_bar, text="＋ 加入订单", width=120, height=30, radius=6,
                      font=(FONT, 9, "bold"),
                      command=self.add_to_cart).pack(side="left", padx=8)

        self.menu_table = DataTable(right, [
            ("category_name", "分类", 110),
            ("dish_name", "菜品名称", 160),
            ("price", "价格", 90),
            ("is_setmeal", "类型", 70),
            ("description", "描述", 320),
        ], height=17)
        self.menu_table.pack(fill="both", expand=True)

        self.load_menu()

    def on_show(self) -> None:
        self.load_menu()

    def load_menu(self) -> None:
        restaurant = self._restaurant_map.get(self.rest_combo.get())
        if not restaurant:
            return
        self.location_label.config(
            text=f"{restaurant['location']}  (营业时间见店内公告)")
        menu = service.list_menu(self.db, restaurant["restaurant_id"])
        self.menu_table.set_rows(menu, formatter=lambda d: (
            d["category_name"] or "未分类",
            d["dish_name"],
            _fmt_money(d["price"]),
            "套餐" if d["is_setmeal"] else "单点",
            d["description"] or "",
        ))

    # --- 购物车 -------------------------------------------------------
    def add_to_cart(self) -> None:
        dish = self.menu_table.selected()
        if dish is None:
            warn("提示", "请先在菜单中选中一道菜", parent=self.app.window)
            return
        try:
            quantity = service.parse_positive_int(self.qty_entry.get(), "数量", maximum=99)
        except BusinessError as exc:
            warn("提示", str(exc), parent=self.app.window)
            return

        entry = self._cart.setdefault(dish["dish_id"], {
            "dish_id": dish["dish_id"],
            "dish_name": dish["dish_name"],
            "price": float(dish["price"]),
            "quantity": 0,
        })
        entry["quantity"] += quantity
        self._refresh_cart()

    def remove_from_cart(self) -> None:
        row = self.cart_table.selected()
        if row is None:
            return
        self._cart.pop(row["dish_id"], None)
        self._refresh_cart()

    def clear_cart(self) -> None:
        self._cart.clear()
        self._refresh_cart()

    def _refresh_cart(self) -> None:
        rows = []
        total = 0.0
        for entry in self._cart.values():
            subtotal = entry["price"] * entry["quantity"]
            total += subtotal
            rows.append({**entry, "subtotal": subtotal})
        self.cart_table.set_rows(rows, formatter=lambda r: (
            r["dish_name"], r["quantity"], _fmt_money(r["subtotal"])))
        self.total_var.set(f"合计：{_fmt_money(total)}")

    # --- 下单 ---------------------------------------------------------
    def book(self) -> None:
        restaurant = self._restaurant_map.get(self.rest_combo.get())
        if restaurant is None:
            warn("提示", "请选择餐厅", parent=self.app.window)
            return

        def action() -> None:
            dining_date = parse_date_input(self.dining_date, "用餐日期")
            guest_count = service.parse_positive_int(self.guest_count.get(), "用餐人数",
                                                     maximum=20)
            items = [(e["dish_id"], e["quantity"]) for e in self._cart.values()]
            order = service.create_dining_order(
                self.db, user_id=self.session.user_id,
                restaurant_id=restaurant["restaurant_id"],
                dining_date=dining_date, dining_time=self.dining_time.get(),
                guest_count=guest_count, items=items)

            info("预订成功",
                 f"订单号：{order['order_id']}\n"
                 f"桌位：{order['table_number']}\n"
                 f"金额：{_fmt_money(order['total_price'])}"
                 + ("\n（未选菜品，可稍后到店点单）" if not items else ""),
                 parent=self.app.window)
            self.clear_cart()
            self.load_menu()
            self.app.notify_order_changed()

        summary = f"{len(self._cart)} 道菜，合计 {self.total_var.get()}"
        self.app.run_guarded(action, confirm_text=f"确认提交该餐饮预订？\n{summary}")


# =====================================================================
#  健身设施
# =====================================================================
class FitnessTab(GuestTab):
    """设施使用情况查询与预约（实时显示剩余名额）。"""

    def __init__(self, parent, window):
        super().__init__(parent, window)

        left, right = self.make_layout(260)

        tk.Label(left, text="健身设施", font=(FONT, 14, "bold"), bg=CS.BG_WHITE,
                 fg=CS.TEXT_PRIMARY).pack(pady=(14, 12))

        form = tk.Frame(left, bg=CS.BG_WHITE)
        form.pack(fill="x", padx=16)

        facilities = service.fitness_facility_options(self.db)
        self._facility_map = {f["facility_name"]: f for f in facilities}

        self.facility_combo = LabeledCombo(
            form, "选择设施", list(self._facility_map), width=22,
            on_change=lambda _v: self._show_info())
        self.facility_combo.pack(fill="x")

        self.info_label = tk.Label(form, text="", font=(FONT, 9), bg=CS.BG_WHITE,
                                   fg=CS.TEXT_SECONDARY, anchor="w", wraplength=215,
                                   justify="left")
        self.info_label.pack(fill="x", pady=(0, 6))

        self.book_date = DateField(form, "预约日期", date.today())
        self.book_date.pack(fill="x")
        self.slot_combo = LabeledCombo(form, "时间段", service.FITNESS_SLOTS, width=22)
        self.slot_combo.pack(fill="x")
        self.guest_count = LabeledEntry(form, "预约人数", initial="1")
        self.guest_count.pack(fill="x")

        buttons = tk.Frame(form, bg=CS.BG_WHITE)
        buttons.pack(fill="x", pady=(4, 0))
        RoundedButton(buttons, text="🔍 查看使用情况", width=105, height=34, radius=7,
                      font=(FONT, 9, "bold"),
                      command=self.refresh).pack(side="left")
        RoundedButton(buttons, text="🏋 确认预约", width=95, height=34, radius=7,
                      color=CS.SUCCESS, hover_color=CS.SUCCESS_DARK,
                      font=(FONT, 9, "bold"),
                      command=self.book).pack(side="left", padx=6)

        tk.Label(right, text="设施时段使用情况（按日期查询）",
                 font=(FONT, 12, "bold"), bg=CS.BG_MAIN,
                 fg=CS.TEXT_PRIMARY).pack(anchor="w", pady=(0, 6))

        self.table = DataTable(right, [
            ("facility_name", "设施", 110),
            ("location", "位置", 100),
            ("time_slot", "时段", 120),
            ("usage", "已约/容量", 110),
            ("remaining", "剩余名额", 90),
            ("availability", "状态", 90),
        ], height=18)
        self.table.pack(fill="both", expand=True)

        self._refresh_facility_list()
        self.refresh()

    def on_show(self) -> None:
        self._refresh_facility_list()

    def _refresh_facility_list(self) -> None:
        facilities = service.fitness_facility_options(self.db)
        self._facility_map = {f["facility_name"]: f for f in facilities}
        current = self.facility_combo.get()
        self.facility_combo.set_values(
            list(self._facility_map), current if current in self._facility_map else None,
            on_change=lambda _v: self._show_info(), notify=True)
        self._show_info()

    def _show_info(self) -> None:
        facility = self._facility_map.get(self.facility_combo.get())
        if facility:
            self.info_label.config(
                text=f"{facility['location']} · 开放 {facility['open_time']}\n"
                     f"单时段容量 {facility['capacity']} 人")

    def refresh(self) -> None:
        def action() -> None:
            target = parse_date_input(self.book_date, "预约日期")
            usage = service.fitness_usage(self.db, target)
            self.table.set_rows(usage, formatter=lambda u: (
                u["facility_name"], u["location"],
                u["time_slot"], f"{u['booked']}/{u['capacity']}",
                f"{u['remaining']} 人",
                "可预约" if u["available"] else "已满",
            ), tagger=lambda u: "空闲" if u["available"] else "维护中")
            self.app.status.show(f"{target} 共 {len(usage)} 个时段", "success")

        self.app.run_guarded(action)

    def book(self) -> None:
        facility = self._facility_map.get(self.facility_combo.get())
        if facility is None:
            warn("提示", "请选择设施", parent=self.app.window)
            return

        def action() -> None:
            target = parse_date_input(self.book_date, "预约日期")
            count = service.parse_positive_int(self.guest_count.get(), "预约人数",
                                               maximum=int(facility["capacity"]))
            result = service.create_fitness_booking(
                self.db, user_id=self.session.user_id,
                facility_id=facility["facility_id"], booking_date=target,
                time_slot=self.slot_combo.get(), guest_count=count)
            info("预约成功",
                 f"预约号：{result['booking_id']}\n"
                 f"{facility['facility_name']} {target} {self.slot_combo.get()}\n"
                 f"{count} 人 · 该时段剩余 {result['remaining']} 个名额",
                 parent=self.app.window)
            self.refresh()
            self.app.notify_order_changed()

        self.app.run_guarded(
            action,
            confirm_text=f"确认预约 {facility['facility_name']} "
                         f"{self.book_date.get()} {self.slot_combo.get()}？")


# =====================================================================
#  SPA
# =====================================================================
class SpaTab(GuestTab):
    """SPA 预约：选服务、选技师，并显示技师当日档期。"""

    def __init__(self, parent, window):
        super().__init__(parent, window)

        left, right = self.make_layout(270)

        tk.Label(left, text="SPA 预约", font=(FONT, 14, "bold"), bg=CS.BG_WHITE,
                 fg=CS.TEXT_PRIMARY).pack(pady=(14, 12))

        form = tk.Frame(left, bg=CS.BG_WHITE)
        form.pack(fill="x", padx=16)

        self._services = {s["service_name"]: s
                          for s in service.spa_service_options(self.db)}

        self.service_combo = LabeledCombo(form, "选择服务", list(self._services), width=23)
        self.service_combo.pack(fill="x")
        self.service_combo.combo.bind("<<ComboboxSelected>>",
                                      lambda _e: self._on_service_change(
                                          self.service_combo.get()))

        self.detail_label = tk.Label(form, text="", font=(FONT, 9), bg=CS.BG_WHITE,
                                     fg=CS.TEXT_SECONDARY, anchor="w", wraplength=225,
                                     justify="left")
        self.detail_label.pack(fill="x", pady=(0, 6))

        self.tech_combo = LabeledCombo(
            form, "选择技师", [], width=23,
            on_change=lambda _v: self.load_schedule() if hasattr(self, "tech_combo")
            else None)
        self.tech_combo.pack(fill="x")
        self._tech_map: dict[str, dict] = {}

        self.book_date = DateField(form, "预约日期", date.today())
        self.book_date.pack(fill="x")
        self.slot_combo = LabeledCombo(
            form, "预约时间",
            [f"{h:02d}:00" for h in range(9, 21)], width=23)
        self.slot_combo.pack(fill="x")

        RoundedButton(form, text="💆 提交预约", width=200, height=38, radius=8,
                      color=CS.PURPLE, hover_color=CS.PURPLE_DARK,
                      command=self.book).pack(pady=(8, 16))

        tk.Label(right, text="SPA 服务项目", font=(FONT, 12, "bold"), bg=CS.BG_MAIN,
                 fg=CS.TEXT_PRIMARY).pack(anchor="w", pady=(0, 6))

        self.service_table = DataTable(right, [
            ("service_name", "服务名称", 170),
            ("duration", "时长(分钟)", 100),
            ("price", "价格", 100),
            ("description", "描述", 400),
        ], height=9)
        self.service_table.pack(fill="both", expand=False)

        tk.Label(right, text="该技师当日档期（已约时段不可选）", font=(FONT, 12, "bold"),
                 bg=CS.BG_MAIN, fg=CS.TEXT_PRIMARY).pack(anchor="w", pady=(14, 6))

        self.schedule_table = DataTable(right, [
            ("time_slot", "时段", 120),
            ("slot_label", "状态", 100),
        ], height=7)
        self.schedule_table.pack(fill="both", expand=True)

        self._load_services()
        self._on_service_change(self.service_combo.get())

    def on_show(self) -> None:
        self.load_schedule()

    def _load_services(self) -> None:
        services = service.spa_service_options(self.db)
        self._services = {s["service_name"]: s for s in services}
        self.service_combo.set_values(list(self._services),
                                      on_change=self._on_service_change, notify=True)
        self.service_table.set_rows(services, formatter=lambda s: (
            s["service_name"], f"{s['duration']} 分钟", _fmt_money(s["price"]),
            s["description"] or ""))

    def _on_service_change(self, service_name: str) -> None:
        service_row = self._services.get(service_name)
        if not service_row:
            return
        self.detail_label.config(
            text=f"时长 {service_row['duration']} 分钟 · {_fmt_money(service_row['price'])}\n"
                 f"{service_row['description'] or ''}")

        technicians = service.list_technicians(self.db, service_row["service_id"])
        self._tech_map = {f"{t['tech_name']}（{t['tech_level']}·{t['rating']}分）": t
                          for t in technicians}
        self.tech_combo.set_values(list(self._tech_map),
                                   on_change=lambda _v: self.load_schedule(),
                                   notify=True)
        self.load_schedule()

    def load_schedule(self) -> None:
        tech = self._tech_map.get(self.tech_combo.get())
        if tech is None:
            self.schedule_table.clear()
            return
        try:
            target = parse_date_input(self.book_date, "预约日期")
        except BusinessError:
            return
        rows = service.tech_availability(self.db, tech["tech_id"], target)
        self.schedule_table.set_rows(rows, formatter=lambda r: (
            r["time_slot"], r["slot_label"]),
            tagger=lambda r: "已预约" if r["is_booked"] else "空闲")

    def book(self) -> None:
        service_row = self._services.get(self.service_combo.get())
        tech = self._tech_map.get(self.tech_combo.get())
        if service_row is None or tech is None:
            warn("提示", "请选择服务与技师", parent=self.app.window)
            return

        def action() -> None:
            target = parse_date_input(self.book_date, "预约日期")
            result = service.create_spa_booking(
                self.db, user_id=self.session.user_id,
                service_id=service_row["service_id"], tech_id=tech["tech_id"],
                booking_date=target, booking_time=self.slot_combo.get())
            info("预约成功",
                 f"预约号：{result['booking_id']}\n"
                 f"{result['service_name']}（{result['duration']} 分钟）\n"
                 f"技师：{result['tech_name']}\n"
                 f"时间：{target} {self.slot_combo.get()}\n"
                 f"金额：{_fmt_money(result['price'])}",
                 parent=self.app.window)
            self.load_schedule()
            self.app.notify_order_changed()

        self.app.run_guarded(
            action,
            confirm_text=f"确认预约 {service_row['service_name']}（{tech['tech_name']}）"
                         f"{self.book_date.get()} {self.slot_combo.get()}？")


# =====================================================================
#  洗衣服务
# =====================================================================
class LaundryTab(GuestTab):
    """
    洗衣服务：实时报价 + 只看自己的订单。

    原实现把**全部住客**的洗衣订单（含房间号）显示给当前客人，
    属于隐私泄露；这里调用 service.laundry_queue(user_id=...) 只看自己的。
    """

    def __init__(self, parent, window):
        super().__init__(parent, window)

        left, right = self.make_layout(260)

        tk.Label(left, text="洗衣服务", font=(FONT, 14, "bold"), bg=CS.BG_WHITE,
                 fg=CS.TEXT_PRIMARY).pack(pady=(14, 12))

        form = tk.Frame(left, bg=CS.BG_WHITE)
        form.pack(fill="x", padx=16)

        self._service_labels = {v[0]: key for key, v in service.LAUNDRY_SERVICES.items()}
        self.service_combo = LabeledCombo(form, "服务类型", list(self._service_labels),
                                         width=22, on_change=lambda _v: self.recalc())
        self.service_combo.pack(fill="x")

        self.item_count = LabeledEntry(form, "衣物数量（件）", initial="1")
        self.item_count.pack(fill="x")
        self.item_count.bind_change(self.recalc)

        self.room_entry = LabeledEntry(form, "房间号（有在住订单时可留空自动识别）")
        self.room_entry.pack(fill="x")

        self.pickup_combo = LabeledCombo(
            form, "预约取衣时间",
            ["立即取衣", "09:00", "10:00", "11:00", "14:00", "15:00", "16:00", "17:00"],
            width=22)
        self.pickup_combo.pack(fill="x")

        self.price_label = tk.Label(form, text="预估费用：¥25.00", font=(FONT, 12, "bold"),
                                    bg=CS.BG_WHITE, fg=CS.DANGER)
        self.price_label.pack(anchor="w", pady=(6, 2))

        self.eta_label = tk.Label(form, text="", font=(FONT, 9), bg=CS.BG_WHITE,
                                  fg=CS.TEXT_SECONDARY, anchor="w")
        self.eta_label.pack(fill="x")

        RoundedButton(form, text="👕 确认预约", width=200, height=38, radius=8,
                      color=CS.WARNING, hover_color=CS.WARNING_DARK,
                      command=self.book).pack(pady=(10, 16))

        header = tk.Frame(right, bg=CS.BG_MAIN)
        header.pack(fill="x")
        tk.Label(header, text="📋 我的洗衣订单", font=(FONT, 12, "bold"), bg=CS.BG_MAIN,
                 fg=CS.TEXT_PRIMARY).pack(side="left", pady=(0, 6))
        tk.Label(header, text="（按加急优先、同时段先到先处理排序）", font=(FONT, 9),
                 bg=CS.BG_MAIN, fg=CS.TEXT_SECONDARY).pack(side="left", padx=6)

        self.table = DataTable(right, [
            ("order_id", "订单号", 190),
            ("service_label", "服务类型", 100),
            ("room_number", "房间号", 80),
            ("item_count", "数量", 60),
            ("total_price", "金额", 80),
            ("status_label", "状态", 90),
            ("pickup_time", "取衣时间", 140),
            ("delivery_time", "送达时间", 140),
        ], height=10)
        self.table.pack(fill="both", expand=True, pady=(0, 6))

        tk.Label(right, text="洗衣价格表", font=(FONT, 12, "bold"), bg=CS.BG_MAIN,
                 fg=CS.TEXT_PRIMARY).pack(anchor="w", pady=(8, 4))

        self.price_table = DataTable(right, [
            ("service_name", "服务类型", 120),
            ("unit_price", "单价(元/件)", 110),
            ("eta", "预计完成时间", 140),
        ], height=6)
        self.price_table.pack(fill="both", expand=True)
        self.price_table.set_rows(
            [{"service_name": name, "unit_price": price, "eta": eta}
             for name, price, eta in service.LAUNDRY_SERVICES.values()],
            formatter=lambda r: (r["service_name"], f"¥{r['unit_price']:.2f}", r["eta"]))

        self.recalc()
        self.refresh()

    def on_show(self) -> None:
        self.refresh()

    def recalc(self) -> None:
        label = self.service_combo.get()
        service_type = self._service_labels.get(label)
        if not service_type:
            return
        try:
            count = int(self.item_count.get() or 0)
        except ValueError:
            count = 0
        quote = service.estimate_laundry(service_type, max(1, count))
        total = quote["unit_price"] * count if count > 0 else 0
        self.price_label.config(text=f"预估费用：{_fmt_money(total)}")
        self.eta_label.config(
            text=f"单价 ¥{quote['unit_price']:.2f}/件 · 预计完成：{quote['eta']}")

    def refresh(self) -> None:
        def action() -> None:
            rows = service.laundry_queue(self.db, user_id=self.session.user_id)
            self.table.set_rows(rows, formatter=lambda o: (
                o["order_id"], o["service_label"], o["room_number"], o["item_count"],
                _fmt_money(o["total_price"]), o["status_label"],
                _fmt_time(o["pickup_time"]) or "—",
                _fmt_time(o["delivery_time"]) or "—",
            ), tagger=lambda o: o["status_label"])
            self.app.status.show(f"共 {len(rows)} 条洗衣订单", "success")

        self.app.run_guarded(action)

    def book(self) -> None:
        label = self.service_combo.get()
        service_type = self._service_labels.get(label)
        if not service_type:
            warn("提示", "请选择洗衣服务类型", parent=self.app.window)
            return

        def action() -> None:
            count = service.parse_positive_int(self.item_count.get(), "衣物数量", maximum=99)
            result = service.create_laundry_order(
                self.db, user_id=self.session.user_id, service_type=service_type,
                item_count=count, room_number=self.room_entry.get(),
                expected_pickup=self.pickup_combo.get())
            info("预约成功",
                 f"订单号：{result['order_id']}\n"
                 f"{label} × {count} 件\n"
                 f"房间号：{result['room_number']}\n"
                 f"金额：{_fmt_money(result['total_price'])}\n"
                 f"取衣时间：{self.pickup_combo.get()}",
                 parent=self.app.window)
            self.refresh()
            self.app.notify_order_changed()

        self.app.run_guarded(
            action,
            confirm_text=f"确认提交洗衣订单？\n{label} × {self.item_count.get()} 件，"
                         f"{self.price_label.cget('text')}")


# =====================================================================
#  我的订单
# =====================================================================
class OrdersTab(GuestTab):
    """
    我的订单：统一走 v_all_orders 视图。

    原实现把 5 张表的查询在界面里 UNION，再用 BST 按"秒级时间戳"排序，
    同一秒创建的多单会互相覆盖、静默丢单。改为视图 + ORDER BY 后，
    排序与去重都由数据库保证。
    """

    def __init__(self, parent, window):
        super().__init__(parent, window)

        toolbar = tk.Frame(self, bg=CS.BG_MAIN)
        toolbar.pack(fill="x", padx=10, pady=(10, 4))

        self.type_combo = ToolbarCombo(
            toolbar, "类型：", ["全部", "客房", "餐饮", "健身", "SPA", "洗衣"],
            width=8, on_change=lambda _v: self.refresh())
        self.type_combo.pack(side="left", padx=(0, 12))

        self.status_combo = ToolbarCombo(
            toolbar, "状态：", ["全部", "进行中", "已完成", "已取消"],
            width=8, on_change=lambda _v: self.refresh())
        self.status_combo.pack(side="left", padx=(0, 12))

        RoundedButton(toolbar, text="🔄 刷新", width=90, height=30, radius=6,
                      font=(FONT, 9, "bold"), command=self.refresh).pack(side="left")

        RoundedButton(toolbar, text="💳 支付选中订单", width=140, height=30, radius=6,
                      color=CS.SUCCESS, hover_color=CS.SUCCESS_DARK,
                      font=(FONT, 9, "bold"),
                      command=self.pay).pack(side="right")
        RoundedButton(toolbar, text="⭐ 评价", width=80, height=30, radius=6,
                      color=CS.WARNING, hover_color=CS.WARNING_DARK,
                      font=(FONT, 9, "bold"),
                      command=self.review).pack(side="right", padx=6)
        RoundedButton(toolbar, text="❌ 取消订单", width=100, height=30, radius=6,
                      color=CS.DANGER, hover_color=CS.DANGER_DARK,
                      font=(FONT, 9, "bold"),
                      command=self.cancel).pack(side="right", padx=6)
        RoundedButton(toolbar, text="📄 详情", width=80, height=30, radius=6,
                      color=CS.PRIMARY, hover_color=CS.PRIMARY_DARK,
                      font=(FONT, 9, "bold"),
                      command=self.detail).pack(side="right")

        self.table = DataTable(self, ORDERS_TABLE, height=18,
                               on_double_click=lambda _row: self.detail())
        self.table.pack(fill="both", expand=True, padx=10, pady=(4, 10))

        self.refresh()

    def on_show(self) -> None:
        self.refresh()

    def refresh(self) -> None:
        def action() -> None:
            type_map = {"全部": None, "客房": "room", "餐饮": "dining",
                        "健身": "fitness", "SPA": "spa", "洗衣": "laundry"}
            rows = service.list_orders(
                self.db, user_id=self.session.user_id,
                order_type=type_map.get(self.type_combo.get()),
                status_category=self.status_combo.get())
            self.table.set_rows(rows, formatter=lambda o: (
                o["order_id"], o["type_label"], o["detail"],
                _fmt_time(o["created_at"]), _fmt_money(o["total_price"]),
                o["status_label"],
            ), tagger=lambda o: o["status_label"])
            self.app.status.show(f"共 {len(rows)} 条订单", "success")

        self.app.run_guarded(action)

    # --- 操作 ---------------------------------------------------------
    def detail(self) -> None:
        row = self.table.selected()
        if row is None:
            warn("提示", "请先选择一条订单", parent=self.app.window)
            return

        pairs = [
            ("订单号", row["order_id"]),
            ("类型", row["type_label"]),
            ("详情", row["detail"]),
            ("下单时间", _fmt_time(row["created_at"])),
            ("金额", _fmt_money(row["total_price"])),
            ("状态", row["status_label"]),
        ]

        list_data = None
        if row["order_type"] == "dining":
            items = service.dining_order_items(self.db, row["order_id"])
            if items:
                list_data = {
                    "title": "菜品明细",
                    "columns": [("dish_name", "菜品", 140), ("quantity", "数量", 60),
                                ("unit_price", "单价", 80), ("subtotal", "小计", 80)],
                    "rows": items,
                    "formatter": lambda i: (i["dish_name"], i["quantity"],
                                            _fmt_money(i["unit_price"]),
                                            _fmt_money(i["subtotal"])),
                }
        elif row["order_type"] == "room":
            paid = service.order_payment(self.db, "room", row["order_id"])
            if paid:
                pairs.append(("支付流水", f"{paid['payment_no']} "
                                          f"{_fmt_money(paid['amount'])} "
                                          f"{'已支付' if paid['status'] == 'paid' else '已退款'}"))

        DetailDialog(self.app.window, "订单详情", pairs, list_data=list_data)

    def _paid(self, order_type: str, order_id: str) -> dict | None:
        paid = service.order_payment(self.db, order_type, order_id)
        return paid if paid and paid["status"] == "paid" else None

    def pay(self) -> None:
        row = self.table.selected()
        if row is None:
            warn("提示", "请先选择一条订单", parent=self.app.window)
            return
        if row["status_category"] == "已取消":
            warn("提示", "已取消的订单无需付款", parent=self.app.window)
            return
        if row["order_type"] == "fitness":
            info("提示", "健身预约免费，无需支付", parent=self.app.window)
            return
        if self._paid(row["order_type"], row["order_id"]):
            info("提示", "该订单已支付", parent=self.app.window)
            return
        if float(row["total_price"] or 0) <= 0:
            info("提示", "该订单金额为 0，无需支付", parent=self.app.window)
            return

        PaymentDialog(self.app.window, self.db, self.session, row, on_success=self.refresh)

    def review(self) -> None:
        row = self.table.selected()
        if row is None:
            warn("提示", "请先选择一条订单", parent=self.app.window)
            return
        if row["status_category"] != "已完成":
            warn("提示", f"订单当前是「{row['status_label']}」，完成后才能评价",
                 parent=self.app.window)
            return

        ReviewDialog(self.app.window, self.db, self.session, row, on_success=self.refresh)

    def cancel(self) -> None:
        row = self.table.selected()
        if row is None:
            warn("提示", "请先选择一条订单", parent=self.app.window)
            return

        def action() -> None:
            has_paid = self._paid(row["order_type"], row["order_id"]) is not None
            service.cancel_order(self.db, row["order_type"], row["order_id"])
            info("已取消",
                 f"订单 {row['order_id']} 已取消。"
                 + ("\n已支付的款项已登记为退款。" if has_paid else ""),
                 parent=self.app.window)
            self.refresh()

        self.app.run_guarded(
            action, confirm_title="确认取消",
            confirm_text=f"确定要取消订单 {row['order_id']} 吗？\n"
                         f"{row['type_label']} · {row['detail']}")


# =====================================================================
#  对话框
# =====================================================================
class PaymentDialog(tk.Toplevel):
    """支付方式选择对话框。"""

    def __init__(self, parent, db, session, order: dict, on_success: Callable[[], None]):
        super().__init__(parent)
        self.db = db
        self.session = session
        self.order = order
        self.on_success = on_success

        self.title("订单支付")
        self.configure(bg=CS.BG_WHITE)
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self._error = tk.StringVar()
        self._build()
        from app.ui.widgets import center_window
        center_window(self, 400, 340)

    def _build(self) -> None:
        order = self.order
        tk.Label(self, text="💳 订单支付", font=(FONT, 15, "bold"), bg=CS.BG_WHITE,
                 fg=CS.TEXT_PRIMARY).pack(pady=(20, 10))

        body = tk.Frame(self, bg=CS.BG_WHITE)
        body.pack(padx=30, fill="x")
        for label, value in (("订单号", order["order_id"]),
                             ("类型", order["type_label"]),
                             ("详情", order["detail"]),
                             ("应付金额", _fmt_money(order["total_price"]))):
            row = tk.Frame(body, bg=CS.BG_WHITE)
            row.pack(fill="x", pady=3)
            tk.Label(row, text=f"{label}：", font=(FONT, 10), bg=CS.BG_WHITE,
                     fg=CS.TEXT_SECONDARY, width=9, anchor="e").pack(side="left")
            tk.Label(row, text=str(value), font=(FONT, 10), bg=CS.BG_WHITE,
                     fg=CS.TEXT_PRIMARY, anchor="w", wraplength=240,
                     justify="left").pack(side="left")

        tk.Label(body, text="支付方式：", font=(FONT, 10), bg=CS.BG_WHITE,
                 fg=CS.TEXT_SECONDARY).pack(anchor="w", pady=(10, 2))
        self.method_combo = ttk.Combobox(body, values=list(PAY_METHODS),
                                        font=(FONT, 10), state="readonly", width=22)
        self.method_combo.current(2)
        self.method_combo.pack(anchor="w")

        tk.Label(self, textvariable=self._error, font=(FONT, 9), bg=CS.BG_WHITE,
                 fg=CS.DANGER, wraplength=330, justify="left").pack(pady=(8, 0))

        buttons = tk.Frame(self, bg=CS.BG_WHITE)
        buttons.pack(pady=12)
        RoundedButton(buttons, text="确认支付", width=130, height=36, radius=8,
                      color=CS.SUCCESS, hover_color=CS.SUCCESS_DARK,
                      command=self._submit).pack(side="left", padx=4)
        RoundedButton(buttons, text="取消", width=80, height=36, radius=8,
                      color=CS.NEUTRAL, hover_color=CS.NEUTRAL_DARK,
                      command=self.destroy).pack(side="left", padx=4)

    def _submit(self) -> None:
        try:
            result = service.pay_order(
                self.db, order_type=self.order["order_type"],
                order_id=self.order["order_id"], user_id=self.session.user_id,
                method=PAY_METHODS[self.method_combo.get()])
        except BusinessError as exc:
            self._error.set(f"⚠ {exc}")
            return

        info("支付成功",
             f"流水号：{result['payment_no']}\n金额：{_fmt_money(result['amount'])}",
             parent=self.master)
        self.destroy()
        self.on_success()


class ReviewDialog(tk.Toplevel):
    """星级评价对话框。"""

    def __init__(self, parent, db, session, order: dict, on_success: Callable[[], None]):
        super().__init__(parent)
        self.db = db
        self.session = session
        self.order = order
        self.on_success = on_success
        self.rating = 5

        self.title("服务评价")
        self.configure(bg=CS.BG_WHITE)
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self._error = tk.StringVar()
        self._stars: list[tk.Button] = []
        self._build()
        from app.ui.widgets import center_window
        center_window(self, 420, 380)

    def _build(self) -> None:
        tk.Label(self, text="⭐ 服务评价", font=(FONT, 15, "bold"), bg=CS.BG_WHITE,
                 fg=CS.TEXT_PRIMARY).pack(pady=(18, 6))
        tk.Label(self, text=f"{self.order['type_label']} · {self.order['detail']}",
                 font=(FONT, 9), bg=CS.BG_WHITE, fg=CS.TEXT_SECONDARY,
                 wraplength=360).pack()

        star_frame = tk.Frame(self, bg=CS.BG_WHITE)
        star_frame.pack(pady=10)
        for value in range(1, 6):
            button = tk.Button(star_frame, text="★", font=(FONT, 20), bd=0,
                               bg=CS.BG_WHITE, fg=CS.WARNING, cursor="hand2",
                               command=lambda v=value: self._set_rating(v))
            button.pack(side="left", padx=3)
            self._stars.append(button)

        self.rating_label = tk.Label(self, text="当前评分：5 星", font=(FONT, 10),
                                     bg=CS.BG_WHITE, fg=CS.TEXT_SECONDARY)
        self.rating_label.pack()

        tk.Label(self, text="评价内容：", font=(FONT, 10), bg=CS.BG_WHITE,
                 fg=CS.TEXT_PRIMARY).pack(anchor="w", padx=40, pady=(12, 2))
        self.content = tk.Text(self, font=(FONT, 10), width=38, height=5,
                               bd=1, relief="solid")
        self.content.pack(padx=40)

        tk.Label(self, textvariable=self._error, font=(FONT, 9), bg=CS.BG_WHITE,
                 fg=CS.DANGER, wraplength=340).pack(pady=(6, 0))

        buttons = tk.Frame(self, bg=CS.BG_WHITE)
        buttons.pack(pady=12)
        RoundedButton(buttons, text="提交评价", width=130, height=36, radius=8,
                      color=CS.SUCCESS, hover_color=CS.SUCCESS_DARK,
                      command=self._submit).pack(side="left", padx=4)
        RoundedButton(buttons, text="取消", width=80, height=36, radius=8,
                      color=CS.NEUTRAL, hover_color=CS.NEUTRAL_DARK,
                      command=self.destroy).pack(side="left", padx=4)

    def _set_rating(self, value: int) -> None:
        self.rating = value
        for index, button in enumerate(self._stars, 1):
            button.config(fg=CS.WARNING if index <= value else CS.TEXT_MUTED)
        self.rating_label.config(text=f"当前评分：{value} 星")

    def _submit(self) -> None:
        try:
            service.submit_review(
                self.db, user_id=self.session.user_id,
                order_id=self.order["order_id"], order_type=self.order["order_type"],
                rating=self.rating, content=self.content.get("1.0", "end-1c"))
        except BusinessError as exc:
            self._error.set(f"⚠ {exc}")
            return

        info("评价成功", "感谢您的反馈！", parent=self.master)
        self.destroy()
        self.on_success()
