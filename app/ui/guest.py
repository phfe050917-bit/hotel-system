"""客人端主窗口：把客房预订与我的订单两个标签页组装到一起。"""

from __future__ import annotations

from tkinter import ttk

from app.ui.base import BaseWindow
from app.ui.guest_tabs import OrdersTab, RoomTab


class GuestWindow(BaseWindow):
    """客人端：客房预订 / 我的订单。"""

    role_title = "客人端"

    def role_icon(self) -> str:
        return "👤"

    def _build_body(self) -> None:
        self.notebook = ttk.Notebook(self.window)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=(6, 0))

        # 订单页需要在任何下单动作后刷新，因此客房页持有对它的引用
        self.orders_tab = OrdersTab(self.notebook, self)
        self.room_tab = RoomTab(self.notebook, self)

        for tab, label in (
            (self.room_tab, "  客房预订  "),
            (self.orders_tab, "  我的订单  "),
        ):
            self.notebook.add(tab, text=label)

        # 进入"我的订单"时自动刷新，避免看到过期数据
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

    def notify_order_changed(self) -> None:
        """任一业务页下单成功后调用，统一刷新订单页。"""
        self.orders_tab.refresh()
