-- =====================================================================
--  酒店服务预约管理系统 —— 数据库结构定义（唯一 schema 源）
--  ------------------------------------------------------------------
--  文件       : sql/01_schema.sql
--  数据库     : hotel_booking
--  MySQL 版本 : 8.0+（使用 CHECK 约束与 INSERT ... ON DUPLICATE KEY）
--  字符集     : utf8mb4 / utf8mb4_0900_ai_ci
--
--  说明：
--    本文件是系统数据库结构的**唯一来源**。Python 代码不再内嵌建表语句，
--    由 tools/init_db.py 按 01 -> 02 -> 03 -> 04 顺序执行。
--    因此不会出现"脚本与代码两份 schema 互相分叉"的问题。
--
--  执行顺序：01_schema.sql -> 02_views.sql -> 03_triggers.sql -> 04_seed.sql
-- =====================================================================

-- ---------------------------------------------------------------------
--  0. 创建数据库
-- ---------------------------------------------------------------------
CREATE DATABASE IF NOT EXISTS `hotel_booking`
    DEFAULT CHARACTER SET utf8mb4
    COLLATE utf8mb4_0900_ai_ci;

USE `hotel_booking`;

-- 重建表结构时需要先解除外键检查，否则 DROP TABLE 会因被引用而失败
-- （例如 room_order 引用了 user，user 就先删不掉）。
-- 脚本结束时必须重新打开。
SET FOREIGN_KEY_CHECKS = 0;


-- =====================================================================
--  一、用户与权限
-- =====================================================================

-- 1. 用户表
--    password_hash 存 PBKDF2-HMAC-SHA256 加盐哈希（见 app/security.py），
--    绝不存储明文密码。
--    is_active 支持"禁用/启用"账号，避免用 DELETE 误删历史订单。
DROP TABLE IF EXISTS `user`;
CREATE TABLE `user` (
    user_id         INT             NOT NULL AUTO_INCREMENT COMMENT '用户ID',
    username        VARCHAR(50)     NOT NULL                COMMENT '登录用户名',
    password_hash   VARCHAR(128)    NOT NULL                COMMENT '密码哈希（PBKDF2-HMAC-SHA256，含盐）',
    phone           VARCHAR(20)     DEFAULT NULL            COMMENT '手机号',
    email           VARCHAR(100)    DEFAULT NULL            COMMENT '邮箱',
    real_name       VARCHAR(50)     DEFAULT NULL            COMMENT '真实姓名',
    role            ENUM('guest','receptionist','admin') NOT NULL DEFAULT 'guest' COMMENT '角色',
    is_active       TINYINT(1)      NOT NULL DEFAULT 1      COMMENT '是否启用：1=启用 0=禁用',
    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    PRIMARY KEY (user_id),
    UNIQUE KEY uk_user_username (username),
    UNIQUE KEY uk_user_phone    (phone),
    UNIQUE KEY uk_user_email    (email),
    KEY idx_user_role_active (role, is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='用户表';


-- =====================================================================
--  二、客房业务
-- =====================================================================

-- 2. 房型表
DROP TABLE IF EXISTS `room_type`;
CREATE TABLE `room_type` (
    type_id         INT             NOT NULL AUTO_INCREMENT COMMENT '房型ID',
    type_name       VARCHAR(50)     NOT NULL                COMMENT '房型名称',
    price           DECIMAL(10,2)   NOT NULL                COMMENT '每晚价格（元）',
    max_occupancy   INT             NOT NULL                COMMENT '最大入住人数',
    description     TEXT                                    COMMENT '房型描述',
    facilities      VARCHAR(500)    DEFAULT NULL            COMMENT '设施说明',
    PRIMARY KEY (type_id),
    UNIQUE KEY uk_room_type_name (type_name),
    CONSTRAINT ck_room_type_price   CHECK (price > 0),
    CONSTRAINT ck_room_type_occup   CHECK (max_occupancy BETWEEN 1 AND 20)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='房型表';

-- 3. 房间表
--    外键改为 RESTRICT：房型下还有房间时不允许删除房型，防止误删级联清空数据。
DROP TABLE IF EXISTS `room`;
CREATE TABLE `room` (
    room_id         INT             NOT NULL AUTO_INCREMENT COMMENT '房间ID',
    room_number     VARCHAR(10)     NOT NULL                COMMENT '房间号',
    type_id         INT             NOT NULL                COMMENT '房型ID',
    floor           INT             DEFAULT NULL            COMMENT '楼层',
    status          ENUM('available','occupied','cleaning','maintenance')
                                    NOT NULL DEFAULT 'available' COMMENT '房间状态',
    PRIMARY KEY (room_id),
    UNIQUE KEY uk_room_number (room_number),
    KEY idx_room_type_status (type_id, status),
    CONSTRAINT fk_room_type FOREIGN KEY (type_id) REFERENCES `room_type`(type_id)
        ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='房间表';

-- 4. 客房订单表
--    外键全部 RESTRICT：订单是账目凭据，绝不能被级联删除。
--    复合索引 (room_id, status, check_in_date, check_out_date) 直接服务
--    "查某段时间可用房间"这个最高频查询。
DROP TABLE IF EXISTS `room_order`;
CREATE TABLE `room_order` (
    order_id        VARCHAR(24)     NOT NULL                COMMENT '订单号',
    user_id         INT             NOT NULL                COMMENT '下单用户ID',
    room_id         INT             NOT NULL                COMMENT '房间ID',
    check_in_date   DATE            NOT NULL                COMMENT '入住日期',
    check_out_date  DATE            NOT NULL                COMMENT '离店日期',
    nights          INT             NOT NULL                COMMENT '入住晚数（触发器自动计算）',
    total_price     DECIMAL(10,2)   NOT NULL                COMMENT '订单总金额',
    guest_name      VARCHAR(50)     NOT NULL                COMMENT '入住人姓名',
    guest_phone     VARCHAR(20)     DEFAULT NULL            COMMENT '入住人电话',
    status          ENUM('confirmed','checked_in','checked_out','cancelled')
                                    NOT NULL DEFAULT 'confirmed' COMMENT '订单状态',
    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    PRIMARY KEY (order_id),
    KEY idx_ro_user        (user_id, created_at),
    KEY idx_ro_availability (room_id, status, check_in_date, check_out_date),
    CONSTRAINT fk_ro_user FOREIGN KEY (user_id) REFERENCES `user`(user_id)
        ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT fk_ro_room FOREIGN KEY (room_id) REFERENCES `room`(room_id)
        ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT ck_ro_dates CHECK (check_out_date > check_in_date),
    CONSTRAINT ck_ro_price CHECK (total_price >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='客房订单表';


-- =====================================================================
--  三、餐饮业务
-- =====================================================================

-- 5. 餐厅表
DROP TABLE IF EXISTS `restaurant`;
CREATE TABLE `restaurant` (
    restaurant_id   INT             NOT NULL AUTO_INCREMENT COMMENT '餐厅ID',
    restaurant_name VARCHAR(50)     NOT NULL                COMMENT '餐厅名称',
    location        VARCHAR(100)    DEFAULT NULL            COMMENT '位置',
    open_time       VARCHAR(100)    DEFAULT NULL            COMMENT '营业时间',
    description     TEXT                                    COMMENT '描述',
    PRIMARY KEY (restaurant_id),
    UNIQUE KEY uk_restaurant_name (restaurant_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='餐厅表';

-- 6. 菜品分类表（自引用树形结构）
--    补上自引用外键，让 parent_id 真正具备引用完整性。
--    约定 parent_id = NULL 表示根分类（原设计用 0，无法建外键）。
DROP TABLE IF EXISTS `dish_category`;
CREATE TABLE `dish_category` (
    category_id     INT             NOT NULL AUTO_INCREMENT COMMENT '分类ID',
    restaurant_id   INT             NOT NULL                COMMENT '所属餐厅ID',
    parent_id       INT             DEFAULT NULL            COMMENT '父分类ID，NULL=根分类',
    category_name   VARCHAR(50)     NOT NULL                COMMENT '分类名称',
    PRIMARY KEY (category_id),
    UNIQUE KEY uk_category (restaurant_id, parent_id, category_name),
    KEY idx_category_parent (parent_id),
    CONSTRAINT fk_category_restaurant FOREIGN KEY (restaurant_id) REFERENCES `restaurant`(restaurant_id)
        ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_category_parent FOREIGN KEY (parent_id) REFERENCES `dish_category`(category_id)
        ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='菜品分类表（树形结构）';

-- 7. 菜品表
DROP TABLE IF EXISTS `dish`;
CREATE TABLE `dish` (
    dish_id         INT             NOT NULL AUTO_INCREMENT COMMENT '菜品ID',
    restaurant_id   INT             NOT NULL                COMMENT '餐厅ID',
    category_id     INT             DEFAULT NULL            COMMENT '分类ID',
    dish_name       VARCHAR(50)     NOT NULL                COMMENT '菜品名称',
    price           DECIMAL(10,2)   NOT NULL                COMMENT '价格',
    description     TEXT                                    COMMENT '描述',
    is_setmeal      TINYINT(1)      NOT NULL DEFAULT 0      COMMENT '是否套餐',
    is_available    TINYINT(1)      NOT NULL DEFAULT 1      COMMENT '是否在售',
    PRIMARY KEY (dish_id),
    KEY idx_dish_restaurant (restaurant_id, category_id),
    CONSTRAINT fk_dish_restaurant FOREIGN KEY (restaurant_id) REFERENCES `restaurant`(restaurant_id)
        ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_dish_category FOREIGN KEY (category_id) REFERENCES `dish_category`(category_id)
        ON DELETE SET NULL ON UPDATE CASCADE,
    CONSTRAINT ck_dish_price CHECK (price >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='菜品表';

-- 8. 餐饮订单表
DROP TABLE IF EXISTS `dining_order`;
CREATE TABLE `dining_order` (
    order_id        VARCHAR(24)     NOT NULL                COMMENT '订单号',
    user_id         INT             NOT NULL                COMMENT '下单用户ID',
    restaurant_id   INT             NOT NULL                COMMENT '餐厅ID',
    table_number    VARCHAR(10)     DEFAULT NULL            COMMENT '桌号',
    dining_date     DATE            NOT NULL                COMMENT '用餐日期',
    dining_time     TIME            NOT NULL                COMMENT '用餐时间',
    guest_count     INT             NOT NULL                COMMENT '用餐人数',
    total_price     DECIMAL(10,2)   NOT NULL DEFAULT 0      COMMENT '总金额（由明细汇总）',
    status          ENUM('confirmed','dining','completed','cancelled')
                                    NOT NULL DEFAULT 'confirmed' COMMENT '订单状态',
    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    PRIMARY KEY (order_id),
    KEY idx_do_user (user_id, created_at),
    KEY idx_do_slot (restaurant_id, dining_date, dining_time),
    CONSTRAINT fk_do_user FOREIGN KEY (user_id) REFERENCES `user`(user_id)
        ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT fk_do_restaurant FOREIGN KEY (restaurant_id) REFERENCES `restaurant`(restaurant_id)
        ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT ck_do_guest_count CHECK (guest_count > 0),
    CONSTRAINT ck_do_price CHECK (total_price >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='餐饮订单表';

-- 9. 餐饮订单明细表（新增）
--    原系统餐饮订单只能"订座位"，没有菜品明细，total_price 恒为 0，
--    管理端统计的"餐饮收入"因此永远是 0。补上明细表使金额可真实汇总。
DROP TABLE IF EXISTS `dining_order_item`;
CREATE TABLE `dining_order_item` (
    item_id         INT             NOT NULL AUTO_INCREMENT COMMENT '明细ID',
    order_id        VARCHAR(24)     NOT NULL                COMMENT '订单号',
    dish_id         INT             NOT NULL                COMMENT '菜品ID',
    quantity        INT             NOT NULL                COMMENT '数量',
    unit_price      DECIMAL(10,2)   NOT NULL                COMMENT '下单时单价（价格快照）',
    subtotal        DECIMAL(10,2)   NOT NULL                COMMENT '小计（触发器自动计算）',
    PRIMARY KEY (item_id),
    UNIQUE KEY uk_item_order_dish (order_id, dish_id),
    KEY idx_item_dish (dish_id),
    CONSTRAINT fk_item_order FOREIGN KEY (order_id) REFERENCES `dining_order`(order_id)
        ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_item_dish FOREIGN KEY (dish_id) REFERENCES `dish`(dish_id)
        ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT ck_item_qty CHECK (quantity > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='餐饮订单明细表';


-- =====================================================================
--  四、健身业务
-- =====================================================================

-- 10. 健身设施表
DROP TABLE IF EXISTS `fitness_facility`;
CREATE TABLE `fitness_facility` (
    facility_id     INT             NOT NULL AUTO_INCREMENT COMMENT '设施ID',
    facility_name   VARCHAR(50)     NOT NULL                COMMENT '设施名称',
    location        VARCHAR(100)    DEFAULT NULL            COMMENT '位置',
    capacity        INT             NOT NULL                COMMENT '单时段最大容量',
    open_time       VARCHAR(50)     DEFAULT NULL            COMMENT '开放时间',
    status          ENUM('available','maintenance') NOT NULL DEFAULT 'available' COMMENT '状态',
    PRIMARY KEY (facility_id),
    UNIQUE KEY uk_facility_name (facility_name),
    CONSTRAINT ck_facility_capacity CHECK (capacity > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='健身设施表';

-- 11. 健身预约表
DROP TABLE IF EXISTS `fitness_booking`;
CREATE TABLE `fitness_booking` (
    booking_id      VARCHAR(24)     NOT NULL                COMMENT '预约单号',
    user_id         INT             NOT NULL                COMMENT '用户ID',
    facility_id     INT             NOT NULL                COMMENT '设施ID',
    booking_date    DATE            NOT NULL                COMMENT '预约日期',
    time_slot       VARCHAR(20)     NOT NULL                COMMENT '时间段',
    guest_count     INT             NOT NULL DEFAULT 1      COMMENT '人数',
    status          ENUM('confirmed','completed','cancelled')
                                    NOT NULL DEFAULT 'confirmed' COMMENT '状态',
    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    PRIMARY KEY (booking_id),
    KEY idx_fb_user (user_id, created_at),
    KEY idx_fb_slot (facility_id, booking_date, time_slot, status),
    CONSTRAINT fk_fb_user FOREIGN KEY (user_id) REFERENCES `user`(user_id)
        ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT fk_fb_facility FOREIGN KEY (facility_id) REFERENCES `fitness_facility`(facility_id)
        ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT ck_fb_guest_count CHECK (guest_count > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='健身预约表';


-- =====================================================================
--  五、SPA 业务
-- =====================================================================

-- 12. SPA服务表
DROP TABLE IF EXISTS `spa_service`;
CREATE TABLE `spa_service` (
    service_id      INT             NOT NULL AUTO_INCREMENT COMMENT '服务ID',
    service_name    VARCHAR(50)     NOT NULL                COMMENT '服务名称',
    duration        INT             NOT NULL                COMMENT '时长（分钟）',
    price           DECIMAL(10,2)   NOT NULL                COMMENT '价格',
    description     TEXT                                    COMMENT '描述',
    PRIMARY KEY (service_id),
    UNIQUE KEY uk_spa_service_name (service_name),
    CONSTRAINT ck_spa_duration CHECK (duration > 0),
    CONSTRAINT ck_spa_price CHECK (price > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='SPA服务表';

-- 13. 技师表
DROP TABLE IF EXISTS `technician`;
CREATE TABLE `technician` (
    tech_id         INT             NOT NULL AUTO_INCREMENT COMMENT '技师ID',
    tech_name       VARCHAR(50)     NOT NULL                COMMENT '技师姓名',
    specialty       VARCHAR(100)    DEFAULT NULL            COMMENT '擅长项目',
    tech_level      VARCHAR(20)     NOT NULL DEFAULT '普通'  COMMENT '级别：普通/高级/资深',
    rating          DECIMAL(3,1)    NOT NULL DEFAULT 5.0    COMMENT '综合评分（0-5）',
    status          ENUM('available','busy','off_duty') NOT NULL DEFAULT 'available' COMMENT '工作状态',
    PRIMARY KEY (tech_id),
    CONSTRAINT ck_tech_rating CHECK (rating BETWEEN 0 AND 5)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='技师表';

-- 14. 技师排班表
--    原系统建了这张表却零读写（纯空表摆设）。这里补上唯一约束与索引，
--    使其可真正支撑 SPA 排班；并提供 v_tech_schedule_today 视图查询。
DROP TABLE IF EXISTS `tech_schedule`;
CREATE TABLE `tech_schedule` (
    schedule_id     INT             NOT NULL AUTO_INCREMENT COMMENT '排班ID',
    tech_id         INT             NOT NULL                COMMENT '技师ID',
    work_date       DATE            NOT NULL                COMMENT '工作日期',
    time_slot       VARCHAR(20)     NOT NULL                COMMENT '时间段',
    is_booked       TINYINT(1)      NOT NULL DEFAULT 0      COMMENT '是否已被预约',
    PRIMARY KEY (schedule_id),
    UNIQUE KEY uk_schedule (tech_id, work_date, time_slot),
    KEY idx_schedule_date (work_date, is_booked),
    CONSTRAINT fk_schedule_tech FOREIGN KEY (tech_id) REFERENCES `technician`(tech_id)
        ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='技师排班表';

-- 15. SPA预约表
DROP TABLE IF EXISTS `spa_booking`;
CREATE TABLE `spa_booking` (
    booking_id      VARCHAR(24)     NOT NULL                COMMENT '预约单号',
    user_id         INT             NOT NULL                COMMENT '用户ID',
    service_id      INT             NOT NULL                COMMENT '服务ID',
    tech_id         INT             NOT NULL                COMMENT '技师ID',
    booking_date    DATE            NOT NULL                COMMENT '预约日期',
    booking_time    TIME            NOT NULL                COMMENT '预约时间',
    room_number     VARCHAR(10)     DEFAULT NULL            COMMENT 'SPA房间号',
    price           DECIMAL(10,2)   NOT NULL DEFAULT 0      COMMENT '服务金额（下单快照）',
    status          ENUM('confirmed','in_progress','completed','cancelled')
                                    NOT NULL DEFAULT 'confirmed' COMMENT '状态',
    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    PRIMARY KEY (booking_id),
    KEY idx_sb_user (user_id, created_at),
    KEY idx_sb_slot (tech_id, booking_date, booking_time, status),
    CONSTRAINT fk_sb_user FOREIGN KEY (user_id) REFERENCES `user`(user_id)
        ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT fk_sb_service FOREIGN KEY (service_id) REFERENCES `spa_service`(service_id)
        ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT fk_sb_tech FOREIGN KEY (tech_id) REFERENCES `technician`(tech_id)
        ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='SPA预约表';


-- =====================================================================
--  六、洗衣业务
-- =====================================================================

-- 16. 洗衣订单表
--    pickup_time / delivery_time 原设计建了列却从不写入，
--    现由触发器在状态流转时自动记录（见 03_triggers.sql）。
DROP TABLE IF EXISTS `laundry_order`;
CREATE TABLE `laundry_order` (
    order_id        VARCHAR(24)     NOT NULL                COMMENT '订单号',
    user_id         INT             NOT NULL                COMMENT '用户ID',
    service_type    ENUM('wash','dry_clean','iron','express_wash','express_dry')
                                    NOT NULL                COMMENT '服务类型',
    item_count      INT             NOT NULL                COMMENT '衣物数量',
    unit_price      DECIMAL(10,2)   NOT NULL                COMMENT '单价（下单快照）',
    total_price     DECIMAL(10,2)   NOT NULL                COMMENT '总金额',
    room_number     VARCHAR(10)     NOT NULL                COMMENT '房间号',
    expected_pickup DATETIME        DEFAULT NULL            COMMENT '用户预约的取衣时间',
    pickup_time     DATETIME        DEFAULT NULL            COMMENT '实际取衣时间（触发器写入）',
    delivery_time   DATETIME        DEFAULT NULL            COMMENT '实际送达时间（触发器写入）',
    status          ENUM('pending','picked_up','processing','delivered','cancelled')
                                    NOT NULL DEFAULT 'pending' COMMENT '状态',
    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    PRIMARY KEY (order_id),
    KEY idx_lo_user (user_id, created_at),
    KEY idx_lo_queue (status, service_type, created_at),
    CONSTRAINT fk_lo_user FOREIGN KEY (user_id) REFERENCES `user`(user_id)
        ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT ck_lo_item_count CHECK (item_count > 0),
    CONSTRAINT ck_lo_price CHECK (total_price >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='洗衣订单表';


-- =====================================================================
--  七、支付与评价
-- =====================================================================

-- 17. 支付流水表（新增）
--    原管理端的"收入"是把各订单表按状态求和，未收款的 'confirmed' 订单
--    也被算成收入，账目不成立。补支付表后收入从真实流水汇总。
DROP TABLE IF EXISTS `payment`;
CREATE TABLE `payment` (
    payment_id      INT             NOT NULL AUTO_INCREMENT COMMENT '支付ID',
    payment_no      VARCHAR(24)     NOT NULL                COMMENT '支付流水号',
    order_id        VARCHAR(24)     NOT NULL                COMMENT '关联订单号',
    order_type      ENUM('room','dining','fitness','spa','laundry') NOT NULL COMMENT '订单类型',
    user_id         INT             NOT NULL                COMMENT '付款用户ID',
    amount          DECIMAL(10,2)   NOT NULL                COMMENT '支付金额',
    method          ENUM('cash','card','wechat','alipay','room_charge')
                                    NOT NULL DEFAULT 'cash' COMMENT '支付方式',
    status          ENUM('paid','refunded') NOT NULL DEFAULT 'paid' COMMENT '支付状态',
    paid_at         DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '支付时间',
    PRIMARY KEY (payment_id),
    UNIQUE KEY uk_payment_no (payment_no),
    KEY idx_pay_order (order_type, order_id),
    KEY idx_pay_time (paid_at),
    CONSTRAINT fk_pay_user FOREIGN KEY (user_id) REFERENCES `user`(user_id)
        ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT ck_pay_amount CHECK (amount >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='支付流水表';

-- 18. 评价表
--    原表无唯一约束，同一订单可被无限重复评价。补 UNIQUE(user_id, order_id, order_type)。
--    order_id 是跨 5 张订单表的多态引用，无法用外键表达，
--    改由触发器 BEFORE INSERT 校验其存在性（见 03_triggers.sql）。
DROP TABLE IF EXISTS `review`;
CREATE TABLE `review` (
    review_id       INT             NOT NULL AUTO_INCREMENT COMMENT '评价ID',
    user_id         INT             NOT NULL                COMMENT '用户ID',
    order_id        VARCHAR(24)     NOT NULL                COMMENT '订单号',
    order_type      ENUM('room','dining','fitness','spa','laundry') NOT NULL COMMENT '订单类型',
    rating          TINYINT         NOT NULL                COMMENT '评分 1-5',
    content         TEXT                                    COMMENT '评价内容',
    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '评价时间',
    PRIMARY KEY (review_id),
    UNIQUE KEY uk_review_order (user_id, order_id, order_type),
    KEY idx_review_time (created_at),
    CONSTRAINT fk_review_user FOREIGN KEY (user_id) REFERENCES `user`(user_id)
        ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT ck_review_rating CHECK (rating BETWEEN 1 AND 5)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='评价表';

-- 恢复外键检查（与文件开头的 SET FOREIGN_KEY_CHECKS = 0 配对）
SET FOREIGN_KEY_CHECKS = 1;
