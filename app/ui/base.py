"""
界面基类。

原系统的三个窗口类各自重复实现了：创建 Tk 根窗口、顶部信息栏、退出登录、
窗口居中，而且在任何回调里一旦出错就把异常栈抛给 Tkinter，
轻则控制台刷屏、重则界面卡死。

BaseWindow 统一处理这些横切关注点：
  · 一个根窗口 + 顶部栏 + 状态栏的骨架；
  · run_guarded()：把业务异常转成友好提示，而不是崩溃；
  · 退出登录时正确销毁窗口并交回登录流程；
  · 会话（user_id / real_name / role）集中存放，子页面通过 self.session 取用。
"""

from __future__ import annotations

import traceback
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable

from app.config import APP_TITLE, WINDOW_SIZE
from app.db import Database, DatabaseError
from app.service import BusinessError, Session
from app.ui.widgets import CS, FONT, RoundedButton, StatusBar, apply_theme, center_window, error, warn


class BaseWindow:
    """所有角色主窗口的公共骨架。"""

    #: 子类覆盖：窗口副标题
    role_title = ""

    def __init__(self, db: Database, session: Session):
        self.db = db
        self.session = session

        #: 界面是否已构建完成。构建期间各标签页会触发首次数据加载，
        #: 此时绝不允许弹出模态对话框（会挂住整个启动流程），
        #: 也避免回调访问到尚未创建的控件。
        self._ready = False

        self.window = tk.Tk()
        self.window.title(f"{APP_TITLE} - {self.role_title} - {session.real_name}")
        self.window.geometry(WINDOW_SIZE)
        self.window.minsize(960, 620)
        self.window.configure(bg=CS.BG_MAIN)

        apply_theme(self.window)

        # 状态栏必须在内容区之前创建：各标签页在 __init__ 里就会触发一次
        # 数据加载，而加载过程会写状态栏。顺序颠倒会让首次加载直接报
        # AttributeError（早期版本踩过这个坑）。
        self.status = StatusBar(self.window)
        self.status.pack(side="bottom", fill="x")

        self._build_top_bar()
        self._build_body()
        self._ready = True

        center_window(self.window)
        self.window.bind("<F5>", lambda _e: self.refresh_current_tab())
        self.window.protocol("WM_DELETE_WINDOW", self._on_close)

        # 内容构建完成后刷新一次当前页，确保首次进入看到的是最新数据
        self.window.after(0, self._initial_refresh)

    def _initial_refresh(self) -> None:
        try:
            self.refresh_current_tab()
        except Exception:                               # noqa: BLE001
            traceback.print_exc()

    # ------------------------------------------------------------------
    #  骨架
    # ------------------------------------------------------------------
    def _build_top_bar(self) -> None:
        bar = tk.Frame(self.window, bg=CS.BG_DARK, height=48)
        bar.pack(fill="x")
        bar.pack_propagate(False)

        tk.Label(bar, text=f"{self.role_icon()} {self.role_title}  |  "
                           f"{self.session.real_name}（{self.session.username}）",
                 font=(FONT, 12), bg=CS.BG_DARK, fg=CS.TEXT_WHITE
                 ).pack(side="left", padx=20, pady=10)

        RoundedButton(bar, text="修改密码", font=(FONT, 9), color=CS.NEUTRAL,
                      hover_color=CS.NEUTRAL_DARK, width=90, height=30, radius=8,
                      command=self._open_change_password).pack(side="right", padx=(6, 20), pady=9)
        RoundedButton(bar, text="退出登录", font=(FONT, 9), color=CS.DANGER,
                      hover_color=CS.DANGER_DARK, width=90, height=30, radius=8,
                      command=self._logout).pack(side="right", pady=9)

    def _build_body(self) -> None:
        """子类在此构建自己的内容区，通常是一个 ttk.Notebook。"""
        self.notebook = ttk.Notebook(self.window)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=(6, 0))

    # ------------------------------------------------------------------
    #  子类可覆盖
    # ------------------------------------------------------------------
    def role_icon(self) -> str:
        return "🏨"

    def refresh_current_tab(self) -> None:
        """F5 刷新当前标签页。子类可覆盖成更精确的实现。"""
        self.status.show("已刷新（F5）")

    def on_close(self) -> None:
        """子类可覆盖以做退出前的清理。"""

    # ------------------------------------------------------------------
    #  异常处理
    # ------------------------------------------------------------------
    def run_guarded(self, action: Callable[[], None],
                    *, success: str | None = None,
                    confirm_text: str | None = None,
                    confirm_title: str = "请确认") -> bool:
        """
        执行一个可能失败的业务动作。

        返回 True 表示成功。业务异常（BusinessError）弹提示并写入状态栏，
        数据库异常同样友好提示 —— 原系统这些异常会直接冲到 Tkinter，
        表现为"点一下按钮程序就崩"。
        """
        if confirm_text and not messagebox.askyesno(confirm_title, confirm_text,
                                                    parent=self.window):
            return False

        def report(message: str, kind: str) -> None:
            bar = getattr(self, "status", None)
            if bar is not None:
                bar.show(message, kind)

        try:
            action()
        except BusinessError as exc:
            report(str(exc), "warn")
            if self._ready:
                warn("操作未完成", str(exc), parent=self.window)
            return False
        except DatabaseError as exc:
            report("数据库操作失败", "error")
            if self._ready:
                error("数据库错误", str(exc), parent=self.window)
            else:
                traceback.print_exc()
            return False
        except Exception as exc:                       # noqa: BLE001
            traceback.print_exc()
            report("发生未预期错误", "error")
            if self._ready:
                error("未预期的错误", f"{exc}\n\n详细信息已输出到控制台。",
                      parent=self.window)
            return False

        if success:
            report(success, "success")
        return True

    def show_error(self, message: str) -> None:
        bar = getattr(self, "status", None)
        if bar is not None:
            bar.show(message, "error")

    # ------------------------------------------------------------------
    #  账号与窗口生命周期
    # ------------------------------------------------------------------
    def _open_change_password(self) -> None:
        from app.ui.login import ChangePasswordDialog
        ChangePasswordDialog(self.window, self.db, self.session)

    def _logout(self) -> None:
        self.window.destroy()
        from app.ui.login import LoginWindow
        LoginWindow(self.db).run()

    def _on_close(self) -> None:
        self.on_close()
        self.window.destroy()

    def run(self) -> None:
        self.window.mainloop()
