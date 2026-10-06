"""管理员端界面"""

import tkinter as tk
from tkinter import ttk, messagebox
from datetime import date, datetime
from styles import RoundedButton, ColorScheme as CS


class AdminWindow:
    """
    管理员端主窗口
    """

    def __init__(self, db, user_id, real_name):
        self.db = db
        self.user_id = user_id
        self.real_name = real_name

        self.window = tk.Tk()
        self.window.title(f"酒店服务预约系统 - 管理员端 - {real_name}")
        self.window.geometry("950x650")
        self.window.configure(bg=CS.BG_MAIN)

        self._create_top_bar()

        self.notebook = ttk.Notebook(self.window)
        self.notebook.pack(fill='both', expand=True, padx=10, pady=(0, 10))

        self.tab_stats = tk.Frame(self.notebook, bg=CS.BG_MAIN)
        self.tab_users = tk.Frame(self.notebook, bg=CS.BG_MAIN)
        self.tab_resources = tk.Frame(self.notebook, bg=CS.BG_MAIN)
        self.tab_orders = tk.Frame(self.notebook, bg=CS.BG_MAIN)

        self.notebook.add(self.tab_stats, text="  数据统计  ")
        self.notebook.add(self.tab_users, text="  用户管理  ")
        self.notebook.add(self.tab_resources, text="  资源管理  ")
        self.notebook.add(self.tab_orders, text="  订单总览  ")

        self._init_stats_tab()
        self._init_users_tab()
        self._init_resources_tab()
        self._init_orders_tab()

        self._center_window()

    def _create_top_bar(self):
        top_frame = tk.Frame(self.window, bg=CS.BG_DARK, height=45)
        top_frame.pack(fill='x')
        top_frame.pack_propagate(False)

        tk.Label(top_frame,
                 text=f"⚙系统管理 - {self.real_name} | 酒店服务预约管理系统",
                 font=("微软雅黑", 12), bg=CS.BG_DARK, fg=CS.TEXT_WHITE
                 ).pack(side='left', padx=20, pady=8)

        RoundedButton(top_frame, text="退出登录",
                  font=("微软雅黑", 9), color='#e74c3c', hover_color='#c0392b',
                  width=100, height=32, radius=8, command=self._logout
                  ).pack(side='right', padx=20, pady=8)

    def _logout(self):
        if messagebox.askyesno("确认退出", "确定要退出登录吗？"):
            self.window.destroy()
            from login_ui import LoginWindow
            LoginWindow(self.db).run()

    def _center_window(self):
        self.window.update_idletasks()
        w = self.window.winfo_width()
        h = self.window.winfo_height()
        x = (self.window.winfo_screenwidth() // 2) - (w // 2)
        y = (self.window.winfo_screenheight() // 2) - (h // 2)
        self.window.geometry(f'{w}x{h}+{x}+{y}')

    def _init_stats_tab(self):
        """数据统计面板"""
        tk.Label(self.tab_stats, text="📊 经营数据统计",
                 font=("微软雅黑", 14, "bold"), bg=CS.BG_MAIN,
                 fg=CS.TEXT_PRIMARY).pack(pady=(15, 20))

        cards_frame = tk.Frame(self.tab_stats, bg=CS.BG_MAIN)
        cards_frame.pack(pady=10)

        # 使用数据类型中的哈希表存储统计数据
        from models import HashTable
        income_ht = HashTable()

        room_income = self.db.query(
            "SELECT COALESCE(SUM(total_price), 0) as total FROM room_order "
            "WHERE status IN ('confirmed','checked_in','checked_out')"
        )
        income_ht.put("客房收入", float(room_income[0]['total']))

        dining_income = self.db.query(
            "SELECT COALESCE(SUM(total_price), 0) as total FROM dining_order "
            "WHERE status IN ('confirmed','dining','completed')"
        )
        income_ht.put("餐饮收入", float(dining_income[0]['total']))

        spa_income = self.db.query(
            "SELECT COALESCE(SUM(ss.price), 0) as total FROM spa_booking sb "
            "JOIN spa_service ss ON sb.service_id=ss.service_id "
            "WHERE sb.status IN ('confirmed','in_progress','completed')"
        )
        income_ht.put("SPA收入", float(spa_income[0]['total']))

        laundry_income = self.db.query(
            "SELECT COALESCE(SUM(total_price), 0) as total FROM laundry_order "
            "WHERE status != 'cancelled'"
        )
        income_ht.put("洗衣收入", float(laundry_income[0]['total']))

        total = sum([income_ht.get(k, 0) for k in ["客房收入", "餐饮收入", "SPA收入", "洗衣收入"]])

        card_data = [
            ("🏨 客房收入", f"¥{income_ht.get('客房收入', 0):,.0f}", "#3498db"),
            ("🍽 餐饮收入", f"¥{income_ht.get('餐饮收入', 0):,.0f}", "#e74c3c"),
            ("💆 SPA收入",  f"¥{income_ht.get('SPA收入', 0):,.0f}", "#9b59b6"),
            ("👕 洗衣收入", f"¥{income_ht.get('洗衣收入', 0):,.0f}", "#1abc9c"),
            ("💰 总收入",   f"¥{total:,.0f}", "#2c3e50"),
        ]

        for i, (label, amount, color) in enumerate(card_data):
            card = tk.Frame(cards_frame, bg=color, width=160, height=80)
            card.grid(row=0, column=i, padx=10, pady=10)
            card.pack_propagate(False)
            tk.Label(card, text=label, font=("微软雅黑", 10),
                     bg=color, fg='white').pack(pady=(12, 2))
            tk.Label(card, text=amount, font=("微软雅黑", 14, "bold"),
                     bg=color, fg='white').pack()

        tk.Label(self.tab_stats, text="📋 详细统计",
                 font=("微软雅黑", 11, "bold"), bg=CS.BG_MAIN,
                 fg=CS.TEXT_PRIMARY).pack(anchor='w', padx=40, pady=(20, 5))

        columns = ("指标", "数值")
        self.stats_tree = ttk.Treeview(self.tab_stats, columns=columns,
                                        show='headings', height=10)
        self.stats_tree.heading("指标", text="指标")
        self.stats_tree.heading("数值", text="数值")
        self.stats_tree.column("指标", width=200)
        self.stats_tree.column("数值", width=200)
        self.stats_tree.pack(padx=40, fill='x')

        room_cnt = self.db.query("SELECT COUNT(*) as cnt FROM room_order")[0]['cnt']
        dining_cnt = self.db.query("SELECT COUNT(*) as cnt FROM dining_order")[0]['cnt']
        fitness_cnt = self.db.query("SELECT COUNT(*) as cnt FROM fitness_booking")[0]['cnt']
        spa_cnt = self.db.query("SELECT COUNT(*) as cnt FROM spa_booking")[0]['cnt']
        laundry_cnt = self.db.query("SELECT COUNT(*) as cnt FROM laundry_order")[0]['cnt']
        user_cnt = self.db.query("SELECT COUNT(*) as cnt FROM user")[0]['cnt']
        review_cnt = self.db.query("SELECT COUNT(*) as cnt FROM review")[0]['cnt']
        available_rooms = self.db.query(
            "SELECT COUNT(*) as cnt FROM room WHERE status='available'")[0]['cnt']
        total_rooms = self.db.query("SELECT COUNT(*) as cnt FROM room")[0]['cnt']

        stats_data = [
            ("系统总用户数", f"{user_cnt} 人"),
            ("客房总数 / 可用", f"{total_rooms} / {available_rooms} 间"),
            ("累计客房订单", f"{room_cnt} 单"),
            ("累计餐饮订单", f"{dining_cnt} 单"),
            ("累计健身预约", f"{fitness_cnt} 次"),
            ("累计SPA预约", f"{spa_cnt} 次"),
            ("累计洗衣订单", f"{laundry_cnt} 单"),
            ("累计评价数", f"{review_cnt} 条"),
        ]

        for stat in stats_data:
            self.stats_tree.insert('', 'end', values=stat)

    def _init_users_tab(self):
        """用户账号管理"""
        tk.Label(self.tab_users, text="👥 用户账号管理",
                 font=("微软雅黑", 14, "bold"), bg=CS.BG_MAIN,
                 fg=CS.TEXT_PRIMARY).pack(pady=(10, 10))

        toolbar = tk.Frame(self.tab_users, bg=CS.BG_MAIN)
        toolbar.pack(fill='x', padx=10)

        tk.Label(toolbar, text="角色筛选：", font=("微软雅黑", 10),
                 bg=CS.BG_MAIN).pack(side='left')
        self.user_role_combo = ttk.Combobox(toolbar, font=("微软雅黑", 10),
                                             width=10, state='readonly')
        self.user_role_combo['values'] = ["全部", "客人", "前台", "管理员"]
        self.user_role_combo.current(0)
        self.user_role_combo.pack(side='left', padx=(0, 15))
        self.user_role_combo.bind('<<ComboboxSelected>>', lambda e: self._load_users())

        RoundedButton(toolbar, text="🔄 刷新", font=("微软雅黑", 10),
                  color='#3498db', hover_color='#2980b9',
                  width=90, height=30, radius=6,
                  command=self._load_users).pack(side='left', padx=(0, 10))

        RoundedButton(toolbar, text="添加用户", font=("微软雅黑", 10),
                  color='#27ae60', hover_color='#219a52',
                  width=90, height=30, radius=6,
                  command=self._add_user).pack(side='right', padx=(5, 0))
        RoundedButton(toolbar, text="重置密码", font=("微软雅黑", 10),
                  color='#f39c12', hover_color='#d68910',
                  width=90, height=30, radius=6,
                  command=self._reset_password).pack(side='right', padx=(5, 0))
        RoundedButton(toolbar, text="禁用/启用", font=("微软雅黑", 10),
                  color='#e74c3c', hover_color='#c0392b',
                  width=90, height=30, radius=6,
                  command=self._toggle_user_status).pack(side='right', padx=(5, 0))

        columns = ("ID", "用户名", "真实姓名", "角色", "手机号", "邮箱", "注册时间")
        self.user_tree = ttk.Treeview(self.tab_users, columns=columns,
                                       show='headings', height=20)
        widths = [50, 100, 80, 70, 110, 150, 130]
        for col, w in zip(columns, widths):
            self.user_tree.heading(col, text=col)
            self.user_tree.column(col, width=w, anchor='center')

        scrollbar = ttk.Scrollbar(self.tab_users, orient='vertical',
                                   command=self.user_tree.yview)
        self.user_tree.configure(yscrollcommand=scrollbar.set)
        self.user_tree.pack(side='left', fill='both', expand=True, padx=10, pady=10)
        scrollbar.pack(side='right', fill='y', pady=10)

        self._load_users()

    def _load_users(self):
        for item in self.user_tree.get_children():
            self.user_tree.delete(item)

        sql = "SELECT * FROM user WHERE 1=1"
        params = []

        role_filter = self.user_role_combo.get()
        role_map = {"客人": "guest", "前台": "receptionist", "管理员": "admin"}
        if role_filter in role_map:
            sql += " AND role = %s"
            params.append(role_map[role_filter])

        sql += " ORDER BY user_id"

        users = self.db.query(sql, params)
        role_labels = {"guest": "客人", "receptionist": "前台", "admin": "管理员"}

        for u in users:
            self.user_tree.insert('', 'end', values=(
                u['user_id'], u['username'], u.get('real_name', ''),
                role_labels.get(u['role'], u['role']),
                u.get('phone', ''), u.get('email', ''),
                str(u['created_at']).split('.')[0] if u['created_at'] else ''
            ))

    def _add_user(self):
        """添加新用户"""
        dialog = tk.Toplevel(self.window)
        dialog.title("添加新用户")
        dialog.geometry("350x380")
        dialog.configure(bg=CS.BG_WHITE)
        dialog.transient(self.window)
        dialog.grab_set()

        tk.Label(dialog, text="添加新用户",
                 font=("微软雅黑", 13, "bold"), bg=CS.BG_WHITE).pack(pady=(15, 15))

        form = tk.Frame(dialog, bg=CS.BG_WHITE)
        form.pack(padx=30)

        fields = [
            ("用户名", "entry_username"),
            ("密码", "entry_password"),
            ("真实姓名", "entry_realname"),
            ("角色", "combo_role"),
        ]

        entries = {}
        for i, (label, name) in enumerate(fields):
            tk.Label(form, text=label + "：", font=("微软雅黑", 10),
                     bg=CS.BG_WHITE).grid(row=i, column=0, sticky='w', pady=8)

            if name == "combo_role":
                combo = ttk.Combobox(form, font=("微软雅黑", 10),
                                      width=18, state='readonly')
                combo['values'] = ["客人", "前台", "管理员"]
                combo.current(0)
                combo.grid(row=i, column=1, padx=(10, 0), pady=8)
                entries[name] = combo
            else:
                entry = tk.Entry(form, font=("微软雅黑", 10), width=20)
                entry.grid(row=i, column=1, padx=(10, 0), pady=8)
                if name == "entry_password":
                    entry.config(show='●')
                entries[name] = entry

        def save():
            username = entries['entry_username'].get().strip()
            password = entries['entry_password'].get().strip()
            realname = entries['entry_realname'].get().strip()
            role_str = entries['combo_role'].get()

            if not username or not password:
                messagebox.showwarning("提示", "用户名和密码不能为空！")
                return

            role_map = {"客人": "guest", "前台": "receptionist", "管理员": "admin"}
            role = role_map[role_str]

            existing = self.db.query_one(
                "SELECT user_id FROM user WHERE username=%s", (username,))
            if existing:
                messagebox.showerror("错误", "用户名已存在！")
                return

            self.db.execute(
                "INSERT INTO user (username, password, real_name, role) VALUES (%s,%s,%s,%s)",
                (username, password, realname, role)
            )
            messagebox.showinfo("成功", f"用户 {username} 添加成功！")
            dialog.destroy()
            self._load_users()

        RoundedButton(dialog, text="确认添加", font=("微软雅黑", 10),
                  color='#27ae60', hover_color='#219a52',
                  width=100, height=32, radius=8,
                  command=save).pack(pady=20)

        self._center_dialog(dialog)

    def _reset_password(self):
        """重置选中用户的密码"""
        selected = self.user_tree.selection()
        if not selected:
            messagebox.showwarning("提示", "请先选择一个用户！")
            return

        item = self.user_tree.item(selected[0])
        values = item['values']
        user_id = values[0]
        username = values[1]

        dialog = tk.Toplevel(self.window)
        dialog.title("重置密码")
        dialog.geometry("320x200")
        dialog.configure(bg=CS.BG_WHITE)
        dialog.transient(self.window)
        dialog.grab_set()

        tk.Label(dialog, text=f"重置 {username} 的密码",
                 font=("微软雅黑", 11), bg=CS.BG_WHITE).pack(pady=(20, 10))

        tk.Label(dialog, text="新密码：", font=("微软雅黑", 10), bg=CS.BG_WHITE).pack()
        pwd_entry = tk.Entry(dialog, font=("微软雅黑", 10), width=20, show='●')
        pwd_entry.pack(pady=10)

        def confirm():
            new_pwd = pwd_entry.get().strip()
            if not new_pwd:
                messagebox.showwarning("提示", "请输入新密码！")
                return
            self.db.execute("UPDATE user SET password=%s WHERE user_id=%s",
                            (new_pwd, user_id))
            messagebox.showinfo("成功", f"用户 {username} 的密码已重置！")
            dialog.destroy()

        RoundedButton(dialog, text="确认重置", font=("微软雅黑", 10),
                  color='#e74c3c', hover_color='#c0392b',
                  width=100, height=32, radius=8,
                  command=confirm).pack(pady=10)

        self._center_dialog(dialog)

    def _toggle_user_status(self):
        """禁用/启用用户（简化实现：删除用户）"""
        selected = self.user_tree.selection()
        if not selected:
            messagebox.showwarning("提示", "请先选择一个用户！")
            return

        item = self.user_tree.item(selected[0])
        values = item['values']
        user_id, username, role = values[0], values[1], values[3]

        if role == "管理员":
            if not messagebox.askyesno("警告", f"确定要删除管理员 {username} 吗？"):
                return
        else:
            if not messagebox.askyesno("确认", f"确定要删除用户 {username} 吗？"):
                return

        self.db.execute("DELETE FROM user WHERE user_id=%s", (user_id,))
        messagebox.showinfo("成功", f"用户 {username} 已删除！")
        self._load_users()

    def _init_resources_tab(self):
        """系统资源管理"""
        tk.Label(self.tab_resources, text="🔧 系统资源管理",
                 font=("微软雅黑", 14, "bold"), bg=CS.BG_MAIN,
                 fg=CS.TEXT_PRIMARY).pack(pady=(10, 15))

        grid = tk.Frame(self.tab_resources, bg=CS.BG_MAIN)
        grid.pack(fill='both', expand=True, padx=10, pady=(0, 10))

        f1 = tk.LabelFrame(grid, text="🏨 房型管理", font=("微软雅黑", 10, "bold"),
                            bg=CS.BG_WHITE, fg=CS.TEXT_PRIMARY)
        f1.grid(row=0, column=0, padx=5, pady=5, sticky='nsew')
        self._resource_list(f1, "room_type",
                            ["类型ID", "房型名称", "价格/晚", "最大入住"],
                            ["type_id", "type_name", "price", "max_occupancy"],
                            extra=lambda r: f"¥{r['price']}")

        f2 = tk.LabelFrame(grid, text="🍽 餐厅管理", font=("微软雅黑", 10, "bold"),
                            bg=CS.BG_WHITE, fg=CS.TEXT_PRIMARY)
        f2.grid(row=0, column=1, padx=5, pady=5, sticky='nsew')
        self._resource_list(f2, "restaurant",
                            ["ID", "餐厅名称", "位置", "营业时间"],
                            ["restaurant_id", "restaurant_name", "location", "open_time"])

        f3 = tk.LabelFrame(grid, text="🏋 健身设施", font=("微软雅黑", 10, "bold"),
                            bg=CS.BG_WHITE, fg=CS.TEXT_PRIMARY)
        f3.grid(row=1, column=0, padx=5, pady=5, sticky='nsew')
        self._resource_list(f3, "fitness_facility",
                            ["ID", "设施名称", "容量", "开放时间"],
                            ["facility_id", "facility_name", "capacity", "open_time"])

        f4 = tk.LabelFrame(grid, text="💆 SPA服务 / 技师", font=("微软雅黑", 10, "bold"),
                            bg=CS.BG_WHITE, fg=CS.TEXT_PRIMARY)
        f4.grid(row=1, column=1, padx=5, pady=5, sticky='nsew')

        f4_inner_left = tk.Frame(f4, bg=CS.BG_WHITE)
        f4_inner_left.pack(side='left', fill='both', expand=True)

        self._resource_list(f4_inner_left, "spa_service",
                            ["ID", "服务名称", "时长", "价格"],
                            ["service_id", "service_name", "duration", "price"],
                            extra=lambda r: f"¥{r['price']}")

        f4_inner_right = tk.Frame(f4, bg=CS.BG_WHITE)
        f4_inner_right.pack(side='right', fill='both', expand=True)

        self._resource_list(f4_inner_right, "technician",
                            ["ID", "技师姓名", "级别", "擅长项目"],
                            ["tech_id", "tech_name", "tech_level", "specialty"])

        # 行列权重（让4个子框架均匀分布）
        grid.grid_rowconfigure(0, weight=1)
        grid.grid_rowconfigure(1, weight=1)
        grid.grid_columnconfigure(0, weight=1)
        grid.grid_columnconfigure(1, weight=1)

    def _resource_list(self, parent, table, columns, fields, extra=None):
        """通用的资源列表显示（支持编辑/添加/删除）"""
        toolbar = tk.Frame(parent, bg=CS.BG_WHITE)
        toolbar.pack(fill='x', padx=2, pady=(2, 0))

        refresh_fn = lambda: self._refresh_resource(tree, table, columns, fields, extra)

        RoundedButton(toolbar, text="编辑", font=("微软雅黑", 9),
                      color=CS.PRIMARY, hover_color=CS.PRIMARY_DARK,
                      width=50, height=24, radius=5,
                      command=lambda: self._edit_resource(tree, table, columns, fields, refresh_fn)
                      ).pack(side='left', padx=2)

        RoundedButton(toolbar, text="添加", font=("微软雅黑", 9),
                      color=CS.SUCCESS, hover_color=CS.SUCCESS_DARK,
                      width=50, height=24, radius=5,
                      command=lambda: self._add_resource(table, columns, fields, refresh_fn)
                      ).pack(side='left', padx=2)

        RoundedButton(toolbar, text="删除", font=("微软雅黑", 9),
                      color=CS.DANGER, hover_color=CS.DANGER_DARK,
                      width=50, height=24, radius=5,
                      command=lambda: self._delete_resource(tree, table, fields)
                      ).pack(side='left', padx=2)

        tree = ttk.Treeview(parent, columns=columns, show='headings', height=5)
        for col, field in zip(columns, fields):
            tree.heading(col, text=col)
            tree.column(col, width=80, anchor='center')

        scrollbar = ttk.Scrollbar(parent, orient='vertical', command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        tree.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')

        refresh_fn()

    def _refresh_resource(self, tree, table, columns, fields, extra=None):
        """刷新资源列表"""
        for item in tree.get_children():
            tree.delete(item)
        data = self.db.query(f"SELECT * FROM {table} ORDER BY {fields[0]}")
        for r in data:
            vals = []
            for f in fields:
                val = r.get(f, '')
                if f == 'price' and extra:
                    val = extra(r)
                vals.append(val)
            tree.insert('', 'end', values=vals)

    def _edit_resource(self, tree, table, columns, fields, refresh_fn):
        """编辑选中的资源项"""
        selected = tree.selection()
        if not selected:
            messagebox.showwarning("提示", "请先选择一条记录！")
            return
        item = tree.item(selected[0])
        vals = item['values']
        id_val = vals[0]
        self._open_resource_dialog(table, columns, fields, refresh_fn,
                                   edit_mode=True, id_val=id_val, old_vals=vals)

    def _add_resource(self, table, columns, fields, refresh_fn):
        """添加新资源"""
        self._open_resource_dialog(table, columns, fields, refresh_fn, edit_mode=False)

    def _delete_resource(self, tree, table, fields):
        """删除选中的资源"""
        selected = tree.selection()
        if not selected:
            messagebox.showwarning("提示", "请先选择一条记录！")
            return
        item = tree.item(selected[0])
        id_val = item['values'][0]
        name_val = item['values'][1]

        if not messagebox.askyesno("确认删除", f"确定要删除「{name_val}」吗？"):
            return
        self.db.execute(f"DELETE FROM {table} WHERE {fields[0]}=%s", (id_val,))
        messagebox.showinfo("成功", f"「{name_val}」已删除！")
        tree.delete(selected[0])

    def _open_resource_dialog(self, table, columns, fields, refresh_fn,
                               edit_mode=False, id_val=None, old_vals=None):
        """资源编辑/添加对话框"""
        dialog = tk.Toplevel(self.window)
        dialog.title("编辑资源" if edit_mode else "添加资源")
        dialog.geometry("360x340")
        dialog.configure(bg=CS.BG_WHITE)
        dialog.transient(self.window)
        dialog.grab_set()

        tk.Label(dialog, text="编辑资源" if edit_mode else "添加新资源",
                 font=("微软雅黑", 13, "bold"), bg=CS.BG_WHITE).pack(pady=(15, 10))

        form = tk.Frame(dialog, bg=CS.BG_WHITE)
        form.pack(padx=30, fill='x')

        entries = {}
        editable_fields = fields[1:]  # 跳过ID列（不可编辑）

        for i, col_name in enumerate(columns[1:]):
            tk.Label(form, text=col_name + "：", font=("微软雅黑", 10),
                     bg=CS.BG_WHITE).grid(row=i, column=0, sticky='e', pady=6, padx=(0, 8))
            entry = tk.Entry(form, font=("微软雅黑", 10), width=22)
            entry.grid(row=i, column=1, sticky='w', pady=6)
            if edit_mode and old_vals:
                entry.insert(0, str(old_vals[i + 1]).replace('¥', ''))
            entries[editable_fields[i]] = entry

        def save():
            vals = [e.get().strip() for e in entries.values()]
            if not all(vals):
                messagebox.showwarning("提示", "请填写所有字段！")
                return
            if edit_mode:
                set_clause = ", ".join(f"{f}=%s" for f in editable_fields)
                self.db.execute(
                    f"UPDATE {table} SET {set_clause} WHERE {fields[0]}=%s",
                    (*vals, id_val)
                )
            else:
                placeholders = ", ".join(["%s"] * len(editable_fields))
                col_names = ", ".join(editable_fields)
                self.db.execute(
                    f"INSERT INTO {table} ({col_names}) VALUES ({placeholders})",
                    vals
                )
            messagebox.showinfo("成功", "保存成功！")
            dialog.destroy()
            refresh_fn()

        RoundedButton(dialog, text="保存", font=("微软雅黑", 11),
                      color=CS.SUCCESS, hover_color=CS.SUCCESS_DARK,
                      width=120, height=36, radius=8,
                      command=save).pack(pady=15)

        self._center_dialog(dialog)

    def _center_dialog(self, dialog):
        dialog.update_idletasks()
        w = dialog.winfo_width()
        h = dialog.winfo_height()
        x = (dialog.winfo_screenwidth() // 2) - (w // 2)
        y = (dialog.winfo_screenheight() // 2) - (h // 2)
        dialog.geometry(f'{w}x{h}+{x}+{y}')

    def _init_orders_tab(self):
        """订单总览（复用前台端的订单管理逻辑）"""
        tk.Label(self.tab_orders, text="📋 全部订单总览",
                 font=("微软雅黑", 14, "bold"), bg=CS.BG_MAIN,
                 fg=CS.TEXT_PRIMARY).pack(pady=(10, 10))

        toolbar = tk.Frame(self.tab_orders, bg=CS.BG_MAIN)
        toolbar.pack(fill='x', padx=10)

        tk.Label(toolbar, text="类型：", font=("微软雅黑", 10),
                 bg=CS.BG_MAIN).pack(side='left')
        self.admin_order_type = ttk.Combobox(toolbar, font=("微软雅黑", 10),
                                              width=8, state='readonly')
        self.admin_order_type['values'] = ["全部", "客房", "餐饮", "健身", "SPA", "洗衣"]
        self.admin_order_type.current(0)
        self.admin_order_type.pack(side='left', padx=(0, 10))
        self.admin_order_type.bind('<<ComboboxSelected>>', lambda e: self._load_admin_orders())

        tk.Label(toolbar, text="状态：", font=("微软雅黑", 10),
                 bg=CS.BG_MAIN).pack(side='left')
        self.admin_order_status = ttk.Combobox(toolbar, font=("微软雅黑", 10),
                                                width=10, state='readonly')
        self.admin_order_status['values'] = ["全部", "进行中", "已完成", "已取消"]
        self.admin_order_status.current(0)
        self.admin_order_status.pack(side='left', padx=(0, 10))
        self.admin_order_status.bind('<<ComboboxSelected>>', lambda e: self._load_admin_orders())

        RoundedButton(toolbar, text="🔄 刷新", font=("微软雅黑", 10),
                  color='#3498db', hover_color='#2980b9',
                  width=90, height=30, radius=6,
                  command=self._load_admin_orders).pack(side='left', padx=(0, 10))

        RoundedButton(toolbar, text="❌ 取消订单", font=("微软雅黑", 10),
                  color='#e74c3c', hover_color='#c0392b',
                  width=90, height=30, radius=6,
                  command=self._admin_cancel_order).pack(side='right')

        columns = ("订单号", "客人", "类型", "详情", "时间", "金额", "状态")
        self.admin_order_tree = ttk.Treeview(self.tab_orders, columns=columns,
                                              show='headings', height=20)
        widths = [110, 80, 60, 220, 130, 80, 80]
        for col, w in zip(columns, widths):
            self.admin_order_tree.heading(col, text=col)
            self.admin_order_tree.column(col, width=w)

        scrollbar = ttk.Scrollbar(self.tab_orders, orient='vertical',
                                   command=self.admin_order_tree.yview)
        self.admin_order_tree.configure(yscrollcommand=scrollbar.set)
        self.admin_order_tree.pack(side='left', fill='both', expand=True, padx=10, pady=10)
        scrollbar.pack(side='right', fill='y', pady=10)

        self._load_admin_orders()

    def _load_admin_orders(self):
        for item in self.admin_order_tree.get_children():
            self.admin_order_tree.delete(item)

        type_filter = self.admin_order_type.get()
        status_filter = self.admin_order_status.get()
        all_rows = []

        queries = [
            ("全部", "客房", """
                SELECT ro.order_id, u.username, '客房' as type,
                    CONCAT(r.room_number, ' / ', ro.check_in_date, '~', ro.check_out_date) as detail,
                    ro.created_at, ro.total_price,
                    CASE ro.status WHEN 'confirmed' THEN '进行中' WHEN 'checked_in' THEN '进行中'
                    WHEN 'checked_out' THEN '已完成' WHEN 'cancelled' THEN '已取消' END as status,
                    'room_order' as tbl, 'order_id' as id_col
                FROM room_order ro JOIN user u ON ro.user_id=u.user_id JOIN room r ON ro.room_id=r.room_id
            """),
            ("全部", "餐饮", """
                SELECT do2.order_id, u.username, '餐饮' as type,
                    CONCAT(r2.restaurant_name, ' / ', do2.dining_date, ' ', do2.dining_time) as detail,
                    do2.created_at, do2.total_price,
                    CASE do2.status WHEN 'confirmed' THEN '进行中' WHEN 'dining' THEN '进行中'
                    WHEN 'completed' THEN '已完成' WHEN 'cancelled' THEN '已取消' END as status,
                    'dining_order' as tbl, 'order_id' as id_col
                FROM dining_order do2 JOIN user u ON do2.user_id=u.user_id JOIN restaurant r2 ON do2.restaurant_id=r2.restaurant_id
            """),
            ("全部", "健身", """
                SELECT fb.booking_id as order_id, u.username, '健身' as type,
                    CONCAT(ff.facility_name, ' / ', fb.booking_date, ' ', fb.time_slot) as detail,
                    fb.created_at, 0 as total_price,
                    CASE fb.status WHEN 'confirmed' THEN '进行中' WHEN 'completed' THEN '已完成'
                    WHEN 'cancelled' THEN '已取消' END as status,
                    'fitness_booking' as tbl, 'booking_id' as id_col
                FROM fitness_booking fb JOIN user u ON fb.user_id=u.user_id
                JOIN fitness_facility ff ON fb.facility_id=ff.facility_id
            """),
            ("全部", "SPA", """
                SELECT sb.booking_id as order_id, u.username, 'SPA' as type,
                    CONCAT(ss.service_name, ' / ', t2.tech_name) as detail,
                    sb.created_at, ss.price as total_price,
                    CASE sb.status WHEN 'confirmed' THEN '进行中' WHEN 'in_progress' THEN '进行中'
                    WHEN 'completed' THEN '已完成' WHEN 'cancelled' THEN '已取消' END as status,
                    'spa_booking' as tbl, 'booking_id' as id_col
                FROM spa_booking sb JOIN user u ON sb.user_id=u.user_id
                JOIN spa_service ss ON sb.service_id=ss.service_id
                JOIN technician t2 ON sb.tech_id=t2.tech_id
            """),
            ("全部", "洗衣", """
                SELECT lo.order_id, u.username, '洗衣' as type,
                    CONCAT(CASE lo.service_type WHEN 'wash' THEN '水洗' WHEN 'dry_clean' THEN '干洗'
                    WHEN 'iron' THEN '熨烫' WHEN 'express_wash' THEN '加急水洗'
                    WHEN 'express_dry' THEN '加急干洗' END, ' / ', lo.room_number) as detail,
                    lo.created_at, lo.total_price,
                    CASE lo.status WHEN 'pending' THEN '进行中' WHEN 'picked_up' THEN '进行中'
                    WHEN 'processing' THEN '进行中' WHEN 'delivered' THEN '已完成'
                    WHEN 'cancelled' THEN '已取消' END as status,
                    'laundry_order' as tbl, 'order_id' as id_col
                FROM laundry_order lo JOIN user u ON lo.user_id=u.user_id
            """),
        ]

        for (all_type, cat, sql) in queries:
            if type_filter in ["全部", cat]:
                rows = self.db.query(sql)
                for r in rows:
                    r['_tbl'] = cat  # 标记表名
                all_rows.extend(rows)

        if status_filter != "全部":
            all_rows = [r for r in all_rows if r['status'] == status_filter]

        all_rows.sort(key=lambda x: str(x['created_at']), reverse=True)

        for r in all_rows:
            tbl = r['_tbl']
            self.admin_order_tree.insert('', 'end', values=(
                r.get('order_id', ''), r.get('username', ''),
                r['type'], r.get('detail', ''),
                str(r['created_at']).split('.')[0] if r['created_at'] else '',
                f"¥{r.get('total_price', 0) or 0}",
                r['status']
            ))

    def _admin_cancel_order(self):
        """管理员取消订单"""
        selected = self.admin_order_tree.selection()
        if not selected:
            messagebox.showwarning("提示", "请先选择一个订单！")
            return

        item = self.admin_order_tree.item(selected[0])
        values = item['values']
        order_id, order_type, status = values[0], values[2], values[6]

        if status != "进行中":
            messagebox.showwarning("提示", "只能取消进行中的订单！")
            return

        table_map = {"客房": "room_order", "餐饮": "dining_order",
                     "健身": "fitness_booking", "SPA": "spa_booking",
                     "洗衣": "laundry_order"}
        id_col = "booking_id" if order_type in ["健身", "SPA"] else "order_id"

        if messagebox.askyesno("确认取消", f"确定要取消订单 {order_id} 吗？"):
            self.db.execute(
                f"UPDATE {table_map[order_type]} SET status='cancelled' WHERE {id_col}=%s",
                (order_id,)
            )
            messagebox.showinfo("成功", f"订单 {order_id} 已取消！")
            self._load_admin_orders()
