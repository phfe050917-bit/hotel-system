"""
酒店服务预约系统 - 客人端界面，使用 Notebook 选项卡组织客房预订、餐饮预约、健身预约、SPA预约、洗衣预约和订单管理六大功能。
"""

import tkinter as tk
from tkinter import ttk, messagebox
from datetime import date, datetime, timedelta
from styles import RoundedButton, ColorScheme as CS


class GuestWindow:
    """
    客人端主窗口

    使用 Notebook 选项卡组织六大功能模块
    """

    def __init__(self, db, user_id, real_name):
        """
        参数:
            db:       数据库对象
            user_id:  当前登录用户的ID
            real_name: 用户的真实姓名
        """
        self.db = db
        self.user_id = user_id
        self.real_name = real_name

        # 创建主窗口
        self.window = tk.Tk()
        self.window.title(f"酒店服务预约系统 - 客人端 - {real_name}")
        self.window.geometry("900x650")
        self.window.configure(bg=CS.BG_MAIN)

        # 创建顶部信息栏
        self._create_top_bar()

        # 创建选项卡容器
        self.notebook = ttk.Notebook(self.window)
        self.notebook.pack(fill='both', expand=True, padx=10, pady=(0, 10))

        # 创建6个标签页
        self.tab_room = tk.Frame(self.notebook, bg=CS.BG_MAIN)
        self.tab_dining = tk.Frame(self.notebook, bg=CS.BG_MAIN)
        self.tab_fitness = tk.Frame(self.notebook, bg=CS.BG_MAIN)
        self.tab_spa = tk.Frame(self.notebook, bg=CS.BG_MAIN)
        self.tab_laundry = tk.Frame(self.notebook, bg=CS.BG_MAIN)
        self.tab_orders = tk.Frame(self.notebook, bg=CS.BG_MAIN)

        self.notebook.add(self.tab_room, text="  客房预订  ")
        self.notebook.add(self.tab_dining, text="  餐饮预约  ")
        self.notebook.add(self.tab_fitness, text="  健身设施  ")
        self.notebook.add(self.tab_spa, text="  SPA服务  ")
        self.notebook.add(self.tab_laundry, text="  洗衣服务  ")
        self.notebook.add(self.tab_orders, text="  我的订单  ")

        # 初始化各标签页的内容
        self._init_room_tab()
        self._init_dining_tab()
        self._init_fitness_tab()
        self._init_spa_tab()
        self._init_laundry_tab()
        self._init_orders_tab()

        # 居中显示
        self._center_window()

    def _create_top_bar(self):
        """创建顶部蓝色信息栏，显示欢迎信息"""
        top_frame = tk.Frame(self.window, bg=CS.BG_DARK, height=45)
        top_frame.pack(fill='x')
        top_frame.pack_propagate(False)

        tk.Label(
            top_frame,
            text=f"👤 {self.real_name}，您好！欢迎使用酒店服务预约系统",
            font=("微软雅黑", 12),
            bg=CS.BG_DARK, fg=CS.TEXT_WHITE
        ).pack(side='left', padx=20, pady=8)

        RoundedButton(
            top_frame, text="退出登录",
            font=("微软雅黑", 9),
            color='#e74c3c', hover_color='#c0392b',
            width=90, height=30, radius=8,
            command=self._logout
        ).pack(side='right', padx=20, pady=8)

    def _logout(self):
        """退出登录，返回登录界面"""
        if messagebox.askyesno("确认退出", "确定要退出登录吗？"):
            self.window.destroy()
            # 重新打开登录界面
            from login_ui import LoginWindow
            LoginWindow(self.db).run()

    def _center_window(self):
        self.window.update_idletasks()
        w = self.window.winfo_width()
        h = self.window.winfo_height()
        x = (self.window.winfo_screenwidth() // 2) - (w // 2)
        y = (self.window.winfo_screenheight() // 2) - (h // 2)
        self.window.geometry(f'{w}x{h}+{x}+{y}')

    def _init_room_tab(self):
        """初始化客房预订标签页"""

        left_frame = tk.Frame(self.tab_room, bg='white', bd=1, relief='solid')
        left_frame.pack(side='left', fill='y', padx=10, pady=10, ipadx=10, ipady=10)

        right_frame = tk.Frame(self.tab_room, bg=CS.BG_MAIN)
        right_frame.pack(side='left', fill='both', expand=True, padx=10, pady=10)

        tk.Label(left_frame, text="客房查询", font=("微软雅黑", 14, "bold"),
                 bg='white', fg=CS.TEXT_PRIMARY).pack(pady=(10, 15))

        tk.Label(left_frame, text="入住日期", font=("微软雅黑", 10),
                 bg='white').pack(anchor='w')
        today_str = date.today().strftime("%Y-%m-%d")
        tomorrow_str = (date.today() + timedelta(days=1)).strftime("%Y-%m-%d")
        self.room_checkin_entry = tk.Entry(left_frame, font=("微软雅黑", 11), width=18,
            bd=0, relief='flat', bg='white', highlightthickness=1,
            highlightbackground=CS.BORDER, highlightcolor=CS.PRIMARY,
            insertbackground=CS.PRIMARY)
        self.room_checkin_entry.pack(pady=(2, 10), ipady=3)
        self.room_checkin_entry.insert(0, today_str)

        tk.Label(left_frame, text="离店日期", font=("微软雅黑", 10),
                 bg='white').pack(anchor='w')
        self.room_checkout_entry = tk.Entry(left_frame, font=("微软雅黑", 11), width=18,
            bd=0, relief='flat', bg='white', highlightthickness=1,
            highlightbackground=CS.BORDER, highlightcolor=CS.PRIMARY,
            insertbackground=CS.PRIMARY)
        self.room_checkout_entry.pack(pady=(2, 10), ipady=3)
        self.room_checkout_entry.insert(0, tomorrow_str)

        tk.Label(left_frame, text="房型偏好（可选）", font=("微软雅黑", 10),
                 bg='white').pack(anchor='w')
        self.room_type_combo = ttk.Combobox(left_frame, font=("微软雅黑", 10),
                                             width=16, state='readonly')
        self.room_type_combo['values'] = ["全部房型"]
        types = self.db.query("SELECT type_id, type_name FROM room_type")
        for t in types:
            self.room_type_combo['values'] = [*self.room_type_combo['values'], t['type_name']]
        self.room_type_combo.current(0)
        self.room_type_combo.pack(pady=(2, 15))

        RoundedButton(left_frame, text="🔍 查询可用客房",
                  font=("微软雅黑", 11), color='#3498db', hover_color='#2980b9',
                  width=160, height=36, radius=8,
                  command=self._search_rooms).pack(pady=(5, 10))

        tk.Label(left_frame, text="入住人姓名", font=("微软雅黑", 10),
                 bg='white').pack(anchor='w')
        self.room_guest_entry = tk.Entry(left_frame, font=("微软雅黑", 11), width=18,
            bd=0, relief='flat', bg='white', highlightthickness=1,
            highlightbackground=CS.BORDER, highlightcolor=CS.PRIMARY,
            insertbackground=CS.PRIMARY)
        self.room_guest_entry.pack(pady=(2, 10), ipady=3)
        self.room_guest_entry.insert(0, self.real_name)

        RoundedButton(left_frame, text="📅 确认预订",
                  font=("微软雅黑", 11, "bold"), color='#27ae60', hover_color='#219a52',
                  width=160, height=36, radius=8,
                  command=self._book_room).pack(pady=(5, 10))

        tk.Label(right_frame, text="可用客房列表",
                 font=("微软雅黑", 12, "bold"), bg=CS.BG_MAIN).pack(anchor='w', pady=(0, 5))

        columns = ("房间号", "房型", "价格/晚", "楼层", "设施")
        self.room_tree = ttk.Treeview(right_frame, columns=columns,
                                       show='headings', height=12)
        for col in columns:
            self.room_tree.heading(col, text=col)
            self.room_tree.column(col, width=120)

        scrollbar = ttk.Scrollbar(right_frame, orient='vertical',
                                   command=self.room_tree.yview)
        self.room_tree.configure(yscrollcommand=scrollbar.set)

        self.room_tree.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')

    def _search_rooms(self):
        """查询可用房间：排除已预订时段冲突的房间，支持房型筛选"""
        for item in self.room_tree.get_children():
            self.room_tree.delete(item)

        checkin = self.room_checkin_entry.get().strip()
        checkout = self.room_checkout_entry.get().strip()
        type_filter = self.room_type_combo.get()

        if not checkin or not checkout:
            messagebox.showwarning("提示", "请填写入住和离店日期！")
            return

        sql = """
            SELECT r.room_number, rt.type_name, rt.price, r.floor, rt.facilities, r.room_id
            FROM room r
            JOIN room_type rt ON r.type_id = rt.type_id
            WHERE r.status = 'available'
            AND r.room_id NOT IN (
                SELECT ro.room_id FROM room_order ro
                WHERE ro.status IN ('confirmed', 'checked_in')
                AND ro.check_in_date < %s AND ro.check_out_date > %s
            )
        """
        params = [checkout, checkin]

        if type_filter != "全部房型":
            sql += " AND rt.type_name = %s"
            params.append(type_filter)

        rooms = self.db.query(sql, params)

        if not rooms:
            tk.Label(self.tab_room, text="暂无可用客房",
                     font=("微软雅黑", 11), fg='#e74c3c',
                     bg=CS.BG_MAIN).pack(pady=20)
        else:
            for r in rooms:
                self.room_tree.insert('', 'end', values=(
                    r['room_number'], r['type_name'],
                    f"¥{r['price']}", f"{r['floor']}楼",
                    r['facilities']
                ))

    def _book_room(self):
        """预订选中的房间，计算总费用并创建订单"""
        selected = self.room_tree.selection()
        if not selected:
            messagebox.showwarning("提示", "请先在表格中选择一个房间！")
            return

        checkin = self.room_checkin_entry.get().strip()
        checkout = self.room_checkout_entry.get().strip()
        guest_name = self.room_guest_entry.get().strip()

        if not checkin or not checkout or not guest_name:
            messagebox.showwarning("提示", "请填写完整信息！")
            return

        item = self.room_tree.item(selected[0])
        values = item['values']  # [房间号, 房型, ¥价格, 楼层, 设施]
        room_number = values[0]
        price_str = values[2].replace('¥', '')

        d1 = datetime.strptime(checkin, "%Y-%m-%d")
        d2 = datetime.strptime(checkout, "%Y-%m-%d")
        days = (d2 - d1).days
        if days <= 0:
            messagebox.showerror("错误", "离店日期必须晚于入住日期！")
            return

        total_price = float(price_str) * days

        room_info = self.db.query_one(
            "SELECT r.room_id, rt.type_id FROM room r "
            "JOIN room_type rt ON r.type_id = rt.type_id "
            "WHERE r.room_number = %s", (room_number,)
        )

        if not messagebox.askyesno("确认预订",
            f"订单详情：\n"
            f"  房间号：{room_number}\n"
            f"  入住日期：{checkin}\n"
            f"  离店日期：{checkout}\n"
            f"  共 {days} 晚\n"
            f"  总费用：¥{total_price}\n\n"
            f"确认预订？"):
            return

        order_id = self.db.generate_order_id("RM")
        self.db.execute(
            "INSERT INTO room_order (order_id, user_id, room_id, check_in_date, "
            "check_out_date, total_price, guest_name, status) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,'confirmed')",
            (order_id, self.user_id, room_info['room_id'],
             checkin, checkout, total_price, guest_name)
        )

        messagebox.showinfo("成功", f"预订成功！\n订单号：{order_id}")
        self._search_rooms()
        self._load_orders()

    def _init_dining_tab(self):
        """初始化餐饮预约标签页"""
        left_frame = tk.Frame(self.tab_dining, bg='white', bd=1, relief='solid')
        left_frame.pack(side='left', fill='y', padx=10, pady=10, ipadx=10, ipady=10)

        right_frame = tk.Frame(self.tab_dining, bg=CS.BG_MAIN)
        right_frame.pack(side='left', fill='both', expand=True, padx=10, pady=10)

        tk.Label(left_frame, text="餐厅预约", font=("微软雅黑", 14, "bold"),
                 bg='white', fg=CS.TEXT_PRIMARY).pack(pady=(10, 15))

        tk.Label(left_frame, text="选择餐厅", font=("微软雅黑", 10),
                 bg='white').pack(anchor='w')
        self.dining_rest_combo = ttk.Combobox(left_frame, font=("微软雅黑", 10),
                                               width=18, state='readonly')
        self.dining_rest_combo.pack(pady=(2, 10))
        restaurants = self.db.query("SELECT restaurant_id, restaurant_name FROM restaurant")
        self.restaurant_map = {r['restaurant_name']: r['restaurant_id'] for r in restaurants}
        self.dining_rest_combo['values'] = list(self.restaurant_map.keys())
        if self.restaurant_map:
            self.dining_rest_combo.current(0)

        tk.Label(left_frame, text="用餐日期", font=("微软雅黑", 10),
                 bg='white').pack(anchor='w')
        self.dining_date_entry = tk.Entry(left_frame, font=("微软雅黑", 11), width=18,
            bd=0, relief='flat', bg='white', highlightthickness=1,
            highlightbackground=CS.BORDER, highlightcolor=CS.PRIMARY,
            insertbackground=CS.PRIMARY)
        self.dining_date_entry.pack(pady=(2, 10), ipady=3)
        self.dining_date_entry.insert(0, date.today().strftime("%Y-%m-%d"))

        tk.Label(left_frame, text="用餐时间", font=("微软雅黑", 10),
                 bg='white').pack(anchor='w')
        self.dining_time_combo = ttk.Combobox(left_frame, font=("微软雅黑", 10),
                                               width=16, state='readonly')
        self.dining_time_combo['values'] = ["12:00", "12:30", "13:00",
                                             "18:00", "18:30", "19:00", "19:30", "20:00"]
        self.dining_time_combo.current(0)
        self.dining_time_combo.pack(pady=(2, 10))

        tk.Label(left_frame, text="用餐人数", font=("微软雅黑", 10),
                 bg='white').pack(anchor='w')
        self.dining_guest_entry = tk.Entry(left_frame, font=("微软雅黑", 11), width=18,
            bd=0, relief='flat', bg='white', highlightthickness=1,
            highlightbackground=CS.BORDER, highlightcolor=CS.PRIMARY,
            insertbackground=CS.PRIMARY)
        self.dining_guest_entry.pack(pady=(2, 10), ipady=3)
        self.dining_guest_entry.insert(0, "2")

        RoundedButton(left_frame, text="📋 查看菜单",
                  font=("微软雅黑", 11), color='#3498db', hover_color='#2980b9',
                  width=130, height=36, radius=8,
                  command=self._show_menu).pack(pady=(5, 10))

        RoundedButton(left_frame, text="🍽 预订座位",
                  font=("微软雅黑", 11, "bold"), color='#27ae60', hover_color='#219a52',
                  width=130, height=36, radius=8,
                  command=self._book_dining).pack(pady=(5, 10))

        tk.Label(right_frame, text="餐厅菜单",
                 font=("微软雅黑", 12, "bold"), bg=CS.BG_MAIN).pack(anchor='w', pady=(0, 5))

        columns = ("分类", "菜品名称", "价格", "类型", "描述")
        self.dining_tree = ttk.Treeview(right_frame, columns=columns,
                                         show='headings', height=14)
        for col in columns:
            self.dining_tree.heading(col, text=col)
            self.dining_tree.column(col, width=110)

        scrollbar = ttk.Scrollbar(right_frame, orient='vertical',
                                   command=self.dining_tree.yview)
        self.dining_tree.configure(yscrollcommand=scrollbar.set)
        self.dining_tree.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')

    def _show_menu(self):
        """查看所选餐厅的菜单"""
        for item in self.dining_tree.get_children():
            self.dining_tree.delete(item)

        restaurant_name = self.dining_rest_combo.get()
        if not restaurant_name:
            return

        rest_id = self.restaurant_map.get(restaurant_name)
        dishes = self.db.query(
            "SELECT d.dish_name, d.price, d.description, d.is_setmeal, c.category_name "
            "FROM dish d "
            "LEFT JOIN dish_category c ON d.category_id = c.category_id "
            "WHERE d.restaurant_id = %s "
            "ORDER BY c.category_id, d.dish_name",
            (rest_id,)
        )

        for d in dishes:
            dish_type = "套餐" if d['is_setmeal'] else "单点"
            self.dining_tree.insert('', 'end', values=(
                d.get('category_name', '未分类'), d['dish_name'],
                f"¥{d['price']}", dish_type, d.get('description', '')
            ))

    def _book_dining(self):
        """预订餐厅座位"""
        restaurant_name = self.dining_rest_combo.get()
        dining_date = self.dining_date_entry.get().strip()
        dining_time = self.dining_time_combo.get()
        guest_count_str = self.dining_guest_entry.get().strip()

        if not all([restaurant_name, dining_date, dining_time, guest_count_str]):
            messagebox.showwarning("提示", "请填写完整信息！")
            return

        try:
            guest_count = int(guest_count_str)
            if guest_count <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("错误", "人数请填写正整数！")
            return

        rest_id = self.restaurant_map[restaurant_name]

        if not messagebox.askyesno("确认预订",
            f"预订详情：\n  餐厅：{restaurant_name}\n"
            f"  日期：{dining_date}\n  时间：{dining_time}\n"
            f"  人数：{guest_count}位\n\n确认预订？"):
            return

        # 简单分配桌号（实际应该智能分配，这里简化处理）
        table_number = f"{rest_id}号桌"

        order_id = self.db.generate_order_id("DN")
        self.db.execute(
            "INSERT INTO dining_order (order_id, user_id, restaurant_id, table_number, "
            "dining_date, dining_time, guest_count, total_price) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (order_id, self.user_id, rest_id, table_number,
             dining_date, dining_time, guest_count, 0)
        )

        messagebox.showinfo("成功", f"预订成功！\n订单号：{order_id}\n桌位：{table_number}")
        self._load_orders()

    def _init_fitness_tab(self):
        """初始化健身设施标签页"""
        left_frame = tk.Frame(self.tab_fitness, bg='white', bd=1, relief='solid')
        left_frame.pack(side='left', fill='y', padx=10, pady=10, ipadx=10, ipady=10)

        right_frame = tk.Frame(self.tab_fitness, bg=CS.BG_MAIN)
        right_frame.pack(side='left', fill='both', expand=True, padx=10, pady=10)

        tk.Label(left_frame, text="健身设施", font=("微软雅黑", 14, "bold"),
                 bg='white', fg=CS.TEXT_PRIMARY).pack(pady=(10, 15))

        tk.Label(left_frame, text="选择设施", font=("微软雅黑", 10),
                 bg='white').pack(anchor='w')
        self.fit_facility_combo = ttk.Combobox(left_frame, font=("微软雅黑", 10),
                                                width=18, state='readonly')
        self.fit_facility_combo.pack(pady=(2, 10))
        facilities = self.db.query("SELECT facility_id, facility_name FROM fitness_facility")
        self.facility_map = {f['facility_name']: f['facility_id'] for f in facilities}
        self.fit_facility_combo['values'] = list(self.facility_map.keys())
        if self.facility_map:
            self.fit_facility_combo.current(0)

        tk.Label(left_frame, text="预约日期", font=("微软雅黑", 10),
                 bg='white').pack(anchor='w')
        self.fit_date_entry = tk.Entry(left_frame, font=("微软雅黑", 11), width=18,
            bd=0, relief='flat', bg='white', highlightthickness=1,
            highlightbackground=CS.BORDER, highlightcolor=CS.PRIMARY,
            insertbackground=CS.PRIMARY)
        self.fit_date_entry.pack(pady=(2, 10), ipady=3)
        self.fit_date_entry.insert(0, date.today().strftime("%Y-%m-%d"))

        tk.Label(left_frame, text="时间段", font=("微软雅黑", 10),
                 bg='white').pack(anchor='w')
        self.fit_time_combo = ttk.Combobox(left_frame, font=("微软雅黑", 10),
                                            width=16, state='readonly')
        self.fit_time_combo['values'] = [
            "06:00-08:00", "08:00-10:00", "10:00-12:00",
            "14:00-16:00", "16:00-18:00", "18:00-20:00", "20:00-22:00"
        ]
        self.fit_time_combo.current(0)
        self.fit_time_combo.pack(pady=(2, 10))

        tk.Label(left_frame, text="预约人数", font=("微软雅黑", 10),
                 bg='white').pack(anchor='w')
        self.fit_guest_entry = tk.Entry(left_frame, font=("微软雅黑", 11), width=18,
            bd=0, relief='flat', bg='white', highlightthickness=1,
            highlightbackground=CS.BORDER, highlightcolor=CS.PRIMARY,
            insertbackground=CS.PRIMARY)
        self.fit_guest_entry.pack(pady=(2, 15), ipady=3)
        self.fit_guest_entry.insert(0, "1")

        RoundedButton(left_frame, text="🔍 查看使用情况",
                  font=("微软雅黑", 11), color='#3498db', hover_color='#2980b9',
                  width=160, height=36, radius=8,
                  command=self._check_fitness).pack(pady=(5, 5))

        RoundedButton(left_frame, text="🏋 确认预约",
                  font=("微软雅黑", 11, "bold"), color='#27ae60', hover_color='#219a52',
                  width=160, height=36, radius=8,
                  command=self._book_fitness).pack(pady=(5, 10))

        tk.Label(right_frame, text="设施使用情况",
                 font=("微软雅黑", 12, "bold"), bg=CS.BG_MAIN).pack(anchor='w', pady=(0, 5))

        columns = ("设施", "日期", "时段", "已预约/容量", "状态")
        self.fit_tree = ttk.Treeview(right_frame, columns=columns,
                                      show='headings', height=12)
        for col in columns:
            self.fit_tree.heading(col, text=col)
            self.fit_tree.column(col, width=130)

        scrollbar = ttk.Scrollbar(right_frame, orient='vertical',
                                   command=self.fit_tree.yview)
        self.fit_tree.configure(yscrollcommand=scrollbar.set)
        self.fit_tree.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')

        self._check_fitness()

    def _check_fitness(self):
        """查看设施使用情况"""
        for item in self.fit_tree.get_children():
            self.fit_tree.delete(item)

        fit_date = self.fit_date_entry.get().strip()
        if not fit_date:
            return

        # 使用数据结构中的哈希表存储设施信息
        from models import HashTable
        facility_ht = HashTable()

        facilities = self.db.query("SELECT * FROM fitness_facility WHERE status='available'")
        for f in facilities:
            facility_ht.put(f['facility_id'], f)

        time_slots = [
            "06:00-08:00", "08:00-10:00", "10:00-12:00",
            "14:00-16:00", "16:00-18:00", "18:00-20:00", "20:00-22:00"
        ]

        for (fid, fac_info) in facility_ht.get_all():
            for slot in time_slots:
                bookings = self.db.query(
                    "SELECT SUM(guest_count) as total FROM fitness_booking "
                    "WHERE facility_id=%s AND booking_date=%s AND time_slot=%s AND status='confirmed'",
                    (fid, fit_date, slot)
                )
                booked = bookings[0]['total'] or 0
                capacity = fac_info['capacity']
                status = "可预约" if booked < capacity else "已满"

                self.fit_tree.insert('', 'end', values=(
                    fac_info['facility_name'], fit_date, slot,
                    f"{booked}/{capacity}", status
                ))

    def _book_fitness(self):
        """预约健身设施"""
        facility_name = self.fit_facility_combo.get()
        fit_date = self.fit_date_entry.get().strip()
        time_slot = self.fit_time_combo.get()
        guest_count_str = self.fit_guest_entry.get().strip()

        if not all([facility_name, fit_date, time_slot, guest_count_str]):
            messagebox.showwarning("提示", "请填写完整信息！")
            return

        try:
            guest_count = int(guest_count_str)
            if guest_count <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("错误", "人数请填写正整数！")
            return

        facility_id = self.facility_map[facility_name]

        bookings = self.db.query(
            "SELECT SUM(guest_count) as total FROM fitness_booking "
            "WHERE facility_id=%s AND booking_date=%s AND time_slot=%s AND status='confirmed'",
            (facility_id, fit_date, time_slot)
        )
        booked = bookings[0]['total'] or 0
        fac_info = self.db.query_one(
            "SELECT capacity FROM fitness_facility WHERE facility_id=%s", (facility_id,)
        )

        if booked + guest_count > fac_info['capacity']:
            messagebox.showerror("容量不足",
                f"该时段已预约{booked}人，剩余{fac_info['capacity'] - booked}个名额，"
                f"您预约{guest_count}人超出容量！")
            return

        if not messagebox.askyesno("确认预约",
            f"预约：{facility_name}\n日期：{fit_date}\n时段：{time_slot}\n人数：{guest_count}\n\n确认？"):
            return

        booking_id = self.db.generate_order_id("FT")
        self.db.execute(
            "INSERT INTO fitness_booking (booking_id, user_id, facility_id, "
            "booking_date, time_slot, guest_count) VALUES (%s,%s,%s,%s,%s,%s)",
            (booking_id, self.user_id, facility_id, fit_date, time_slot, guest_count)
        )

        messagebox.showinfo("成功", f"预约成功！\n预约号：{booking_id}")
        self._check_fitness()
        self._load_orders()

    def _init_spa_tab(self):
        """初始化SPA预约标签页"""
        left_frame = tk.Frame(self.tab_spa, bg='white', bd=1, relief='solid')
        left_frame.pack(side='left', fill='y', padx=10, pady=10, ipadx=10, ipady=10)

        right_frame = tk.Frame(self.tab_spa, bg=CS.BG_MAIN)
        right_frame.pack(side='left', fill='both', expand=True, padx=10, pady=10)

        tk.Label(left_frame, text="SPA预约", font=("微软雅黑", 14, "bold"),
                 bg='white', fg=CS.TEXT_PRIMARY).pack(pady=(10, 15))

        tk.Label(left_frame, text="选择服务", font=("微软雅黑", 10),
                 bg='white').pack(anchor='w')
        self.spa_service_combo = ttk.Combobox(left_frame, font=("微软雅黑", 10),
                                               width=18, state='readonly')
        self.spa_service_combo.pack(pady=(2, 10))

        services = self.db.query("SELECT service_id, service_name, price, duration FROM spa_service")
        self.spa_service_map = {}
        combo_values = []
        for s in services:
            self.spa_service_map[s['service_name']] = s
            combo_values.append(s['service_name'])
        self.spa_service_combo['values'] = combo_values
        if combo_values:
            self.spa_service_combo.current(0)

        self.spa_detail_label = tk.Label(left_frame, text="",
                                          font=("微软雅黑", 9), bg='white', fg=CS.TEXT_SECONDARY,
                                          wraplength=200, justify='left')
        self.spa_detail_label.pack(pady=(0, 10))

        self.spa_service_combo.bind('<<ComboboxSelected>>', self._on_spa_select)

        tk.Label(left_frame, text="选择技师", font=("微软雅黑", 10),
                 bg='white').pack(anchor='w')
        self.spa_tech_combo = ttk.Combobox(left_frame, font=("微软雅黑", 10),
                                            width=18, state='readonly')
        self.spa_tech_combo.pack(pady=(2, 10))
        technicians = self.db.query(
            "SELECT tech_id, tech_name, specialty, tech_level, rating FROM technician WHERE status='available'"
        )
        self.tech_map = {}
        tech_values = []
        for t in technicians:
            self.tech_map[t['tech_name']] = t
            tech_values.append(f"{t['tech_name']} ({t['tech_level']})")
        self.spa_tech_combo['values'] = tech_values
        if tech_values:
            self.spa_tech_combo.current(0)

        tk.Label(left_frame, text="预约日期", font=("微软雅黑", 10),
                 bg='white').pack(anchor='w')
        self.spa_date_entry = tk.Entry(left_frame, font=("微软雅黑", 11), width=18,
            bd=0, relief='flat', bg='white', highlightthickness=1,
            highlightbackground=CS.BORDER, highlightcolor=CS.PRIMARY,
            insertbackground=CS.PRIMARY)
        self.spa_date_entry.pack(pady=(2, 10), ipady=3)
        self.spa_date_entry.insert(0, date.today().strftime("%Y-%m-%d"))

        tk.Label(left_frame, text="预约时间", font=("微软雅黑", 10),
                 bg='white').pack(anchor='w')
        self.spa_time_combo = ttk.Combobox(left_frame, font=("微软雅黑", 10),
                                            width=16, state='readonly')
        self.spa_time_combo['values'] = [
            "09:00", "10:00", "11:00", "13:00", "14:00",
            "15:00", "16:00", "17:00", "18:00", "19:00"
        ]
        self.spa_time_combo.current(0)
        self.spa_time_combo.pack(pady=(2, 15))

        RoundedButton(left_frame, text="💆 确认预约",
                  font=("微软雅黑", 11, "bold"), color='#9b59b6', hover_color='#8e44ad',
                  width=160, height=36, radius=8,
                  command=self._book_spa).pack(pady=(5, 10))

        tk.Label(right_frame, text="SPA服务项目",
                 font=("微软雅黑", 12, "bold"), bg=CS.BG_MAIN).pack(anchor='w', pady=(0, 5))

        columns = ("服务名称", "时长(分钟)", "价格", "描述")
        self.spa_tree = ttk.Treeview(right_frame, columns=columns,
                                      show='headings', height=12)
        for col in columns:
            self.spa_tree.heading(col, text=col)
            self.spa_tree.column(col, width=130)

        scrollbar = ttk.Scrollbar(right_frame, orient='vertical',
                                   command=self.spa_tree.yview)
        self.spa_tree.configure(yscrollcommand=scrollbar.set)
        self.spa_tree.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')

        self._load_spa_services()

        self._on_spa_select()

    def _load_spa_services(self):
        """加载SPA服务到右侧表格"""
        for item in self.spa_tree.get_children():
            self.spa_tree.delete(item)
        services = self.db.query("SELECT * FROM spa_service")
        for s in services:
            self.spa_tree.insert('', 'end', values=(
                s['service_name'], s['duration'], f"¥{s['price']}",
                s.get('description', '')
            ))

    def _on_spa_select(self, event=None):
        """选择SPA服务时更新详情显示"""
        service_name = self.spa_service_combo.get()
        if service_name in self.spa_service_map:
            s = self.spa_service_map[service_name]
            self.spa_detail_label.config(
                text=f"时长: {s['duration']}分钟\n价格: ¥{s['price']}\n"
                     f"描述: {s.get('description', '暂无')}"
            )

    def _book_spa(self):
        """预约SPA服务"""
        service_name = self.spa_service_combo.get()
        tech_str = self.spa_tech_combo.get()
        spa_date = self.spa_date_entry.get().strip()
        spa_time = self.spa_time_combo.get()

        if not all([service_name, tech_str, spa_date, spa_time]):
            messagebox.showwarning("提示", "请填写完整信息！")
            return

        tech_name = tech_str.split(' (')[0]

        service_info = self.spa_service_map.get(service_name)
        tech_info = self.tech_map.get(tech_name)

        if not service_info or not tech_info:
            return

        if not messagebox.askyesno("确认预约",
            f"服务：{service_name}\n技师：{tech_name}\n"
            f"日期：{spa_date}\n时间：{spa_time}\n价格：¥{service_info['price']}\n\n确认？"):
            return

        booking_id = self.db.generate_order_id("SP")
        self.db.execute(
            "INSERT INTO spa_booking (booking_id, user_id, service_id, tech_id, "
            "booking_date, booking_time) VALUES (%s,%s,%s,%s,%s,%s)",
            (booking_id, self.user_id, service_info['service_id'],
             tech_info['tech_id'], spa_date, spa_time)
        )

        messagebox.showinfo("成功", f"SPA预约成功！\n预约号：{booking_id}")
        self._load_orders()

    def _init_laundry_tab(self):
        """初始化洗衣服务标签页，使用队列数据结构管理请求顺序"""
        left_frame = tk.Frame(self.tab_laundry, bg='white', bd=1, relief='solid')
        left_frame.pack(side='left', fill='y', padx=10, pady=10, ipadx=10, ipady=10)

        right_frame = tk.Frame(self.tab_laundry, bg=CS.BG_MAIN)
        right_frame.pack(side='left', fill='both', expand=True, padx=10, pady=10)

        tk.Label(left_frame, text="洗衣服务", font=("微软雅黑", 14, "bold"),
                 bg='white', fg=CS.TEXT_PRIMARY).pack(pady=(10, 15))

        tk.Label(left_frame, text="服务类型", font=("微软雅黑", 10),
                 bg='white').pack(anchor='w')
        self.laundry_type_combo = ttk.Combobox(left_frame, font=("微软雅黑", 10),
                                                width=18, state='readonly')

        self.laundry_prices = {
            "普通水洗":    ("wash", 25),
            "普通干洗":    ("dry_clean", 45),
            "熨烫服务":    ("iron", 20),
            "加急水洗":    ("express_wash", 50),
            "加急干洗":    ("express_dry", 80),
        }
        self.laundry_type_combo['values'] = list(self.laundry_prices.keys())
        self.laundry_type_combo.current(0)
        self.laundry_type_combo.pack(pady=(2, 10))
        self.laundry_type_combo.bind('<<ComboboxSelected>>', self._calc_laundry_price)

        tk.Label(left_frame, text="衣物数量（件）", font=("微软雅黑", 10),
                 bg='white').pack(anchor='w')
        self.laundry_count_entry = tk.Entry(left_frame, font=("微软雅黑", 11), width=18,
            bd=0, relief='flat', bg='white', highlightthickness=1,
            highlightbackground=CS.BORDER, highlightcolor=CS.PRIMARY,
            insertbackground=CS.PRIMARY)
        self.laundry_count_entry.pack(pady=(2, 10), ipady=3)
        self.laundry_count_entry.insert(0, "1")
        self.laundry_count_entry.bind('<KeyRelease>', self._calc_laundry_price)

        self.laundry_price_label = tk.Label(left_frame, text="预估费用：¥25",
                                             font=("微软雅黑", 11, "bold"),
                                             bg='white', fg='#e74c3c')
        self.laundry_price_label.pack(pady=(5, 10))

        tk.Label(left_frame, text="您的房间号", font=("微软雅黑", 10),
                 bg='white').pack(anchor='w')
        self.laundry_room_entry = tk.Entry(left_frame, font=("微软雅黑", 11), width=18,
            bd=0, relief='flat', bg='white', highlightthickness=1,
            highlightbackground=CS.BORDER, highlightcolor=CS.PRIMARY,
            insertbackground=CS.PRIMARY)
        self.laundry_room_entry.pack(pady=(2, 10), ipady=3)

        tk.Label(left_frame, text="预约取衣时间", font=("微软雅黑", 10),
                 bg='white').pack(anchor='w')
        self.laundry_pickup_combo = ttk.Combobox(left_frame, font=("微软雅黑", 10),
                                                  width=16, state='readonly')
        self.laundry_pickup_combo['values'] = [
            "立即取衣", "09:00", "10:00", "11:00", "14:00", "15:00", "16:00", "17:00"
        ]
        self.laundry_pickup_combo.current(0)
        self.laundry_pickup_combo.pack(pady=(2, 15))

        RoundedButton(left_frame, text="👕 确认预约",
                  font=("微软雅黑", 11, "bold"), color='#e67e22', hover_color='#d35400',
                  width=160, height=36, radius=8,
                  command=self._book_laundry).pack(pady=(5, 10))

        tk.Label(right_frame, text="洗衣服务价格表",
                 font=("微软雅黑", 12, "bold"), bg=CS.BG_MAIN).pack(anchor='w', pady=(0, 5))

        columns = ("服务类型", "单价(元/件)", "预计完成时间")
        self.laundry_tree = ttk.Treeview(right_frame, columns=columns,
                                          show='headings', height=8)
        for col in columns:
            self.laundry_tree.heading(col, text=col)
            self.laundry_tree.column(col, width=150)

        laundry_data = [
            ("普通水洗", "25", "当日18:00前"),
            ("普通干洗", "45", "次日12:00前"),
            ("熨烫服务", "20", "当日16:00前"),
            ("加急水洗", "50", "4小时内"),
            ("加急干洗", "80", "6小时内"),
        ]
        for item in laundry_data:
            self.laundry_tree.insert('', 'end', values=item)

        self.laundry_tree.pack(fill='both', expand=True)

        self._init_laundry_queue(right_frame)

    def _init_laundry_queue(self, parent):
        """初始化洗衣请求队列显示区域"""
        queue_frame = tk.LabelFrame(parent, text="📋 洗衣请求队列（先预约先处理）",
                                     font=("微软雅黑", 10, "bold"),
                                     bg=CS.BG_MAIN, fg=CS.TEXT_PRIMARY)
        queue_frame.pack(fill='both', expand=True, pady=10)

        columns = ("序号", "订单号", "房间号", "服务类型", "数量", "状态")
        self.queue_tree = ttk.Treeview(queue_frame, columns=columns,
                                        show='headings', height=5)
        for col in columns:
            self.queue_tree.heading(col, text=col)
            self.queue_tree.column(col, width=100)

        scrollbar = ttk.Scrollbar(queue_frame, orient='vertical',
                                   command=self.queue_tree.yview)
        self.queue_tree.configure(yscrollcommand=scrollbar.set)
        self.queue_tree.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')

        self._refresh_laundry_queue()

    def _refresh_laundry_queue(self):
        """刷新洗衣请求队列"""
        for item in self.queue_tree.get_children():
            self.queue_tree.delete(item)

        orders = self.db.query(
            "SELECT * FROM laundry_order WHERE status != 'cancelled' "
            "ORDER BY created_at ASC"
        )
        for i, o in enumerate(orders, 1):
            type_name = {
                'wash': '普通水洗', 'dry_clean': '普通干洗', 'iron': '熨烫',
                'express_wash': '加急水洗', 'express_dry': '加急干洗'
            }.get(o['service_type'], o['service_type'])

            status_name = {
                'pending': '等待取衣', 'picked_up': '已取衣',
                'processing': '洗涤中', 'delivered': '已送达'
            }.get(o['status'], o['status'])

            self.queue_tree.insert('', 'end', values=(
                i, o['order_id'], o['room_number'], type_name,
                o['item_count'], status_name
            ))

    def _calc_laundry_price(self, event=None):
        """计算洗衣预估费用"""
        service_name = self.laundry_type_combo.get()
        count_str = self.laundry_count_entry.get().strip()

        if service_name not in self.laundry_prices:
            return

        try:
            count = int(count_str) if count_str else 0
        except ValueError:
            count = 0

        unit_price = self.laundry_prices[service_name][1]
        total = unit_price * count
        self.laundry_price_label.config(text=f"预估费用：¥{total}")

    def _book_laundry(self):
        """预约洗衣服务"""
        service_name = self.laundry_type_combo.get()
        count_str = self.laundry_count_entry.get().strip()
        room_number = self.laundry_room_entry.get().strip()

        if not all([service_name, count_str, room_number]):
            messagebox.showwarning("提示", "请填写完整信息（包括房间号）！")
            return

        try:
            count = int(count_str)
            if count <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("错误", "衣物数量请填写正整数！")
            return

        service_type = self.laundry_prices[service_name][0]
        unit_price = self.laundry_prices[service_name][1]
        total_price = unit_price * count

        if not messagebox.askyesno("确认预约",
            f"洗衣详情：\n  服务类型：{service_name}\n"
            f"  衣物数量：{count}件\n  房间号：{room_number}\n"
            f"  总费用：¥{total_price}\n\n确认预约？"):
            return

        order_id = self.db.generate_order_id("LN")
        self.db.execute(
            "INSERT INTO laundry_order (order_id, user_id, service_type, "
            "item_count, total_price, room_number) VALUES (%s,%s,%s,%s,%s,%s)",
            (order_id, self.user_id, service_type, count, total_price, room_number)
        )

        messagebox.showinfo("成功", f"洗衣预约成功！\n订单号：{order_id}")
        self._refresh_laundry_queue()
        self._load_orders()

    def _init_orders_tab(self):
        """初始化订单管理标签页"""
        filter_frame = tk.Frame(self.tab_orders, bg=CS.BG_MAIN)
        filter_frame.pack(fill='x', padx=10, pady=10)

        tk.Label(filter_frame, text="订单类型：", font=("微软雅黑", 10),
                 bg=CS.BG_MAIN).pack(side='left', padx=(0, 5))

        self.order_type_combo = ttk.Combobox(filter_frame, font=("微软雅黑", 10),
                                              width=10, state='readonly')
        self.order_type_combo['values'] = ["全部", "客房", "餐饮", "健身", "SPA", "洗衣"]
        self.order_type_combo.current(0)
        self.order_type_combo.pack(side='left', padx=(0, 15))
        self.order_type_combo.bind('<<ComboboxSelected>>', lambda e: self._load_orders())

        tk.Label(filter_frame, text="状态：", font=("微软雅黑", 10),
                 bg=CS.BG_MAIN).pack(side='left', padx=(0, 5))

        self.order_status_combo = ttk.Combobox(filter_frame, font=("微软雅黑", 10),
                                                width=10, state='readonly')
        self.order_status_combo['values'] = ["全部", "进行中", "已完成", "已取消"]
        self.order_status_combo.current(0)
        self.order_status_combo.pack(side='left', padx=(0, 15))
        self.order_status_combo.bind('<<ComboboxSelected>>', lambda e: self._load_orders())

        tk.Button(filter_frame, text="🔄 刷新",
                  font=("微软雅黑", 10), bg=CS.PRIMARY, fg=CS.TEXT_WHITE,
                  bd=0, cursor='hand2',
                  command=self._load_orders).pack(side='left', padx=(0, 10))

        columns = ("订单号", "类型", "详情", "时间", "金额", "状态", "操作")
        self.order_tree = ttk.Treeview(self.tab_orders, columns=columns,
                                        show='headings', height=18)
        widths = [120, 60, 200, 140, 80, 80, 100]
        for col, w in zip(columns, widths):
            self.order_tree.heading(col, text=col)
            self.order_tree.column(col, width=w)

        scrollbar = ttk.Scrollbar(self.tab_orders, orient='vertical',
                                   command=self.order_tree.yview)
        self.order_tree.configure(yscrollcommand=scrollbar.set)
        self.order_tree.pack(side='left', fill='both', expand=True, padx=10, pady=(0, 10))
        scrollbar.pack(side='right', fill='y', pady=(0, 10))

        self.order_tree.bind('<Double-1>', self._order_detail)

        btn_frame = tk.Frame(self.tab_orders, bg=CS.BG_MAIN)
        btn_frame.pack(fill='x', padx=10, pady=(0, 10))

        RoundedButton(btn_frame, text="取消订单",
                  font=("微软雅黑", 10), color='#e74c3c', hover_color='#c0392b',
                  width=90, height=30, radius=8,
                  command=self._cancel_order).pack(side='left', padx=(0, 10))

        RoundedButton(btn_frame, text="评价服务",
                  font=("微软雅黑", 10), color='#f39c12', hover_color='#d68910',
                  width=90, height=30, radius=8,
                  command=self._review_order).pack(side='left', padx=(0, 10))

        self._load_orders()

    def _load_orders(self):
        """加载用户的所有订单（合并5张订单表的数据）"""
        for item in self.order_tree.get_children():
            self.order_tree.delete(item)

        type_filter = self.order_type_combo.get()
        status_filter = self.order_status_combo.get()

        all_orders = []

        # 使用二叉搜索树（BST）存储订单，按时间排序
        from models import BinarySearchTree
        order_bst = BinarySearchTree()

        if type_filter in ["全部", "客房"]:
            orders = self.db.query(
                "SELECT ro.order_id, '客房' as type, CONCAT(r.room_number, ' / ', "
                "ro.check_in_date, '~', ro.check_out_date) as detail, "
                "ro.created_at, ro.total_price, "
                "CASE ro.status WHEN 'confirmed' THEN '进行中' WHEN 'checked_in' THEN '进行中' "
                "WHEN 'checked_out' THEN '已完成' WHEN 'cancelled' THEN '已取消' END as status "
                "FROM room_order ro JOIN room r ON ro.room_id=r.room_id "
                "WHERE ro.user_id=%s", (self.user_id,)
            )
            for o in orders:
                o['type_raw'], o['table'] = '客房', 'room_order'
                all_orders.append(o)

        if type_filter in ["全部", "餐饮"]:
            orders = self.db.query(
                "SELECT do2.order_id, '餐饮' as type, CONCAT(r2.restaurant_name, ' / ', "
                "do2.dining_date, ' ', do2.dining_time) as detail, do2.created_at, do2.total_price, "
                "CASE do2.status WHEN 'confirmed' THEN '进行中' WHEN 'dining' THEN '进行中' "
                "WHEN 'completed' THEN '已完成' WHEN 'cancelled' THEN '已取消' END as status "
                "FROM dining_order do2 JOIN restaurant r2 ON do2.restaurant_id=r2.restaurant_id "
                "WHERE do2.user_id=%s", (self.user_id,)
            )
            for o in orders:
                o['type_raw'], o['table'] = '餐饮', 'dining_order'
                all_orders.append(o)

        if type_filter in ["全部", "健身"]:
            orders = self.db.query(
                "SELECT fb.booking_id as order_id, '健身' as type, CONCAT(ff.facility_name, ' / ', "
                "fb.booking_date, ' ', fb.time_slot) as detail, fb.created_at, 0 as total_price, "
                "CASE fb.status WHEN 'confirmed' THEN '进行中' WHEN 'completed' THEN '已完成' "
                "WHEN 'cancelled' THEN '已取消' END as status "
                "FROM fitness_booking fb JOIN fitness_facility ff ON fb.facility_id=ff.facility_id "
                "WHERE fb.user_id=%s", (self.user_id,)
            )
            for o in orders:
                o['type_raw'], o['table'] = '健身', 'fitness_booking'
                all_orders.append(o)

        if type_filter in ["全部", "SPA"]:
            orders = self.db.query(
                "SELECT sb.booking_id as order_id, 'SPA' as type, CONCAT(ss.service_name, ' / ', "
                "t2.tech_name, ' / ', sb.booking_date, ' ', sb.booking_time) as detail, "
                "sb.created_at, ss.price as total_price, "
                "CASE sb.status WHEN 'confirmed' THEN '进行中' WHEN 'in_progress' THEN '进行中' "
                "WHEN 'completed' THEN '已完成' WHEN 'cancelled' THEN '已取消' END as status "
                "FROM spa_booking sb "
                "JOIN spa_service ss ON sb.service_id=ss.service_id "
                "JOIN technician t2 ON sb.tech_id=t2.tech_id "
                "WHERE sb.user_id=%s", (self.user_id,)
            )
            for o in orders:
                o['type_raw'], o['table'] = 'SPA', 'spa_booking'
                all_orders.append(o)

        if type_filter in ["全部", "洗衣"]:
            orders = self.db.query(
                "SELECT lo.order_id, '洗衣' as type, CONCAT("
                "CASE lo.service_type WHEN 'wash' THEN '普通水洗' WHEN 'dry_clean' THEN '普通干洗' "
                "WHEN 'iron' THEN '烫' WHEN 'express_wash' THEN '加急水洗' "
                "WHEN 'express_dry' THEN '加急干洗' END, ' / ', lo.room_number) as detail, "
                "lo.created_at, lo.total_price, "
                "CASE lo.status WHEN 'pending' THEN '进行中' WHEN 'picked_up' THEN '进行中' "
                "WHEN 'processing' THEN '进行中' WHEN 'delivered' THEN '已完成' "
                "WHEN 'cancelled' THEN '已取消' END as status "
                "FROM laundry_order lo WHERE lo.user_id=%s", (self.user_id,)
            )
            for o in orders:
                o['type_raw'], o['table'] = '洗衣', 'laundry_order'
                all_orders.append(o)

        if status_filter != "全部":
            all_orders = [o for o in all_orders if o['status'] == status_filter]

        import time
        for o in all_orders:
            # 用created_at字符串转换时间戳作为key
            try:
                ts = datetime.strptime(str(o['created_at']), "%Y-%m-%d %H:%M:%S").timestamp()
            except:
                ts = time.time()
            order_bst.insert(ts, o)

        # 中序遍历得到按时间排序的订单
        sorted_orders = order_bst.inorder_traversal()

        for o in sorted_orders:
            self.order_tree.insert('', 'end', values=(
                o['order_id'], o['type'], o['detail'],
                str(o['created_at']).split('.')[0] if o['created_at'] else '',
                f"¥{o['total_price'] or 0}", o['status'],
                "可操作" if o['status'] == '进行中' else ""
            ))

    def _order_detail(self, event=None):
        """双击查看订单详情"""
        selected = self.order_tree.selection()
        if not selected:
            return
        item = self.order_tree.item(selected[0])
        values = item['values']
        messagebox.showinfo("订单详情",
            f"订单号：{values[0]}\n类型：{values[1]}\n"
            f"详情：{values[2]}\n时间：{values[3]}\n"
            f"金额：{values[4]}\n状态：{values[5]}")

    def _cancel_order(self):
        """取消选中的订单"""
        selected = self.order_tree.selection()
        if not selected:
            messagebox.showwarning("提示", "请先选择一个订单！")
            return

        item = self.order_tree.item(selected[0])
        values = item['values']
        order_id, order_type, status = values[0], values[1], values[5]

        if status != "进行中":
            messagebox.showwarning("提示", "只能取消进行中的订单！")
            return

        if not messagebox.askyesno("确认取消", f"确定要取消订单 {order_id} 吗？"):
            return

        table_map = {
            "客房": ("room_order", "order_id"),
            "餐饮": ("dining_order", "order_id"),
            "健身": ("fitness_booking", "booking_id"),
            "SPA": ("spa_booking", "booking_id"),
            "洗衣": ("laundry_order", "order_id"),
        }

        table_info = table_map.get(order_type)
        if table_info:
            self.db.execute(
                f"UPDATE {table_info[0]} SET status='cancelled' "
                f"WHERE {table_info[1]}=%s", (order_id,)
            )
            messagebox.showinfo("成功", f"订单 {order_id} 已取消！")
            self._load_orders()

    def _review_order(self):
        """对已完成的订单进行评价"""
        selected = self.order_tree.selection()
        if not selected:
            messagebox.showwarning("提示", "请先选择一个已完成的订单！")
            return

        item = self.order_tree.item(selected[0])
        values = item['values']
        order_id, order_type, status = values[0], values[1], values[5]

        if status != "已完成":
            messagebox.showwarning("提示", "只能评价已完成的订单！")
            return

        ReviewDialog(self.db, self.user_id, order_id, order_type, self.window,
                     callback=self._load_orders)


class ReviewDialog:
    """评价对话框"""

    def __init__(self, db, user_id, order_id, order_type, parent, callback=None):
        self.db = db
        self.user_id = user_id
        self.order_id = order_id
        self.order_type = order_type
        self.callback = callback

        self.window = tk.Toplevel(parent)
        self.window.title("服务评价")
        self.window.geometry("400x300")
        self.window.configure(bg=CS.BG_WHITE)
        self.window.transient(parent)
        self.window.grab_set()

        self._create_widgets()
        self._center_window()

    def _create_widgets(self):
        tk.Label(self.window, text=f"评价订单：{self.order_id}",
                 font=("微软雅黑", 13, "bold"), bg=CS.BG_WHITE).pack(pady=(20, 10))

        # 星级评分（用5个按钮模拟）
        tk.Label(self.window, text="评分：", font=("微软雅黑", 10),
                 bg=CS.BG_WHITE).pack()

        star_frame = tk.Frame(self.window, bg=CS.BG_WHITE)
        star_frame.pack(pady=5)
        self.rating = tk.IntVar(value=5)
        self.star_buttons = []
        for i in range(1, 6):
            btn = tk.Button(star_frame, text="★", font=("微软雅黑", 16),
                            bg=CS.BG_WHITE, fg=CS.WARNING, bd=0,
                            command=lambda v=i: self._set_rating(v))
            btn.pack(side='left', padx=3)
            self.star_buttons.append(btn)

        tk.Label(self.window, text=f"当前评分：5星", font=("微软雅黑", 9),
                 bg=CS.BG_WHITE, fg=CS.TEXT_SECONDARY).pack()
        self.rating_label = tk.Label(self.window, text="当前评分：5星",
                                      font=("微软雅黑", 9), bg=CS.BG_WHITE, fg=CS.TEXT_SECONDARY)
        self.rating_label.pack()

        tk.Label(self.window, text="评价内容：", font=("微软雅黑", 10),
                 bg=CS.BG_WHITE).pack(anchor='w', padx=60, pady=(15, 2))
        self.content_text = tk.Text(self.window, font=("微软雅黑", 10),
                                     width=35, height=4, bd=1, relief='solid')
        self.content_text.pack(padx=60)

        RoundedButton(self.window, text="提交评价",
                  font=("微软雅黑", 11), color='#27ae60', hover_color='#219a52',
                  width=130, height=36, radius=8,
                  command=self._submit).pack(pady=15)

    def _set_rating(self, value):
        """设置评分"""
        self.rating.set(value)
        for i, btn in enumerate(self.star_buttons, 1):
            btn.config(fg=CS.WARNING if i <= value else CS.TEXT_MUTED)
        self.rating_label.config(text=f"当前评分：{value}星")

    def _submit(self):
        """提交评价"""
        rating = self.rating.get()
        content = self.content_text.get("1.0", "end-1c").strip()

        if not content:
            messagebox.showwarning("提示", "请填写评价内容！")
            return

        type_map = {"客房": "room", "餐饮": "dining", "健身": "fitness",
                    "SPA": "spa", "洗衣": "laundry"}

        self.db.execute(
            "INSERT INTO review (user_id, order_id, order_type, rating, content) "
            "VALUES (%s,%s,%s,%s,%s)",
            (self.user_id, self.order_id, type_map.get(self.order_type, 'other'),
             rating, content)
        )

        messagebox.showinfo("成功", "评价提交成功，感谢您的反馈！")
        self.window.destroy()
        if self.callback:
            self.callback()

    def _center_window(self):
        self.window.update_idletasks()
        w = self.window.winfo_width()
        h = self.window.winfo_height()
        x = (self.window.winfo_screenwidth() // 2) - (w // 2)
        y = (self.window.winfo_screenheight() // 2) - (h // 2)
        self.window.geometry(f'{w}x{h}+{x}+{y}')

    def run(self):
        self.window.mainloop()
