"""管理端主窗口。"""

from __future__ import annotations

from tkinter import ttk

from app.ui.base import BaseWindow
from app.ui.admin_tabs import (
    AboutTab, AdminOrdersTab, ResourcesTab, RevenueTab, SettlementReportTab,
    UsersTab,
)


class AdminWindow(BaseWindow):
    """管理端：数据统计 / 结账报表 / 用户管理 / 资源管理 / 订单总览 / 关于。"""

    role_title = "系统管理端"

    def role_icon(self) -> str:
        return "⚙"

    def _build_body(self) -> None:
        self.notebook = ttk.Notebook(self.window)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=(6, 0))

        self.revenue_tab = RevenueTab(self.notebook, self)
        self.settlement_tab = SettlementReportTab(self.notebook, self)
        self.users_tab = UsersTab(self.notebook, self)
        self.resources_tab = ResourcesTab(self.notebook, self)
        self.orders_tab = AdminOrdersTab(self.notebook, self)
        self.about_tab = AboutTab(self.notebook, self)

        for tab, label in (
            (self.revenue_tab, "  数据统计  "),
            (self.settlement_tab, "  结账报表  "),
            (self.users_tab, "  用户管理  "),
            (self.resources_tab, "  资源管理  "),
            (self.orders_tab, "  订单总览  "),
            (self.about_tab, "  关于系统  "),
        ):
            self.notebook.add(tab, text=label)

        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

    def _on_tab_changed(self, _event=None) -> None:
        current = self.notebook.nametowidget(self.notebook.select())
        if hasattr(current, "on_show"):
            current.on_show()

    def refresh_current_tab(self) -> None:
        current = self.notebook.nametowidget(self.notebook.select())
        if hasattr(current, "on_show"):
            current.on_show()
            self.status.show("已刷新（F5）", "success")

    def refresh_all(self) -> None:
        for tab in (self.revenue_tab, self.settlement_tab, self.users_tab,
                    self.resources_tab, self.orders_tab):
            if hasattr(tab, "on_show"):
                tab.on_show()
