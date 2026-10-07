-- =====================================================================
--  宾馆客房管理系统 —— 数据库结构定义（唯一 schema 源）
--  ------------------------------------------------------------------
--  文件       : sql/01_schema.sql
--  数据库     : hotel_booking
--  MySQL 版本 : 8.0+（使用 CHECK 约束与 INSERT ... ON DUPLICATE KEY）
--  字符集     : utf8mb4 / utf8mb4_0900_ai_ci
--  范围       : 选题19 宾馆客房管理系统 —— 客房主线，共 9 张表
--               原设计中的餐饮/健身/SPA/洗衣 4 条业务线已按题目要求整体移除；
--               本版本补齐了题目要求 (1)(3)(4)(5) 对应的
--               团体登记/团体结账（guest_group、settlement）、
--               客人信息查询字段（room_order.id_card）与
--               价格变更留痕（price_change_log）。
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


-- ---------------------------------------------------------------------
--  0.1 清理历史对象（已移除的业务线）
--
--  说明：本版本按课程题目（选题19 宾馆客房管理系统）只保留客房主线，
--  餐饮/健身/SPA/洗衣 4 条业务线已被移除。下面这些 DROP 语句本身不创建
--  任何东西，作用是让**从旧版本升级上来的数据库**不留残留表 ——
--  否则旧库里的 dining_order 等表会一直存在，information_schema 统计
--  与"关于系统"页的数字都会虚高。全新数据库上执行时它们只是空操作。
-- ---------------------------------------------------------------------
DROP TABLE IF EXISTS `dining_order_item`;
DROP TABLE IF EXISTS `dining_order`;
DROP TABLE IF EXISTS `dish`;
DROP TABLE IF EXISTS `dish_category`;
DROP TABLE IF EXISTS `restaurant`;
DROP TABLE IF EXISTS `fitness_booking`;
DROP TABLE IF EXISTS `fitness_facility`;
DROP TABLE IF EXISTS `spa_booking`;
DROP TABLE IF EXISTS `tech_schedule`;
DROP TABLE IF EXISTS `technician`;
DROP TABLE IF EXISTS `spa_service`;
DROP TABLE IF EXISTS `laundry_order`;


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


-- =====================================================================
--  三、团体与结账单
--    建表顺序由外键依赖决定：room_order 需要引用 guest_group 与 settlement，
--    所以这两张表必须排在被引用的顺序之前。
-- =====================================================================

-- 4. 团体单表
--    题目要求 (1)「能够支持团体登记和团体结账」：
--    一张团体单下挂多张客房订单（相同的入住/离店日期），
--    团体结账时按 group_id 一次汇总收款并生成一张结账单。
DROP TABLE IF EXISTS `guest_group`;
CREATE TABLE `guest_group` (
    group_id        INT             NOT NULL AUTO_INCREMENT COMMENT '团体单ID',
    group_name      VARCHAR(80)     NOT NULL                COMMENT '团体名称',
    contact_name    VARCHAR(50)     NOT NULL                COMMENT '联系人姓名',
    contact_phone   VARCHAR(20)     DEFAULT NULL            COMMENT '联系人电话',
    id_card         VARCHAR(20)     DEFAULT NULL            COMMENT '联系人证件号',
    leader_user_id  INT             DEFAULT NULL            COMMENT '团体负责人账号，可为空',
    check_in_date   DATE            NOT NULL                COMMENT '全团入住日期',
    check_out_date  DATE            NOT NULL                COMMENT '全团离店日期',
    remark          VARCHAR(200)    DEFAULT NULL            COMMENT '备注',
    status          ENUM('reserved','checked_in','checked_out','cancelled')
                                    NOT NULL DEFAULT 'reserved' COMMENT '团体状态',
    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '登记时间',
    PRIMARY KEY (group_id),
    UNIQUE KEY uk_group_name_start (group_name, check_in_date),
    KEY idx_group_status (status, check_in_date),
    CONSTRAINT fk_group_leader FOREIGN KEY (leader_user_id) REFERENCES `user`(user_id)
        ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT ck_group_dates CHECK (check_out_date > check_in_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='团体登记表';

-- 5. 结账单表
--    题目要求 (1)(5)：散客或团体一次结清时生成一张结账单。
--    total_amount 是**金额快照** —— 之后调价或改单都不会改动历史账单。
--    与客房订单是一对多关系（由 room_order.settlement_no 指回来）。
DROP TABLE IF EXISTS `settlement`;
CREATE TABLE `settlement` (
    settlement_no   VARCHAR(24)     NOT NULL                COMMENT '结账单号',
    group_id        INT             DEFAULT NULL            COMMENT '团体单ID，NULL=散客结账',
    user_id         INT             NOT NULL                COMMENT '付款人账号',
    room_count      INT             NOT NULL                COMMENT '本单房间数（快照）',
    total_amount    DECIMAL(10,2)   NOT NULL                COMMENT '结账总金额（快照）',
    method          ENUM('cash','card','wechat','alipay','room_charge')
                                    NOT NULL DEFAULT 'cash' COMMENT '结算方式',
    operator_id     INT             DEFAULT NULL            COMMENT '经手人（前台账号）',
    remark          VARCHAR(200)    DEFAULT NULL            COMMENT '备注',
    status          ENUM('settled','refunded') NOT NULL DEFAULT 'settled' COMMENT '结账单状态',
    settled_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '结账时间',
    PRIMARY KEY (settlement_no),
    KEY idx_st_time (settled_at),
    KEY idx_st_group (group_id),
    CONSTRAINT fk_st_group FOREIGN KEY (group_id) REFERENCES `guest_group`(group_id)
        ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT fk_st_user FOREIGN KEY (user_id) REFERENCES `user`(user_id)
        ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT fk_st_operator FOREIGN KEY (operator_id) REFERENCES `user`(user_id)
        ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT ck_st_amount CHECK (total_amount >= 0),
    CONSTRAINT ck_st_rooms CHECK (room_count > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='结账单表';


-- =====================================================================
--  四、客房订单
-- =====================================================================

-- 6. 客房订单表
--    group_id / settlement_no 分别指回团体单与结账单，支撑
--    「团体一次登记多间房」与「一次结清多张订单」。
--    id_card 用于宾馆登记与多手段查询客人信息（题目要求 (3)）。
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
    id_card         VARCHAR(20)     DEFAULT NULL            COMMENT '入住人证件号（选填，供登记与查询）',
    group_id        INT             DEFAULT NULL            COMMENT '所属团体单，NULL=散客',
    settlement_no   VARCHAR(24)     DEFAULT NULL            COMMENT '所属结账单，NULL=尚未结账',
    status          ENUM('confirmed','checked_in','checked_out','cancelled')
                                    NOT NULL DEFAULT 'confirmed' COMMENT '订单状态',
    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    PRIMARY KEY (order_id),
    KEY idx_ro_user        (user_id, created_at),
    KEY idx_ro_availability (room_id, status, check_in_date, check_out_date),
    KEY idx_ro_group       (group_id),
    KEY idx_ro_settlement  (settlement_no),
    CONSTRAINT fk_ro_user FOREIGN KEY (user_id) REFERENCES `user`(user_id)
        ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT fk_ro_room FOREIGN KEY (room_id) REFERENCES `room`(room_id)
        ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT fk_ro_group FOREIGN KEY (group_id) REFERENCES `guest_group`(group_id)
        ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT fk_ro_settlement FOREIGN KEY (settlement_no) REFERENCES `settlement`(settlement_no)
        ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT ck_ro_dates CHECK (check_out_date > check_in_date),
    CONSTRAINT ck_ro_price CHECK (total_price >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='客房订单表';


-- =====================================================================
--  五、支付与评价
-- =====================================================================

-- 7. 支付流水表
--    原管理端的"收入"是把各订单表按状态求和，未收款的 'confirmed' 订单
--    也被算成收入，账目不成立。补支付表后收入从真实流水汇总。
--    order_type 仍保留 ENUM，为后续扩展业务线留位。
DROP TABLE IF EXISTS `payment`;
CREATE TABLE `payment` (
    payment_id      INT             NOT NULL AUTO_INCREMENT COMMENT '支付ID',
    payment_no      VARCHAR(24)     NOT NULL                COMMENT '支付流水号',
    order_id        VARCHAR(24)     NOT NULL                COMMENT '关联订单号',
    order_type      ENUM('room')                                NOT NULL COMMENT '订单类型',
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

-- 8. 评价表
--    原表无唯一约束，同一订单可被无限重复评价。补 UNIQUE(user_id, order_id, order_type)。
--    order_id 存的是其它订单表的业务主键（订单号），无法用外键表达，
--    改由触发器 BEFORE INSERT 校验其存在性（见 03_triggers.sql）。
--    order_type 同样保留 ENUM，为后续扩展业务线留位。
DROP TABLE IF EXISTS `review`;
CREATE TABLE `review` (
    review_id       INT             NOT NULL AUTO_INCREMENT COMMENT '评价ID',
    user_id         INT             NOT NULL                COMMENT '用户ID',
    order_id        VARCHAR(24)     NOT NULL                COMMENT '订单号',
    order_type      ENUM('room')                                NOT NULL COMMENT '订单类型',
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


-- =====================================================================
--  六、操作审计
-- =====================================================================

-- 9. 价格与房型变更日志表
--    题目要求 (4)「操作员在密码支持下才可更改房价、房间类型、增加客房」。
--    密码校验由 app/service.py 的 Approval 机制完成（二次输入当前账号密码）；
--    本表负责**留痕**：谁、什么时候、把哪个对象的哪个字段从什么改成了什么。
--    原系统这类改动没有任何记录，出错无法追溯。
DROP TABLE IF EXISTS `price_change_log`;
CREATE TABLE `price_change_log` (
    log_id          INT             NOT NULL AUTO_INCREMENT COMMENT '日志ID',
    table_name      VARCHAR(50)     NOT NULL                COMMENT '被改动的表',
    pk_value        VARCHAR(32)     NOT NULL                COMMENT '被改动记录的主键值',
    target_label    VARCHAR(100)    NOT NULL                COMMENT '可读对象名（如房型名称）',
    field_name      VARCHAR(50)     NOT NULL                COMMENT '被改动的字段；* 表示新增/删除整条记录',
    old_value       VARCHAR(100)    DEFAULT NULL            COMMENT '改动前的值',
    new_value       VARCHAR(100)    DEFAULT NULL            COMMENT '改动后的值',
    reason          VARCHAR(200)    DEFAULT NULL            COMMENT '操作原因',
    operator_id     INT             NOT NULL                COMMENT '操作人账号',
    operator_name   VARCHAR(50)     NOT NULL                COMMENT '操作人用户名',
    changed_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '操作时间',
    PRIMARY KEY (log_id),
    KEY idx_pcl_time (changed_at),
    KEY idx_pcl_target (table_name, pk_value),
    CONSTRAINT fk_pcl_operator FOREIGN KEY (operator_id) REFERENCES `user`(user_id)
        ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='价格与房型变更日志表';

-- 恢复外键检查（与文件开头的 SET FOREIGN_KEY_CHECKS = 0 配对）
SET FOREIGN_KEY_CHECKS = 1;
