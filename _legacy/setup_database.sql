-- 1. 用户表
-- 存储所有系统用户（客人、前台、管理员）的信息
-- ----------------------------
CREATE TABLE IF NOT EXISTS user (
    user_id         INT             PRIMARY KEY AUTO_INCREMENT  COMMENT '用户唯一ID，自增',
    username        VARCHAR(50)     UNIQUE NOT NULL             COMMENT '登录用户名，不可重复',
    password        VARCHAR(100)    NOT NULL                    COMMENT '登录密码（建议加密存储）',
    phone           VARCHAR(20)     UNIQUE DEFAULT NULL         COMMENT '手机号，唯一',
    email           VARCHAR(100)    UNIQUE DEFAULT NULL         COMMENT '邮箱，唯一',
    real_name       VARCHAR(50)     DEFAULT NULL                COMMENT '真实姓名',
    role            ENUM('guest', 'receptionist', 'admin') 
                                    DEFAULT 'guest'             COMMENT '角色：guest=客人, receptionist=前台, admin=管理员',
    created_at      DATETIME        DEFAULT CURRENT_TIMESTAMP   COMMENT '账户创建时间'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='用户表';

-- ----------------------------
-- 2. 房型表
-- 存储酒店提供的不同房型及其价格
-- ----------------------------
CREATE TABLE IF NOT EXISTS room_type (
    type_id         INT             PRIMARY KEY AUTO_INCREMENT  COMMENT '房型唯一ID',
    type_name       VARCHAR(50)     NOT NULL                    COMMENT '房型名称，如"标准单人间"',
    price           DECIMAL(10,2)   NOT NULL                    COMMENT '每晚价格（元）',
    max_occupancy   INT             NOT NULL                    COMMENT '最大可入住人数',
    description     TEXT                                        COMMENT '房型描述',
    facilities      VARCHAR(500)                                COMMENT '房间设施说明，如"WiFi、空调"'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='房型表';

-- ----------------------------
-- 3. 房间表
-- 存储酒店每一间具体房间的信息
-- ----------------------------
CREATE TABLE IF NOT EXISTS room (
    room_id         INT             PRIMARY KEY AUTO_INCREMENT  COMMENT '房间唯一ID',
    room_number     VARCHAR(10)     UNIQUE NOT NULL             COMMENT '房间号，如"301"',
    type_id         INT             NOT NULL                    COMMENT '所属房型ID，关联room_type表',
    floor           INT                                         COMMENT '所在楼层',
    status          ENUM('available','occupied','cleaning','maintenance')
                                    DEFAULT 'available'         COMMENT '房间状态：available=可用, occupied=已入住, cleaning=打扫中, maintenance=维护中',
    FOREIGN KEY (type_id) REFERENCES room_type(type_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='房间表';

-- ----------------------------
-- 4. 客房订单表
-- 存储客人的客房预订记录
-- ----------------------------
CREATE TABLE IF NOT EXISTS room_order (
    order_id        VARCHAR(20)     PRIMARY KEY                 COMMENT '订单号，如"RM20260510001"',
    user_id         INT             NOT NULL                    COMMENT '下单用户ID',
    room_id         INT             NOT NULL                    COMMENT '预订的房间ID',
    check_in_date   DATE            NOT NULL                    COMMENT '入住日期',
    check_out_date  DATE            NOT NULL                    COMMENT '离店日期',
    total_price     DECIMAL(10,2)   NOT NULL                    COMMENT '订单总金额',
    guest_name      VARCHAR(50)     NOT NULL                    COMMENT '入住人姓名',
    guest_phone     VARCHAR(20)                                 COMMENT '入住人联系电话',
    status          ENUM('confirmed','checked_in','checked_out','cancelled')
                                    DEFAULT 'confirmed'         COMMENT '订单状态',
    created_at      DATETIME        DEFAULT CURRENT_TIMESTAMP   COMMENT '订单创建时间',
    FOREIGN KEY (user_id) REFERENCES user(user_id) ON DELETE CASCADE,
    FOREIGN KEY (room_id) REFERENCES room(room_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='客房订单表';

-- ----------------------------
-- 5. 餐厅表
-- ----------------------------
CREATE TABLE IF NOT EXISTS restaurant (
    restaurant_id   INT             PRIMARY KEY AUTO_INCREMENT  COMMENT '餐厅唯一ID',
    restaurant_name VARCHAR(50)     NOT NULL                    COMMENT '餐厅名称',
    location        VARCHAR(100)                                COMMENT '餐厅位置描述',
    open_time       VARCHAR(50)                                 COMMENT '营业时间说明',
    description     TEXT                                        COMMENT '餐厅描述'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='餐厅表';

-- ----------------------------
-- 6. 菜品分类表（树形结构存储）
-- parent_id 指向父分类，实现无限层级分类
-- ----------------------------
CREATE TABLE IF NOT EXISTS dish_category (
    category_id     INT             PRIMARY KEY AUTO_INCREMENT  COMMENT '分类ID',
    restaurant_id   INT             NOT NULL                    COMMENT '所属餐厅ID',
    parent_id       INT             DEFAULT 0                   COMMENT '父分类ID，0表示根分类',
    category_name   VARCHAR(50)     NOT NULL                    COMMENT '分类名称',
    FOREIGN KEY (restaurant_id) REFERENCES restaurant(restaurant_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='菜品分类表';

-- ----------------------------
-- 7. 菜品表
-- ----------------------------
CREATE TABLE IF NOT EXISTS dish (
    dish_id         INT             PRIMARY KEY AUTO_INCREMENT  COMMENT '菜品唯一ID',
    restaurant_id   INT             NOT NULL                    COMMENT '所属餐厅ID',
    category_id     INT                                         COMMENT '所属分类ID',
    dish_name       VARCHAR(50)     NOT NULL                    COMMENT '菜品名称',
    price           DECIMAL(10,2)   NOT NULL                    COMMENT '价格',
    description     TEXT                                        COMMENT '菜品描述',
    is_setmeal      TINYINT         DEFAULT 0                   COMMENT '是否为套餐：0=单点, 1=套餐',
    FOREIGN KEY (restaurant_id) REFERENCES restaurant(restaurant_id) ON DELETE CASCADE,
    FOREIGN KEY (category_id)   REFERENCES dish_category(category_id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='菜品表';

-- ----------------------------
-- 8. 餐饮订单表
-- ----------------------------
CREATE TABLE IF NOT EXISTS dining_order (
    order_id        VARCHAR(20)     PRIMARY KEY                 COMMENT '订单号',
    user_id         INT             NOT NULL                    COMMENT '下单用户ID',
    restaurant_id   INT             NOT NULL                    COMMENT '餐厅ID',
    table_number    VARCHAR(10)     NOT NULL                    COMMENT '预订的桌号',
    dining_date     DATE            NOT NULL                    COMMENT '用餐日期',
    dining_time     TIME            NOT NULL                    COMMENT '用餐时间',
    guest_count     INT             NOT NULL                    COMMENT '用餐人数',
    total_price     DECIMAL(10,2)   DEFAULT 0                   COMMENT '总金额',
    status          ENUM('confirmed','dining','completed','cancelled')
                                    DEFAULT 'confirmed'         COMMENT '订单状态',
    created_at      DATETIME        DEFAULT CURRENT_TIMESTAMP   COMMENT '创建时间',
    FOREIGN KEY (user_id)       REFERENCES user(user_id)             ON DELETE CASCADE,
    FOREIGN KEY (restaurant_id) REFERENCES restaurant(restaurant_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='餐饮订单表';

-- ----------------------------
-- 9. 健身设施表
-- ----------------------------
CREATE TABLE IF NOT EXISTS fitness_facility (
    facility_id     INT             PRIMARY KEY AUTO_INCREMENT  COMMENT '设施唯一ID',
    facility_name   VARCHAR(50)     NOT NULL                    COMMENT '设施名称，如"健身房"',
    location        VARCHAR(100)                                COMMENT '设施位置',
    capacity        INT             NOT NULL                    COMMENT '最大容纳人数',
    open_time       VARCHAR(50)                                 COMMENT '开放时间说明',
    status          ENUM('available','maintenance') 
                                    DEFAULT 'available'         COMMENT '设施状态'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='健身设施表';

-- ----------------------------
-- 10. 健身预约表
-- ----------------------------
CREATE TABLE IF NOT EXISTS fitness_booking (
    booking_id      VARCHAR(20)     PRIMARY KEY                 COMMENT '预约单号',
    user_id         INT             NOT NULL                    COMMENT '用户ID',
    facility_id     INT             NOT NULL                    COMMENT '设施ID',
    booking_date    DATE            NOT NULL                    COMMENT '预约日期',
    time_slot       VARCHAR(20)     NOT NULL                    COMMENT '时间段，如"08:00-10:00"',
    guest_count     INT             DEFAULT 1                   COMMENT '预约人数',
    status          ENUM('confirmed','completed','cancelled')
                                    DEFAULT 'confirmed'         COMMENT '预约状态',
    created_at      DATETIME        DEFAULT CURRENT_TIMESTAMP   COMMENT '创建时间',
    FOREIGN KEY (user_id)     REFERENCES user(user_id)                   ON DELETE CASCADE,
    FOREIGN KEY (facility_id) REFERENCES fitness_facility(facility_id)   ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='健身预约表';

-- ----------------------------
-- 11. SPA服务表
-- ----------------------------
CREATE TABLE IF NOT EXISTS spa_service (
    service_id      INT             PRIMARY KEY AUTO_INCREMENT  COMMENT 'SPA服务ID',
    service_name    VARCHAR(50)     NOT NULL                    COMMENT '服务名称，如"精油SPA"',
    duration        INT             NOT NULL                    COMMENT '服务时长（分钟）',
    price           DECIMAL(10,2)   NOT NULL                    COMMENT '服务价格',
    description     TEXT                                        COMMENT '服务详细描述'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='SPA服务表';

-- ----------------------------
-- 12. 技师表
-- ----------------------------
CREATE TABLE IF NOT EXISTS technician (
    tech_id         INT             PRIMARY KEY AUTO_INCREMENT  COMMENT '技师唯一ID',
    tech_name       VARCHAR(50)     NOT NULL                    COMMENT '技师姓名',
    specialty       VARCHAR(100)                                COMMENT '擅长项目',
    level           VARCHAR(20)     DEFAULT '普通'              COMMENT '技师级别：普通/高级/资深',
    rating          DECIMAL(3,1)    DEFAULT 5.0                 COMMENT '综合评分（1-5）',
    status          ENUM('available','busy','off_duty')
                                    DEFAULT 'available'         COMMENT '工作状态'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='技师表';

-- ----------------------------
-- 13. 技师排班表
-- 存储技师每天的可用时间段
-- ----------------------------
CREATE TABLE IF NOT EXISTS tech_schedule (
    schedule_id     INT             PRIMARY KEY AUTO_INCREMENT  COMMENT '排班记录ID',
    tech_id         INT             NOT NULL                    COMMENT '技师ID',
    work_date       DATE            NOT NULL                    COMMENT '工作日期',
    time_slot       VARCHAR(20)     NOT NULL                    COMMENT '时间段',
    is_booked       TINYINT         DEFAULT 0                   COMMENT '是否已被预约：0=空闲, 1=已预约',
    FOREIGN KEY (tech_id) REFERENCES technician(tech_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='技师排班表';

-- ----------------------------
-- 14. SPA预约表
-- ----------------------------
CREATE TABLE IF NOT EXISTS spa_booking (
    booking_id      VARCHAR(20)     PRIMARY KEY                 COMMENT '预约单号',
    user_id         INT             NOT NULL                    COMMENT '用户ID',
    service_id      INT             NOT NULL                    COMMENT 'SPA服务ID',
    tech_id         INT             NOT NULL                    COMMENT '预约的技师ID',
    booking_date    DATE            NOT NULL                    COMMENT '预约日期',
    booking_time    TIME            NOT NULL                    COMMENT '预约时间',
    room_number     VARCHAR(10)                                 COMMENT 'SPA房间号',
    status          ENUM('confirmed','in_progress','completed','cancelled')
                                    DEFAULT 'confirmed'         COMMENT '预约状态',
    created_at      DATETIME        DEFAULT CURRENT_TIMESTAMP   COMMENT '创建时间',
    FOREIGN KEY (user_id)    REFERENCES user(user_id)          ON DELETE CASCADE,
    FOREIGN KEY (service_id) REFERENCES spa_service(service_id) ON DELETE CASCADE,
    FOREIGN KEY (tech_id)    REFERENCES technician(tech_id)     ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='SPA预约表';

-- ----------------------------
-- 15. 洗衣订单表
-- ----------------------------
CREATE TABLE IF NOT EXISTS laundry_order (
    order_id        VARCHAR(20)     PRIMARY KEY                 COMMENT '订单号',
    user_id         INT             NOT NULL                    COMMENT '用户ID',
    service_type    ENUM('wash','dry_clean','iron','express_wash','express_dry')
                                    NOT NULL                    COMMENT '服务类型：wash=水洗, dry_clean=干洗, iron=熨烫, express_wash=加急水洗, express_dry=加急干洗',
    item_count      INT             NOT NULL                    COMMENT '衣物数量',
    total_price     DECIMAL(10,2)   NOT NULL                    COMMENT '总金额',
    pickup_time     DATETIME                                    COMMENT '预约取衣时间',
    delivery_time   DATETIME                                    COMMENT '预计送衣时间',
    room_number     VARCHAR(10)     NOT NULL                    COMMENT '房间号',
    status          ENUM('pending','picked_up','processing','delivered','cancelled')
                                    DEFAULT 'pending'           COMMENT '订单状态',
    created_at      DATETIME        DEFAULT CURRENT_TIMESTAMP   COMMENT '创建时间',
    FOREIGN KEY (user_id) REFERENCES user(user_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='洗衣订单表';

-- ----------------------------
-- 16. 评价表
-- ----------------------------
CREATE TABLE IF NOT EXISTS review (
    review_id       INT             PRIMARY KEY AUTO_INCREMENT  COMMENT '评价唯一ID',
    user_id         INT             NOT NULL                    COMMENT '评价用户ID',
    order_id        VARCHAR(20)     NOT NULL                    COMMENT '关联的订单号',
    order_type      VARCHAR(20)     NOT NULL                    COMMENT '订单类型：room/dining/fitness/spa/laundry',
    rating          TINYINT         NOT NULL                    COMMENT '评分（1-5星）',
    content         TEXT                                        COMMENT '评价文字内容',
    created_at      DATETIME        DEFAULT CURRENT_TIMESTAMP   COMMENT '评价时间',
    FOREIGN KEY (user_id) REFERENCES user(user_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='评价表';

-- ============================================
-- 插入测试数据
-- ============================================

-- 插入默认管理员和前台账号
-- 密码目前用明文，实际开发中应该用加密如bcrypt
INSERT INTO user (username, password, real_name, role) VALUES
('admin',      'admin123',   '系统管理员',   'admin'),
('reception',  'recep123',   '前台小王',     'receptionist');

-- 插入房型数据
INSERT INTO room_type (type_name, price, max_occupancy, description, facilities) VALUES
('标准单人间',   298.00, 1, '经济实惠的单人间，适合商务出差', 'WiFi、空调、独立卫浴、电视'),
('标准双人间',   398.00, 2, '舒适的双人间，适合结伴出行', 'WiFi、空调、独立卫浴、电视、书桌'),
('商务套房',     698.00, 2, '宽敞的商务套房，配备办公区域', 'WiFi、空调、独立卫浴、电视、迷你吧、书桌'),
('豪华总统套房', 1888.00,4, '顶级奢华套房，尽享尊贵体验', 'WiFi、空调、独立卫浴、电视、迷你吧、浴缸、景观阳台、客厅');

-- 为每种房型插入4个房间
INSERT INTO room (room_number, type_id, floor) VALUES
('101', 1, 1), ('102', 1, 1), ('103', 1, 1), ('104', 1, 1),
('201', 2, 2), ('202', 2, 2), ('203', 2, 2), ('204', 2, 2),
('301', 3, 3), ('302', 3, 3), ('303', 3, 3), ('304', 3, 3),
('401', 4, 4), ('402', 4, 4), ('403', 4, 4), ('404', 4, 4);

-- 插入餐厅数据
INSERT INTO restaurant (restaurant_name, location, open_time, description) VALUES
('中餐厅·雅苑', '酒店2楼东侧', '早餐7:00-9:30 / 午餐11:30-13:30 / 晚餐17:30-20:30', '提供精致中式料理，汇聚各地名菜'),
('西餐厅·蓝海', '酒店2楼西侧', '午餐11:30-14:00 / 晚餐17:30-21:00',   '浪漫西式用餐体验，精选进口食材');

-- 插入菜品分类
INSERT INTO dish_category (category_id, restaurant_id, parent_id, category_name) VALUES
(1, 1, 0, '中式冷菜'),
(2, 1, 0, '中式热菜'),
(3, 1, 0, '中式汤品'),
(4, 1, 0, '中式套餐'),
(5, 2, 0, '西式前菜'),
(6, 2, 0, '西式主菜'),
(7, 2, 0, '西式甜点'),
(8, 2, 0, '西式套餐');

-- 插入菜品
INSERT INTO dish (restaurant_id, category_id, dish_name, price, description, is_setmeal) VALUES
(1, 1, '凉拌黄瓜',       22.00,  '爽脆可口的开胃小菜', 0),
(1, 1, '皮蛋豆腐',       28.00,  '经典中式冷菜', 0),
(1, 2, '宫保鸡丁',       48.00,  '经典川菜，麻辣鲜香', 0),
(1, 2, '清蒸鲈鱼',       88.00,  '新鲜鲈鱼，清蒸保留原味', 0),
(1, 2, '红烧排骨',       58.00,  '软烂入味，酱香浓郁', 0),
(1, 3, '番茄蛋花汤',     18.00,  '家常美味汤品', 0),
(1, 3, '排骨莲藕汤',     38.00,  '慢火炖煮，营养滋补', 0),
(1, 4, '商务双人套餐A',  168.00, '含宫保鸡丁+清蒸鲈鱼+番茄蛋花汤+米饭×2', 1),
(1, 4, '家庭四人套餐B',  298.00, '含红烧排骨+宫保鸡丁+清蒸鲈鱼+排骨莲藕汤+米饭×4', 1);

INSERT INTO dish (restaurant_id, category_id, dish_name, price, description, is_setmeal) VALUES
(2, 5, '凯撒沙拉',       38.00,  '新鲜罗马生菜配凯撒酱', 0),
(2, 5, '奶油蘑菇汤',     32.00,  '法式经典浓汤', 0),
(2, 6, '澳洲西冷牛排',   168.00, '精选澳洲谷饲牛肉，配黑椒汁', 0),
(2, 6, '香煎三文鱼',     128.00, '挪威三文鱼，外酥里嫩', 0),
(2, 6, '意大利肉酱面',   58.00,  '经典意式风味', 0),
(2, 7, '提拉米苏',       42.00,  '意大利经典甜品', 0),
(2, 7, '巧克力熔岩蛋糕', 38.00,  '热巧克力流心，甜蜜诱惑', 0),
(2, 8, '浪漫双人晚餐',   398.00, '含凯撒沙拉+奶油蘑菇汤+西冷牛排×2+提拉米苏×2+红酒×2', 1);

-- 插入健身设施
INSERT INTO fitness_facility (facility_name, location, capacity, open_time) VALUES
('健身房',   '酒店3楼', 20, '06:00-22:00'),
('游泳池',   '酒店3楼', 15, '08:00-21:00'),
('瑜伽室',   '酒店3楼', 10, '07:00-20:00'),
('乒乓球室', '酒店3楼', 8,  '09:00-21:00');

-- 插入SPA服务
INSERT INTO spa_service (service_name, duration, price, description) VALUES
('中式推拿60分钟', 60,  298.00, '全身经络推拿、穴位按摩，缓解疲劳'),
('中式推拿90分钟', 90,  398.00, '全身经络推拿、穴位按摩、热敷，深层放松'),
('精油SPA 60分钟', 60,  398.00, '精油开背、全身按摩，芳香疗法'),
('精油SPA 90分钟', 90,  528.00, '精油开背、全身按摩、头部护理，全方位呵护'),
('热石SPA',        90,  688.00, '热石疗法、全身按摩、精油护理，极致享受'),
('足部护理',       45,  198.00, '足底按摩、足部去角质、足膜护理');

-- 插入技师
INSERT INTO technician (tech_name, specialty, level) VALUES
('李老师', '中式推拿、穴位按摩', '资深'),
('王老师', '精油SPA、热石SPA',  '高级'),
('张老师', '中式推拿、足部护理', '高级'),
('赵老师', '精油SPA、头部护理',  '普通');
