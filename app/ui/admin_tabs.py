"""
管理端各标签页。

重点修正：
  · 「禁用/启用」按钮原先实际执行 DELETE FROM user，且外键是 CASCADE，
    会连带删掉该用户全部订单。现在改为 is_active 软禁用，历史订单完整保留；
  · 「收入」原先按订单状态求和（未收款的订单也计入），现在只统计
    payment 表的真实流水，并支持日期区间筛选；
  · 资源管理原先直接拼表名与列名做增删改，且列顺序一变就错位。
    现在按显式声明的字段规格操作，并明确禁止修改主键。
"""

from __future__ import annotations

import tkinter as tk
from datetime import date, timedelta
from tkinter import ttk

from app import service, stats
from app.service import BusinessError
from app.ui.widgets import (
    CS, FONT, DataTable, DateField, DetailDialog, LabeledCombo, LabeledEntry,
    RoundedButton, StatCard, info, warn,
)

# =====================================================================
#  资源管理
#  字段规格由 service.RESOURCE_CATALOG 提供（白名单），
#  界面只负责渲染，增删改一律走 service.resource_* 系列函数。
# =====================================================================


def _fmt_time(value) -> str:
    return str(value).split(".")[0] if value else ""


def _fmt_money(value) -> str:
    try:
        return f"¥{float(value or 0):,.2f}"
    except (TypeError, ValueError):
        return "¥0.00"


class AdminTab(tk.Frame):
    """管理端标签页基类。"""

    def __init__(self, parent, window):
        super().__init__(parent, bg=CS.BG_MAIN)
        self.app = window
        self.db = window.db
        self.session = window.session

    def on_show(self) -> None:
        pass


# =====================================================================
#  数据统计 / 营收
# =====================================================================
class RevenueTab(AdminTab):
    """
    营收与统计。

    收入只来自 payment 表的真实流水（paid 状态），
    可按起止日期筛选，并展示支付方式与每日趋势。
    """

    def __init__(self, parent, window):
        super().__init__(parent, window)

        header = tk.Frame(self, bg=CS.BG_MAIN)
        header.pack(fill="x", padx=14, pady=(12, 6))
        tk.Label(header, text="📊 经营数据统计", font=(FONT, 14, "bold"),
                 bg=CS.BG_MAIN, fg=CS.TEXT_PRIMARY).pack(side="left")

        self.range_combo = ttk.Combobox(
            header, values=["今日", "近 7 天", "近 30 天", "本月", "全部"],
            font=(FONT, 10), width=10, state="readonly")
        self.range_combo.current(4)
        self.range_combo.pack(side="left", padx=12)
        self.range_combo.bind("<<ComboboxSelected>>", lambda _e: self.on_show())

        RoundedButton(header, text="🔄 刷新", width=90, height=30, radius=6,
                      font=(FONT, 9, "bold"), command=self.on_show).pack(side="right")

        cards = tk.Frame(self, bg=CS.BG_MAIN)
        cards.pack(fill="x", padx=14, pady=(4, 8))
        self.cards: dict[str, StatCard] = {}
        for index, (key, label, color) in enumerate((
            ("total", "实收总额", CS.SUCCESS),
            ("refunded", "已退款", CS.DANGER),
            ("net", "净收入", CS.BG_DARK),
            ("orders", "订单总数", CS.PRIMARY),
            ("payment_count", "收款笔数", CS.PURPLE),
            ("pending_payment", "待收款订单", CS.WARNING),
        )):
            card = StatCard(cards, label, "-", color, width=152, height=80)
            card.grid(row=0, column=index, padx=7, pady=6)
            self.cards[key] = card

        body = tk.Frame(self, bg=CS.BG_MAIN)
        body.pack(fill="both", expand=True, padx=14, pady=(0, 12))

        # 左：按业务线
        left = tk.Frame(body, bg=CS.BG_MAIN)
        left.pack(side="left", fill="both", expand=True, padx=(0, 6))
        tk.Label(left, text="按业务线（实收）", font=(FONT, 11, "bold"), bg=CS.BG_MAIN,
                 fg=CS.TEXT_PRIMARY).pack(anchor="w", pady=(0, 4))
        self.type_table = DataTable(left, [
            ("type_label", "业务", 80),
            ("payment_count", "笔数", 60),
            ("amount", "金额", 110),
        ], height=6)
        self.type_table.pack(fill="both", expand=True)

        tk.Label(left, text="订单量 / 状态分布", font=(FONT, 11, "bold"), bg=CS.BG_MAIN,
                 fg=CS.TEXT_PRIMARY).pack(anchor="w", pady=(8, 4))
        self.service_table = DataTable(left, [
            ("type_label", "业务", 80),
            ("order_count", "总量", 60),
            ("active_count", "进行中", 70),
            ("completed_count", "已完成", 70),
            ("cancelled_count", "已取消", 70),
            ("order_amount", "订单金额", 110),
        ], height=7)
        self.service_table.pack(fill="both", expand=True)

        # 右：支付方式 + 每日趋势
        right = tk.Frame(body, bg=CS.BG_MAIN)
        right.pack(side="left", fill="both", expand=True, padx=(6, 0))
        tk.Label(right, text="支付方式分布", font=(FONT, 11, "bold"), bg=CS.BG_MAIN,
                 fg=CS.TEXT_PRIMARY).pack(anchor="w", pady=(0, 4))
        self.method_table = DataTable(right, [
            ("method_label", "方式", 90),
            ("payment_count", "笔数", 60),
            ("amount", "金额", 110),
        ], height=5)
        self.method_table.pack(fill="x")

        tk.Label(right, text="每日营收", font=(FONT, 11, "bold"), bg=CS.BG_MAIN,
                 fg=CS.TEXT_PRIMARY).pack(anchor="w", pady=(8, 4))
        self.day_table = DataTable(right, [
            ("pay_date", "日期", 110),
            ("payment_count", "笔数", 60),
            ("amount", "金额", 110),
        ], height=8)
        self.day_table.pack(fill="both", expand=True)

        self.on_show()

    def _range(self) -> tuple[date | None, date | None]:
        choice = self.range_combo.get()
        today = date.today()
        if choice == "今日":
            return today, today
        if choice == "近 7 天":
            return today - timedelta(days=6), today
        if choice == "近 30 天":
            return today - timedelta(days=29), today
        if choice == "本月":
            return today.replace(day=1), today
        return None, None

    def on_show(self) -> None:
        def action() -> None:
            start, end = self._range()
            revenue = stats.revenue_summary(self.db, start, end)
            overview = stats.overview(self.db)

            self.cards["total"].update_value(_fmt_money(revenue["total"]))
            self.cards["refunded"].update_value(_fmt_money(revenue["refunded"]))
            self.cards["net"].update_value(_fmt_money(revenue["net"]))
            self.cards["payment_count"].update_value(str(
                sum(int(r["payment_count"]) for r in revenue["by_type"])))
            self.cards["pending_payment"].update_value(str(overview["pending_payment"]))

            orders = service.list_orders(self.db, limit=None)
            self.cards["orders"].update_value(str(len(orders)))

            self.type_table.set_rows(revenue["by_type"], formatter=lambda r: (
                r["type_label"], r["payment_count"], _fmt_money(r["amount"])))
            self.method_table.set_rows(revenue["by_method"], formatter=lambda r: (
                r["method_label"], r["payment_count"], _fmt_money(r["amount"])))
            self.day_table.set_rows(revenue["by_day"], formatter=lambda r: (
                str(r["pay_date"]), r["payment_count"], _fmt_money(r["amount"])))
            self.service_table.set_rows(stats.service_stats(self.db),
                                        formatter=lambda s: (
                s["type_label"], s["order_count"], s["active_count"],
                s["completed_count"], s["cancelled_count"],
                _fmt_money(s["order_amount"])))

            label = self.range_combo.get()
            self.app.status.show(
                f"{label}：实收 {_fmt_money(revenue['total'])}，"
                f"净收入 {_fmt_money(revenue['net'])}", "success")

        self.app.run_guarded(action)


# =====================================================================
#  用户管理
# =====================================================================
class UsersTab(AdminTab):
    """用户账号管理：软禁用而非删除，历史订单完整保留。"""

    def __init__(self, parent, window):
        super().__init__(parent, window)

        toolbar = tk.Frame(self, bg=CS.BG_MAIN)
        toolbar.pack(fill="x", padx=14, pady=(12, 6))

        tk.Label(toolbar, text="角色：", font=(FONT, 10), bg=CS.BG_MAIN).pack(side="left")
        self.role_combo = ttk.Combobox(
            toolbar, values=["全部", "客人", "前台", "管理员"],
            font=(FONT, 10), width=8, state="readonly")
        self.role_combo.current(0)
        self.role_combo.pack(side="left", padx=(0, 10))
        self.role_combo.bind("<<ComboboxSelected>>", lambda _e: self.on_show())

        tk.Label(toolbar, text="搜索：", font=(FONT, 10), bg=CS.BG_MAIN).pack(side="left")
        self.keyword_entry = tk.Entry(toolbar, font=(FONT, 10), width=14,
                                      bd=1, relief="solid")
        self.keyword_entry.pack(side="left")
        self.keyword_entry.bind("<Return>", lambda _e: self.on_show())

        RoundedButton(toolbar, text="🔄 刷新", width=90, height=30, radius=6,
                      font=(FONT, 9, "bold"), command=self.on_show).pack(side="left", padx=8)

        RoundedButton(toolbar, text="＋ 添加用户", width=110, height=30, radius=6,
                      font=(FONT, 9, "bold"), color=CS.SUCCESS,
                      hover_color=CS.SUCCESS_DARK,
                      command=self.add_user).pack(side="right", padx=5)
        RoundedButton(toolbar, text="🔑 重置密码", width=110, height=30, radius=6,
                      font=(FONT, 9, "bold"), color=CS.WARNING,
                      hover_color=CS.WARNING_DARK,
                      command=self.reset_password).pack(side="right", padx=5)
        RoundedButton(toolbar, text="🚫 禁用 / 启用", width=120, height=30, radius=6,
                      font=(FONT, 9, "bold"), color=CS.DANGER,
                      hover_color=CS.DANGER_DARK,
                      command=self.toggle_active).pack(side="right", padx=5)

        self.table = DataTable(self, [
            ("user_id", "ID", 50),
            ("username", "用户名", 110),
            ("real_name", "真实姓名", 100),
            ("role_label", "角色", 80),
            ("phone", "手机号", 120),
            ("email", "邮箱", 170),
            ("active_label", "状态", 80),
            ("created_at", "注册时间", 140),
            ("order_count", "订单数", 70),
        ], height=18)
        self.table.pack(fill="both", expand=True, padx=14, pady=(0, 14))

        self.on_show()

    def on_show(self) -> None:
        def action() -> None:
            role_map = {"全部": None, "客人": "guest", "前台": "receptionist",
                        "管理员": "admin"}
            rows = service.list_users(self.db, role=role_map.get(self.role_combo.get()),
                                      keyword=self.keyword_entry.get().strip())
            labels = {"guest": "客人", "receptionist": "前台", "admin": "管理员"}

            # 一次性统计每个用户的订单数（避免逐行查询）
            counts = service.user_order_counts(self.db)

            for row in rows:
                row["role_label"] = labels.get(row["role"], row["role"])
                row["active_label"] = "启用" if row["is_active"] else "已禁用"
                row["order_count"] = counts.get(row["user_id"], 0)

            self.table.set_rows(rows, formatter=lambda u: (
                u["user_id"], u["username"], u["real_name"] or "—", u["role_label"],
                u["phone"] or "—", u["email"] or "—", u["active_label"],
                _fmt_time(u["created_at"]), u["order_count"],
            ), tagger=lambda u: "空闲" if u["is_active"] else "已取消")

            self.app.status.show(f"共 {len(rows)} 个账号", "info")

        self.app.run_guarded(action)

    def add_user(self) -> None:
        dialog = tk.Toplevel(self.app.window)
        dialog.title("添加用户")
        dialog.configure(bg=CS.BG_WHITE)
        dialog.resizable(False, False)
        dialog.transient(self.app.window)
        dialog.grab_set()

        tk.Label(dialog, text="添加新用户", font=(FONT, 14, "bold"), bg=CS.BG_WHITE,
                 fg=CS.TEXT_PRIMARY).pack(pady=(18, 12))
        form = tk.Frame(dialog, bg=CS.BG_WHITE)
        form.pack(padx=30, fill="x")

        username = LabeledEntry(form, "用户名", width=26)
        username.pack(fill="x")
        password = LabeledEntry(form, "密码（至少 6 位）", width=26, show="●")
        password.pack(fill="x")
        realname = LabeledEntry(form, "真实姓名", width=26)
        realname.pack(fill="x")
        phone = LabeledEntry(form, "手机号（选填）", width=26)
        phone.pack(fill="x")
        email = LabeledEntry(form, "邮箱（选填）", width=26)
        email.pack(fill="x")
        role = LabeledCombo(form, "角色", ["客人", "前台", "管理员"], width=24)
        role.pack(fill="x")

        error_var = tk.StringVar()
        tk.Label(dialog, textvariable=error_var, font=(FONT, 9), bg=CS.BG_WHITE,
                 fg=CS.DANGER, wraplength=300, justify="left").pack(pady=(8, 0))

        def submit() -> None:
            role_map = {"客人": "guest", "前台": "receptionist", "管理员": "admin"}
            try:
                service.create_user(
                    self.db, username=username.get(), password=password.get(),
                    real_name=realname.get(), role=role_map[role.get()],
                    phone=phone.get(), email=email.get())
            except BusinessError as exc:
                error_var.set(f"⚠ {exc}")
                return
            info("添加成功", f"用户 {username.get()} 已创建。", parent=dialog)
            dialog.destroy()
            self.app.refresh_all()

        buttons = tk.Frame(dialog, bg=CS.BG_WHITE)
        buttons.pack(pady=14)
        RoundedButton(buttons, text="确认添加", width=120, height=36, radius=8,
                      color=CS.SUCCESS, hover_color=CS.SUCCESS_DARK,
                      command=submit).pack(side="left", padx=4)
        RoundedButton(buttons, text="取消", width=80, height=36, radius=8,
                      color=CS.NEUTRAL, hover_color=CS.NEUTRAL_DARK,
                      command=dialog.destroy).pack(side="left", padx=4)

        from app.ui.widgets import center_window
        center_window(dialog, 380, 560)

    def reset_password(self) -> None:
        row = self.table.selected()
        if row is None:
            warn("提示", "请先选择一个用户", parent=self.app.window)
            return

        dialog = tk.Toplevel(self.app.window)
        dialog.title("重置密码")
        dialog.configure(bg=CS.BG_WHITE)
        dialog.resizable(False, False)
        dialog.transient(self.app.window)
        dialog.grab_set()

        tk.Label(dialog, text=f"重置「{row['username']}」的密码", font=(FONT, 12, "bold"),
                 bg=CS.BG_WHITE, fg=CS.TEXT_PRIMARY).pack(pady=(18, 10))
        entry = LabeledEntry(dialog, "新密码（至少 6 位）", width=24, show="●")
        entry.pack(padx=30, fill="x")

        error_var = tk.StringVar()
        tk.Label(dialog, textvariable=error_var, font=(FONT, 9), bg=CS.BG_WHITE,
                 fg=CS.DANGER, wraplength=260).pack()

        def submit() -> None:
            try:
                service.admin_reset_password(self.db, row["user_id"], entry.get())
            except BusinessError as exc:
                error_var.set(f"⚠ {exc}")
                return
            info("已重置", f"用户 {row['username']} 的密码已更新为加盐哈希。",
                 parent=dialog)
            dialog.destroy()

        buttons = tk.Frame(dialog, bg=CS.BG_WHITE)
        buttons.pack(pady=12)
        RoundedButton(buttons, text="确认重置", width=110, height=34, radius=7,
                      color=CS.WARNING, hover_color=CS.WARNING_DARK,
                      command=submit).pack(side="left", padx=4)
        RoundedButton(buttons, text="取消", width=80, height=34, radius=7,
                      color=CS.NEUTRAL, hover_color=CS.NEUTRAL_DARK,
                      command=dialog.destroy).pack(side="left", padx=4)

        from app.ui.widgets import center_window
        center_window(dialog, 330, 250)

    def toggle_active(self) -> None:
        row = self.table.selected()
        if row is None:
            warn("提示", "请先选择一个用户", parent=self.app.window)
            return

        target_active = not bool(row["is_active"])
        action_text = "启用" if target_active else "禁用"

        def action() -> None:
            service.set_user_active(self.db, row["user_id"], target_active,
                                    current_user_id=self.session.user_id)
            info(f"已{action_text}",
                 f"账号 {row['username']} 已{action_text}。\n"
                 + ("该账号现在可以正常登录。" if target_active
                    else "该账号将无法登录，但其历史订单完整保留（不会删除任何数据）。"),
                 parent=self.app.window)
            self.on_show()

        self.app.run_guarded(
            action, confirm_title=f"确认{action_text}",
            confirm_text=f"确定要{action_text}账号 {row['username']}"
                         f"（{row['role_label']}）吗？\n"
                         f"当前订单数：{row['order_count']}\n\n"
                         + ("启用后该账号可正常登录。"
                            if target_active else
                            "禁用只影响登录，不会删除该用户的任何订单数据。"))


# =====================================================================
#  资源管理
# =====================================================================
class ResourcesTab(AdminTab):
    """基础资源（房型/房间/餐厅/菜品/设施/SPA/技师）维护。"""

    def __init__(self, parent, window):
        super().__init__(parent, window)

        header = tk.Frame(self, bg=CS.BG_MAIN)
        header.pack(fill="x", padx=14, pady=(12, 6))
        tk.Label(header, text="🔧 基础资源管理", font=(FONT, 14, "bold"), bg=CS.BG_MAIN,
                 fg=CS.TEXT_PRIMARY).pack(side="left")
        tk.Label(header, text="（选择左侧资源类型 → 右侧增删改；主键不可修改）",
                 font=(FONT, 9), bg=CS.BG_MAIN, fg=CS.TEXT_SECONDARY).pack(side="left",
                                                                            padx=8)

        body = tk.Frame(self, bg=CS.BG_MAIN)
        body.pack(fill="both", expand=True, padx=14, pady=(0, 14))

        # 左：资源类型列表
        left = tk.Frame(body, bg=CS.BG_WHITE, width=170,
                        highlightbackground=CS.BORDER, highlightthickness=1)
        left.pack(side="left", fill="y", padx=(0, 8))
        left.pack_propagate(False)
        tk.Label(left, text="资源类型", font=(FONT, 11, "bold"), bg=CS.BG_WHITE,
                 fg=CS.TEXT_PRIMARY).pack(pady=(10, 6))

        self._listbox = tk.Listbox(left, font=(FONT, 10), bd=0, highlightthickness=0,
                                   selectbackground=CS.PRIMARY, selectforeground="white",
                                   activestyle="none")
        # 资源类型与字段规格由 service.RESOURCE_CATALOG 提供（白名单）
        self._specs = service.resource_catalog()
        for spec in self._specs:
            self._listbox.insert("end", f"  {spec['label']}")
        self._listbox.configure(height=len(self._specs))
        self._listbox.pack(fill="x", padx=6)
        self._listbox.bind("<<ListboxSelect>>", lambda _e: self.on_show())
        self._listbox.selection_set(0)

        # 右：数据表 + 操作
        right = tk.Frame(body, bg=CS.BG_MAIN)
        right.pack(side="left", fill="both", expand=True)

        toolbar = tk.Frame(right, bg=CS.BG_MAIN)
        toolbar.pack(fill="x", pady=(0, 6))
        self.title_label = tk.Label(toolbar, text="", font=(FONT, 12, "bold"),
                                    bg=CS.BG_MAIN, fg=CS.TEXT_PRIMARY)
        self.title_label.pack(side="left")

        RoundedButton(toolbar, text="＋ 新增", width=90, height=30, radius=6,
                      font=(FONT, 9, "bold"), color=CS.SUCCESS,
                      hover_color=CS.SUCCESS_DARK,
                      command=self.add).pack(side="right", padx=4)
        RoundedButton(toolbar, text="✎ 修改", width=90, height=30, radius=6,
                      font=(FONT, 9, "bold"), color=CS.PRIMARY,
                      hover_color=CS.PRIMARY_DARK,
                      command=self.edit).pack(side="right", padx=4)
        RoundedButton(toolbar, text="✖ 删除", width=90, height=30, radius=6,
                      font=(FONT, 9, "bold"), color=CS.DANGER,
                      hover_color=CS.DANGER_DARK,
                      command=self.delete).pack(side="right", padx=4)
        RoundedButton(toolbar, text="🔄 刷新", width=90, height=30, radius=6,
                      font=(FONT, 9, "bold"),
                      command=self.on_show).pack(side="right", padx=4)

        self.table_host = tk.Frame(right, bg=CS.BG_MAIN)
        self.table_host.pack(fill="both", expand=True)
        self.table: DataTable | None = None

        self.on_show()

    def _current_spec(self) -> dict:
        index = self._listbox.curselection()
        return self._specs[index[0] if index else 0]

    def on_show(self) -> None:
        spec = self._current_spec()
        table_name, name = spec["table"], spec["label"]
        self.title_label.config(text=f"{name}（{table_name}）")

        if self.table is not None:
            self.table.destroy()
        self.table = DataTable(
            self.table_host,
            [(f["name"], f["label"], f["width"]) for f in spec["fields"]],
            height=17)
        self.table.pack(fill="both", expand=True)

        def action() -> None:
            rows = service.resource_list(self.db, table_name)
            self.table.set_rows(rows, formatter=lambda r: tuple(
                r.get(f["name"]) for f in spec["fields"]))
            self.app.status.show(f"{name}：{len(rows)} 条记录", "info")

        self.app.run_guarded(action)

    def _open_editor(self, row: dict | None) -> None:
        spec = self._current_spec()
        table_name, name, pk = spec["table"], spec["label"], spec["pk"]
        editable = [f for f in spec["fields"] if f["editable"]]

        dialog = tk.Toplevel(self.app.window)
        dialog.title(("修改" if row else "新增") + name)
        dialog.configure(bg=CS.BG_WHITE)
        dialog.transient(self.app.window)
        dialog.grab_set()

        tk.Label(dialog, text=("修改" if row else "新增") + f"{name}",
                 font=(FONT, 14, "bold"), bg=CS.BG_WHITE,
                 fg=CS.TEXT_PRIMARY).pack(pady=(18, 10))

        form = tk.Frame(dialog, bg=CS.BG_WHITE)
        form.pack(padx=30, fill="x")
        entries: dict[str, LabeledEntry] = {}
        for field in editable:
            initial = "" if row is None else ("" if row.get(field["name"]) is None
                                              else str(row.get(field["name"])))
            label = field["label"]
            if field["choices"]:
                label += "（" + "/".join(field["choices"]) + "）"
            entry = LabeledEntry(form, label, width=28, initial=initial)
            entry.pack(fill="x")
            entries[field["name"]] = entry

        error_var = tk.StringVar()
        tk.Label(dialog, textvariable=error_var, font=(FONT, 9), bg=CS.BG_WHITE,
                 fg=CS.DANGER, wraplength=320, justify="left").pack(pady=(8, 0))

        def submit() -> None:
            values = {col: entry.get() for col, entry in entries.items()}
            try:
                if row is None:
                    service.resource_create(self.db, table_name, values)
                else:
                    service.resource_update(self.db, table_name, row[pk], values)
            except BusinessError as exc:
                error_var.set(f"⚠ {exc}")
                return
            info("保存成功", f"{name}数据已保存。", parent=dialog)
            dialog.destroy()
            self.on_show()

        buttons = tk.Frame(dialog, bg=CS.BG_WHITE)
        buttons.pack(pady=14)
        RoundedButton(buttons, text="保存", width=110, height=36, radius=8,
                      color=CS.SUCCESS, hover_color=CS.SUCCESS_DARK,
                      command=submit).pack(side="left", padx=4)
        RoundedButton(buttons, text="取消", width=80, height=36, radius=8,
                      color=CS.NEUTRAL, hover_color=CS.NEUTRAL_DARK,
                      command=dialog.destroy).pack(side="left", padx=4)

        from app.ui.widgets import center_window
        center_window(dialog, 400, 160 + 62 * len(editable))

    def add(self) -> None:
        self._open_editor(None)

    def edit(self) -> None:
        row = self.table.selected() if self.table else None
        if row is None:
            warn("提示", "请先选择一条记录", parent=self.app.window)
            return
        self._open_editor(row)

    def delete(self) -> None:
        row = self.table.selected() if self.table else None
        if row is None:
            warn("提示", "请先选择一条记录", parent=self.app.window)
            return

        spec = self._current_spec()
        table_name, name, pk = spec["table"], spec["label"], spec["pk"]
        # 用第二个显示字段作为提示名（第一个是主键 ID）；没有则退回主键
        name_field = next((f["name"] for f in spec["fields"][1:]), pk)
        label = str(row.get(name_field, row.get(pk)))

        def action() -> None:
            service.resource_delete(self.db, table_name, row[pk])
            info("已删除", f"{name}「{label}」已删除。", parent=self.app.window)
            self.on_show()

        self.app.run_guarded(
            action, confirm_title="确认删除",
            confirm_text=f"确定要删除{name}「{label}」吗？\n\n"
                         f"若该记录被房间/订单等数据引用，数据库会拒绝删除。")


# =====================================================================
#  订单总览
# =====================================================================
class AdminOrdersTab(AdminTab):
    """全部订单总览（只读 + 取消 + 详情）。"""

    def __init__(self, parent, window):
        super().__init__(parent, window)

        toolbar = tk.Frame(self, bg=CS.BG_MAIN)
        toolbar.pack(fill="x", padx=14, pady=(12, 6))

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
        RoundedButton(toolbar, text="❌ 取消订单", width=110, height=30, radius=6,
                      font=(FONT, 9, "bold"), color=CS.DANGER,
                      hover_color=CS.DANGER_DARK,
                      command=self.cancel).pack(side="right", padx=6)

        self.table = DataTable(self, [
            ("order_id", "订单号", 190),
            ("username", "客人", 90),
            ("type_label", "类型", 60),
            ("detail", "详情", 250),
            ("created_at", "下单时间", 140),
            ("total_price", "金额", 85),
            ("status_label", "状态", 95),
            ("paid_label", "支付", 80),
        ], height=18, on_double_click=lambda _r: self.detail())
        self.table.pack(fill="both", expand=True, padx=14, pady=(0, 14))

        self.on_show()

    def on_show(self) -> None:
        def action() -> None:
            type_map = {"全部": None, "客房": "room", "餐饮": "dining",
                        "健身": "fitness", "SPA": "spa", "洗衣": "laundry"}
            rows = service.list_orders(self.db, order_type=type_map.get(self.type_combo.get()),
                                       status_category=self.status_combo.get())
            paid = service.paid_order_map(self.db)

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
        payments = service.list_payments(self.db, order_type=row["order_type"])
        related = [p for p in payments if p["order_id"] == row["order_id"]]
        list_data = None
        if related:
            list_data = {
                "title": "支付流水",
                "columns": [("payment_no", "流水号", 180), ("amount", "金额", 90),
                            ("method_label", "方式", 80), ("status", "状态", 80),
                            ("paid_at", "时间", 140)],
                "rows": related,
                "formatter": lambda p: (p["payment_no"], _fmt_money(p["amount"]),
                                        p["method_label"],
                                        "已支付" if p["status"] == "paid" else "已退款",
                                        _fmt_time(p["paid_at"])),
            }
        DetailDialog(self.app.window, "订单详情", pairs, list_data=list_data)

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
                         f"{row['username']} · {row['type_label']} · {row['detail']}\n"
                         f"当前状态：{row['status_label']}")


# =====================================================================
#  关于系统
# =====================================================================
class AboutTab(AdminTab):
    """
    系统与数据库信息。

    专门把"数据库对象清单"展示出来：原系统的视图/触发器/存储过程全是 0，
    这里可以直观看到本次重构补齐了哪些数据库能力。
    """

    def __init__(self, parent, window):
        super().__init__(parent, window)

        tk.Label(self, text="ℹ 系统与数据库信息", font=(FONT, 14, "bold"),
                 bg=CS.BG_MAIN, fg=CS.TEXT_PRIMARY).pack(pady=(14, 8), anchor="w",
                                                          padx=16)

        self.objects_frame = tk.Frame(self, bg=CS.BG_MAIN)
        self.objects_frame.pack(fill="x", padx=16, pady=(0, 10))
        self.cards: dict[str, StatCard] = {}
        for index, (key, label, color) in enumerate((
            ("tables", "数据表", CS.PRIMARY),
            ("views", "视图", CS.SUCCESS),
            ("triggers", "触发器", CS.PURPLE),
            ("indexes", "索引", CS.TEAL),
            ("foreign_keys", "外键约束", CS.WARNING),
            ("check_constraints", "CHECK 约束", CS.DANGER),
        )):
            card = StatCard(self.objects_frame, label, "-", color, width=145, height=78)
            card.grid(row=0, column=index, padx=7, pady=6)
            self.cards[key] = card

        body = tk.Frame(self, bg=CS.BG_MAIN)
        body.pack(fill="both", expand=True, padx=16, pady=(0, 14))

        left = tk.Frame(body, bg=CS.BG_MAIN)
        left.pack(side="left", fill="both", expand=True, padx=(0, 8))
        tk.Label(left, text="视图清单", font=(FONT, 11, "bold"), bg=CS.BG_MAIN,
                 fg=CS.TEXT_PRIMARY).pack(anchor="w", pady=(0, 4))
        self.view_table = DataTable(left, [("name", "视图名", 220)], height=7)
        self.view_table.pack(fill="both", expand=True)

        tk.Label(left, text="触发器清单", font=(FONT, 11, "bold"), bg=CS.BG_MAIN,
                 fg=CS.TEXT_PRIMARY).pack(anchor="w", pady=(8, 4))
        self.trigger_table = DataTable(left, [
            ("name", "触发器", 220), ("timing", "时机", 90), ("table", "表", 130),
        ], height=10)
        self.trigger_table.pack(fill="both", expand=True)

        right = tk.Frame(body, bg=CS.BG_MAIN)
        right.pack(side="left", fill="both", expand=True, padx=(8, 0))
        tk.Label(right, text="数据表行数", font=(FONT, 11, "bold"), bg=CS.BG_MAIN,
                 fg=CS.TEXT_PRIMARY).pack(anchor="w", pady=(0, 4))
        self.table_count = DataTable(right, [
            ("table_name", "表名", 190), ("rows", "行数", 90),
        ], height=18)
        self.table_count.pack(fill="both", expand=True)

        self.on_show()

    def on_show(self) -> None:
        def action() -> None:
            counts = stats.schema_objects(self.db)
            for key, card in self.cards.items():
                card.update_value(str(counts.get(key, 0)))

            names = service.schema_object_names(self.db)
            self.view_table.set_rows(names["views"])

            self.trigger_table.set_rows(names["triggers"], formatter=lambda r: (
                r["name"], r["timing"], r["table"]))

            self.table_count.set_rows(service.table_row_counts(self.db),
                                      formatter=lambda r: (r["table_name"], r["rows"]))

            self.app.status.show(
                f"数据库对象：{counts['tables']} 表 / {counts['views']} 视图 / "
                f"{counts['triggers']} 触发器 / {counts['indexes']} 索引 / "
                f"{counts['foreign_keys']} 外键 / {counts['check_constraints']} CHECK 约束",
                "success")

        self.app.run_guarded(action)
