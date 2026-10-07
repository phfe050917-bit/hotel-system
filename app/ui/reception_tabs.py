"""
前台端各标签页。

重点修正原系统的几处问题：
  · 概览页原本只在窗口初始化时算一次，没有刷新入口，数字永远是旧的
    （而且最初那版 SQL 的日期参数是错位的）。现在每次切页都重算；
  · 客房状态只能手工改，且选项里没有"在住"，与订单完全脱节。
    现在"在住"由触发器维护，前台只能设置空闲/打扫中/维护中；
  · 新增「入住 / 退房」工作台 —— 原系统完全没有入住登记流程；
  · 订单状态一律按状态机推进（service._TRANSITIONS），界面不再允许任意跳状态；
  · 补齐题目要求的团体业务（登记 / 整团入住 / 整团退房 / 整团结账），见 GroupTab；
  · 补齐题目要求的客人信息多手段查询（用户名/姓名/手机/证件/房间/订单/日期），
    见 GuestQueryTab；
  · 散客结账入口见 CheckInTab.settle()，与「💳 登记收款」并存：前者按订单生成
    结账单，后者只登记一笔收款流水。

界面层只做「收集输入 → 调 service → 展示结果」，不出现任何 SQL。
"""

from __future__ import annotations

import tkinter as tk
from datetime import date, timedelta
from tkinter import ttk

from app import service, stats
from app.service import BusinessError
from app.ui.widgets import (
    CS, FONT, Card, DataTable, DateField, DetailDialog, LabeledCombo, LabeledEntry,
    RoundedButton, StatCard, ToolbarCombo, center_window, info, warn,
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


#: 结算方式：界面显示中文，传给 service 的是 PAYMENT_METHODS 里的码。
#: 码值必须与 app/service.py 的 PAYMENT_METHODS 保持一致。
PAY_METHOD_CHOICES: tuple[tuple[str, str], ...] = (
    ("现金", "cash"),
    ("银行卡", "card"),
    ("微信", "wechat"),
    ("支付宝", "alipay"),
    ("挂房账", "room_charge"),
)
PAY_METHOD_LABEL = {label: code for label, code in PAY_METHOD_CHOICES}


def _method_label(code: str) -> str:
    """支付方式码 -> 中文（确认框与结账结果展示用）。"""
    for label, value in PAY_METHOD_CHOICES:
        if value == code:
            return label
    return code


def _text(value, dash: str = "—") -> str:
    """把可能为空的字段转成展示文本（None 不显示成 "None"）。"""
    return dash if value in (None, "") else str(value)


def _require_date(field: DateField, name: str) -> date:
    """读取必填日期输入框；格式非法时抛 BusinessError，由 run_guarded 转成提示。"""
    try:
        return field.value()
    except ValueError as exc:
        raise BusinessError(f"{name}格式不正确，请按 2026-05-01 的格式填写") from exc


def _optional_date(field: DateField, name: str) -> date | None:
    """读取可留空的日期输入框：留空表示该条件不限。"""
    if not field.get().strip():
        return None
    return _require_date(field, name)


def _settle_summary(result: dict) -> str:
    """结账结果的统一展示（结账单号 / 房间数 / 账单总额 / 实收金额）。"""
    return (f"结账单号：{result['settlement_no']}\n"
            f"房间数：{result['room_count']} 间\n"
            f"账单总额：{_fmt_money(result['total_amount'])}\n"
            f"实收金额：{_fmt_money(result['collected'])}")


def ask_settlement_options(parent: tk.Misc, title: str,
                           hint: str = "") -> tuple[str, str] | None:
    """
    弹出「结算方式 + 备注」小对话框。

    返回 (支付方式码, 备注)；用户取消时返回 None。
    下拉里是中文，提交前映射成 service.PAYMENT_METHODS 里的码再交给业务层。
    """
    dialog = tk.Toplevel(parent)
    dialog.title(title)
    dialog.configure(bg=CS.BG_WHITE)
    dialog.resizable(False, False)
    dialog.transient(parent)
    dialog.grab_set()

    tk.Label(dialog, text=title, font=(FONT, 12, "bold"), bg=CS.BG_WHITE,
             fg=CS.TEXT_PRIMARY).pack(pady=(16, 4))
    if hint:
        tk.Label(dialog, text=hint, font=(FONT, 9), bg=CS.BG_WHITE,
                 fg=CS.TEXT_SECONDARY, wraplength=280, justify="left"
                 ).pack(padx=16)

    body = tk.Frame(dialog, bg=CS.BG_WHITE)
    body.pack(fill="x", padx=24, pady=(10, 0))
    method = LabeledCombo(body, "结算方式",
                          [label for label, _code in PAY_METHOD_CHOICES], width=20)
    method.pack(fill="x")
    remark = LabeledEntry(body, "备注（选填）", width=20)
    remark.pack(fill="x")

    result: dict[str, tuple[str, str]] = {}

    def submit() -> None:
        result["value"] = (PAY_METHOD_LABEL[method.get()], remark.get())
        dialog.destroy()

    buttons = tk.Frame(dialog, bg=CS.BG_WHITE)
    buttons.pack(pady=12)
    RoundedButton(buttons, text="确认", width=100, height=34, radius=7,
                  color=CS.SUCCESS, hover_color=CS.SUCCESS_DARK,
                  command=submit).pack(side="left", padx=4)
    RoundedButton(buttons, text="取消", width=80, height=34, radius=7,
                  color=CS.NEUTRAL, hover_color=CS.NEUTRAL_DARK,
                  command=dialog.destroy).pack(side="left", padx=4)

    center_window(dialog, 340, 300)
    parent.wait_window(dialog)
    return result.get("value")


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
            ("rooms_available", "空闲房间", CS.TEAL),
            ("pending_payment", "待收款", "#e67e22"),
        ]
        for index, (key, label, color) in enumerate(layout):
            card = StatCard(self.cards_frame, label, "-", color,
                            width=150, height=82)
            card.grid(row=index // 5, column=index % 5, padx=8, pady=8)
            self.cards[key] = card

        body = tk.Frame(self, bg=CS.BG_MAIN)
        body.pack(fill="both", expand=True, padx=16, pady=(0, 10))

        left = tk.Frame(body, bg=CS.BG_MAIN)
        left.pack(side="left", fill="both", expand=True, padx=(0, 8))
        tk.Label(left, text="客房订单统计", font=(FONT, 11, "bold"), bg=CS.BG_MAIN,
                 fg=CS.TEXT_PRIMARY).pack(anchor="w", pady=(0, 4))
        self.service_table = DataTable(left, [
            ("type_label", "类型", 90),
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

        RoundedButton(toolbar, text="＋ 代客开单", width=110, height=30, radius=6,
                      font=(FONT, 9, "bold"), color=CS.PRIMARY,
                      hover_color=CS.PRIMARY_DARK,
                      command=self.walk_in).pack(side="right", padx=6)

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

    def walk_in(self) -> None:
        """
        前台代客现场开单（散客 walk-in 登记）。

        题目要求 (1) 的"登记"不只是给已有订单办理入住：直接到店的客人没有
        客人端账号，前台要能当场登记。订单记在当前登录的前台账号名下
        （即"前台代客登记"），金额仍由数据库按当前房价计算，
        创建后可在「入住 / 退房」页直接办理入住。
        """
        selected = self.table.selected()
        dialog = tk.Toplevel(self.app.window)
        dialog.title("代客开单（散客登记）")
        dialog.configure(bg=CS.BG_WHITE)
        dialog.resizable(False, False)
        dialog.transient(self.app.window)
        dialog.grab_set()

        tk.Label(dialog, text="代客开单（散客登记）", font=(FONT, 13, "bold"),
                 bg=CS.BG_WHITE, fg=CS.TEXT_PRIMARY).pack(pady=(16, 2))
        tk.Label(dialog, text="金额由数据库按当前房价计算；订单归到当前前台账号名下，"
                             "创建后可在「入住 / 退房」页直接办理入住。",
                 font=(FONT, 9), bg=CS.BG_WHITE, fg=CS.TEXT_SECONDARY,
                 wraplength=330, justify="left").pack(padx=16)

        body = tk.Frame(dialog, bg=CS.BG_WHITE)
        body.pack(fill="x", padx=26, pady=(10, 0))
        room_no = LabeledEntry(body, "房间号（如 201）", width=20)
        if selected:
            room_no.set(str(selected["room_number"]))
        room_no.pack(fill="x")
        check_in = DateField(body, "入住日期", initial=date.today())
        check_in.pack(fill="x")
        check_out = DateField(body, "离店日期", initial=date.today() + timedelta(days=1))
        check_out.pack(fill="x")
        guest_name = LabeledEntry(body, "入住人姓名", width=20)
        guest_name.pack(fill="x")
        guest_phone = LabeledEntry(body, "联系电话（选填）", width=20)
        guest_phone.pack(fill="x")
        id_card = LabeledEntry(body, "证件号（选填）", width=20)
        id_card.pack(fill="x")

        error_var = tk.StringVar()
        tk.Label(dialog, textvariable=error_var, font=(FONT, 9), bg=CS.BG_WHITE,
                 fg=CS.DANGER, wraplength=320, justify="left").pack(pady=(8, 0))

        def submit() -> None:
            try:
                ci = _require_date(check_in, "入住日期")
                co = _require_date(check_out, "离店日期")
                name = guest_name.get().strip()
                number = room_no.get().strip()
                if not name:
                    raise BusinessError("请填写入住人姓名")
                if not number:
                    raise BusinessError("请填写房间号")
            except BusinessError as exc:
                error_var.set(f"⚠ {exc}")
                return

            matched = [r for r in service.list_rooms(self.db, keyword=number)
                       if r["room_number"] == number]
            if not matched:
                error_var.set(f"⚠ 找不到房间号「{number}」")
                return
            room_id = int(matched[0]["room_id"])
            dialog.destroy()

            def action() -> None:
                available = {int(r["room_id"])
                             for r in service.search_available_rooms(self.db, ci, co)}
                if room_id not in available:
                    raise BusinessError(
                        f"房间 {number} 在 {ci} ~ {co} 不可预订，请更换房间或日期")
                order = service.create_room_order(
                    self.db, user_id=int(self.session.user_id), room_id=room_id,
                    check_in=ci, check_out=co, guest_name=name,
                    guest_phone=guest_phone.get().strip(),
                    id_card=id_card.get().strip())
                info("代客开单成功",
                     f"订单号：{order['order_id']}\n房间：{number}\n"
                     f"{ci} → {co}（{order['nights']} 晚）\n"
                     f"金额：{_fmt_money(order['total_price'])}\n\n"
                     f"该订单记在当前前台账号名下，可在「入住 / 退房」页办理入住。",
                     parent=self.app.window)
                self.app.refresh_all()

            self.app.run_guarded(action)

        buttons = tk.Frame(dialog, bg=CS.BG_WHITE)
        buttons.pack(pady=12)
        RoundedButton(buttons, text="确认开单", width=110, height=36, radius=8,
                      color=CS.SUCCESS, hover_color=CS.SUCCESS_DARK,
                      command=submit).pack(side="left", padx=4)
        RoundedButton(buttons, text="取消", width=80, height=36, radius=8,
                      color=CS.NEUTRAL, hover_color=CS.NEUTRAL_DARK,
                      command=dialog.destroy).pack(side="left", padx=4)

        center_window(dialog, 380, 520)
        dialog.wait_window(dialog)

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
        RoundedButton(toolbar, text="🧾 办理结账", width=110, height=30, radius=6,
                      font=(FONT, 9, "bold"), color=CS.PURPLE,
                      hover_color=CS.PURPLE_DARK,
                      command=self.settle).pack(side="right", padx=6)
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

    def settle(self) -> None:
        """
        散客结账：为选中的一张订单生成结账单（题目要求 (5) 的散客入口）。

        与「💳 登记收款」的区别：登记收款只写一笔收款流水；结账会生成结账单、
        回填订单的 settlement_no，并按结算方式登记收款。已结账的订单再点这里，
        service 会抛 BusinessError，由 run_guarded 弹出提示（不静默吞掉）。
        """
        row = self.table.selected()
        if row is None:
            warn("提示", "请先选择一条订单", parent=self.app.window)
            return

        options = ask_settlement_options(
            self.app.window, "办理结账",
            f"订单 {row['order_id']}\n房间 {row['room_number']} · {row['guest_name']}\n"
            f"账单金额 {_fmt_money(row['total_price'])}")
        if options is None:
            return
        method, remark = options

        def action() -> None:
            result = service.settle_order(
                self.db, order_id=row["order_id"], method=method,
                operator_id=int(self.session.user_id), remark=remark)
            info("结账完成", _settle_summary(result), parent=self.app.window)
            self.app.refresh_all()

        self.app.run_guarded(
            action, confirm_title="确认办理结账",
            confirm_text=f"订单 {row['order_id']}（房间 {row['room_number']}）\n"
                         f"{row['guest_name']} · {row['check_in_date']} → "
                         f"{row['check_out_date']}\n"
                         f"账单金额：{_fmt_money(row['total_price'])}\n"
                         f"结算方式：{_method_label(method)}\n"
                         f"备注：{remark or '—'}\n\n"
                         f"确认生成结账单并按上述方式登记收款？")


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
            toolbar, values=["全部", "客房"],
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
            type_map = {"全部": None, "客房": "room"}
            rows = service.list_orders(
                self.db, order_type=type_map.get(self.type_combo.get()),
                status_category=self.status_combo.get())
            paid = self.paid_map()
            for row in rows:
                row["paid_label"] = paid.get((row["order_type"], row["order_id"]),
                                             "未支付")
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
        if row["order_type"] == "room":
            paid = service.order_payment(self.db, "room", row["order_id"])
            if paid:
                pairs.append(("支付流水", f"{paid['payment_no']} "
                                          f"{_fmt_money(paid['amount'])} "
                                          f"{'已支付' if paid['status'] == 'paid' else '已退款'}"))
        DetailDialog(self.app.window, "订单详情", pairs, list_data=list_data)

    # --- 状态推进 -----------------------------------------------------
    NEXT_STATUS = {
        # 订单类型 -> {当前原始状态: [(按钮文案, 目标状态), ...]}
        "room": {"confirmed": [("办理入住", "checked_in")],
                 "checked_in": [("办理退房", "checked_out")]},
    }

    def advance(self) -> None:
        row = self.table.selected()
        if row is None:
            warn("提示", "请先选择一条订单", parent=self.app.window)
            return

        options = self.NEXT_STATUS.get(row["order_type"], {}).get(row["raw_status"], [])
        if not options:
            warn("提示",
                 f"订单当前是「{row['status_label']}」，没有可推进的下一步。",
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


# =====================================================================
#  团体登记 / 团体入住 / 团体结账（题目要求 (1)）
# =====================================================================
class GroupTab(ReceptionTab):
    """
    团体业务工作台（题目要求 (1)）。

    一条流水线走到底：登记团体（一次为多间房生成同一张团体单下的订单）
    → 整团入住 → 整团退房 → 团体结账（整团合成一张结账单）。

    负责人用户名留空时，订单记在当前前台账号名下，即"前台代客登记"；
    填了则先用 service.list_users 解析成 user_id 再交给业务层。
    可用房列表只在点过「查询可用房」后出现，避免默认窗口（1000x680）被挤满。
    """

    def __init__(self, parent, window):
        super().__init__(parent, window)
        self._members_for: int | None = None     # 成员明细当前对应的团体
        self._room_area_shown = False

        # ---------------- 团体信息表单 ----------------
        form_card = Card(self, padding=10)
        form_card.pack(fill="x", padx=12, pady=(10, 4))
        form = form_card.body()

        head = tk.Frame(form, bg=CS.BG_WHITE)
        head.pack(fill="x")
        tk.Label(head, text="🧳 团体登记", font=(FONT, 12, "bold"), bg=CS.BG_WHITE,
                 fg=CS.TEXT_PRIMARY).pack(side="left")
        tk.Label(head,
                 text=f"（负责人用户名留空 → 订单记在当前账号"
                      f"「{self.session.username}」名下，即前台代客登记）",
                 font=(FONT, 9), bg=CS.BG_WHITE, fg=CS.TEXT_SECONDARY
                 ).pack(side="left", padx=8)

        grid = tk.Frame(form, bg=CS.BG_WHITE)
        grid.pack(fill="x", pady=(6, 0))
        for column in range(4):
            grid.columnconfigure(column, weight=1, uniform="group_form")

        self.name_entry = LabeledEntry(grid, "团体名称 *", width=16)
        self.contact_entry = LabeledEntry(grid, "联系人 *", width=16)
        self.phone_entry = LabeledEntry(grid, "联系电话", width=16)
        self.id_card_entry = LabeledEntry(grid, "证件号（选填）", width=16)
        self.check_in_field = DateField(grid, "入住日期 *", initial=date.today())
        self.check_out_field = DateField(grid, "离店日期 *",
                                        initial=date.today() + timedelta(days=1))
        self.leader_entry = LabeledEntry(grid, "负责人用户名（选填）", width=16)
        self.remark_entry = LabeledEntry(grid, "备注（选填）", width=16)
        for index, widget in enumerate((
                self.name_entry, self.contact_entry, self.phone_entry,
                self.id_card_entry, self.check_in_field, self.check_out_field,
                self.leader_entry, self.remark_entry)):
            widget.grid(row=index // 4, column=index % 4, sticky="ew", padx=6)

        # ---------------- 工具栏 ----------------
        toolbar = tk.Frame(self, bg=CS.BG_MAIN)
        toolbar.pack(fill="x", padx=12, pady=(4, 4))

        RoundedButton(toolbar, text="🔍 查询可用房", width=120, height=30, radius=6,
                      font=(FONT, 9, "bold"), color=CS.TEAL,
                      hover_color=CS.TEAL_DARK,
                      command=self.search_rooms).pack(side="left")
        RoundedButton(toolbar, text="✅ 创建团体登记", width=140, height=30, radius=6,
                      font=(FONT, 9, "bold"), color=CS.SUCCESS,
                      hover_color=CS.SUCCESS_DARK,
                      command=self.create_group).pack(side="left", padx=8)

        RoundedButton(toolbar, text="🔄 刷新", width=90, height=30, radius=6,
                      font=(FONT, 9, "bold"), command=self.on_show).pack(side="right")
        self.status_filter = ToolbarCombo(
            toolbar, "状态：", ["全部"] + list(service.GROUP_STATUS_LABEL.values()),
            width=8, on_change=lambda _value: self.on_show())
        self.status_filter.pack(side="right", padx=(0, 10))
        self.keyword_entry = tk.Entry(toolbar, font=(FONT, 10), width=12, bd=1,
                                      relief="solid")
        self.keyword_entry.pack(side="right", padx=(0, 6))
        self.keyword_entry.bind("<Return>", lambda _e: self.on_show())
        tk.Label(toolbar, text="关键字：", font=(FONT, 10), bg=CS.BG_MAIN
                 ).pack(side="right")

        # ---------------- 可预订房间（查询后才显示） ----------------
        self.room_area = tk.Frame(self, bg=CS.BG_MAIN)
        tk.Label(self.room_area,
                 text="可预订房间（按住 Ctrl / Shift 可勾选多间，"
                      "选好后点「创建团体登记」）",
                 font=(FONT, 11, "bold"), bg=CS.BG_MAIN,
                 fg=CS.TEXT_PRIMARY).pack(anchor="w", pady=(0, 4))
        self.room_table = DataTable(self.room_area, [
            ("room_number", "房间号", 80),
            ("type_name", "房型", 130),
            ("price", "房价/晚", 95),
            ("floor", "楼层", 60),
            ("max_occupancy", "最大入住", 80),
        ], height=3)
        self.room_table.pack(fill="both", expand=True)

        # ---------------- 团体列表 ----------------
        self.group_area = tk.Frame(self, bg=CS.BG_MAIN)
        self.group_area.pack(fill="both", expand=True, padx=12, pady=(2, 2))
        tk.Label(self.group_area, text="团体列表（点一行即可在下方查看成员明细）",
                 font=(FONT, 11, "bold"), bg=CS.BG_MAIN,
                 fg=CS.TEXT_PRIMARY).pack(anchor="w", pady=(0, 4))
        self.group_table = DataTable(self.group_area, [
            ("group_name", "团体名", 130),
            ("contact_name", "联系人", 80),
            ("contact_phone", "电话", 110),
            ("check_in_date", "入住", 90),
            ("check_out_date", "离店", 90),
            ("order_count", "房数", 50),
            ("total_amount", "总金额", 95),
            ("in_house_count", "在住", 50),
            ("paid_count", "已收款", 60),
            ("bill_label", "结账状态", 90),
            ("status_label", "状态", 70),
        ], height=4, on_select=self.show_members)
        self.group_table.pack(fill="both", expand=True)

        # ---------------- 成员明细 + 团体动作 ----------------
        member_area = tk.Frame(self, bg=CS.BG_MAIN)
        member_area.pack(fill="both", expand=True, padx=12, pady=(2, 10))
        member_head = tk.Frame(member_area, bg=CS.BG_MAIN)
        member_head.pack(fill="x")
        tk.Label(member_head, text="团体成员明细", font=(FONT, 11, "bold"),
                 bg=CS.BG_MAIN, fg=CS.TEXT_PRIMARY).pack(side="left")
        self.members_hint = tk.Label(member_head, text="（未选择团体）", font=(FONT, 9),
                                     bg=CS.BG_MAIN, fg=CS.TEXT_SECONDARY)
        self.members_hint.pack(side="left", padx=8)

        RoundedButton(member_head, text="🔄 刷新", width=90, height=30, radius=6,
                      font=(FONT, 9, "bold"), command=self.on_show
                      ).pack(side="right", padx=(4, 0))
        RoundedButton(member_head, text="🧾 团体结账", width=120, height=30, radius=6,
                      font=(FONT, 9, "bold"), color=CS.PURPLE,
                      hover_color=CS.PURPLE_DARK,
                      command=self.settle_group).pack(side="right", padx=4)
        RoundedButton(member_head, text="🚪 整团退房", width=120, height=30, radius=6,
                      font=(FONT, 9, "bold"), color=CS.WARNING,
                      hover_color=CS.WARNING_DARK,
                      command=self.checkout_group).pack(side="right", padx=4)
        RoundedButton(member_head, text="🔑 整团入住", width=120, height=30, radius=6,
                      font=(FONT, 9, "bold"), color=CS.SUCCESS,
                      hover_color=CS.SUCCESS_DARK,
                      command=self.checkin_group).pack(side="right", padx=4)

        self.member_table = DataTable(member_area, [
            ("room_number", "房间号", 80),
            ("guest_name", "入住人", 100),
            ("id_card", "证件号", 160),
            ("nights", "床位天数", 80),
            ("total_price", "金额", 95),
            ("status_label", "订单状态", 90),
            ("paid_label", "支付", 80),
            ("settle_label", "结账", 80),
        ], height=3)
        self.member_table.pack(fill="both", expand=True, pady=(4, 0))

        self.on_show()

    # ---------------- 可用房 ----------------
    def _show_room_area(self) -> None:
        """把可用房列表插到团体列表上方（只在查询成功后显示）。"""
        if not self._room_area_shown:
            self.room_area.pack(fill="both", expand=True, padx=12, pady=(0, 2),
                                before=self.group_area)
            self._room_area_shown = True

    def _hide_room_area(self) -> None:
        """团体登记完成后收起可用房列表，把空间还给团体列表与成员明细。"""
        self.room_area.pack_forget()
        self.room_table.clear()
        self._room_area_shown = False

    def search_rooms(self) -> None:
        """按表单里的入住/离店日期查可用房，结果表支持勾选多间。"""
        def action() -> None:
            check_in = _require_date(self.check_in_field, "入住日期")
            check_out = _require_date(self.check_out_field, "离店日期")
            rows = service.search_available_rooms(self.db, check_in, check_out)
            self.room_table.set_rows(rows, formatter=lambda r: (
                r["room_number"], r["type_name"], _fmt_money(r["price"]),
                f"{r['floor']}楼", r["max_occupancy"],
            ))
            self._show_room_area()
            self.app.status.show(
                f"{check_in} ~ {check_out} 共 {len(rows)} 间可用房；"
                f"按住 Ctrl / Shift 勾选多间后点「创建团体登记」", "success")

        self.app.run_guarded(action)

    # ---------------- 创建团体登记 ----------------
    def _resolve_leader(self, username: str) -> int | None:
        """
        把负责人用户名解析成 user_id。

        留空返回 None —— 表示前台代客登记，业务层会把订单挂到当前前台账号；
        查不到时抛 BusinessError（由 run_guarded 提示用户改名或留空）。
        """
        username = username.strip()
        if not username:
            return None
        matches = service.list_users(self.db, keyword=username)
        for user in matches:
            if str(user["username"]).lower() == username.lower():
                return int(user["user_id"])
        if len(matches) == 1:                    # 允许输入真实姓名（唯一命中时）
            return int(matches[0]["user_id"])
        raise BusinessError(f"负责人用户名「{username}」不存在，"
                            f"请留空（前台代客登记）或填写正确的账号名")

    def create_group(self) -> None:
        """校验表单与选中的房间，调用 service.create_group_booking 生成团体单。"""
        selected = self.room_table.selected_many()
        if not selected:
            warn("提示", "请先点「🔍 查询可用房」，再在房间列表中勾选至少一间房",
                 parent=self.app.window)
            return
        if not self.name_entry.get():
            warn("提示", "请填写团体名称", parent=self.app.window)
            return
        if not self.contact_entry.get():
            warn("提示", "请填写联系人姓名", parent=self.app.window)
            return

        room_ids = [int(r["room_id"]) for r in selected]
        room_numbers = "、".join(str(r["room_number"]) for r in selected)

        def action() -> None:
            check_in = _require_date(self.check_in_field, "入住日期")
            check_out = _require_date(self.check_out_field, "离店日期")
            leader_id = self._resolve_leader(self.leader_entry.get())
            result = service.create_group_booking(
                self.db,
                group_name=self.name_entry.get(),
                contact_name=self.contact_entry.get(),
                contact_phone=self.phone_entry.get(),
                id_card=self.id_card_entry.get(),
                booker_user_id=int(self.session.user_id),
                leader_user_id=leader_id,
                check_in=check_in,
                check_out=check_out,
                room_ids=room_ids,
                remark=self.remark_entry.get())
            order_lines = "\n".join(f"  · {order_id}"
                                    for order_id in result["order_ids"])
            info("团体登记成功",
                 f"团体单号：{result['group_id']}\n"
                 f"房间数：{result['room_count']} 间（{room_numbers}）\n"
                 f"住宿天数：{result['nights']} 晚\n"
                 f"账单总额：{_fmt_money(result['total_price'])}\n"
                 f"生成的订单号：\n{order_lines}",
                 parent=self.app.window)
            self._hide_room_area()
            self.app.refresh_all()

        self.app.run_guarded(
            action, confirm_title="确认创建团体登记",
            confirm_text=f"团体：{self.name_entry.get()}\n"
                         f"联系人：{self.contact_entry.get()}"
                         f"{'（' + self.phone_entry.get() + '）' if self.phone_entry.get() else ''}\n"
                         f"日期：{self.check_in_field.get()} → "
                         f"{self.check_out_field.get()}\n"
                         f"房间（{len(room_ids)} 间）：{room_numbers}\n"
                         f"负责人：{self.leader_entry.get() or '留空 · 前台代客登记'}\n\n"
                         f"确认创建团体登记并生成订单？")

    # ---------------- 团体列表与成员明细 ----------------
    def on_show(self) -> None:
        def action() -> None:
            status_map = {label: code
                          for code, label in service.GROUP_STATUS_LABEL.items()}
            rows = service.list_groups(
                self.db, keyword=self.keyword_entry.get().strip(),
                status=status_map.get(self.status_filter.get(), ""))
            self.group_table.set_rows(rows, formatter=lambda g: (
                g["group_name"], g["contact_name"], _text(g["contact_phone"]),
                _text(g["check_in_date"]), _text(g["check_out_date"]),
                g["order_count"], _fmt_money(g["total_amount"]),
                g["in_house_count"], g["paid_count"], g["bill_label"],
                g["status_label"],
            ), tagger=lambda g: g["status_label"])
            # 列表重建后原选中行已失效，成员明细同步清空，避免展示过期数据
            self.member_table.clear()
            self._members_for = None
            self.members_hint.config(text="（未选择团体，点击上方团体行查看成员明细）")
            self.app.status.show(f"共 {len(rows)} 个团体单", "info")

        self.app.run_guarded(action)

    def show_members(self, group: dict) -> None:
        """展示选中团体的成员明细（房间号/入住人/证件号/天数/金额/支付/结账）。"""
        group_id = int(group["group_id"])
        if self._members_for == group_id:
            return
        label = group["group_name"]
        total_amount = group.get("total_amount")
        bill_label = group.get("bill_label", "")

        def action() -> None:
            rows = service.group_members(self.db, group_id)
            self.member_table.set_rows(rows, formatter=lambda m: (
                m["room_number"], m["guest_name"], _text(m["id_card"]),
                m["nights"], _fmt_money(m["total_price"]), m["status_label"],
                m["paid_label"], m["settle_label"],
            ), tagger=lambda m: m["status_label"])
            self._members_for = group_id
            self.members_hint.config(
                text=f"团体「{label}」共 {len(rows)} 间房 · "
                     f"总额 {_fmt_money(total_amount)} · {bill_label}")

        self.app.run_guarded(action)

    def _selected_group(self) -> dict | None:
        row = self.group_table.selected()
        if row is None:
            warn("提示", "请先在上方的团体列表中选择一个团体单",
                 parent=self.app.window)
        return row

    # ---------------- 整团入住 / 退房 / 结账 ----------------
    def checkin_group(self) -> None:
        row = self._selected_group()
        if row is None:
            return
        if row["status"] == "checked_in":
            warn("提示", "该团体已是「已入住」状态", parent=self.app.window)
            return

        def action() -> None:
            count = service.checkin_group(self.db, int(row["group_id"]))
            info("整团入住完成",
                 f"团体「{row['group_name']}」共 {count} 间房已办理入住。\n"
                 f"房间：{_text(row['room_numbers'])}",
                 parent=self.app.window)
            self.app.refresh_all()

        self.app.run_guarded(
            action, confirm_title="确认整团入住",
            confirm_text=f"团体：{row['group_name']}\n"
                         f"日期：{_text(row['check_in_date'])} → "
                         f"{_text(row['check_out_date'])}\n"
                         f"房间：{_text(row['room_numbers'])}\n\n"
                         f"将为该团体所有「待入住」订单办理入住，"
                         f"房间自动置为「在住」。确认？")

    def checkout_group(self) -> None:
        row = self._selected_group()
        if row is None:
            return
        if row["status"] == "checked_out":
            warn("提示", "该团体已是「已退房」状态", parent=self.app.window)
            return

        def action() -> None:
            count = service.checkout_group(self.db, int(row["group_id"]))
            info("整团退房完成",
                 f"团体「{row['group_name']}」共 {count} 间房已办理退房。\n"
                 f"房间已置为「打扫中」，如需收费请继续点「🧾 团体结账」。",
                 parent=self.app.window)
            self.app.refresh_all()

        self.app.run_guarded(
            action, confirm_title="确认整团退房",
            confirm_text=f"团体：{row['group_name']}\n"
                         f"日期：{_text(row['check_in_date'])} → "
                         f"{_text(row['check_out_date'])}\n"
                         f"房间：{_text(row['room_numbers'])}\n\n"
                         f"将为该团体所有「已入住」订单办理退房，"
                         f"房间自动置为「打扫中」。确认？")

    def settle_group(self) -> None:
        row = self._selected_group()
        if row is None:
            return

        options = ask_settlement_options(
            self.app.window, "团体结账",
            f"团体：{row['group_name']}\n"
            f"{row['order_count']} 间房 · 总额 {_fmt_money(row['total_amount'])} · "
            f"{row['bill_label']}")
        if options is None:
            return
        method, remark = options
        unsettled = int(row["order_count"]) - int(row["settled_count"])

        def action() -> None:
            result = service.settle_group(
                self.db, group_id=int(row["group_id"]), method=method,
                operator_id=int(self.session.user_id), remark=remark)
            info("团体结账完成", _settle_summary(result), parent=self.app.window)
            self.app.refresh_all()

        self.app.run_guarded(
            action, confirm_title="确认团体结账",
            confirm_text=f"团体：{row['group_name']}\n"
                         f"房间：{_text(row['room_numbers'])}\n"
                         f"待结账房间数：{unsettled}\n"
                         f"结算方式：{_method_label(method)}\n"
                         f"备注：{remark or '—'}\n\n"
                         f"将为该团体所有未结账房间生成一张结账单并登记收款，确认？")


# =====================================================================
#  客人信息多手段查询（题目要求 (3)）
# =====================================================================
class GuestQueryTab(ReceptionTab):
    """
    客人信息多手段查询（题目要求 (3)）。

    条件之间是「与」关系，可任意组合；数据来自视图 v_guest_profile，
    因此"没下过单的客人"也查得到。双击某行可用 service.guest_orders
    查看该客人的全部订单（含结账单号与团体名）。
    """

    COLUMNS = [
        ("user_id", "客人ID", 60),
        ("username", "用户名", 90),
        ("real_name", "姓名", 80),
        ("phone", "手机号", 110),
        ("email", "邮箱", 120),
        ("room_number", "房间号", 70),
        ("type_name", "房型", 100),
        ("guest_name", "入住人", 80),
        ("id_card", "证件号", 140),
        ("check_in_date", "入住", 90),
        ("check_out_date", "离店", 90),
        ("nights", "晚数", 55),
        ("total_price", "金额", 90),
        ("status_label", "订单状态", 85),
        ("group_name", "团体", 100),
        ("settlement_no", "结账单号", 140),
    ]

    def __init__(self, parent, window):
        super().__init__(parent, window)

        # ---------------- 查询条件 ----------------
        card = Card(self, padding=10)
        card.pack(fill="x", padx=12, pady=(10, 4))
        form = card.body()

        head = tk.Frame(form, bg=CS.BG_WHITE)
        head.pack(fill="x")
        tk.Label(head, text="🔎 客人信息查询", font=(FONT, 12, "bold"),
                 bg=CS.BG_WHITE, fg=CS.TEXT_PRIMARY).pack(side="left")
        tk.Label(head,
                 text="（关键字匹配 用户名/姓名/手机号/证件号/入住人姓名；"
                      "日期留空表示不限；双击结果行查看该客人全部订单）",
                 font=(FONT, 9), bg=CS.BG_WHITE, fg=CS.TEXT_SECONDARY
                 ).pack(side="left", padx=8)

        grid = tk.Frame(form, bg=CS.BG_WHITE)
        grid.pack(fill="x", pady=(6, 0))
        for column in range(5):
            grid.columnconfigure(column, weight=1, uniform="guest_form")

        self.keyword_entry = LabeledEntry(grid, "关键字", width=16)
        self.name_entry = LabeledEntry(grid, "姓名", width=16)
        self.phone_entry = LabeledEntry(grid, "手机号", width=16)
        self.id_card_entry = LabeledEntry(grid, "证件号", width=16)
        self.room_entry = LabeledEntry(grid, "房间号", width=16)
        self.order_entry = LabeledEntry(grid, "订单号", width=16)
        self.check_in_from = DateField(grid, "入住日期起（留空不限）")
        self.check_in_from.set("")
        self.check_in_to = DateField(grid, "入住日期止（留空不限）")
        self.check_in_to.set("")
        for index, widget in enumerate((
                self.keyword_entry, self.name_entry, self.phone_entry,
                self.id_card_entry, self.room_entry, self.order_entry,
                self.check_in_from, self.check_in_to)):
            widget.grid(row=index // 5, column=index % 5, sticky="ew", padx=6)

        # ---------------- 工具栏 ----------------
        toolbar = tk.Frame(self, bg=CS.BG_MAIN)
        toolbar.pack(fill="x", padx=12, pady=(4, 4))

        RoundedButton(toolbar, text="🔍 查询", width=100, height=30, radius=6,
                      font=(FONT, 9, "bold"), color=CS.PRIMARY,
                      hover_color=CS.PRIMARY_DARK,
                      command=self.search).pack(side="left")
        RoundedButton(toolbar, text="🧹 清空条件", width=110, height=30, radius=6,
                      font=(FONT, 9, "bold"), color=CS.NEUTRAL,
                      hover_color=CS.NEUTRAL_DARK,
                      command=self.clear_conditions).pack(side="left", padx=8)
        RoundedButton(toolbar, text="📄 查看全部订单", width=140, height=30, radius=6,
                      font=(FONT, 9, "bold"), color=CS.TEAL,
                      hover_color=CS.TEAL_DARK,
                      command=self.show_orders).pack(side="left")
        RoundedButton(toolbar, text="🔄 刷新", width=90, height=30, radius=6,
                      font=(FONT, 9, "bold"), command=self.search).pack(side="right")
        self.summary = tk.Label(toolbar, text="", font=(FONT, 10), bg=CS.BG_MAIN,
                                fg=CS.TEXT_SECONDARY)
        self.summary.pack(side="right", padx=10)

        # ---------------- 结果 ----------------
        # 双击行 = 看该客人的全部订单（DataTable 会把行数据传给回调，这里丢弃）
        self.table = DataTable(self, self.COLUMNS, height=12,
                               on_double_click=lambda _row: self.show_orders())
        self.table.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        self.on_show()

    # ---------------- 查询 ----------------
    def on_show(self) -> None:
        """切换标签页/F5 时按当前条件重查一次（默认条件即列出全部客人）。"""
        self.search()

    def search(self) -> None:
        def action() -> None:
            rows = service.search_guest_profile(
                self.db,
                keyword=self.keyword_entry.get(),
                name=self.name_entry.get(),
                phone=self.phone_entry.get(),
                id_card=self.id_card_entry.get(),
                room_number=self.room_entry.get(),
                order_id=self.order_entry.get(),
                check_in_from=_optional_date(self.check_in_from, "入住日期起"),
                check_in_to=_optional_date(self.check_in_to, "入住日期止"))
            self.table.set_rows(rows, formatter=self._row_values,
                                tagger=lambda r: r["status_label"])
            with_order = sum(1 for r in rows if r.get("order_id"))
            self.summary.config(
                text=f"命中 {len(rows)} 条（其中有订单 {with_order} 条）")
            self.app.status.show(f"共 {len(rows)} 条客人信息", "info")

        self.app.run_guarded(action)

    @staticmethod
    def _row_values(row: dict) -> tuple:
        return (row["user_id"], row["username"], _text(row["real_name"]),
                _text(row["phone"]), _text(row["email"]), _text(row["room_number"]),
                _text(row["type_name"]), _text(row["guest_name"]),
                _text(row["id_card"]), _text(row["check_in_date"]),
                _text(row["check_out_date"]), _text(row["nights"], "-"),
                _fmt_money(row["total_price"]), _text(row["status_label"], "无订单"),
                _text(row["group_name"]), _text(row["settlement_no"]))

    def clear_conditions(self) -> None:
        for entry in (self.keyword_entry, self.name_entry, self.phone_entry,
                      self.id_card_entry, self.room_entry, self.order_entry):
            entry.set("")
        self.check_in_from.set("")
        self.check_in_to.set("")
        self.table.clear()
        self.summary.config(text="已清空查询条件")
        self.app.status.show("查询条件已清空", "info")

    # ---------------- 客人全部订单 ----------------
    def show_orders(self) -> None:
        """工具栏按钮与双击共同的入口：看选中客人的全部订单。"""
        row = self.table.selected()
        if row is None:
            warn("提示", "请先在结果列表中选择一位客人", parent=self.app.window)
            return
        self._open_guest_orders(row)

    def _open_guest_orders(self, row: dict) -> None:
        user_id = row.get("user_id")
        if user_id is None:
            warn("提示", "该行没有关联的客人账号", parent=self.app.window)
            return

        def action() -> None:
            orders = service.guest_orders(self.db, int(user_id))
            paid = self.paid_map()
            for order in orders:
                order["paid_label"] = paid.get(("room", order["order_id"]),
                                               "未支付")
            total = sum(float(order["total_price"] or 0) for order in orders)
            pairs = [
                ("客人ID", user_id),
                ("用户名", _text(row.get("username"))),
                ("姓名", _text(row.get("real_name"))),
                ("手机号", _text(row.get("phone"))),
                ("邮箱", _text(row.get("email"))),
                ("账号角色", _text(row.get("role"))),
                ("账号状态", "启用" if row.get("is_active") else "已禁用"),
                ("订单数", len(orders)),
                ("累计金额", _fmt_money(total)),
            ]
            DetailDialog(
                self.app.window, f"客人「{_text(row.get('username'))}」的全部订单",
                pairs, size=(900, 560),
                list_data={
                    "title": "全部订单（含团体与结账单号）",
                    "columns": [("order_id", "订单号", 180),
                                ("room_number", "房间号", 75),
                                ("type_name", "房型", 110),
                                ("check_in_date", "入住", 90),
                                ("check_out_date", "离店", 90),
                                ("nights", "晚数", 55),
                                ("total_price", "金额", 95),
                                ("status_label", "订单状态", 85),
                                ("paid_label", "支付", 75),
                                ("group_name", "团体", 110),
                                ("settlement_no", "结账单号", 150)],
                    "rows": orders,
                    "formatter": lambda o: (
                        o["order_id"], _text(o["room_number"]),
                        _text(o["type_name"]), _text(o["check_in_date"]),
                        _text(o["check_out_date"]), o["nights"],
                        _fmt_money(o["total_price"]), _text(o["status_label"]),
                        o["paid_label"], _text(o["group_name"]),
                        _text(o["settlement_no"])),
                })

        self.app.run_guarded(action)
