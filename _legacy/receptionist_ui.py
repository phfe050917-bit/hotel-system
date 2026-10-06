"""酒店服务预约系统 - 前台接待端"""

import tkinter as tk
from tkinter import ttk, messagebox
from datetime import date, datetime
from styles import RoundedButton, ColorScheme as CS


class ReceptionistWindow:
    """
    前台接待端主窗口
    """

    def __init__(self, db, user_id, real_name):
        self.db = db
        self.user_id = user_id
        self.real_name = real_name

        self.window = tk.Tk()
        self.window.title(f"酒店服务预约系统 - 前台端 - {real_name}")
        self.window.geometry("950x650")
        self.window.configure(bg=CS.BG_MAIN)

        self._create_top_bar()

        self.notebook = ttk.Notebook(self.window)
        self.notebook.pack(fill='both', expand=True, padx=10, pady=(0, 10))

        self.tab_overview = tk.Frame(self.notebook, bg=CS.BG_MAIN)
        self.tab_rooms = tk.Frame(self.notebook, bg=CS.BG_MAIN)
        self.tab_orders = tk.Frame(self.notebook, bg=CS.BG_MAIN)
        self.tab_laundry = tk.Frame(self.notebook, bg=CS.BG_MAIN)
        self.tab_reviews = tk.Frame(self.notebook, bg=CS.BG_MAIN)

        self.notebook.add(self.tab_overview, text="  预约概览  ")
        self.notebook.add(self.tab_rooms, text="  客房管理  ")
        self.notebook.add(self.tab_orders, text="  订单管理  ")
        self.notebook.add(self.tab_laundry, text="  洗衣服务  ")
        self.notebook.add(self.tab_reviews, text="  评价查看  ")

        self._init_overview_tab()
        self._init_rooms_tab()
        self._init_orders_tab()
        self._init_laundry_tab()
        self._init_reviews_tab()

        self._center_window()

    def _create_top_bar(self):
        """顶部蓝色信息栏"""
        top_frame = tk.Frame(self.window, bg=CS.BG_DARK, height=45)
        top_frame.pack(fill='x')
        top_frame.pack_propagate(False)

        tk.Label(top_frame,
                 text=f"🛎 前台接待 - {self.real_name} | 酒店服务预约管理系统",
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

    def _init_overview_tab(self):
        """预约概览 - 展示今日各服务的预约统计"""
        tk.Label(self.tab_overview, text="📊 今日预约概览",
                 font=("微软雅黑", 14, "bold"), bg=CS.BG_MAIN,
                 fg=CS.TEXT_PRIMARY).pack(pady=(15, 20))

        today = date.today().strftime("%Y-%m-%d")

        # 使用哈希表存储统计数据
        from models import HashTable
        stats_ht = HashTable()

        room_orders = self.db.query(
            "SELECT COUNT(*) as cnt FROM room_order "
            "WHERE check_in_date <= %s AND check_out_date > %s AND status IN ('confirmed','checked_in')",
            (today, today)
        )
        stats_ht.put("客房入住中", room_orders[0]['cnt'])

        dining = self.db.query(
            "SELECT COUNT(*) as cnt FROM dining_order "
            "WHERE dining_date = %s AND status = 'confirmed'", (today,)
        )
        stats_ht.put("餐饮预约", dining[0]['cnt'])

        fitness = self.db.query(
            "SELECT COUNT(*) as cnt FROM fitness_booking "
            "WHERE booking_date = %s AND status = 'confirmed'", (today,)
        )
        stats_ht.put("健身预约", fitness[0]['cnt'])

        spa = self.db.query(
            "SELECT COUNT(*) as cnt FROM spa_booking "
            "WHERE booking_date = %s AND status = 'confirmed'", (today,)
        )
        stats_ht.put("SPA预约", spa[0]['cnt'])

        laundry = self.db.query(
            "SELECT COUNT(*) as cnt FROM laundry_order "
            "WHERE DATE(created_at) = %s AND status != 'cancelled'", (today,)
        )
        stats_ht.put("洗衣服务", laundry[0]['cnt'])

        available = self.db.query(
            "SELECT COUNT(*) as cnt FROM room WHERE status='available'"
        )
        stats_ht.put("可用客房", available[0]['cnt'])

        cards_frame = tk.Frame(self.tab_overview, bg=CS.BG_MAIN)
        cards_frame.pack(pady=20)

        card_info = [
            ("🏨 可用客房", stats_ht.get("可用客房", 0), "#3498db"),
            ("🛏 入住中", stats_ht.get("客房入住中", 0), "#2ecc71"),
            ("🍽 今日餐饮", stats_ht.get("餐饮预约", 0), "#e74c3c"),
            ("🏋 今日健身", stats_ht.get("健身预约", 0), "#f39c12"),
            ("💆 今日SPA", stats_ht.get("SPA预约", 0), "#9b59b6"),
            ("👕 今日洗衣", stats_ht.get("洗衣服务", 0), "#1abc9c"),
        ]

        for i, (label, count, color) in enumerate(card_info):
            row, col = i // 3, i % 3
            card = tk.Frame(cards_frame, bg=color, width=200, height=100)
            card.grid(row=row, column=col, padx=15, pady=15)
            card.pack_propagate(False)

            tk.Label(card, text=label,
                     font=("微软雅黑", 12), bg=color, fg='white').pack(pady=(18, 0))
            tk.Label(card, text=str(count),
                     font=("微软雅黑", 24, "bold"), bg=color, fg='white').pack()

        tk.Label(self.tab_overview, text="最新评价",
                 font=("微软雅黑", 11, "bold"), bg=CS.BG_MAIN,
                 fg=CS.TEXT_PRIMARY).pack(anchor='w', padx=60, pady=(10, 5))

        reviews = self.db.query(
            "SELECT r.*, u.username FROM review r "
            "JOIN user u ON r.user_id=u.user_id "
            "ORDER BY r.created_at DESC LIMIT 5"
        )
        for rev in reviews:
            stars = "★" * rev['rating'] + "☆" * (5 - rev['rating'])
            tk.Label(self.tab_overview,
                     text=f"{stars} {rev['username']}: {rev['content'][:50]}...",
                     font=("微软雅黑", 9), bg=CS.BG_MAIN, fg='#34495e'
                     ).pack(anchor='w', padx=70)

    def _init_rooms_tab(self):
        """客房管理 - 查看和修改客房状态"""
        tk.Label(self.tab_rooms, text="🏨 客房状态管理",
                 font=("微软雅黑", 14, "bold"), bg=CS.BG_MAIN,
                 fg=CS.TEXT_PRIMARY).pack(pady=(10, 10))

        toolbar = tk.Frame(self.tab_rooms, bg=CS.BG_MAIN)
        toolbar.pack(fill='x', padx=10)

        tk.Label(toolbar, text="楼层筛选：", font=("微软雅黑", 10),
                 bg=CS.BG_MAIN).pack(side='left', padx=(0, 5))
        self.room_floor_combo = ttk.Combobox(toolbar, font=("微软雅黑", 10),
                                              width=8, state='readonly')
        self.room_floor_combo['values'] = ["全部", "1", "2", "3", "4"]
        self.room_floor_combo.current(0)
        self.room_floor_combo.pack(side='left', padx=(0, 15))
        self.room_floor_combo.bind('<<ComboboxSelected>>', lambda e: self._load_rooms())

        tk.Label(toolbar, text="状态筛选：", font=("微软雅黑", 10),
                 bg=CS.BG_MAIN).pack(side='left', padx=(0, 5))
        self.room_status_combo = ttk.Combobox(toolbar, font=("微软雅黑", 10),
                                               width=10, state='readonly')
        self.room_status_combo['values'] = ["全部", "可用", "已入住", "打扫中", "维护中"]
        self.room_status_combo.current(0)
        self.room_status_combo.pack(side='left', padx=(0, 15))
        self.room_status_combo.bind('<<ComboboxSelected>>', lambda e: self._load_rooms())

        RoundedButton(toolbar, text="🔄 刷新", font=("微软雅黑", 10),
                      color='#3498db', hover_color='#2980b9',
                      width=100, height=32, radius=8,
                      command=self._load_rooms).pack(side='left', padx=(0, 10))

        RoundedButton(toolbar, text="➡ 修改状态",
                      font=("微软雅黑", 10), color='#27ae60', hover_color='#219a52',
                      width=100, height=32, radius=8,
                      command=self._change_room_status
                      ).pack(side='right')

        columns = ("房间号", "房型", "楼层", "状态", "价格/晚")
        self.room_tree = ttk.Treeview(self.tab_rooms, columns=columns,
                                       show='headings', height=16)
        widths = [100, 150, 80, 100, 100]
        for col, w in zip(columns, widths):
            self.room_tree.heading(col, text=col)
            self.room_tree.column(col, width=w, anchor='center')

        scrollbar = ttk.Scrollbar(self.tab_rooms, orient='vertical',
                                   command=self.room_tree.yview)
        self.room_tree.configure(yscrollcommand=scrollbar.set)
        self.room_tree.pack(side='left', fill='both', expand=True, padx=10, pady=10)
        scrollbar.pack(side='right', fill='y', pady=10)

        self.room_tree.tag_configure('available', background='#d5f5e3')
        self.room_tree.tag_configure('occupied', background='#fadbd8')
        self.room_tree.tag_configure('cleaning', background='#fcf3cf')
        self.room_tree.tag_configure('maintenance', background='#d6dbdf')

        self._load_rooms()

    def _load_rooms(self):
        """加载房间列表"""
        for item in self.room_tree.get_children():
            self.room_tree.delete(item)

        sql = """
            SELECT r.room_number, rt.type_name, r.floor, r.status, rt.price, r.room_id
            FROM room r JOIN room_type rt ON r.type_id = rt.type_id WHERE 1=1
        """
        params = []

        floor_filter = self.room_floor_combo.get()
        if floor_filter != "全部":
            sql += " AND r.floor = %s"
            params.append(floor_filter)

        status_filter = self.room_status_combo.get()
        status_map = {"可用": "available", "已入住": "occupied",
                      "打扫中": "cleaning", "维护中": "maintenance"}
        if status_filter in status_map:
            sql += " AND r.status = %s"
            params.append(status_map[status_filter])

        sql += " ORDER BY r.room_number"

        rooms = self.db.query(sql, params)
        status_labels = {"available": "可用", "occupied": "已入住",
                         "cleaning": "打扫中", "maintenance": "维护中"}

        for r in rooms:
            status = r['status']
            self.room_tree.insert('', 'end', values=(
                r['room_number'], r['type_name'], f"{r['floor']}楼",
                status_labels.get(status, status), f"¥{r['price']}"
            ), tags=(status,))

    def _change_room_status(self):
        """修改选中房间的状态"""
        selected = self.room_tree.selection()
        if not selected:
            messagebox.showwarning("提示", "请先选择一个房间！")
            return

        item = self.room_tree.item(selected[0])
        values = item['values']
        room_number = values[0]
        current_status = values[3]

        dialog = tk.Toplevel(self.window)
        dialog.title(f"修改房间 {room_number} 状态")
        dialog.geometry("320x200")
        dialog.configure(bg=CS.BG_WHITE)
        dialog.transient(self.window)
        dialog.grab_set()

        tk.Label(dialog, text=f"房间 {room_number} 当前状态：{current_status}",
                 font=("微软雅黑", 11), bg=CS.BG_WHITE).pack(pady=(20, 10))

        tk.Label(dialog, text="选择新状态：", font=("微软雅黑", 10),
                 bg=CS.BG_WHITE).pack()

        status_var = tk.StringVar(value='available')
        status_combo = ttk.Combobox(dialog, textvariable=status_var,
                                     font=("微软雅黑", 10), width=12, state='readonly')
        status_combo['values'] = ["可用", "打扫中", "维护中"]
        status_combo.current(0)
        status_combo.pack(pady=10)

        def confirm():
            status_map = {"可用": "available", "打扫中": "cleaning", "维护中": "maintenance"}
            new_status = status_map[status_var.get()]
            self.db.execute(
                "UPDATE room SET status=%s WHERE room_number=%s",
                (new_status, room_number)
            )
            messagebox.showinfo("成功", f"房间 {room_number} 状态已更新为 {status_var.get()}！")
            dialog.destroy()
            self._load_rooms()

        RoundedButton(dialog, text="确认修改",
                      font=("微软雅黑", 10), color='#3498db', hover_color='#2980b9',
                      width=100, height=32, radius=8,
                      command=confirm).pack()

        dialog.update_idletasks()
        w = dialog.winfo_width()
        h = dialog.winfo_height()
        x = (dialog.winfo_screenwidth() // 2) - (w // 2)
        y = (dialog.winfo_screenheight() // 2) - (h // 2)
        dialog.geometry(f'{w}x{h}+{x}+{y}')

    def _init_orders_tab(self):
        """订单管理 - 查看所有订单"""
        tk.Label(self.tab_orders, text="📋 全部订单管理",
                 font=("微软雅黑", 14, "bold"), bg=CS.BG_MAIN,
                 fg=CS.TEXT_PRIMARY).pack(pady=(10, 10))

        toolbar = tk.Frame(self.tab_orders, bg=CS.BG_MAIN)
        toolbar.pack(fill='x', padx=10)

        tk.Label(toolbar, text="类型：", font=("微软雅黑", 10),
                 bg=CS.BG_MAIN).pack(side='left')
        self.rec_order_type = ttk.Combobox(toolbar, font=("微软雅黑", 10),
                                            width=8, state='readonly')
        self.rec_order_type['values'] = ["全部", "客房", "餐饮", "健身", "SPA", "洗衣"]
        self.rec_order_type.current(0)
        self.rec_order_type.pack(side='left', padx=(0, 10))
        self.rec_order_type.bind('<<ComboboxSelected>>', lambda e: self._load_all_orders())

        tk.Label(toolbar, text="状态：", font=("微软雅黑", 10),
                 bg=CS.BG_MAIN).pack(side='left')
        self.rec_order_status = ttk.Combobox(toolbar, font=("微软雅黑", 10),
                                              width=10, state='readonly')
        self.rec_order_status['values'] = ["全部", "进行中", "已完成", "已取消"]
        self.rec_order_status.current(0)
        self.rec_order_status.pack(side='left', padx=(0, 10))
        self.rec_order_status.bind('<<ComboboxSelected>>', lambda e: self._load_all_orders())

        RoundedButton(toolbar, text="🔄 刷新", font=("微软雅黑", 10),
                      color='#3498db', hover_color='#2980b9',
                      width=100, height=32, radius=8,
                      command=self._load_all_orders).pack(side='left')

        RoundedButton(toolbar, text="➡ 标记已完成", font=("微软雅黑", 10),
                      color='#27ae60', hover_color='#219a52',
                      width=100, height=32, radius=8,
                      command=self._complete_order).pack(side='right', padx=(5, 0))
        RoundedButton(toolbar, text="❌ 取消订单", font=("微软雅黑", 10),
                      color='#e74c3c', hover_color='#c0392b',
                      width=100, height=32, radius=8,
                      command=self._cancel_any_order).pack(side='right')

        columns = ("订单号", "客人", "类型", "详情", "时间", "金额", "状态")
        self.all_orders_tree = ttk.Treeview(self.tab_orders, columns=columns,
                                             show='headings', height=18)
        widths = [110, 80, 60, 220, 130, 80, 80]
        for col, w in zip(columns, widths):
            self.all_orders_tree.heading(col, text=col)
            self.all_orders_tree.column(col, width=w)
        self.all_orders_tree.pack(fill='both', expand=True, padx=10, pady=10)

        self._load_all_orders()

    def _load_all_orders(self):
        """加载所有订单（包含客人信息）"""
        for item in self.all_orders_tree.get_children():
            self.all_orders_tree.delete(item)

        type_filter = self.rec_order_type.get()
        status_filter = self.rec_order_status.get()
        all_rows = []

        if type_filter in ["全部", "客房"]:
            rows = self.db.query(
                "SELECT ro.order_id, u.username, '客房' as type, "
                "CONCAT(r.room_number, ' / ', ro.check_in_date, '~', ro.check_out_date) as detail, "
                "ro.created_at, ro.total_price, "
                "CASE ro.status WHEN 'confirmed' THEN '进行中' WHEN 'checked_in' THEN '进行中' "
                "WHEN 'checked_out' THEN '已完成' WHEN 'cancelled' THEN '已取消' END as status, "
                "'room_order' as tbl "
                "FROM room_order ro "
                "JOIN user u ON ro.user_id=u.user_id "
                "JOIN room r ON ro.room_id=r.room_id"
            )
            all_rows.extend(rows)

        if type_filter in ["全部", "餐饮"]:
            rows = self.db.query(
                "SELECT do2.order_id, u.username, '餐饮' as type, "
                "CONCAT(r2.restaurant_name, ' / ', do2.dining_date, ' ', do2.dining_time) as detail, "
                "do2.created_at, do2.total_price, "
                "CASE do2.status WHEN 'confirmed' THEN '进行中' WHEN 'dining' THEN '进行中' "
                "WHEN 'completed' THEN '已完成' WHEN 'cancelled' THEN '已取消' END as status, "
                "'dining_order' as tbl "
                "FROM dining_order do2 "
                "JOIN user u ON do2.user_id=u.user_id "
                "JOIN restaurant r2 ON do2.restaurant_id=r2.restaurant_id"
            )
            all_rows.extend(rows)

        if type_filter in ["全部", "健身"]:
            rows = self.db.query(
                "SELECT fb.booking_id as order_id, u.username, '健身' as type, "
                "CONCAT(ff.facility_name, ' / ', fb.booking_date, ' ', fb.time_slot) as detail, "
                "fb.created_at, 0 as total_price, "
                "CASE fb.status WHEN 'confirmed' THEN '进行中' WHEN 'completed' THEN '已完成' "
                "WHEN 'cancelled' THEN '已取消' END as status, 'fitness_booking' as tbl "
                "FROM fitness_booking fb "
                "JOIN user u ON fb.user_id=u.user_id "
                "JOIN fitness_facility ff ON fb.facility_id=ff.facility_id"
            )
            all_rows.extend(rows)

        if type_filter in ["全部", "SPA"]:
            rows = self.db.query(
                "SELECT sb.booking_id as order_id, u.username, 'SPA' as type, "
                "CONCAT(ss.service_name, ' / ', t2.tech_name) as detail, "
                "sb.created_at, ss.price as total_price, "
                "CASE sb.status WHEN 'confirmed' THEN '进行中' WHEN 'in_progress' THEN '进行中' "
                "WHEN 'completed' THEN '已完成' WHEN 'cancelled' THEN '已取消' END as status, "
                "'spa_booking' as tbl "
                "FROM spa_booking sb "
                "JOIN user u ON sb.user_id=u.user_id "
                "JOIN spa_service ss ON sb.service_id=ss.service_id "
                "JOIN technician t2 ON sb.tech_id=t2.tech_id"
            )
            all_rows.extend(rows)

        if type_filter in ["全部", "洗衣"]:
            rows = self.db.query(
                "SELECT lo.order_id, u.username, '洗衣' as type, "
                "CONCAT(CASE lo.service_type WHEN 'wash' THEN '水洗' WHEN 'dry_clean' THEN '干洗' "
                "WHEN 'iron' THEN '熨烫' WHEN 'express_wash' THEN '加急水洗' "
                "WHEN 'express_dry' THEN '加急干洗' END, ' / ', lo.room_number) as detail, "
                "lo.created_at, lo.total_price, "
                "CASE lo.status WHEN 'pending' THEN '进行中' WHEN 'picked_up' THEN '进行中' "
                "WHEN 'processing' THEN '进行中' WHEN 'delivered' THEN '已完成' "
                "WHEN 'cancelled' THEN '已取消' END as status, 'laundry_order' as tbl "
                "FROM laundry_order lo JOIN user u ON lo.user_id=u.user_id"
            )
            all_rows.extend(rows)

        if status_filter != "全部":
            all_rows = [r for r in all_rows if r['status'] == status_filter]

        all_rows.sort(key=lambda x: str(x['created_at']), reverse=True)

        for r in all_rows:
            self.all_orders_tree.insert('', 'end', values=(
                r.get('order_id', ''), r.get('username', ''),
                r['type'], r.get('detail', ''),
                str(r['created_at']).split('.')[0] if r['created_at'] else '',
                f"¥{r.get('total_price', 0) or 0}",
                r['status']
            ))

    def _complete_order(self):
        """标记订单为已完成"""
        self._handle_order_status("complete")

    def _cancel_any_order(self):
        """取消订单"""
        self._handle_order_status("cancel")

    def _handle_order_status(self, action):
        """处理订单状态变更"""
        selected = self.all_orders_tree.selection()
        if not selected:
            messagebox.showwarning("提示", "请先选择一个订单！")
            return

        item = self.all_orders_tree.item(selected[0])
        values = item['values']
        order_id, order_type = values[0], values[2]

        table_map = {"客房": "room_order", "餐饮": "dining_order",
                     "健身": "fitness_booking", "SPA": "spa_booking",
                     "洗衣": "laundry_order"}
        id_col = "booking_id" if order_type in ["健身", "SPA"] else "order_id"

        # 各表对应的"完成"状态值
        completed_status = {
            "客房": "checked_out", "餐饮": "completed",
            "健身": "completed", "SPA": "completed", "洗衣": "delivered"
        }

        status = completed_status[order_type] if action == "complete" else "cancelled"
        action_text = "标记完成" if action == "complete" else "取消"
        if messagebox.askyesno(f"确认{action_text}", f"确定要{action_text}订单 {order_id} 吗？"):
            tbl = table_map[order_type]
            self.db.execute(
                f"UPDATE {tbl} SET status=%s WHERE {id_col}=%s",
                (status, order_id)
            )
            messagebox.showinfo("成功", f"订单 {order_id} 已{action_text}！")
            self._load_all_orders()

    def _init_laundry_tab(self):
        """洗衣服务管理"""
        tk.Label(self.tab_laundry, text="👕 洗衣服务管理",
                 font=("微软雅黑", 14, "bold"), bg=CS.BG_MAIN,
                 fg=CS.TEXT_PRIMARY).pack(pady=(10, 10))

        # 使用优先队列数据结构管理洗衣请求
        # 加急订单优先处理，普通订单按时间顺序
        note_frame = tk.Frame(self.tab_laundry, bg='#fef9e7')
        note_frame.pack(fill='x', padx=10, pady=(0, 10))
        tk.Label(note_frame,
                 text="💡 洗衣订单按优先级排列（加急 > 普通），同优先级按时间先后处理",
                 font=("微软雅黑", 9), bg='#fef9e7', fg='#7d6608'
                 ).pack(pady=5)

        columns = ("订单号", "客人", "房间号", "服务类型", "数量", "金额", "状态", "操作")
        self.laundry_tree = ttk.Treeview(self.tab_laundry, columns=columns,
                                          show='headings', height=18)
        widths = [110, 80, 80, 90, 60, 70, 80, 100]
        for col, w in zip(columns, widths):
            self.laundry_tree.heading(col, text=col)
            self.laundry_tree.column(col, width=w, anchor='center')

        scrollbar = ttk.Scrollbar(self.tab_laundry, orient='vertical',
                                   command=self.laundry_tree.yview)
        self.laundry_tree.configure(yscrollcommand=scrollbar.set)
        self.laundry_tree.pack(side='left', fill='both', expand=True, padx=10, pady=(0, 10))
        scrollbar.pack(side='right', fill='y', pady=(0, 10))

        btn_frame = tk.Frame(self.tab_laundry, bg=CS.BG_MAIN)
        btn_frame.pack(fill='x', padx=10, pady=(0, 10))

        RoundedButton(btn_frame, text="📦 标记已取衣",
                      font=("微软雅黑", 10), color='#e67e22', hover_color='#d35400',
                      width=100, height=32, radius=8,
                      command=lambda: self._update_laundry_status('picked_up')
                      ).pack(side='left', padx=(0, 10))

        RoundedButton(btn_frame, text="🔄 标记洗涤中",
                      font=("微软雅黑", 10), color='#3498db', hover_color='#2980b9',
                      width=100, height=32, radius=8,
                      command=lambda: self._update_laundry_status('processing')
                      ).pack(side='left', padx=(0, 10))

        RoundedButton(btn_frame, text="✅ 标记已送达",
                      font=("微软雅黑", 10), color='#27ae60', hover_color='#219a52',
                      width=100, height=32, radius=8,
                      command=lambda: self._update_laundry_status('delivered')
                      ).pack(side='left', padx=(0, 10))

        RoundedButton(btn_frame, text="🔄 刷新",
                      font=("微软雅黑", 10), color='#95a5a6', hover_color='#7f8c8d',
                      width=100, height=32, radius=8,
                      command=self._load_laundry_orders).pack(side='right')

        self._load_laundry_orders()

    def _load_laundry_orders(self):
        """加载洗衣订单列表，使用优先队列按加急 > 普通排列"""
        for item in self.laundry_tree.get_children():
            self.laundry_tree.delete(item)

        orders = self.db.query(
            "SELECT lo.*, u.username FROM laundry_order lo "
            "JOIN user u ON lo.user_id=u.user_id "
            "ORDER BY lo.created_at ASC"
        )

        # 使用优先队列排序
        from models import PriorityQueue
        pq = PriorityQueue()

        for o in orders:
            # 设置优先级：加急=1, 普通=2
            priority = 1 if 'express' in o['service_type'] else 2
            pq.add(priority, o)

        while not pq.is_empty():
            item = pq.poll()
            o = item[1] if isinstance(item, tuple) else item

            type_name = {'wash': '普通水洗', 'dry_clean': '普通干洗',
                         'iron': '熨烫', 'express_wash': '🏃加急水洗',
                         'express_dry': '🏃加急干洗'
                         }.get(o['service_type'], o['service_type'])

            status_name = {'pending': '等待取衣', 'picked_up': '已取衣',
                           'processing': '洗涤中', 'delivered': '已送达',
                           'cancelled': '已取消'
                           }.get(o['status'], o['status'])

            tag = 'express' if 'express' in o['service_type'] else 'normal'
            self.laundry_tree.insert('', 'end', values=(
                o['order_id'], o.get('username', ''),
                o['room_number'], type_name, o['item_count'],
                f"¥{o['total_price']}", status_name, ""
            ), tags=(tag,))

        self.laundry_tree.tag_configure('express', background='#fdebd0')

    def _update_laundry_status(self, new_status):
        """更新洗衣订单状态"""
        selected = self.laundry_tree.selection()
        if not selected:
            messagebox.showwarning("提示", "请先选择一个订单！")
            return

        item = self.laundry_tree.item(selected[0])
        values = item['values']
        order_id = values[0]

        status_labels = {
            'picked_up': '已取衣', 'processing': '洗涤中', 'delivered': '已送达'
        }

        self.db.execute(
            "UPDATE laundry_order SET status=%s WHERE order_id=%s",
            (new_status, order_id)
        )
        messagebox.showinfo("成功", f"订单 {order_id} 状态已更新为「{status_labels[new_status]}」！")
        self._load_laundry_orders()

    def _init_reviews_tab(self):
        """查看客人评价"""
        tk.Label(self.tab_reviews, text="⭐ 客人评价",
                 font=("微软雅黑", 14, "bold"), bg=CS.BG_MAIN,
                 fg=CS.TEXT_PRIMARY).pack(pady=(10, 10))

        columns = ("时间", "客人", "订单号", "评分", "内容")
        self.review_tree = ttk.Treeview(self.tab_reviews, columns=columns,
                                         show='headings', height=20)
        widths = [140, 80, 120, 80, 300]
        for col, w in zip(columns, widths):
            self.review_tree.heading(col, text=col)
            self.review_tree.column(col, width=w)

        scrollbar = ttk.Scrollbar(self.tab_reviews, orient='vertical',
                                   command=self.review_tree.yview)
        self.review_tree.configure(yscrollcommand=scrollbar.set)
        self.review_tree.pack(side='left', fill='both', expand=True, padx=10, pady=10)
        scrollbar.pack(side='right', fill='y', pady=10)

        self._load_reviews()

    def _load_reviews(self):
        for item in self.review_tree.get_children():
            self.review_tree.delete(item)

        reviews = self.db.query(
            "SELECT r.*, u.username FROM review r "
            "JOIN user u ON r.user_id=u.user_id "
            "ORDER BY r.created_at DESC"
        )

        stars_dict = {1: "★☆☆☆☆", 2: "★★☆☆☆", 3: "★★★☆☆", 4: "★★★★☆", 5: "★★★★★"}

        for rev in reviews:
            self.review_tree.insert('', 'end', values=(
                str(rev['created_at']).split('.')[0],
                rev['username'],
                rev['order_id'],
                stars_dict.get(rev['rating'], f"{rev['rating']}星"),
                rev.get('content', '')
            ))
