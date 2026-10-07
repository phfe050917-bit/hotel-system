"""前台接待端主窗口。"""

from __future__ import annotations

from tkinter import ttk

from app.ui.base import BaseWindow
from app.ui.reception_tabs import (
    CheckInTab, GroupTab, GuestQueryTab, OverviewTab, ReceptionOrdersTab,
    ReviewsTab, RoomsTab,
)


class ReceptionWindow(BaseWindow):
    """前台端：今日概览 / 客房管理 / 团体登记 / 入住·退房 / 客人查询 / 订单管理 / 客户评价。"""

    role_title = "前台接待端"

    def role_icon(self) -> str:
        return "🛎"

    def _build_body(self) -> None:
        self.notebook = ttk.Notebook(self.window)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=(6, 0))

        self.overview_tab = OverviewTab(self.notebook, self)
        self.rooms_tab = RoomsTab(self.notebook, self)
        self.group_tab = GroupTab(self.notebook, self)
        self.checkin_tab = CheckInTab(self.notebook, self)
        self.guest_tab = GuestQueryTab(self.notebook, self)
        self.orders_tab = ReceptionOrdersTab(self.notebook, self)
        self.reviews_tab = ReviewsTab(self.notebook, self)

        for tab, label in (
            (self.overview_tab, "  今日概览  "),
            (self.rooms_tab, "  客房管理  "),
            (self.group_tab, "  团体登记  "),
            (self.checkin_tab, "  入住 / 退房  "),
            (self.guest_tab, "  客人查询  "),
            (self.orders_tab, "  订单管理  "),
            (self.reviews_tab, "  客户评价  "),
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
        """房间/订单/团体数据变化后，通知相关标签页同步。"""
        for tab in (self.overview_tab, self.rooms_tab, self.group_tab,
                    self.checkin_tab, self.guest_tab, self.orders_tab):
            if hasattr(tab, "on_show"):
                tab.on_show()
