"""
客人端各标签页。

每个标签页只做三件事：读取输入、调用 app.service、渲染结果。
所有校验与写库都发生在 service 层，界面层不再出现任何 SQL。
"""

from __future__ import annotations

import tkinter as tk
from datetime import date, timedelta
from tkinter import ttk
from typing import Callable

from app import service
from app.service import BusinessError
from app.ui.widgets import (
    CS, FONT, DataTable, DateField, DetailDialog, LabeledCombo, LabeledEntry,
    RoundedButton, ToolbarCombo, info, warn,
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
        self.id_card = LabeledEntry(form, "证件号（选填）")
        self.id_card.pack(fill="x")

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
                guest_name=self.guest_name.get(), guest_phone=self.guest_phone.get(),
                id_card=self.id_card.get())

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
            toolbar, "类型：", ["全部", "客房"],
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
            type_map = {"全部": None, "客房": "room"}
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
            ("团体", row.get("group_name") or "—"),
            ("结账单号", row.get("settlement_no") or "—"),
            ("详情", row["detail"]),
            ("下单时间", _fmt_time(row["created_at"])),
            ("金额", _fmt_money(row["total_price"])),
            ("状态", row["status_label"]),
        ]

        list_data = None
        if row["order_type"] == "room":
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
