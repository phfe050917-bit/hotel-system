"""
登录 / 注册 / 修改密码界面。

相对原实现的变化：
  · 登录走 service.authenticate，密码比对为加盐哈希，不再是明文 SQL 比对；
  · 被禁用的账号会被明确拒绝（原系统没有"禁用"概念）；
  · 注册做了用户名长度、密码长度、两次一致性、手机号格式校验，
    校验失败在对话框内提示而不是弹一堆 messagebox；
  · 新增修改密码入口（原系统完全没有这个功能）；
  · 用户名不存在与密码错误返回同一提示，避免账号枚举。
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from app.config import APP_TITLE
from app.db import Database, DatabaseError
from app import service
from app.service import BusinessError
from app.ui.widgets import (
    CS, FONT, RoundedButton, apply_theme, center_window, error, info, warn,
)


class LoginWindow:
    """登录窗口。验证通过后按角色打开对应主窗口。"""

    def __init__(self, db: Database):
        self.db = db

        self.window = tk.Tk()
        self.window.title(f"{APP_TITLE} - 登录")
        self.window.configure(bg=CS.BG_MAIN)
        self.window.resizable(False, False)
        apply_theme(self.window)

        self._build()
        center_window(self.window, 460, 470)

    def _build(self) -> None:
        tk.Label(self.window, text="🏨 酒店服务预约管理系统", font=(FONT, 19, "bold"),
                 bg=CS.BG_MAIN, fg=CS.TEXT_PRIMARY).pack(pady=(36, 4))
        tk.Label(self.window, text="请登录您的账户", font=(FONT, 11),
                 bg=CS.BG_MAIN, fg=CS.TEXT_SECONDARY).pack(pady=(0, 22))

        form = tk.Frame(self.window, bg=CS.BG_MAIN)
        form.pack()

        def field(label: str, show: str | None = None) -> tk.Entry:
            tk.Label(form, text=label, font=(FONT, 10), bg=CS.BG_MAIN,
                     fg=CS.TEXT_PRIMARY).pack(anchor="w", pady=(6, 0))
            entry = tk.Entry(form, font=(FONT, 12), width=26, bd=0, relief="flat",
                             bg="white", highlightthickness=1,
                             highlightbackground=CS.BORDER, highlightcolor=CS.PRIMARY,
                             show=show, insertbackground=CS.PRIMARY)
            entry.pack(pady=(3, 0), ipady=5)
            return entry

        self.username_entry = field("用户名")
        self.password_entry = field("密码", show="●")

        RoundedButton(self.window, text="登  录", width=210, height=44, radius=10,
                      color=CS.PRIMARY, hover_color=CS.PRIMARY_DARK,
                      font=(FONT, 13, "bold"),
                      command=self._login).pack(pady=(22, 8))

        links = tk.Frame(self.window, bg=CS.BG_MAIN)
        links.pack()
        tk.Button(links, text="注册新账户", font=(FONT, 9), bg=CS.BG_MAIN,
                  fg=CS.PRIMARY, bd=0, cursor="hand2",
                  command=self._open_register).pack(side="left", padx=8)
        tk.Button(links, text="修改密码", font=(FONT, 9), bg=CS.BG_MAIN,
                  fg=CS.TEXT_SECONDARY, bd=0, cursor="hand2",
                  command=self._open_change_password).pack(side="left", padx=8)

        tk.Label(self.window,
                 text="演示账号：admin/admin123 · reception/recep123 · guest01/guest123",
                 font=(FONT, 8), bg=CS.BG_MAIN, fg=CS.TEXT_MUTED).pack(side="bottom", pady=12)

        self.window.bind("<Return>", lambda _e: self._login())
        self.username_entry.focus_set()

    # ------------------------------------------------------------------
    def _login(self) -> None:
        username = self.username_entry.get()
        password = self.password_entry.get()
        try:
            session = service.authenticate(self.db, username, password)
        except BusinessError as exc:
            warn("登录失败", str(exc), parent=self.window)
            self.password_entry.delete(0, "end")
            return
        except DatabaseError as exc:
            error("数据库错误", str(exc), parent=self.window)
            return

        info("登录成功", f"欢迎回来，{session.real_name}！", parent=self.window)
        self.window.destroy()
        self._open_role_window(session)

    def _open_role_window(self, session: service.Session) -> None:
        if session.role == "guest":
            from app.ui.guest import GuestWindow
            window_cls = GuestWindow
        elif session.role == "receptionist":
            from app.ui.reception import ReceptionWindow
            window_cls = ReceptionWindow
        else:
            from app.ui.admin import AdminWindow
            window_cls = AdminWindow
        window_cls(self.db, session).run()

    def _open_register(self) -> None:
        RegisterDialog(self.window, self.db)

    def _open_change_password(self) -> None:
        ChangePasswordDialog(self.window, self.db, session=None)

    def run(self) -> None:
        self.window.mainloop()


class RegisterDialog(tk.Toplevel):
    """注册窗口：校验统一交给 service.register_guest。"""

    def __init__(self, parent, db: Database):
        super().__init__(parent)
        self.db = db
        self.title("注册新账户")
        self.configure(bg=CS.BG_WHITE)
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        apply_theme(self)

        self._error = tk.StringVar()
        self._build()
        center_window(self, 430, 470)

    def _build(self) -> None:
        tk.Label(self, text="注册新账户", font=(FONT, 16, "bold"),
                 bg=CS.BG_WHITE, fg=CS.TEXT_PRIMARY).pack(pady=(22, 14))

        form = tk.Frame(self, bg=CS.BG_WHITE)
        form.pack(padx=44, fill="x")

        def field(label: str, show: str | None = None) -> tk.Entry:
            tk.Label(form, text=label, font=(FONT, 10), bg=CS.BG_WHITE,
                     fg=CS.TEXT_PRIMARY).pack(anchor="w", pady=(5, 0))
            entry = tk.Entry(form, font=(FONT, 11), width=30, bd=0, relief="flat",
                             bg="white", highlightthickness=1,
                             highlightbackground=CS.BORDER, highlightcolor=CS.PRIMARY,
                             show=show, insertbackground=CS.PRIMARY)
            entry.pack(fill="x", pady=(2, 0), ipady=4)
            return entry

        self.entry_username = field("用户名（至少 3 个字符）")
        self.entry_password = field("密码（至少 6 位）", show="●")
        self.entry_confirm = field("确认密码", show="●")
        self.entry_phone = field("手机号（选填，11 位）")
        self.entry_realname = field("真实姓名（选填）")

        tk.Label(self, textvariable=self._error, font=(FONT, 9), bg=CS.BG_WHITE,
                 fg=CS.DANGER, wraplength=350, justify="left").pack(pady=(8, 0))

        buttons = tk.Frame(self, bg=CS.BG_WHITE)
        buttons.pack(pady=12)
        RoundedButton(buttons, text="立即注册", width=150, height=38, radius=9,
                      color=CS.SUCCESS, hover_color=CS.SUCCESS_DARK,
                      command=self._register).pack(side="left", padx=4)
        RoundedButton(buttons, text="返回", width=90, height=38, radius=9,
                      color=CS.NEUTRAL, hover_color=CS.NEUTRAL_DARK,
                      command=self.destroy).pack(side="left", padx=4)

    def _register(self) -> None:
        self._error.set("")
        try:
            user_id = service.register_guest(
                self.db,
                self.entry_username.get(), self.entry_password.get(),
                self.entry_confirm.get(), self.entry_phone.get(),
                self.entry_realname.get(),
            )
        except BusinessError as exc:
            self._error.set(f"⚠ {exc}")
            return
        except DatabaseError as exc:
            self._error.set(f"⚠ 数据库错误：{exc}")
            return

        info("注册成功", f"账号已创建（ID {user_id}），请返回登录。", parent=self.master)
        self.destroy()


class ChangePasswordDialog(tk.Toplevel):
    """
    修改密码。

    session 为 None 时表示从登录页进入：此时要求先输入用户名，
    避免"不登录就能改任意账号密码"这种设计缺陷。
    """

    def __init__(self, parent, db: Database, session: service.Session | None):
        super().__init__(parent)
        self.db = db
        self.session = session
        self.title("修改密码")
        self.configure(bg=CS.BG_WHITE)
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        apply_theme(self)

        self._error = tk.StringVar()
        self._build()
        center_window(self, 400, 360 if session is None else 330)

    def _build(self) -> None:
        tk.Label(self, text="修改密码", font=(FONT, 15, "bold"), bg=CS.BG_WHITE,
                 fg=CS.TEXT_PRIMARY).pack(pady=(22, 12))

        form = tk.Frame(self, bg=CS.BG_WHITE)
        form.pack(padx=40, fill="x")

        def field(label: str) -> tk.Entry:
            tk.Label(form, text=label, font=(FONT, 10), bg=CS.BG_WHITE,
                     fg=CS.TEXT_PRIMARY).pack(anchor="w", pady=(5, 0))
            entry = tk.Entry(form, font=(FONT, 11), width=28, bd=0, relief="flat",
                             bg="white", highlightthickness=1,
                             highlightbackground=CS.BORDER, highlightcolor=CS.PRIMARY,
                             show="●", insertbackground=CS.PRIMARY)
            entry.pack(fill="x", pady=(2, 0), ipady=4)
            return entry

        self.entry_username = field("用户名") if self.session is None else None
        self.entry_old = field("原密码")
        self.entry_new = field("新密码（至少 6 位）")
        self.entry_confirm = field("确认新密码")

        tk.Label(self, textvariable=self._error, font=(FONT, 9), bg=CS.BG_WHITE,
                 fg=CS.DANGER, wraplength=320, justify="left").pack(pady=(8, 0))

        buttons = tk.Frame(self, bg=CS.BG_WHITE)
        buttons.pack(pady=12)
        RoundedButton(buttons, text="确认修改", width=140, height=36, radius=8,
                      color=CS.WARNING, hover_color=CS.WARNING_DARK,
                      command=self._submit).pack(side="left", padx=4)
        RoundedButton(buttons, text="取消", width=80, height=36, radius=8,
                      color=CS.NEUTRAL, hover_color=CS.NEUTRAL_DARK,
                      command=self.destroy).pack(side="left", padx=4)

    def _submit(self) -> None:
        self._error.set("")
        try:
            if self.session is not None:
                service.change_password(self.db, self.entry_old.get(),
                                        self.entry_new.get(), self.entry_confirm.get(),
                                        user_id=self.session.user_id)
            else:
                service.change_password(self.db, self.entry_old.get(),
                                        self.entry_new.get(), self.entry_confirm.get(),
                                        username=self.entry_username.get())
        except BusinessError as exc:
            self._error.set(f"⚠ {exc}")
            return
        except DatabaseError as exc:
            self._error.set(f"⚠ 数据库错误：{exc}")
            return

        info("修改成功", "密码已更新，请使用新密码登录。", parent=self.master)
        self.destroy()
