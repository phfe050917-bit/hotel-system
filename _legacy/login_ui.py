"""酒店服务预约系统 - 登录界面"""

import tkinter as tk
from tkinter import messagebox
from styles import RoundedButton, ColorScheme as CS


class LoginWindow:
    """登录窗口，验证用户身份并根据角色打开对应功能界面。"""

    def __init__(self, db):
        """初始化登录窗口"""
        self.db = db

        self.window = tk.Tk()
        self.window.title("酒店服务预约系统 - 登录")
        self.window.geometry("450x420")
        self.window.resizable(False, False)
        self.window.configure(bg=CS.BG_MAIN)

        self._create_widgets()
        self._center_window()

    def _create_widgets(self):
        """创建登录界面的所有控件"""

        title_label = tk.Label(
            self.window,
            text="🏨 酒店服务预约系统",
            font=("微软雅黑", 20, "bold"),
            bg=CS.BG_MAIN,
            fg=CS.TEXT_PRIMARY
        )
        title_label.pack(pady=(40, 5))

        subtitle_label = tk.Label(
            self.window,
            text="请登录您的账户",
            font=("微软雅黑", 12),
            bg=CS.BG_MAIN,
            fg=CS.TEXT_SECONDARY
        )
        subtitle_label.pack(pady=(0, 25))

        username_label = tk.Label(
            self.window,
            text="用户名",
            font=("微软雅黑", 10),
            bg=CS.BG_MAIN,
            fg=CS.TEXT_PRIMARY
        )
        username_label.pack(anchor='w', padx=80)

        self.username_entry = tk.Entry(
            self.window,
            font=("微软雅黑", 12),
            width=28,
            bd=0,
            relief='flat',
            bg='white',
            highlightthickness=1,
            highlightbackground=CS.BORDER,
            highlightcolor=CS.PRIMARY,
            insertbackground=CS.PRIMARY
        )
        self.username_entry.pack(pady=(2, 15), ipady=5)


        password_label = tk.Label(
            self.window,
            text="密码",
            font=("微软雅黑", 10),
            bg=CS.BG_MAIN,
            fg=CS.TEXT_PRIMARY
        )
        password_label.pack(anchor='w', padx=80)

        self.password_entry = tk.Entry(
            self.window,
            font=("微软雅黑", 12),
            width=28,
            bd=0,
            relief='flat',
            bg='white',
            highlightthickness=1,
            highlightbackground=CS.BORDER,
            highlightcolor=CS.PRIMARY,
            show='●',
            insertbackground=CS.PRIMARY
        )
        self.password_entry.pack(pady=(2, 20), ipady=5)

        login_btn = RoundedButton(
            self.window,
            text="登  录",
            width=200, height=44, radius=10,
            color=CS.PRIMARY,
            hover_color=CS.PRIMARY_DARK,
            font=("微软雅黑", 13, "bold"),
            command=self._login
        )
        login_btn.pack(pady=(0, 8))

        register_btn = tk.Button(
            self.window,
            text="还没有账户？立即注册",
            font=("微软雅黑", 9),
            bg=CS.BG_MAIN,
            fg=CS.PRIMARY,
            bd=0,
            cursor='hand2',
            command=self._open_register
        )
        register_btn.pack(pady=(0, 5))

        tip_label = tk.Label(
            self.window,
            text="测试账号: admin/admin123 | reception/recep123 | guest01/guest123",
            font=("微软雅黑", 8),
            bg=CS.BG_MAIN,
            fg=CS.TEXT_MUTED
        )
        tip_label.pack(side='bottom', pady=10)

        self.window.bind('<Return>', lambda event: self._login())

    def _center_window(self):
        """让窗口在屏幕中央显示"""
        self.window.update_idletasks()
        w = self.window.winfo_width()
        h = self.window.winfo_height()
        x = (self.window.winfo_screenwidth() // 2) - (w // 2)
        y = (self.window.winfo_screenheight() // 2) - (h // 2)
        self.window.geometry(f'{w}x{h}+{x}+{y}')

    def _login(self):
        """登录验证：查询数据库验证用户名密码，根据角色打开对应界面"""
        username = self.username_entry.get().strip()
        password = self.password_entry.get().strip()

        if not username or not password:
            messagebox.showwarning("提示", "用户名和密码不能为空！")
            return

        user = self.db.query_one(
            "SELECT * FROM user WHERE username = %s AND password = %s",
            (username, password)
        )

        if user is None:
            messagebox.showerror("登录失败", "用户名或密码错误！")
        else:
            role = user['role']
            user_id = user['user_id']
            real_name = user.get('real_name', username)

            messagebox.showinfo("登录成功", f"欢迎回来，{real_name}！")

            if role == 'guest':
                self._open_guest_window(user_id, real_name)
            elif role == 'receptionist':
                self._open_receptionist_window(user_id, real_name)
            elif role == 'admin':
                self._open_admin_window(user_id, real_name)

    def _open_guest_window(self, user_id, real_name):
        """关闭登录窗口，打开客人端界面"""
        self.window.destroy()
        from guest_ui import GuestWindow
        guest_win = GuestWindow(self.db, user_id, real_name)
        guest_win.run()

    def _open_receptionist_window(self, user_id, real_name):
        """打开前台端界面"""
        self.window.destroy()
        from receptionist_ui import ReceptionistWindow
        rec_win = ReceptionistWindow(self.db, user_id, real_name)
        rec_win.run()

    def _open_admin_window(self, user_id, real_name):
        """打开管理员端界面"""
        self.window.destroy()
        from admin_ui import AdminWindow
        admin_win = AdminWindow(self.db, user_id, real_name)
        admin_win.run()

    def _open_register(self):
        """打开注册窗口"""
        RegisterWindow(self.db, self.window)

    def run(self):
        """启动登录窗口主循环"""
        self.window.mainloop()


class RegisterWindow:
    """注册窗口，新用户在此创建账户"""

    def __init__(self, db, parent):
        """初始化注册窗口"""
        self.db = db

        self.window = tk.Toplevel(parent)
        self.window.title("用户注册")
        self.window.geometry("430x420")
        self.window.resizable(False, False)
        self.window.configure(bg=CS.BG_MAIN)

        self._create_widgets()
        self._center_window()

        self.window.transient(parent)
        self.window.grab_set()

    def _create_widgets(self):
        """创建注册表单控件"""
        tk.Label(
            self.window, text="注册新账户",
            font=("微软雅黑", 16, "bold"), bg=CS.BG_MAIN, fg=CS.TEXT_PRIMARY
        ).pack(pady=(25, 20))

        form_frame = tk.Frame(self.window, bg=CS.BG_MAIN)
        form_frame.pack(padx=50)

        def make_field(row, label_text, show_char=None):
            tk.Label(
                form_frame, text=label_text,
                font=("微软雅黑", 10), bg=CS.BG_MAIN, fg=CS.TEXT_PRIMARY
            ).grid(row=row, column=0, sticky='w', padx=(0, 10), pady=(8, 2))

            entry = tk.Entry(
                form_frame, font=("微软雅黑", 11),
                width=28, bd=0, relief='flat',
                bg='white',
                highlightthickness=1,
                highlightbackground=CS.BORDER,
                highlightcolor=CS.PRIMARY,
                show=show_char, insertbackground=CS.PRIMARY
            )
            entry.grid(row=row, column=1, sticky='w', pady=(8, 2), ipady=3)
            return entry

        self.entry_username = make_field(0, "用户名")
        self.entry_password = make_field(1, "密码", show_char='●')
        self.entry_password2 = make_field(2, "确认密码", show_char='●')
        self.entry_phone = make_field(3, "手机号（选填）")
        self.entry_realname = make_field(4, "真实姓名")

        RoundedButton(
            form_frame, text="立即注册",
            width=200, height=40, radius=10,
            color=CS.SUCCESS, hover_color=CS.SUCCESS_DARK,
            font=("微软雅黑", 11, "bold"),
            command=self._register
        ).grid(row=5, column=0, columnspan=2, pady=(20, 5))

        tk.Button(
            form_frame, text="返回登录",
            font=("微软雅黑", 9),
            bg=CS.BG_MAIN, fg=CS.TEXT_SECONDARY, bd=0,
            cursor='hand2',
            command=self.window.destroy
        ).grid(row=6, column=0, columnspan=2)

    def _center_window(self):
        """居中显示"""
        self.window.update_idletasks()
        w = self.window.winfo_width()
        h = self.window.winfo_height()
        x = (self.window.winfo_screenwidth() // 2) - (w // 2)
        y = (self.window.winfo_screenheight() // 2) - (h // 2)
        self.window.geometry(f'{w}x{h}+{x}+{y}')

    def _register(self):
        """处理注册：验证输入、检查用户名唯一性，写入数据库"""
        username = self.entry_username.get().strip()
        password = self.entry_password.get().strip()
        password2 = self.entry_password2.get().strip()
        phone = self.entry_phone.get().strip()
        realname = self.entry_realname.get().strip()

        if not username or not password:
            messagebox.showwarning("提示", "用户名和密码不能为空！")
            return

        if password != password2:
            messagebox.showerror("错误", "两次输入的密码不一致！")
            return

        existing = self.db.query_one(
            "SELECT user_id FROM user WHERE username = %s", (username,)
        )
        if existing:
            messagebox.showerror("错误", "该用户名已被注册，请换一个！")
            return

        try:
            self.db.execute(
                "INSERT INTO user (username, password, phone, real_name, role) "
                "VALUES (%s, %s, %s, %s, 'guest')",
                (username, password, phone or None, realname or None)
            )
            messagebox.showinfo("成功", "注册成功！请返回登录。")
            self.window.destroy()
        except Exception as e:
            messagebox.showerror("错误", f"注册失败：{e}")