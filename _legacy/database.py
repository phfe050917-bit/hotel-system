"""
酒店服务预约系统 - 数据库操作模块
"""

import pymysql
import pymysql.cursors


class Database:
    """数据库操作类，封装MySQL数据库的基本操作。"""

    def __init__(self, host='localhost', user='root', password='123456',
                 database='hotel_booking', port=3306):
        """初始化数据库连接，自动创建数据库和表。"""
        self.connection = None
        self.cursor = None

        try:
            self.connection = pymysql.connect(
                host=host,
                user=user,
                password=password,
                port=port,
                charset='utf8mb4',
                cursorclass=pymysql.cursors.DictCursor
            )
            self.cursor = self.connection.cursor()
            print("✓ 数据库连接成功！")

            self.cursor.execute(
                f"CREATE DATABASE IF NOT EXISTS `{database}` "
                f"DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
            self.cursor.execute(f"USE `{database}`")
            print(f"✓ 数据库 '{database}' 已就绪")

            self._create_tables()

        except pymysql.Error as e:
            print(f"✗ 数据库连接失败，错误信息：{e}")
            print("  请检查：1.MySQL是否启动 2.用户名密码是否正确")
            raise e

    def _create_tables(self):
        """自动创建系统所需的全部数据表。"""
        # 1. 用户表
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS user (
                user_id     INT AUTO_INCREMENT PRIMARY KEY COMMENT '用户ID，自动递增',
                username    VARCHAR(50)  UNIQUE NOT NULL        COMMENT '登录用户名',
                password    VARCHAR(100) NOT NULL                COMMENT '登录密码',
                phone       VARCHAR(20)  UNIQUE DEFAULT NULL     COMMENT '手机号',
                email       VARCHAR(100) UNIQUE DEFAULT NULL     COMMENT '邮箱',
                real_name   VARCHAR(50)  DEFAULT NULL            COMMENT '真实姓名',
                role        ENUM('guest','receptionist','admin') DEFAULT 'guest' COMMENT '角色',
                created_at  DATETIME DEFAULT CURRENT_TIMESTAMP   COMMENT '创建时间'
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        # 2. 房型表（父表，被房间表引用）
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS room_type (
                type_id       INT AUTO_INCREMENT PRIMARY KEY COMMENT '房型ID',
                type_name     VARCHAR(50)  NOT NULL           COMMENT '房型名称',
                price         DECIMAL(10,2) NOT NULL          COMMENT '每晚价格',
                max_occupancy INT          NOT NULL           COMMENT '最大入住人数',
                description   TEXT                             COMMENT '房型描述',
                facilities    VARCHAR(500)                    COMMENT '设施说明'
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        # 3. 房间表
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS room (
                room_id      INT AUTO_INCREMENT PRIMARY KEY  COMMENT '房间ID',
                room_number  VARCHAR(10) UNIQUE NOT NULL     COMMENT '房间号',
                type_id      INT NOT NULL                    COMMENT '房型ID',
                floor        INT                             COMMENT '楼层',
                status       ENUM('available','occupied','cleaning','maintenance')
                              DEFAULT 'available'            COMMENT '房间状态',
                FOREIGN KEY (type_id) REFERENCES room_type(type_id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        # 4. 客房订单表
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS room_order (
                order_id       VARCHAR(20) PRIMARY KEY   COMMENT '订单号',
                user_id        INT NOT NULL              COMMENT '用户ID',
                room_id        INT NOT NULL              COMMENT '房间ID',
                check_in_date  DATE NOT NULL             COMMENT '入住日期',
                check_out_date DATE NOT NULL             COMMENT '离店日期',
                total_price    DECIMAL(10,2) NOT NULL    COMMENT '总金额',
                guest_name     VARCHAR(50) NOT NULL      COMMENT '入住人姓名',
                guest_phone    VARCHAR(20)               COMMENT '联系电话',
                status         ENUM('confirmed','checked_in','checked_out','cancelled')
                               DEFAULT 'confirmed'       COMMENT '订单状态',
                created_at     DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
                FOREIGN KEY (user_id) REFERENCES user(user_id) ON DELETE CASCADE,
                FOREIGN KEY (room_id) REFERENCES room(room_id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        # 5. 餐厅表
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS restaurant (
                restaurant_id   INT AUTO_INCREMENT PRIMARY KEY COMMENT '餐厅ID',
                restaurant_name VARCHAR(50) NOT NULL            COMMENT '餐厅名称',
                location        VARCHAR(100)                    COMMENT '位置',
                open_time       VARCHAR(50)                     COMMENT '营业时间',
                description     TEXT                            COMMENT '描述'
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        # 6. 菜品分类表（树形结构）
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS dish_category (
                category_id   INT AUTO_INCREMENT PRIMARY KEY COMMENT '分类ID',
                restaurant_id INT NOT NULL                   COMMENT '所属餐厅ID',
                parent_id     INT DEFAULT 0                  COMMENT '父分类ID, 0=根',
                category_name VARCHAR(50) NOT NULL           COMMENT '分类名称',
                FOREIGN KEY (restaurant_id) REFERENCES restaurant(restaurant_id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        # 7. 菜品表
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS dish (
                dish_id       INT AUTO_INCREMENT PRIMARY KEY COMMENT '菜品ID',
                restaurant_id INT NOT NULL                   COMMENT '餐厅ID',
                category_id   INT                            COMMENT '分类ID',
                dish_name     VARCHAR(50) NOT NULL            COMMENT '菜品名称',
                price         DECIMAL(10,2) NOT NULL          COMMENT '价格',
                description   TEXT                            COMMENT '描述',
                is_setmeal    TINYINT DEFAULT 0               COMMENT '是否套餐',
                FOREIGN KEY (restaurant_id) REFERENCES restaurant(restaurant_id) ON DELETE CASCADE,
                FOREIGN KEY (category_id) REFERENCES dish_category(category_id) ON DELETE SET NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        # 8. 餐饮订单表
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS dining_order (
                order_id      VARCHAR(20) PRIMARY KEY     COMMENT '订单号',
                user_id       INT NOT NULL                COMMENT '用户ID',
                restaurant_id INT NOT NULL                COMMENT '餐厅ID',
                table_number  VARCHAR(10) NOT NULL        COMMENT '桌号',
                dining_date   DATE NOT NULL               COMMENT '用餐日期',
                dining_time   TIME NOT NULL               COMMENT '用餐时间',
                guest_count   INT NOT NULL                COMMENT '用餐人数',
                total_price   DECIMAL(10,2) DEFAULT 0     COMMENT '总金额',
                status        ENUM('confirmed','dining','completed','cancelled')
                              DEFAULT 'confirmed'         COMMENT '订单状态',
                created_at    DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
                FOREIGN KEY (user_id) REFERENCES user(user_id) ON DELETE CASCADE,
                FOREIGN KEY (restaurant_id) REFERENCES restaurant(restaurant_id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        # 9. 健身设施表
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS fitness_facility (
                facility_id   INT AUTO_INCREMENT PRIMARY KEY COMMENT '设施ID',
                facility_name VARCHAR(50) NOT NULL            COMMENT '设施名称',
                location      VARCHAR(100)                    COMMENT '位置',
                capacity      INT NOT NULL                    COMMENT '最大容量',
                open_time     VARCHAR(50)                     COMMENT '开放时间',
                status        ENUM('available','maintenance') DEFAULT 'available' COMMENT '状态'
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        # 10. 健身预约表
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS fitness_booking (
                booking_id   VARCHAR(20) PRIMARY KEY      COMMENT '预约单号',
                user_id      INT NOT NULL                 COMMENT '用户ID',
                facility_id  INT NOT NULL                 COMMENT '设施ID',
                booking_date DATE NOT NULL                COMMENT '预约日期',
                time_slot    VARCHAR(20) NOT NULL         COMMENT '时间段',
                guest_count  INT DEFAULT 1                COMMENT '人数',
                status       ENUM('confirmed','completed','cancelled')
                             DEFAULT 'confirmed'          COMMENT '状态',
                created_at   DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
                FOREIGN KEY (user_id) REFERENCES user(user_id) ON DELETE CASCADE,
                FOREIGN KEY (facility_id) REFERENCES fitness_facility(facility_id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        # 11. SPA服务表
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS spa_service (
                service_id   INT AUTO_INCREMENT PRIMARY KEY COMMENT '服务ID',
                service_name VARCHAR(50)  NOT NULL           COMMENT '服务名称',
                duration     INT          NOT NULL           COMMENT '时长(分钟)',
                price        DECIMAL(10,2) NOT NULL          COMMENT '价格',
                description  TEXT                            COMMENT '描述'
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        # 12. 技师表
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS technician (
                tech_id    INT AUTO_INCREMENT PRIMARY KEY      COMMENT '技师ID',
                tech_name  VARCHAR(50) NOT NULL                COMMENT '技师姓名',
                specialty  VARCHAR(100)                        COMMENT '擅长项目',
                tech_level VARCHAR(20) DEFAULT '普通'           COMMENT '级别',
                rating     DECIMAL(3,1) DEFAULT 5.0            COMMENT '评分',
                status     ENUM('available','busy','off_duty') DEFAULT 'available' COMMENT '工作状态'
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        # 13. 技师排班表
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS tech_schedule (
                schedule_id  INT AUTO_INCREMENT PRIMARY KEY COMMENT '排班ID',
                tech_id      INT NOT NULL                   COMMENT '技师ID',
                work_date    DATE NOT NULL                  COMMENT '工作日期',
                time_slot    VARCHAR(20) NOT NULL           COMMENT '时间段',
                is_booked    TINYINT DEFAULT 0               COMMENT '是否被预约',
                FOREIGN KEY (tech_id) REFERENCES technician(tech_id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        # 14. SPA预约表
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS spa_booking (
                booking_id   VARCHAR(20) PRIMARY KEY       COMMENT '预约单号',
                user_id      INT NOT NULL                  COMMENT '用户ID',
                service_id   INT NOT NULL                  COMMENT '服务ID',
                tech_id      INT NOT NULL                  COMMENT '技师ID',
                booking_date DATE NOT NULL                 COMMENT '预约日期',
                booking_time TIME NOT NULL                 COMMENT '预约时间',
                room_number  VARCHAR(10)                    COMMENT 'SPA房间号',
                status       ENUM('confirmed','in_progress','completed','cancelled')
                             DEFAULT 'confirmed'           COMMENT '状态',
                created_at   DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
                FOREIGN KEY (user_id) REFERENCES user(user_id) ON DELETE CASCADE,
                FOREIGN KEY (service_id) REFERENCES spa_service(service_id) ON DELETE CASCADE,
                FOREIGN KEY (tech_id) REFERENCES technician(tech_id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        # 15. 洗衣订单表
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS laundry_order (
                order_id      VARCHAR(20) PRIMARY KEY       COMMENT '订单号',
                user_id       INT NOT NULL                  COMMENT '用户ID',
                service_type  ENUM('wash','dry_clean','iron','express_wash','express_dry')
                              NOT NULL                      COMMENT '服务类型',
                item_count    INT NOT NULL                  COMMENT '衣物数量',
                total_price   DECIMAL(10,2) NOT NULL        COMMENT '总金额',
                pickup_time   DATETIME                      COMMENT '取衣时间',
                delivery_time DATETIME                      COMMENT '送衣时间',
                room_number   VARCHAR(10) NOT NULL          COMMENT '房间号',
                status        ENUM('pending','picked_up','processing','delivered','cancelled')
                              DEFAULT 'pending'             COMMENT '状态',
                created_at    DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
                FOREIGN KEY (user_id) REFERENCES user(user_id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        # 16. 评价表
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS review (
                review_id  INT AUTO_INCREMENT PRIMARY KEY COMMENT '评价ID',
                user_id    INT NOT NULL                    COMMENT '用户ID',
                order_id   VARCHAR(20) NOT NULL            COMMENT '订单号',
                order_type VARCHAR(20) NOT NULL            COMMENT '订单类型',
                rating     TINYINT NOT NULL                COMMENT '评分1-5',
                content    TEXT                            COMMENT '评价内容',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '评价时间',
                FOREIGN KEY (user_id) REFERENCES user(user_id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        self.connection.commit()
        print("✓ 数据表创建/检查完成")

    def _ensure_connection(self):
        """确保数据库连接有效，连接断开时自动重连。"""
        try:
            self.connection.ping(reconnect=True)
        except Exception:
            self.connection.ping(reconnect=True)

    def execute(self, sql, params=None):
        """执行修改数据的SQL语句（INSERT、UPDATE、DELETE）。"""
        self._ensure_connection()
        if params is None:
            params = ()
        self.cursor.execute(sql, params)
        self.connection.commit()
        return self.cursor.rowcount

    def query(self, sql, params=None):
        """执行查询SQL语句（SELECT），返回结果列表。"""
        self._ensure_connection()
        if params is None:
            params = ()
        self.cursor.execute(sql, params)
        return self.cursor.fetchall()

    def query_one(self, sql, params=None):
        """执行查询并返回一条结果，无结果时返回None。"""
        self._ensure_connection()
        if params is None:
            params = ()
        self.cursor.execute(sql, params)
        return self.cursor.fetchone()

    def generate_order_id(self, prefix):
        """生成唯一订单号，格式：前缀 + 年月日时分秒 + 2位随机数。"""
        from datetime import datetime
        import random
        now = datetime.now()
        time_part = now.strftime("%Y%m%d%H%M%S")
        rand_part = str(random.randint(10, 99))
        return f"{prefix}{time_part}{rand_part}"

    def insert_sample_data(self):
        """插入测试数据（仅在数据库为空时执行）。"""
        existing = self.query_one("SELECT COUNT(*) as cnt FROM user")
        if existing and existing['cnt'] > 0:
            print("  已有数据，跳过插入测试数据")
            return

        print("  正在插入测试数据...")

        # 默认管理员和前台账号
        self.execute(
            "INSERT INTO user (username, password, real_name, role) VALUES (%s,%s,%s,%s)",
            ("admin", "admin123", "系统管理员", "admin")
        )
        self.execute(
            "INSERT INTO user (username, password, real_name, role) VALUES (%s,%s,%s,%s)",
            ("reception", "recep123", "前台小王", "receptionist")
        )
        self.execute(
            "INSERT INTO user (username, password, real_name, role) VALUES (%s,%s,%s,%s)",
            ("guest01", "guest123", "测试客人张三", "guest")
        )

        # 房型数据
        room_types = [
            ("标准单人间",   298.00, 1, "经济实惠的单人间，适合商务出差",       "WiFi、空调、独立卫浴、电视"),
            ("标准双人间",   398.00, 2, "舒适的双人间，适合结伴出行",           "WiFi、空调、独立卫浴、电视、书桌"),
            ("商务套房",     698.00, 2, "宽敞的商务套房，配备办公区域",         "WiFi、空调、独立卫浴、电视、迷你吧、书桌"),
            ("豪华总统套房", 1888.00,4, "顶级奢华套房，尽享尊贵体验",           "WiFi、空调、独立卫浴、电视、迷你吧、浴缸、景观阳台、客厅"),
        ]
        for rt in room_types:
            self.execute(
                "INSERT INTO room_type (type_name, price, max_occupancy, description, facilities) "
                "VALUES (%s,%s,%s,%s,%s)", rt
            )

        # 房间数据（每种房型4间，共16间）
        for type_id in range(1, 5):
            for i in range(1, 5):
                room_num = f"{type_id}0{i}"
                self.execute(
                    "INSERT INTO room (room_number, type_id, floor) VALUES (%s,%s,%s)",
                    (room_num, type_id, type_id)
                )

        # 餐厅数据
        self.execute(
            "INSERT INTO restaurant (restaurant_name, location, open_time, description) "
            "VALUES (%s,%s,%s,%s)",
            ("中餐厅·雅苑", "酒店2楼东侧", "早餐7:00-9:30 午餐11:30-13:30 晚餐17:30-20:30", "提供精致中式料理")
        )
        self.execute(
            "INSERT INTO restaurant (restaurant_name, location, open_time, description) "
            "VALUES (%s,%s,%s,%s)",
            ("西餐厅·蓝海", "酒店2楼西侧", "午餐11:30-14:00 晚餐17:30-21:00", "浪漫西式用餐体验")
        )

        # 菜品分类
        categories = [
            (1, 0, "中式冷菜"), (1, 0, "中式热菜"), (1, 0, "中式汤品"), (1, 0, "中式套餐"),
            (2, 0, "西式前菜"), (2, 0, "西式主菜"), (2, 0, "西式甜点"), (2, 0, "西式套餐"),
        ]
        for cat in categories:
            self.execute(
                "INSERT INTO dish_category (restaurant_id, parent_id, category_name) VALUES (%s,%s,%s)", cat
            )

        # 菜品数据
        dishes = [
            (1, 1, "凉拌黄瓜",      22.00,  "爽脆可口的开胃小菜"),
            (1, 1, "皮蛋豆腐",      28.00,  "经典中式冷菜"),
            (1, 2, "宫保鸡丁",      48.00,  "经典川菜，麻辣鲜香"),
            (1, 2, "清蒸鲈鱼",      88.00,  "新鲜鲈鱼，清蒸保留原味"),
            (1, 2, "红烧排骨",      58.00,  "软烂入味，酱香浓郁"),
            (1, 3, "番茄蛋花汤",    18.00,  "家常美味汤品"),
            (1, 3, "排骨莲藕汤",    38.00,  "慢火炖煮，营养滋补"),
            (1, 4, "商务双人套餐A", 168.00, "含宫保鸡丁+清蒸鲈鱼+番茄蛋花汤"),
            (1, 4, "家庭四人套餐B", 298.00, "含红烧排骨+宫保鸡丁+清蒸鲈鱼+排骨莲藕汤"),
            (2, 5, "凯撒沙拉",      38.00,  "新鲜生菜配凯撒酱"),
            (2, 5, "奶油蘑菇汤",    32.00,  "法式经典浓汤"),
            (2, 6, "澳洲西冷牛排",  168.00, "精选澳洲谷饲牛肉，配黑椒汁"),
            (2, 6, "香煎三文鱼",    128.00, "挪威三文鱼，外酥里嫩"),
            (2, 6, "意大利肉酱面",  58.00,  "经典意式风味"),
            (2, 7, "提拉米苏",      42.00,  "意大利经典甜品"),
            (2, 7, "巧克力熔岩蛋糕",38.00,  "热巧克力流心，甜蜜诱惑"),
            (2, 8, "浪漫双人晚餐",  398.00, "含凯撒沙拉+奶油蘑菇汤+西冷牛排×2+提拉米苏×2"),
        ]
        for d in dishes:
            self.execute(
                "INSERT INTO dish (restaurant_id, category_id, dish_name, price, description, is_setmeal) "
                "VALUES (%s,%s,%s,%s,%s, %s)",
                (d[0], d[1], d[2], d[3], d[4], 1 if "套餐" in d[2] else 0)
            )

        # 健身设施
        facilities = [
            ("健身房",   "酒店3楼", 20, "06:00-22:00"),
            ("游泳池",   "酒店3楼", 15, "08:00-21:00"),
            ("瑜伽室",   "酒店3楼", 10, "07:00-20:00"),
            ("乒乓球室", "酒店3楼", 8,  "09:00-21:00"),
        ]
        for f in facilities:
            self.execute(
                "INSERT INTO fitness_facility (facility_name, location, capacity, open_time) "
                "VALUES (%s,%s,%s,%s)", f
            )

        # SPA服务
        spa_services = [
            ("中式推拿60分钟", 60,  298.00, "全身经络推拿、穴位按摩，缓解疲劳"),
            ("中式推拿90分钟", 90,  398.00, "全身经络推拿、穴位按摩、热敷，深层放松"),
            ("精油SPA 60分钟", 60,  398.00, "精油开背、全身按摩，芳香疗法"),
            ("精油SPA 90分钟", 90,  528.00, "精油开背、全身按摩、头部护理，全方位呵护"),
            ("热石SPA",        90,  688.00, "热石疗法、全身按摩、精油护理，极致享受"),
            ("足部护理",       45,  198.00, "足底按摩、足部去角质、足膜护理"),
        ]
        for s in spa_services:
            self.execute(
                "INSERT INTO spa_service (service_name, duration, price, description) VALUES (%s,%s,%s,%s)", s
            )

        # 技师
        technicians = [
            ("李老师", "中式推拿、穴位按摩",      "资深"),
            ("王老师", "精油SPA、热石SPA",       "高级"),
            ("张老师", "中式推拿、足部护理",      "高级"),
            ("赵老师", "精油SPA、头部护理",       "普通"),
        ]
        for t in technicians:
            self.execute(
                "INSERT INTO technician (tech_name, specialty, tech_level) VALUES (%s,%s,%s)", t
            )

        self.connection.commit()
        print("  测试数据插入完成！")

    def close(self):
        """关闭数据库连接，释放资源。"""
        if self.cursor:
            self.cursor.close()
        if self.connection:
            self.connection.close()
        print("数据库连接已关闭")


if __name__ == '__main__':
    print("=" * 50)
    print("  测试数据库连接...")
    print("=" * 50)

    db = Database()
    db.insert_sample_data()

    users = db.query("SELECT * FROM user")
    print(f"\n共有 {len(users)} 个用户：")
    for u in users:
        print(f"  - {u['username']} ({u['role']})")

    db.close()
    print("\n测试完成！")