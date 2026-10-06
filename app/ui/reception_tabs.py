"""
前台端各标签页。

重点修正原系统的几处问题：
  · 概览页原本只在窗口初始化时算一次，没有刷新入口，数字永远是旧的
    （而且最初那版 SQL 的日期参数是错位的）。现在每次切页都重算；
  · 客房状态只能手工改，且选项里没有"在住"，与订单完全脱节。
    现在"在住"由触发器维护，前台只能设置空闲/打扫中/维护中；
  · 新增「入住 / 退房」工作台 —— 原系统完全没有入住登记流程；
  · 洗衣队列用 SQL 的 ORDER BY 保证"加急优先 + 同优先级先到先处理"，
    原实现用优先队列比较 (priority, dict)，同优先级顺序不稳定。
"""

from __future__ import annotations

import tkinter as tk
from datetime import date, timedelta
from tkinter import ttk

from app import service, stats
from app.service import BusinessError
from app.ui.widgets import (
    CS, FONT, DataTable, DetailDialog, RoundedButton, StatCard, info, warn,
)
ORDERS_COLUMNS = [
    ("order_id", "订单号", 190),
    ("username", "客人", 90),
    ("type_label", "类型", 60),
    ("detail", "详情", 240),
    ("created_at", "下单时间", 140),
    ("total_price", "金额", 85),
    ("status_label", "状态", 95),
    ("paid_label", "支付", 80),
]


def _fmt_time(value) -> str:
    return str(value).split(".")[0] if value else ""


def _fmt_money(value) -> str:
    try:
        return f"¥{float(value or 0):,.2f}"
    except (TypeError, ValueError):
        return "¥0.00"


class ReceptionTab(tk.Frame):
    """前台标签页基类。"""

    def __init__(self, parent, window):
        super().__init__(parent, bg=CS.BG_MAIN)
        self.app = window
        self.db = window.db
        self.session = window.session

    def on_show(self) -> None:
        pass

    def paid_map(self) -> dict[tuple[str, str], str]:
        """一次性取回所有订单的支付状态，避免列表里逐行查询。"""
        return service.paid_order_map(self.db)


# =====================================================================
#  今日概览
# =====================================================================
class OverviewTab(ReceptionTab):
    """今日经营概览（每次进入都会重新统计）。"""

    def __init__(self, parent, window):
        super().__init__(parent, window)

        header = tk.Frame(self, bg=CS.BG_MAIN)
        header.pack(fill="x", padx=16, pady=(14, 6))
        tk.Label(header, text="📊 今日概览", font=(FONT, 14, "bold"), bg=CS.BG_MAIN,
                 fg=CS.TEXT_PRIMARY).pack(side="left")
        self.date_label = tk.Label(header, text="", font=(FONT, 10), bg=CS.BG_MAIN,
                                  fg=CS.TEXT_SECONDARY)
        self.date_label.pack(side="left", padx=10)
        RoundedButton(header, text="🔄 重新统计", width=110, height=30, radius=6,
                      font=(FONT, 9, "bold"), command=self.on_show).pack(side="right")

        self.cards_frame = tk.Frame(self, bg=CS.BG_MAIN)
        self.cards_frame.pack(fill="x", padx=16, pady=(6, 10))

        self.cards: dict[str, StatCard] = {}
        layout = [
            ("arrivals", "今日到店", CS.PRIMARY),
            ("in_house", "在住", CS.SUCCESS),
            ("departures", "今日离店", CS.WARNING),
            ("dining_today", "今日餐饮", CS.DANGER),
            ("fitness_today", "今日健身", CS.PURPLE),
            ("spa_today", "今日SPA", CS.TEAL),
            ("laundry_active", "洗衣处理中", CS.NEUTRAL),
            ("pending_payment", "待收款", "#e67e22"),
        ]
        for index, (key, label, color) in enumerate(layout):
            card = StatCard(self.cards_frame, label, "-", color,
                            width=150, height=82)
            card.grid(row=index // 4, column=index % 4, padx=8, pady=8)
            self.cards[key] = card

        body = tk.Frame(self, bg=CS.BG_MAIN)
        body.pack(fill="both", expand=True, padx=16, pady=(0, 10))

        left = tk.Frame(body, bg=CS.BG_MAIN)
        left.pack(side="left", fill="both", expand=True, padx=(0, 8))
        tk.Label(left, text="各业务线统计", font=(FONT, 11, "bold"), bg=CS.BG_MAIN,
                 fg=CS.TEXT_PRIMARY).pack(anchor="w", pady=(0, 4))
        self.service_table = DataTable(left, [
            ("type_label", "业务", 90),
            ("order_count", "订单量", 80),
            ("active_count", "进行中", 80),
            ("completed_count", "已完成", 80),
            ("cancelled_count", "已取消", 80),
            ("order_amount", "订单金额", 110),
        ], height=8)
        self.service_table.pack(fill="both", expand=True)

        right = tk.Frame(body, bg=CS.BG_MAIN)
        right.pack(side="left", fill="both", expand=True, padx=(8, 0))
        tk.Label(right, text="最新评价", font=(FONT, 11, "bold"), bg=CS.BG_MAIN,
                 fg=CS.TEXT_PRIMARY).pack(anchor="w", pady=(0, 4))
        self.review_table = DataTable(right, [
            ("created_at", "时间", 140),
            ("username", "客人", 90),
            ("type_label", "类型", 60),
            ("rating", "评分", 70),
            ("content", "内容", 260),
        ], height=8)
        self.review_table.pack(fill="both", expand=True)

        self.on_show()

    def on_show(self) -> None:
        def action() -> None:
            data = stats.overview(self.db)
            self.date_label.config(text=f"统计日期：{data['today']}")
            for key, card in self.cards.items():
                card.update_value(str(data.get(key, 0)))

            rooms_hint = (f"{data['rooms_total']} 间 · "
                          f"空闲 {data['rooms_available']} / 在住 {data['rooms_occupied']} / "
                          f"打扫 {data['rooms_cleaning']} / 维护 {data['rooms_maintenance']}")
            self.app.status.show(rooms_hint, "info")

            services = stats.service_stats(self.db)
            self.service_table.set_rows(services, formatter=lambda s: (
                s["type_label"], s["order_count"], s["active_count"],
                s["completed_count"], s["cancelled_count"],
                _fmt_money(s["order_amount"])))

            rows = service.list_reviews(self.db, limit=10)
            self.review_table.set_rows(rows, formatter=lambda r: (
                _fmt_time(r["created_at"]), r["username"], r["type_label"],
                "★" * int(r["rating"]), (r["content"] or "")[:40]))

        self.app.run_guarded(action)


# =====================================================================
#  客房管理
# =====================================================================
class RoomsTab(ReceptionTab):
    """房间状态管理。在住由订单触发器维护，人工只能设置空闲/打扫/维护。"""

    def __init__(self, parent, window):
        super().__init__(parent, window)

        toolbar = tk.Frame(self, bg=CS.BG_MAIN)
        toolbar.pack(fill="x", padx=12, pady=(12, 6))

        tk.Label(toolbar, text="楼层：", font=(FONT, 10), bg=CS.BG_MAIN).pack(side="left")
        floors = ["全部"] + [str(f) for f in service.room_floors(self.db)]
        self.floor_combo = ttk.Combobox(toolbar, values=floors, font=(FONT, 10),
                                       width=6, state="readonly")
        self.floor_combo.current(0)
        self.floor_combo.pack(side="left", padx=(0, 10))
        self.floor_combo.bind("<<ComboboxSelected>>", lambda _e: self.on_show())

        tk.Label(toolbar, text="状态：", font=(FONT, 10), bg=CS.BG_MAIN).pack(side="left")
        self.status_combo = ttk.Combobox(
            toolbar, values=["全部", "空闲", "在住", "打扫中", "维护中"],
            font=(FONT, 10), width=8, state="readonly")
        self.status_combo.current(0)
        self.status_combo.pack(side="left", padx=(0, 10))
        self.status_combo.bind("<<ComboboxSelected>>", lambda _e: self.on_show())

        tk.Label(toolbar, text="房号：", font=(FONT, 10), bg=CS.BG_MAIN).pack(side="left")
        self.keyword_entry = tk.Entry(toolbar, font=(FONT, 10), width=8, bd=1,
                                      relief="solid")
        self.keyword_entry.pack(side="left")
        self.keyword_entry.bind("<Return>", lambda _e: self.on_show())

        RoundedButton(toolbar, text="🔄 刷新", width=90, height=30, radius=6,
                      font=(FONT, 9, "bold"), command=self.on_show).pack(side="left", padx=8)

        RoundedButton(toolbar, text="查看预订日历", width=120, height=30, radius=6,
                      font=(FONT, 9, "bold"), color=CS.PURPLE,
                      hover_color=CS.PURPLE_DARK,
                      command=self.show_calendar).pack(side="right", padx=6)
        RoundedButton(toolbar, text="✔ 打扫完成 / 维护", width=150, height=30, radius=6,
                      font=(FONT, 9, "bold"), color=CS.SUCCESS,
                      hover_color=CS.SUCCESS_DARK,
                      command=self.change_status).pack(side="right")

        self.table = DataTable(self, [
            ("room_number", "房间号", 80),
            ("type_name", "房型", 130),
            ("price", "价格/晚", 95),
            ("floor", "楼层", 60),
            ("state_label", "当前状态", 90),
            ("active_orders", "有效订单", 80),
            ("current_guest", "在住客人", 100),
            ("nearest_check_in", "最近入住", 100),
            ("nearest_check_out", "最近离店", 100),
        ], height=17, on_double_click=lambda _r: self.show_calendar())
        self.table.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        self.on_show()

    def on_show(self) -> None:
        def action() -> None:
            floor = self.floor_combo.get()
            status = {"空闲": "available", "在住": "occupied",
                      "打扫中": "cleaning", "维护中": "maintenance"}.get(
                self.status_combo.get())
            rows = service.list_rooms(
                self.db,
                floor=int(floor) if floor.isdigit() else None,
                status=status,
                keyword=self.keyword_entry.get().strip())
            self.table.set_rows(rows, formatter=lambda r: (
                r["room_number"], r["type_name"], _fmt_money(r["price"]),
                f"{r['floor']}楼", r["state_label"], r["active_orders"],
                r["current_guest"] or "—",
                r["nearest_check_in"] or "—", r["nearest_check_out"] or "—",
            ), tagger=lambda r: r["state_label"])
            self.app.status.show(f"共 {len(rows)} 间房", "info")

        self.app.run_guarded(action)

    def change_status(self) -> None:
        room = self.table.selected()
        if room is None:
            warn("提示", "请先选择一个房间", parent=self.app.window)
            return

        dialog = tk.Toplevel(self.app.window)
        dialog.title(f"房间 {room['room_number']} 状态")
        dialog.configure(bg=CS.BG_WHITE)
        dialog.resizable(False, False)
        dialog.transient(self.app.window)
        dialog.grab_set()

        tk.Label(dialog, text=f"房间 {room['room_number']}（{room['type_name']}）",
                 font=(FONT, 12, "bold"), bg=CS.BG_WHITE,
                 fg=CS.TEXT_PRIMARY).pack(pady=(18, 4))
        tk.Label(dialog, text=f"当前状态：{room['state_label']}",
                 font=(FONT, 10), bg=CS.BG_WHITE,
                 fg=CS.TEXT_SECONDARY).pack()
        tk.Label(dialog,
                 text="「在住」由订单自动维护，不能手工设置",
                 font=(FONT, 8), bg=CS.BG_WHITE, fg=CS.TEXT_MUTED).pack(pady=(2, 8))

        options = ["空闲", "打扫中", "维护中"]
        combo = ttk.Combobox(dialog, values=options, font=(FONT, 10),
                             state="readonly", width=14)
        combo.current(0)
        combo.pack(pady=6)

        error_var = tk.StringVar()
        tk.Label(dialog, textvariable=error_var, font=(FONT, 9), bg=CS.BG_WHITE,
                 fg=CS.DANGER, wraplength=260).pack()

        def submit() -> None:
            mapping = {"空闲": "available", "打扫中": "cleaning", "维护中": "maintenance"}
            try:
                service.set_room_status(self.db, room["room_id"], mapping[combo.get()])
            except BusinessError as exc:
                error_var.set(f"⚠ {exc}")
                return
            info("已更新", f"房间 {room['room_number']} 状态已改为「{combo.get()}」",
                 parent=dialog)
            dialog.destroy()
            self.app.refresh_all()

        buttons = tk.Frame(dialog, bg=CS.BG_WHITE)
        buttons.pack(pady=12)
        RoundedButton(buttons, text="确认修改", width=110, height=34, radius=7,
                      command=submit).pack(side="left", padx=4)
        RoundedButton(buttons, text="取消", width=80, height=34, radius=7,
                      color=CS.NEUTRAL, hover_color=CS.NEUTRAL_DARK,
                      command=dialog.destroy).pack(side="left", padx=4)

        from app.ui.widgets import center_window
        center_window(dialog, 320, 290)

    def show_calendar(self) -> None:
        room = self.table.selected()
        if room is None:
            warn("提示", "请先选择一个房间", parent=self.app.window)
            return

        def action() -> None:
            rows = service.room_calendar(self.db, room["room_id"])
            DetailDialog(
                self.app.window, f"房间 {room['room_number']} 预订日历",
                [("房间号", room["room_number"]), ("房型", room["type_name"]),
                 ("有效订单", room["active_orders"])],
                list_data={
                    "title": "有效订单（已确认 / 已入住）",
                    "columns": [("check_in_date", "入住", 100),
                                ("check_out_date", "离店", 100),
                                ("guest_name", "入住人", 90),
                                ("username", "下单账号", 90),
                                ("order_id", "订单号", 180)],
                    "rows": rows,
                    "formatter": lambda r: (
                        str(r["check_in_date"]), str(r["check_out_date"]),
                        r["guest_name"], r["username"], r["order_id"]),
                }, size=(560, 460))

        self.app.run_guarded(action)


# =====================================================================
#  入住 / 退房
# =====================================================================
class CheckInTab(ReceptionTab):
    """
    入住退房工作台。

    原系统完全没有入住登记功能：订单状态只能靠「标记已完成」直接跳到
    checked_out，房间状态也不会随之变化。这里把流程拆成两步：
    待入住 → 办理入住（房间自动置为在住）→ 办理退房（房间自动转打扫）。
    """

    def __init__(self, parent, window):
        super().__init__(parent, window)

        toolbar = tk.Frame(self, bg=CS.BG_MAIN)
        toolbar.pack(fill="x", padx=12, pady=(12, 6))

        tk.Label(toolbar, text="入住日期：", font=(FONT, 10), bg=CS.BG_MAIN).pack(side="left")
        self.date_combo = ttk.Combobox(
            toolbar, values=["今天", "明天", "未来 7 天", "全部待入住"],
            font=(FONT, 10), width=12, state="readonly")
        self.date_combo.current(0)
        self.date_combo.pack(side="left", padx=(0, 10))
        self.date_combo.bind("<<ComboboxSelected>>", lambda _e: self.on_show())

        RoundedButton(toolbar, text="🔄 刷新", width=90, height=30, radius=6,
                      font=(FONT, 9, "bold"), command=self.on_show).pack(side="left")

        RoundedButton(toolbar, text="✅ 办理退房", width=110, height=30, radius=6,
                      font=(FONT, 9, "bold"), color=CS.WARNING,
                      hover_color=CS.WARNING_DARK,
                      command=lambda: self._advance("checked_out")).pack(side="right", padx=6)
        RoundedButton(toolbar, text="🔑 办理入住", width=110, height=30, radius=6,
                      font=(FONT, 9, "bold"), color=CS.SUCCESS,
                      hover_color=CS.SUCCESS_DARK,
                      command=lambda: self._advance("checked_in")).pack(side="right", padx=6)
        RoundedButton(toolbar, text="💳 登记收款", width=110, height=30, radius=6,
                      font=(FONT, 9, "bold"), color=CS.PRIMARY,
                      hover_color=CS.PRIMARY_DARK,
                      command=self.collect_payment).pack(side="right")

        self.table = DataTable(self, [
            ("order_id", "订单号", 190),
            ("room_number", "房间号", 80),
            ("type_name", "房型", 120),
            ("guest_name", "入住人", 100),
            ("guest_phone", "联系电话", 110),
            ("check_in_date", "入住日期", 100),
            ("check_out_date", "离店日期", 100),
            ("nights", "晚数", 60),
            ("total_price", "金额", 95),
            ("raw_status", "状态", 95),
            ("paid_label", "支付", 80),
        ], height=16)
        self.table.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        self.on_show()

    def on_show(self) -> None:
        def action() -> None:
            choice = self.date_combo.get()
            rows = service.checkin_candidates(self.db, choice)

            paid = self.paid_map()
            for row in rows:
                row["paid_label"] = paid.get(("room", row["order_id"]), "未支付")

            self.table.set_rows(rows, formatter=lambda r: (
                r["order_id"], r["room_number"], r["type_name"], r["guest_name"],
                r["guest_phone"] or "—", str(r["check_in_date"]),
                str(r["check_out_date"]), r["nights"], _fmt_money(r["total_price"]),
                {"confirmed": "待入住", "checked_in": "已入住"}.get(r["raw_status"],
                                                                  r["raw_status"]),
                r["paid_label"],
            ), tagger=lambda r: ("已入住" if r["raw_status"] == "checked_in" else "待确认/待入住"))

            self.app.status.show(f"共 {len(rows)} 条待处理客房订单", "info")

        self.app.run_guarded(action)

    def _advance(self, new_status: str) -> None:
        row = self.table.selected()
        if row is None:
            warn("提示", "请先选择一条订单", parent=self.app.window)
            return
        if new_status == "checked_in" and row["raw_status"] != "confirmed":
            warn("提示", "只能为「待入住」的订单办理入住", parent=self.app.window)
            return
        if new_status == "checked_out" and row["raw_status"] != "checked_in":
            warn("提示", "只能为「已入住」的订单办理退房", parent=self.app.window)
            return

        action_text = "入住" if new_status == "checked_in" else "退房"
        unpaid = row["paid_label"] == "未支付"
        warning = "\n\n⚠ 该订单尚未收款，请确认已线下收取。" if unpaid else ""

        def action() -> None:
            service.advance_order_status(self.db, "room", row["order_id"], new_status)
            room_note = ("房间已置为「在住」" if new_status == "checked_in"
                         else "房间已置为「打扫中」")
            info(f"{action_text}完成",
                 f"订单 {row['order_id']}（房间 {row['room_number']}）已办理{action_text}。\n"
                 f"{room_note}。", parent=self.app.window)
            self.app.refresh_all()

        self.app.run_guarded(
            action, confirm_title=f"确认办理{action_text}",
            confirm_text=f"订单 {row['order_id']}\n房间 {row['room_number']} · "
                         f"{row['guest_name']}\n"
                         f"{row['check_in_date']} → {row['check_out_date']}\n"
                         f"金额 {_fmt_money(row['total_price'])}"
                         f"{warning}\n\n确认办理{action_text}？")

    def collect_payment(self) -> None:
        row = self.table.selected()
        if row is None:
            warn("提示", "请先选择一条订单", parent=self.app.window)
            return
        if row["paid_label"] == "已支付":
            info("提示", "该订单已收款", parent=self.app.window)
            return

        def action() -> None:
            owner = service.order_owner_id(self.db, "room", row["order_id"])
            if not owner:
                raise BusinessError("无法确定该订单的所属用户")
            result = service.pay_order(
                self.db, order_type="room", order_id=row["order_id"],
                user_id=int(owner), method="cash")
            info("收款成功",
                 f"流水号：{result['payment_no']}\n金额：{_fmt_money(result['amount'])}",
                 parent=self.app.window)
            self.on_show()

        self.app.run_guarded(
            action, confirm_title="确认收款",
            confirm_text=f"为订单 {row['order_id']} 登记收款 "
                         f"{_fmt_money(row['total_price'])}（现金）？")


# =====================================================================
#  订单管理
# =====================================================================
class ReceptionOrdersTab(ReceptionTab):
    """全部订单管理：按状态机推进，不再允许任意跳转状态。"""

    def __init__(self, parent, window):
        super().__init__(parent, window)

        toolbar = tk.Frame(self, bg=CS.BG_MAIN)
        toolbar.pack(fill="x", padx=12, pady=(12, 6))

        tk.Label(toolbar, text="类型：", font=(FONT, 10), bg=CS.BG_MAIN).pack(side="left")
        self.type_combo = ttk.Combobox(
            toolbar, values=["全部", "客房", "餐饮", "健身", "SPA", "洗衣"],
            font=(FONT, 10), width=8, state="readonly")
        self.type_combo.current(0)
        self.type_combo.pack(side="left", padx=(0, 10))
        self.type_combo.bind("<<ComboboxSelected>>", lambda _e: self.on_show())

        tk.Label(toolbar, text="状态：", font=(FONT, 10), bg=CS.BG_MAIN).pack(side="left")
        self.status_combo = ttk.Combobox(
            toolbar, values=["全部", "进行中", "已完成", "已取消"],
            font=(FONT, 10), width=8, state="readonly")
        self.status_combo.current(0)
        self.status_combo.pack(side="left", padx=(0, 10))
        self.status_combo.bind("<<ComboboxSelected>>", lambda _e: self.on_show())

        RoundedButton(toolbar, text="🔄 刷新", width=90, height=30, radius=6,
                      font=(FONT, 9, "bold"), command=self.on_show).pack(side="left")

        RoundedButton(toolbar, text="❌ 取消订单", width=100, height=30, radius=6,
                      font=(FONT, 9, "bold"), color=CS.DANGER,
                      hover_color=CS.DANGER_DARK,
                      command=self.cancel).pack(side="right", padx=6)
        RoundedButton(toolbar, text="➡ 推进状态", width=110, height=30, radius=6,
                      font=(FONT, 9, "bold"), color=CS.SUCCESS,
                      hover_color=CS.SUCCESS_DARK,
                      command=self.advance).pack(side="right")
        RoundedButton(toolbar, text="💳 登记收款", width=110, height=30, radius=6,
                      font=(FONT, 9, "bold"), color=CS.PRIMARY,
                      hover_color=CS.PRIMARY_DARK,
                      command=self.collect_payment).pack(side="right", padx=6)

        self.table = DataTable(self, ORDERS_COLUMNS, height=17,
                               on_double_click=lambda _r: self.detail())
        self.table.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        self.on_show()

    def on_show(self) -> None:
        def action() -> None:
            type_map = {"全部": None, "客房": "room", "餐饮": "dining",
                        "健身": "fitness", "SPA": "spa", "洗衣": "laundry"}
            rows = service.list_orders(
                self.db, order_type=type_map.get(self.type_combo.get()),
                status_category=self.status_combo.get())
            paid = self.paid_map()
            for row in rows:
                row["paid_label"] = ("免支付" if row["order_type"] == "fitness"
                                     else paid.get((row["order_type"], row["order_id"]),
                                                   "未支付"))
            self.table.set_rows(rows, formatter=lambda o: (
                o["order_id"], o["username"], o["type_label"], o["detail"],
                _fmt_time(o["created_at"]), _fmt_money(o["total_price"]),
                o["status_label"], o["paid_label"],
            ), tagger=lambda o: o["status_label"])
            self.app.status.show(f"共 {len(rows)} 条订单", "info")

        self.app.run_guarded(action)

    def detail(self) -> None:
        row = self.table.selected()
        if row is None:
            warn("提示", "请先选择一条订单", parent=self.app.window)
            return
        pairs = [("订单号", row["order_id"]), ("客人", row["username"]),
                 ("类型", row["type_label"]), ("详情", row["detail"]),
                 ("下单时间", _fmt_time(row["created_at"])),
                 ("金额", _fmt_money(row["total_price"])),
                 ("状态", row["status_label"]), ("支付", row["paid_label"])]
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
        DetailDialog(self.app.window, "订单详情", pairs, list_data=list_data)

    # --- 状态推进 -----------------------------------------------------
    NEXT_STATUS = {
        # 订单类型 -> {当前原始状态: [(按钮文案, 目标状态), ...]}
        "room": {"confirmed": [("办理入住", "checked_in")],
                 "checked_in": [("办理退房", "checked_out")]},
        "dining": {"confirmed": [("开始用餐", "dining"), ("直接完成", "completed")],
                   "dining": [("完成用餐", "completed")]},
        "fitness": {"confirmed": [("标记已完成", "completed")]},
        "spa": {"confirmed": [("开始服务", "in_progress"), ("直接完成", "completed")],
                "in_progress": [("完成服务", "completed")]},
        "laundry": {"pending": [("已取衣", "picked_up")],
                    "picked_up": [("洗涤中", "processing"), ("已送达", "delivered")],
                    "processing": [("已送达", "delivered")]},
    }

    def advance(self) -> None:
        row = self.table.selected()
        if row is None:
            warn("提示", "请先选择一条订单", parent=self.app.window)
            return

        options = self.NEXT_STATUS.get(row["order_type"], {}).get(row["raw_status"], [])
        if not options:
            warn("提示",
                 f"订单当前是「{row['status_label']}」，没有可推进的下一步。"
                 + ("\n（洗衣订单请到「洗衣服务」页处理）"
                    if row["order_type"] == "laundry" else ""),
                 parent=self.app.window)
            return

        if len(options) == 1:
            label, target = options[0]
            self._do_advance(row, target, label)
            return

        dialog = tk.Toplevel(self.app.window)
        dialog.title("选择下一步")
        dialog.configure(bg=CS.BG_WHITE)
        dialog.resizable(False, False)
        dialog.transient(self.app.window)
        dialog.grab_set()
        tk.Label(dialog, text=f"订单 {row['order_id']} 当前：{row['status_label']}",
                 font=(FONT, 11, "bold"), bg=CS.BG_WHITE,
                 fg=CS.TEXT_PRIMARY).pack(pady=(18, 10))
        tk.Label(dialog, text="请选择要推进到的状态：", font=(FONT, 10),
                 bg=CS.BG_WHITE, fg=CS.TEXT_SECONDARY).pack()

        for label, target in options:
            RoundedButton(dialog, text=label, width=160, height=34, radius=7,
                          command=lambda t=target, l=label: (dialog.destroy(),
                                                             self._do_advance(row, t, l))
                          ).pack(pady=4)
        RoundedButton(dialog, text="取消", width=90, height=30, radius=6,
                      color=CS.NEUTRAL, hover_color=CS.NEUTRAL_DARK,
                      command=dialog.destroy).pack(pady=(8, 14))

        from app.ui.widgets import center_window
        center_window(dialog, 320, 200 + 46 * len(options))

    def _do_advance(self, row: dict, target: str, label: str) -> None:
        def action() -> None:
            result = service.advance_order_status(self.db, row["order_type"],
                                                  row["order_id"], target)
            info("已更新", f"订单 {row['order_id']} 状态已更新为「{result}」。",
                 parent=self.app.window)
            self.app.refresh_all()

        self.app.run_guarded(
            action, confirm_title=f"确认{label}",
            confirm_text=f"订单 {row['order_id']}\n{row['type_label']} · {row['detail']}\n"
                         f"{row['status_label']} → {label}\n\n确认操作？")

    def cancel(self) -> None:
        row = self.table.selected()
        if row is None:
            warn("提示", "请先选择一条订单", parent=self.app.window)
            return

        def action() -> None:
            service.cancel_order(self.db, row["order_type"], row["order_id"],
                                 actor_role=self.session.role)
            info("已取消", f"订单 {row['order_id']} 已取消。", parent=self.app.window)
            self.app.refresh_all()

        self.app.run_guarded(
            action, confirm_title="确认取消",
            confirm_text=f"确定要取消订单 {row['order_id']} 吗？\n"
                         f"{row['username']} · {row['type_label']} · {row['detail']}\n\n"
                         f"若该订单已收款，将同时登记退款。")

    def collect_payment(self) -> None:
        row = self.table.selected()
        if row is None:
            warn("提示", "请先选择一条订单", parent=self.app.window)
            return
        if row["order_type"] == "fitness":
            info("提示", "健身预约免费，无需收款", parent=self.app.window)
            return
        if row["paid_label"] == "已支付":
            info("提示", "该订单已收款", parent=self.app.window)
            return
        if float(row["total_price"] or 0) <= 0:
            info("提示", "该订单金额为 0，无需收款", parent=self.app.window)
            return

        user_id = service.order_owner_id(self.db, row["order_type"], row["order_id"])
        if not user_id:
            warn("提示", "无法确定该订单的所属用户", parent=self.app.window)
            return

        def action() -> None:
            result = service.pay_order(
                self.db, order_type=row["order_type"], order_id=row["order_id"],
                user_id=int(user_id), method="cash")
            info("收款成功",
                 f"流水号：{result['payment_no']}\n金额：{_fmt_money(result['amount'])}",
                 parent=self.app.window)
            self.app.refresh_all()

        self.app.run_guarded(
            action, confirm_title="确认收款",
            confirm_text=f"为订单 {row['order_id']} 登记现金收款 "
                         f"{_fmt_money(row['total_price'])}？")


# =====================================================================
#  洗衣服务台
# =====================================================================
class LaundryDeskTab(ReceptionTab):
    """洗衣处理队列：加急优先，同优先级按先到先处理。"""

    def __init__(self, parent, window):
        super().__init__(parent, window)

        toolbar = tk.Frame(self, bg=CS.BG_MAIN)
        toolbar.pack(fill="x", padx=12, pady=(12, 6))
        tk.Label(toolbar,
                 text="💡 排序规则：加急 > 普通；同优先级按预约时间先后处理",
                 font=(FONT, 9), bg=CS.BG_MAIN, fg=CS.TEXT_SECONDARY).pack(side="left")

        RoundedButton(toolbar, text="🔄 刷新", width=90, height=30, radius=6,
                      font=(FONT, 9, "bold"), command=self.on_show).pack(side="right")
        self.show_finished = tk.BooleanVar(value=False)
        tk.Checkbutton(toolbar, text="包含已取消", variable=self.show_finished,
                       font=(FONT, 9), bg=CS.BG_MAIN, activebackground=CS.BG_MAIN,
                       command=self.on_show).pack(side="right", padx=10)

        self.table = DataTable(self, [
            ("priority_label", "优先级", 70),
            ("order_id", "订单号", 190),
            ("username", "客人", 90),
            ("room_number", "房间号", 80),
            ("service_label", "服务类型", 100),
            ("item_count", "数量", 60),
            ("total_price", "金额", 85),
            ("status_label", "状态", 90),
            ("expected_pickup", "预约取衣", 140),
            ("pickup_time", "实际取衣", 140),
            ("delivery_time", "送达时间", 140),
        ], height=15)
        self.table.pack(fill="both", expand=True, padx=12, pady=(0, 8))

        buttons = tk.Frame(self, bg=CS.BG_MAIN)
        buttons.pack(fill="x", padx=12, pady=(0, 12))
        for label, target, color, hover in (
            ("📦 已取衣", "picked_up", CS.WARNING, CS.WARNING_DARK),
            ("🔄 洗涤中", "processing", CS.PRIMARY, CS.PRIMARY_DARK),
            ("✅ 已送达", "delivered", CS.SUCCESS, CS.SUCCESS_DARK),
        ):
            RoundedButton(buttons, text=label, width=120, height=34, radius=7,
                          font=(FONT, 9, "bold"), color=color, hover_color=hover,
                          command=lambda t=target: self.update_status(t)
                          ).pack(side="left", padx=6)

        self.on_show()

    def on_show(self) -> None:
        def action() -> None:
            rows = service.laundry_queue(self.db,
                                         include_finished=self.show_finished.get())
            for row in rows:
                row["priority_label"] = "🏃 加急" if row["priority"] == 1 else "普通"
            self.table.set_rows(rows, formatter=lambda o: (
                o["priority_label"], o["order_id"], o["username"], o["room_number"],
                o["service_label"], o["item_count"], _fmt_money(o["total_price"]),
                o["status_label"],
                _fmt_time(o["expected_pickup"]) or "立即",
                _fmt_time(o["pickup_time"]) or "—",
                _fmt_time(o["delivery_time"]) or "—",
            ), tagger=lambda o: o["status_label"])
            self.app.status.show(f"队列共 {len(rows)} 条洗衣订单", "info")

        self.app.run_guarded(action)

    def update_status(self, new_status: str) -> None:
        row = self.table.selected()
        if row is None:
            warn("提示", "请先选择一条洗衣订单", parent=self.app.window)
            return

        labels = {"picked_up": "已取衣", "processing": "洗涤中", "delivered": "已送达"}

        def action() -> None:
            result = service.advance_order_status(
                self.db, "laundry", row["order_id"], new_status)
            info("已更新",
                 f"订单 {row['order_id']} 状态已更新为「{result}」。\n"
                 + ("取衣时间已自动记录。" if new_status == "picked_up" else
                    "送达时间已自动记录。" if new_status == "delivered" else ""),
                 parent=self.app.window)
            self.on_show()

        self.app.run_guarded(
            action, confirm_title=f"确认{labels[new_status]}",
            confirm_text=f"订单 {row['order_id']}（{row['service_label']}）\n"
                         f"{row['status_label']} → {labels[new_status]}\n\n确认？")


# =====================================================================
#  客户评价
# =====================================================================
class ReviewsTab(ReceptionTab):
    """客户评价查看。"""

    def __init__(self, parent, window):
        super().__init__(parent, window)

        header = tk.Frame(self, bg=CS.BG_MAIN)
        header.pack(fill="x", padx=12, pady=(12, 6))
        tk.Label(header, text="⭐ 客户评价", font=(FONT, 13, "bold"), bg=CS.BG_MAIN,
                 fg=CS.TEXT_PRIMARY).pack(side="left")
        self.summary = tk.Label(header, text="", font=(FONT, 10), bg=CS.BG_MAIN,
                                fg=CS.TEXT_SECONDARY)
        self.summary.pack(side="left", padx=12)

        RoundedButton(header, text="🔄 刷新", width=90, height=30, radius=6,
                      font=(FONT, 9, "bold"), command=self.on_show).pack(side="right")

        self.table = DataTable(self, [
            ("created_at", "时间", 150),
            ("username", "客人", 100),
            ("real_name", "姓名", 100),
            ("type_label", "类型", 70),
            ("order_id", "订单号", 190),
            ("rating", "评分", 80),
            ("content", "内容", 340),
        ], height=18)
        self.table.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        self.on_show()

    def on_show(self) -> None:
        def action() -> None:
            rows = service.list_reviews(self.db)
            self.table.set_rows(rows, formatter=lambda r: (
                _fmt_time(r["created_at"]), r["username"], r["real_name"] or "—",
                r["type_label"], r["order_id"], "★" * int(r["rating"]),
                (r["content"] or "").replace("\n", " ")[:60],
            ))
            if rows:
                average = sum(float(r["rating"]) for r in rows) / len(rows)
                self.summary.config(text=f"共 {len(rows)} 条，平均 {average:.2f} 分")
            else:
                self.summary.config(text="暂无评价")
            self.app.status.show(f"共 {len(rows)} 条评价", "info")

        self.app.run_guarded(action)
