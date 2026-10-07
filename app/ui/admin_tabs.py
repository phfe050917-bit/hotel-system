"""
管理端各标签页。

重点修正：
  · 「禁用/启用」按钮原先实际把用户记录物理删除，且外键是 CASCADE，
    会连带删掉该用户全部订单。现在改为 is_active 软禁用，历史订单完整保留；
  · 「收入」原先按订单状态求和（未收款的订单也计入），现在只统计
    payment 表的真实流水，并支持日期区间筛选；
  · 资源管理原先直接拼表名与列名做增删改，且列顺序一变就错位。
    现在按显式声明的字段规格操作，并明确禁止修改主键，且对
    房型/房间的改动强制走「密码支持 + 变更留痕」（题目要求 (4)）；
  · 新增「结账报表」页：汇总结账单、支持按时间范围筛选、导出 CSV
    与整单退款（题目要求 (5)）。
"""

from __future__ import annotations

import csv
import tkinter as tk
from datetime import date, timedelta
from tkinter import filedialog, ttk

from app import service, stats
from app.service import BusinessError
from app.ui.widgets import (
    CS, FONT, DataTable, DetailDialog, LabeledCombo, LabeledEntry,
    RoundedButton, StatCard, info, warn,
)

#: 支付流水状态 -> 中文（结账单明细的「支付状态」列）
PAYMENT_STATUS_LABEL = {"paid": "已支付", "refunded": "已退款",
                        "pending": "待支付", "failed": "支付失败"}


def _fmt_time(value) -> str:
    return str(value).split(".")[0] if value else ""


def _fmt_money(value) -> str:
    try:
        return f"¥{float(value or 0):,.2f}"
    except (TypeError, ValueError):
        return "¥0.00"


def _fmt_payment_status(status) -> str:
    return PAYMENT_STATUS_LABEL.get(status, status or "未支付")


def _fmt_audit_value(value) -> str:
    """审计留痕里的旧值/新值可能很长，列表里截断显示。"""
    if value is None:
        return "—"
    text = str(value)
    return text if len(text) <= 60 else text[:57] + "..."


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
    可按起止日期筛选，并展示支付方式与每日营收流水。
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

        # 左：支付方式分布
        left = tk.Frame(body, bg=CS.BG_MAIN)
        left.pack(side="left", fill="both", expand=True, padx=(0, 6))
        tk.Label(left, text="支付方式分布", font=(FONT, 11, "bold"), bg=CS.BG_MAIN,
                 fg=CS.TEXT_PRIMARY).pack(anchor="w", pady=(0, 4))
        self.method_table = DataTable(left, [
            ("method_label", "方式", 90),
            ("payment_count", "笔数", 60),
            ("amount", "金额", 110),
        ], height=12)
        self.method_table.pack(fill="both", expand=True)

        # 右：每日营收流水
        right = tk.Frame(body, bg=CS.BG_MAIN)
        right.pack(side="left", fill="both", expand=True, padx=(6, 0))
        tk.Label(right, text="每日营收", font=(FONT, 11, "bold"), bg=CS.BG_MAIN,
                 fg=CS.TEXT_PRIMARY).pack(anchor="w", pady=(0, 4))
        self.day_table = DataTable(right, [
            ("pay_date", "日期", 110),
            ("payment_count", "笔数", 60),
            ("amount", "金额", 110),
        ], height=14)
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
                sum(int(r["payment_count"]) for r in revenue["by_method"])))
            self.cards["pending_payment"].update_value(str(overview["pending_payment"]))

            orders = service.list_orders(self.db, limit=None)
            self.cards["orders"].update_value(str(len(orders)))

            self.method_table.set_rows(revenue["by_method"], formatter=lambda r: (
                r["method_label"], r["payment_count"], _fmt_money(r["amount"])))
            self.day_table.set_rows(revenue["by_day"], formatter=lambda r: (
                str(r["pay_date"]), r["payment_count"], _fmt_money(r["amount"])))

            label = self.range_combo.get()
            self.app.status.show(
                f"{label}：实收 {_fmt_money(revenue['total'])}，"
                f"净收入 {_fmt_money(revenue['net'])}", "success")

        self.app.run_guarded(action)


# =====================================================================
#  结账报表（题目要求 (5)）
# =====================================================================
class SettlementReportTab(AdminTab):
    """
    结账报表。

    与「数据统计」页的分工：
      · 数据统计看的是收款流水（payment）——「收了多少钱」；
      · 本页看的是结账单（settlement）——「结了多少单、多少间房、怎么结的」。

    数据全部来自业务层：
      stats.settlement_report 负责汇总，service.list_settlements /
      settlement_detail 负责明细，refund_settlement 负责整单退款。
    界面层不出现任何 SQL。
    """

    def __init__(self, parent, window):
        super().__init__(parent, window)
        self._rows: list[dict] = []          # 当前筛选出的结账单，供导出 CSV 使用

        header = tk.Frame(self, bg=CS.BG_MAIN)
        header.pack(fill="x", padx=14, pady=(12, 6))
        tk.Label(header, text="🧾 结账报表", font=(FONT, 14, "bold"),
                 bg=CS.BG_MAIN, fg=CS.TEXT_PRIMARY).pack(side="left")

        self.range_combo = ttk.Combobox(
            header, values=["今日", "近 7 天", "近 30 天", "本月", "全部"],
            font=(FONT, 10), width=10, state="readonly")
        self.range_combo.current(4)
        self.range_combo.pack(side="left", padx=12)
        self.range_combo.bind("<<ComboboxSelected>>", lambda _e: self.on_show())

        RoundedButton(header, text="🔄 刷新", width=90, height=30, radius=6,
                      font=(FONT, 9, "bold"), command=self.on_show).pack(side="right")
        RoundedButton(header, text="📤 导出 CSV", width=110, height=30, radius=6,
                      font=(FONT, 9, "bold"), color=CS.TEAL,
                      hover_color=CS.TEAL_DARK,
                      command=self.export_csv).pack(side="right", padx=6)
        RoundedButton(header, text="↩ 整单退款", width=110, height=30, radius=6,
                      font=(FONT, 9, "bold"), color=CS.DANGER,
                      hover_color=CS.DANGER_DARK,
                      command=self.refund).pack(side="right", padx=6)

        # --- 统计卡片：结账单数 / 房间数 / 金额 / 散客 / 团体 / 均单 / 退款 / 未结账
        cards = tk.Frame(self, bg=CS.BG_MAIN)
        cards.pack(fill="x", padx=14, pady=(4, 6))
        self.cards: dict[str, StatCard] = {}
        for index, (key, label, color) in enumerate((
            ("bill_count", "结账单数", CS.PRIMARY),
            ("room_count", "结账房间数", CS.TEAL),
            ("total_amount", "结账金额", CS.SUCCESS),
            ("avg_bill", "平均单额", CS.BG_DARK),
            ("walkin_count", "散客单数", CS.PURPLE),
            ("group_count", "团体单数", CS.WARNING),
            ("refunded_count", "已退款单数", CS.DANGER),
            ("unsettled_orders", "未结账订单", CS.NEUTRAL),
        )):
            card = StatCard(cards, label, "-", color, width=210, height=72)
            card.grid(row=index // 4, column=index % 4, padx=6, pady=4)
            self.cards[key] = card

        # --- 结账单列表
        list_host = tk.Frame(self, bg=CS.BG_MAIN)
        list_host.pack(fill="both", expand=True, padx=14)
        tk.Label(list_host, text="结账单列表（选中一行即可查看该账单的房间明细）",
                 font=(FONT, 11, "bold"), bg=CS.BG_MAIN,
                 fg=CS.TEXT_PRIMARY).pack(anchor="w", pady=(0, 4))
        self.table = DataTable(list_host, [
            ("settlement_no", "结账单号", 170),
            ("bill_type", "类型", 60),
            ("group_name", "团体名", 100),
            ("username", "付款人", 85),
            ("room_count", "房间数", 60),
            ("total_amount", "金额", 95),
            ("method_label", "结算方式", 80),
            ("operator_name", "经手人", 85),
            ("status_label", "状态", 75),
            ("settled_at", "结账时间", 135),
            ("remark", "备注", 130),
        ], height=6, on_select=lambda _row: self.load_detail(),
            on_double_click=lambda _row: self.load_detail())
        self.table.pack(fill="both", expand=True)

        # --- 结账单明细（选中账单后填充）
        detail_host = tk.Frame(self, bg=CS.BG_MAIN)
        detail_host.pack(fill="x", padx=14, pady=(8, 0))
        self.detail_label = tk.Label(detail_host, text="结账单明细（请先选择账单）",
                                     font=(FONT, 11, "bold"), bg=CS.BG_MAIN,
                                     fg=CS.TEXT_PRIMARY)
        self.detail_label.pack(anchor="w", pady=(0, 4))
        self.detail_table = DataTable(detail_host, [
            ("room_number", "房间号", 80),
            ("type_name", "房型", 100),
            ("guest_name", "入住人", 90),
            ("id_card", "证件号", 150),
            ("check_in_date", "入住", 95),
            ("check_out_date", "离店", 95),
            ("nights", "晚数", 55),
            ("total_price", "订单金额", 90),
            ("payment_no", "支付流水号", 165),
            ("payment_status", "支付状态", 85),
        ], height=4)
        self.detail_table.pack(fill="both", expand=True)

        # --- 下方两个分组小表：按结算方式分布 / 按日结账流水
        bottom = tk.Frame(self, bg=CS.BG_MAIN)
        bottom.pack(fill="both", expand=True, padx=14, pady=(8, 12))

        left = tk.Frame(bottom, bg=CS.BG_MAIN)
        left.pack(side="left", fill="both", expand=True, padx=(0, 6))
        tk.Label(left, text="按结算方式分布", font=(FONT, 11, "bold"), bg=CS.BG_MAIN,
                 fg=CS.TEXT_PRIMARY).pack(anchor="w", pady=(0, 4))
        self.method_table = DataTable(left, [
            ("method_label", "结算方式", 90),
            ("bill_count", "结账单数", 80),
            ("amount", "金额", 120),
        ], height=4)
        self.method_table.pack(fill="both", expand=True)

        right = tk.Frame(bottom, bg=CS.BG_MAIN)
        right.pack(side="left", fill="both", expand=True, padx=(6, 0))
        tk.Label(right, text="按日结账流水", font=(FONT, 11, "bold"), bg=CS.BG_MAIN,
                 fg=CS.TEXT_PRIMARY).pack(anchor="w", pady=(0, 4))
        self.day_table = DataTable(right, [
            ("settle_date", "日期", 110),
            ("bill_count", "结账单数", 80),
            ("room_count", "房间数", 70),
            ("amount", "金额", 120),
        ], height=4)
        self.day_table.pack(fill="both", expand=True)

        self.on_show()

    def _range(self) -> tuple[date | None, date | None]:
        """把时间范围下拉框转成起止日期（与「数据统计」页保持一致）。"""
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
            report = stats.settlement_report(self.db, start, end)

            self.cards["bill_count"].update_value(str(report["bill_count"]))
            self.cards["room_count"].update_value(str(report["room_count"]))
            self.cards["total_amount"].update_value(_fmt_money(report["total_amount"]))
            self.cards["avg_bill"].update_value(_fmt_money(report["avg_bill"]))
            self.cards["walkin_count"].update_value(str(report["walkin_count"]))
            self.cards["group_count"].update_value(str(report["group_count"]))
            self.cards["refunded_count"].update_value(str(report["refunded_count"]))
            self.cards["unsettled_orders"].update_value(
                str(report["unsettled_orders"]))

            self._rows = service.list_settlements(self.db, start=start, end=end)
            self.table.set_rows(self._rows, formatter=lambda s: (
                s["settlement_no"], s["bill_type"], s.get("group_name") or "—",
                s["username"], s["room_count"], _fmt_money(s["total_amount"]),
                s.get("method_label") or "—", s.get("operator_name") or "—",
                s.get("status_label") or s["status"], _fmt_time(s["settled_at"]),
                s.get("remark") or "—",
            ))

            # 列表重填后选中项会丢失，明细同步清空，避免显示上一张账单
            self.detail_table.clear()
            self.detail_label.config(text="结账单明细（请先选择账单）")

            self.method_table.set_rows(report["by_method"], formatter=lambda r: (
                r.get("method_label") or "—", r["bill_count"], _fmt_money(r["amount"])))
            self.day_table.set_rows(report["by_day"], formatter=lambda r: (
                str(r["settle_date"]), r["bill_count"], r["room_count"],
                _fmt_money(r["amount"])))

            self.app.status.show(
                f"{self.range_combo.get()}：{report['bill_count']} 张结账单 / "
                f"{report['room_count']} 间房 / 金额 {_fmt_money(report['total_amount'])}，"
                f"已退款 {report['refunded_count']} 张", "success")

        self.app.run_guarded(action)

    def load_detail(self) -> None:
        """加载选中结账单的房间明细（v_settlement_detail）。"""
        row = self.table.selected()
        if row is None:
            return

        def action() -> None:
            details = service.settlement_detail(self.db, row["settlement_no"])
            self.detail_label.config(
                text=f"结账单明细：{row['settlement_no']}"
                     f"（{row['bill_type']}・{row['username']}・"
                     f"{row['room_count']} 间房・{len(details)} 条明细）")
            self.detail_table.set_rows(details, formatter=lambda d: (
                d.get("room_number") or "—", d.get("type_name") or "—",
                d.get("guest_name") or "—", d.get("id_card") or "—",
                str(d.get("check_in_date") or "—"),
                str(d.get("check_out_date") or "—"),
                d.get("nights") or 0, _fmt_money(d.get("total_price")),
                d.get("payment_no") or "—",
                _fmt_payment_status(d.get("payment_status")),
            ))
            self.app.status.show(
                f"结账单 {row['settlement_no']}：{len(details)} 条房间明细", "info")

        self.app.run_guarded(action)

    def export_csv(self) -> None:
        """
        导出当前结账单列表为 CSV。

        用标准库 csv + tkinter.filedialog，编码固定 utf-8-sig（带 BOM），
        Excel 双击即可正确显示中文，不引入任何新依赖。
        """
        if not self._rows:
            warn("提示", "当前时间范围内没有结账单可导出，请调整范围后刷新。",
                 parent=self.app.window)
            return

        path = filedialog.asksaveasfilename(
            parent=self.app.window, title="导出结账报表（结账单列表）",
            defaultextension=".csv", initialfile=f"结账报表_{date.today():%Y%m%d}.csv",
            filetypes=[("CSV 文件", "*.csv"), ("所有文件", "*.*")])
        if not path:
            return

        rows = list(self._rows)
        scope = self.range_combo.get()

        def action() -> None:
            with open(path, "w", newline="", encoding="utf-8-sig") as handle:
                writer = csv.writer(handle)
                writer.writerow(["结账单号", "类型", "团体名", "付款人", "房间数",
                                 "金额", "结算方式", "经手人", "状态", "结账时间",
                                 "备注"])
                for row in rows:
                    writer.writerow([
                        row["settlement_no"], row["bill_type"],
                        row.get("group_name") or "", row["username"],
                        row["room_count"],
                        f"{float(row['total_amount'] or 0):.2f}",
                        row.get("method_label") or "",
                        row.get("operator_name") or "",
                        row.get("status_label") or row["status"],
                        _fmt_time(row["settled_at"]), row.get("remark") or "",
                    ])
            info("导出成功",
                 f"导出内容：结账单列表（不含房间明细）\n"
                 f"时间范围：{scope}　共 {len(rows)} 张结账单\n"
                 f"编码：utf-8-sig（Excel 可直接打开）\n\n"
                 f"文件路径：\n{path}", parent=self.app.window)

        self.app.run_guarded(action)

    def refund(self) -> None:
        """对选中的结账单办理整单退款（二次确认 + 记录退款原因）。"""
        row = self.table.selected()
        if row is None:
            warn("提示", "请先选择一张结账单", parent=self.app.window)
            return
        if row["status"] != "settled":
            warn("提示", f"结账单 {row['settlement_no']} 当前是"
                         f"「{row['status_label']}」，无需重复退款。",
                 parent=self.app.window)
            return

        reason = self._ask_reason(
            "整单退款",
            f"结账单：{row['settlement_no']}\n付款人：{row['username']}　"
            f"金额：{_fmt_money(row['total_amount'])}　房间数：{row['room_count']}")
        if reason is None:
            return

        settlement_no = row["settlement_no"]

        def action() -> None:
            result = service.refund_settlement(
                self.db, settlement_no=settlement_no,
                operator_id=self.session.user_id, reason=reason)
            info("已退款",
                 f"结账单 {result['settlement_no']} 已整单退款。\n"
                 f"涉及房间订单 {result['order_count']} 张，"
                 f"置为退款的收款流水 {result['refunded_payments']} 笔，\n"
                 f"退款金额：{_fmt_money(result['refund_amount'])}\n\n"
                 f"成员订单已回到「未结账」状态，如需作废请再执行取消订单。",
                 parent=self.app.window)
            self.on_show()

        self.app.run_guarded(
            action, confirm_title="确认整单退款",
            confirm_text=f"确定要为结账单 {settlement_no} 办理整单退款吗？\n\n"
                         f"付款人：{row['username']}\n"
                         f"金额：{_fmt_money(row['total_amount'])}\n"
                         f"退款原因：{reason or '（未填写）'}\n\n"
                         f"退款后收款流水置为已退款，成员订单回到未结账状态。")

    def _ask_reason(self, title: str, detail: str) -> str | None:
        """弹出「退款原因」对话框；用户取消时返回 None。"""
        dialog = tk.Toplevel(self.app.window)
        dialog.title(title)
        dialog.configure(bg=CS.BG_WHITE)
        dialog.resizable(False, False)
        dialog.transient(self.app.window)
        dialog.grab_set()

        tk.Label(dialog, text="↩ 整单退款", font=(FONT, 14, "bold"),
                 bg=CS.BG_WHITE, fg=CS.TEXT_PRIMARY).pack(pady=(18, 8))
        tk.Label(dialog, text=detail, font=(FONT, 9), bg=CS.BG_WHITE,
                 fg=CS.TEXT_SECONDARY, justify="left", wraplength=330).pack(padx=26)

        form = tk.Frame(dialog, bg=CS.BG_WHITE)
        form.pack(padx=30, fill="x", pady=(8, 0))
        reason = LabeledEntry(form, "退款原因（选填）", width=28)
        reason.pack(fill="x")

        holder: dict[str, str | None] = {"value": None}

        def submit() -> None:
            holder["value"] = reason.get()
            dialog.destroy()

        buttons = tk.Frame(dialog, bg=CS.BG_WHITE)
        buttons.pack(pady=14)
        RoundedButton(buttons, text="确认退款", width=120, height=36, radius=8,
                      color=CS.DANGER, hover_color=CS.DANGER_DARK,
                      command=submit).pack(side="left", padx=4)
        RoundedButton(buttons, text="取消", width=80, height=36, radius=8,
                      color=CS.NEUTRAL, hover_color=CS.NEUTRAL_DARK,
                      command=dialog.destroy).pack(side="left", padx=4)

        from app.ui.widgets import center_window
        center_window(dialog, 390, 300)
        reason.entry.focus_set()
        self.app.window.wait_window(dialog)
        return holder["value"]


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
#: 需要「密码支持」的资源表，与 service.AUDITED_TABLES 一致：
#: 房价在 room_type、房间类型在 room_type、增加客房在 room —— 即题目要求 (4)。
APPROVAL_TABLES = ("room_type", "room")


class ApprovalDialog(tk.Toplevel):
    """
    敏感操作的密码支持对话框（题目要求 (4)）。

    题目原文要求「操作员在密码支持下才可更改房价，房间类型，增加客房」。
    因此对房型 / 房间的任何增删改，都要先在这里重新输入当前账号密码并填写
    变更原因；密码是否正确由业务层（service.Approval + 哈希校验）判定，
    界面只负责收集，既不预判也不吞掉 BusinessError。
    """

    def __init__(self, parent, *, action_label: str, target_label: str,
                 operator_name: str):
        super().__init__(parent)
        self.title("密码支持与变更留痕")
        self.configure(bg=CS.BG_WHITE)
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        #: (密码, 变更原因)；用户取消时保持 None
        self.result: tuple[str, str] | None = None

        tk.Label(self, text="🔐 密码支持", font=(FONT, 14, "bold"),
                 bg=CS.BG_WHITE, fg=CS.TEXT_PRIMARY).pack(pady=(18, 6))
        tk.Label(self, text=f"{action_label}「{target_label}」属于房价 / 房型 / 房间的"
                            f"敏感改动，需要操作员密码支持，并会记录变更原因。",
                 font=(FONT, 9), bg=CS.BG_WHITE, fg=CS.TEXT_SECONDARY,
                 justify="left", wraplength=320).pack(padx=28)

        form = tk.Frame(self, bg=CS.BG_WHITE)
        form.pack(padx=30, pady=(10, 0), fill="x")
        tk.Label(form, text=f"操作员：{operator_name}", font=(FONT, 10),
                 bg=CS.BG_WHITE, fg=CS.TEXT_PRIMARY).pack(anchor="w")
        self.password = LabeledEntry(form, "当前账号密码", width=26, show="●")
        self.password.pack(fill="x", pady=(6, 0))
        self.reason = LabeledEntry(form, "变更原因（建议填写）", width=26)
        self.reason.pack(fill="x")

        self._error = tk.StringVar()
        tk.Label(self, textvariable=self._error, font=(FONT, 9), bg=CS.BG_WHITE,
                 fg=CS.DANGER, wraplength=320, justify="left").pack(pady=(4, 0))

        buttons = tk.Frame(self, bg=CS.BG_WHITE)
        buttons.pack(pady=14)
        RoundedButton(buttons, text="确认", width=110, height=36, radius=8,
                      color=CS.SUCCESS, hover_color=CS.SUCCESS_DARK,
                      command=self._submit).pack(side="left", padx=4)
        RoundedButton(buttons, text="取消", width=80, height=36, radius=8,
                      color=CS.NEUTRAL, hover_color=CS.NEUTRAL_DARK,
                      command=self.destroy).pack(side="left", padx=4)

        from app.ui.widgets import center_window
        center_window(self, 380, 350)
        self.password.entry.focus_set()

    def _submit(self) -> None:
        password = self.password.get()
        if not password:
            # 密码为空不提交，留在对话框里提示
            self._error.set("⚠ 密码为空，操作未提交。请输入当前账号密码。")
            return
        self.result = (password, self.reason.get())
        self.destroy()


class ResourcesTab(AdminTab):
    """基础资源（房型/房间）维护。"""

    def __init__(self, parent, window):
        super().__init__(parent, window)

        header = tk.Frame(self, bg=CS.BG_MAIN)
        header.pack(fill="x", padx=14, pady=(12, 6))
        tk.Label(header, text="🔧 基础资源管理", font=(FONT, 14, "bold"), bg=CS.BG_MAIN,
                 fg=CS.TEXT_PRIMARY).pack(side="left")
        tk.Label(header, text="（选择左侧资源类型 → 右侧增删改；房价/房型/房间的改动"
                              "需输入密码并自动留痕，主键不可修改）",
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
        RoundedButton(toolbar, text="📜 变更记录", width=110, height=30, radius=6,
                      font=(FONT, 9, "bold"), color=CS.PURPLE,
                      hover_color=CS.PURPLE_DARK,
                      command=self.show_logs).pack(side="right", padx=4)
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

        needs_approval = table_name in APPROVAL_TABLES
        if needs_approval:
            tk.Label(dialog, text="⚠ 该资源属于「房价 / 房型 / 房间」，保存时需要输入"
                                  "当前账号密码（题目要求的密码支持）。",
                     font=(FONT, 9), bg=CS.BG_WHITE, fg=CS.TEXT_SECONDARY,
                     wraplength=320, justify="left").pack(padx=24, pady=(8, 0))

        def submit() -> None:
            values = {col: entry.get() for col, entry in entries.items()}
            action_label = "新增" if row is None else "修改"

            # 房价 / 房型 / 房间：必须先拿到密码凭据，密码为空不提交
            approval = None
            if needs_approval:
                approval = self._ask_approval(action_label=action_label,
                                              target_label=name)
                if approval is None:
                    return

            def action() -> None:
                if row is None:
                    service.resource_create(self.db, table_name, values,
                                            approval=approval)
                else:
                    service.resource_update(self.db, table_name, row[pk], values,
                                            approval=approval)
                info("保存成功", f"{name}数据已保存。", parent=dialog)
                dialog.destroy()
                self.on_show()

            # 密码错误会由业务层抛 BusinessError，统一交给 run_guarded 提示
            self.app.run_guarded(action)

        buttons = tk.Frame(dialog, bg=CS.BG_WHITE)
        buttons.pack(pady=14)
        RoundedButton(buttons, text="保存", width=110, height=36, radius=8,
                      color=CS.SUCCESS, hover_color=CS.SUCCESS_DARK,
                      command=submit).pack(side="left", padx=4)
        RoundedButton(buttons, text="取消", width=80, height=36, radius=8,
                      color=CS.NEUTRAL, hover_color=CS.NEUTRAL_DARK,
                      command=dialog.destroy).pack(side="left", padx=4)

        from app.ui.widgets import center_window
        center_window(dialog, 400, 180 + 62 * len(editable))

    def _ask_approval(self, *, action_label: str,
                      target_label: str) -> service.Approval | None:
        """
        弹出密码支持对话框并组装 service.Approval。

        用户取消、或密码为空时返回 None（调用方据此不提交任何请求）。
        """
        dialog = ApprovalDialog(self.app.window, action_label=action_label,
                                target_label=target_label,
                                operator_name=f"{self.session.real_name}"
                                              f"（{self.session.username}）")
        self.app.window.wait_window(dialog)

        if dialog.result is None:
            self.app.status.show(f"{action_label}已取消：未输入密码", "warn")
            return None

        password, reason = dialog.result
        if not password.strip():
            warn("提示", "密码为空，操作未提交。", parent=self.app.window)
            return None

        return service.Approval(operator_id=self.session.user_id,
                                operator_name=self.session.username,
                                password=password, reason=reason)

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

        # 删除同样属于敏感改动：先取密码凭据，再走二次确认
        approval = None
        if table_name in APPROVAL_TABLES:
            approval = self._ask_approval(action_label="删除", target_label=label)
            if approval is None:
                return

        def action() -> None:
            service.resource_delete(self.db, table_name, row[pk], approval=approval)
            info("已删除", f"{name}「{label}」已删除。", parent=self.app.window)
            self.on_show()

        self.app.run_guarded(
            action, confirm_title="确认删除",
            confirm_text=f"确定要删除{name}「{label}」吗？\n\n"
                         f"若该记录被房间/订单等数据引用，数据库会拒绝删除。")

    def show_logs(self) -> None:
        """
        变更记录：展示当前资源类型的 price_change_log 留痕。

        每次改动房价 / 房型 / 房间都会记录「旧值 → 新值」、原因与操作人，
        用于回答题目要求 (4) 的「密码支持下才可改动 + 留痕」。
        """
        spec = self._current_spec()
        table_name, name = spec["table"], spec["label"]

        dialog = tk.Toplevel(self.app.window)
        dialog.title(f"{name}变更记录")
        dialog.configure(bg=CS.BG_WHITE)
        dialog.transient(self.app.window)
        dialog.grab_set()

        tk.Label(dialog, text=f"📜 {name}变更记录（最近 100 条）",
                 font=(FONT, 13, "bold"), bg=CS.BG_WHITE,
                 fg=CS.TEXT_PRIMARY).pack(pady=(16, 6))
        tk.Label(dialog, text="对房价 / 房型 / 房间的每次增删改都会留下记录："
                              "对象、字段、旧值、新值、原因与操作人。",
                 font=(FONT, 9), bg=CS.BG_WHITE, fg=CS.TEXT_SECONDARY,
                 wraplength=820).pack(padx=16)

        table = DataTable(dialog, [
            ("changed_at", "时间", 140),
            ("table_label", "资源", 70),
            ("target_label", "对象", 110),
            ("field_label", "字段", 90),
            ("old_value", "旧值", 130),
            ("new_value", "新值", 130),
            ("reason", "原因", 150),
            ("operator_name", "操作人", 90),
        ], height=14)
        table.pack(fill="both", expand=True, padx=16, pady=(8, 0))

        def load() -> None:
            logs = service.list_price_change_logs(self.db, limit=100,
                                                  table=table_name)
            table.set_rows(logs, formatter=lambda item: (
                _fmt_time(item.get("changed_at")),
                item.get("table_label") or "—",
                item.get("target_label") or "—",
                item.get("field_label") or item.get("field_name") or "—",
                _fmt_audit_value(item.get("old_value")),
                _fmt_audit_value(item.get("new_value")),
                item.get("reason") or "—",
                item.get("operator_name") or "—",
            ))
            self.app.status.show(f"{name}：{len(logs)} 条变更记录", "info")

        buttons = tk.Frame(dialog, bg=CS.BG_WHITE)
        buttons.pack(pady=12)
        RoundedButton(buttons, text="🔄 刷新", width=100, height=34, radius=8,
                      command=lambda: self.app.run_guarded(load)).pack(side="left",
                                                                       padx=4)
        RoundedButton(buttons, text="关闭", width=90, height=34, radius=8,
                      color=CS.NEUTRAL, hover_color=CS.NEUTRAL_DARK,
                      command=dialog.destroy).pack(side="left", padx=4)

        from app.ui.widgets import center_window
        center_window(dialog, 880, 520)
        self.app.run_guarded(load)


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
            type_map = {"全部": None, "客房": "room"}
            rows = service.list_orders(self.db, order_type=type_map.get(self.type_combo.get()),
                                       status_category=self.status_combo.get())
            paid = service.paid_order_map(self.db)

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
