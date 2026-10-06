"""客人端主窗口：把六个标签页组装到一起。"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from app.ui.base import BaseWindow
from app.ui.guest_tabs import (
    DiningTab, FitnessTab, LaundryTab, OrdersTab, RoomTab, SpaTab,
)
from app.ui.widgets import CS


class GuestWindow(BaseWindow):
    """客人端：客房预订 / 餐饮 / 健身 / SPA / 洗衣 / 我的订单。"""

    role_title = "客人端"

    def role_icon(self) -> str:
        return "👤"

    def _build_body(self) -> None:
        self.notebook = ttk.Notebook(self.window)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=(6, 0))

        # 订单页需要在任何下单动作后刷新，因此各业务页持有对它的引用
        self.orders_tab = OrdersTab(self.notebook, self)

        self.room_tab = RoomTab(self.notebook, self)
        self.dining_tab = DiningTab(self.notebook, self)
        self.fitness_tab = FitnessTab(self.notebook, self)
        self.spa_tab = SpaTab(self.notebook, self)
        self.laundry_tab = LaundryTab(self.notebook, self)

        for tab, label in (
            (self.room_tab, "  客房预订  "),
            (self.dining_tab, "  餐饮预约  "),
            (self.fitness_tab, "  健身设施  "),
            (self.spa_tab, "  SPA服务  "),
            (self.laundry_tab, "  洗衣服务  "),
            (self.orders_tab, "  我的订单  "),
        ):
            self.notebook.add(tab, text=label)

        # 进入"我的订单"时自动刷新，避免看到过期数据
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

    def _on_tab_changed(self, _event=None) -> None:
        current = self.notebook.nametowidget(self.notebook.select())
        if hasattr(current, "on_show"):
            current.on_show()
        # 切到订单页时，顺带刷新各业务页的列表
        if current is self.orders_tab:
            self.room_tab.on_show()
            self.laundry_tab.on_show()

    def refresh_current_tab(self) -> None:
        current = self.notebook.nametowidget(self.notebook.select())
        if hasattr(current, "on_show"):
            current.on_show()
            self.status.show("已刷新（F5）", "success")

    def notify_order_changed(self) -> None:
        """任一业务页下单成功后调用，统一刷新订单页。"""
        self.orders_tab.refresh()
