-- =====================================================================
--  宾馆客房管理系统 —— 触发器定义
--  ------------------------------------------------------------------
--  文件   : sql/03_triggers.sql
--  依赖   : 01_schema.sql
--
--  设计意图：
--    原系统的业务约束全部写在 Python 界面里，数据库本身几乎不设防：
--      · room.status 与订单完全脱节，永远停在 available；
--      · room_order.total_price 由界面算好再写库，界面算错无从发现；
--      · review.order_id 没有外键，可以评价任意不存在的订单。
--    以下触发器把"必须成立的不变量"交给数据库保证 —— 即使有人绕过
--    界面直接执行 SQL，数据依然自洽。
-- =====================================================================

USE `hotel_booking`;

DROP TRIGGER IF EXISTS `trg_room_order_before_insert`;
DROP TRIGGER IF EXISTS `trg_room_order_after_insert`;
DROP TRIGGER IF EXISTS `trg_room_order_after_update`;
DROP TRIGGER IF EXISTS `trg_room_order_before_update`;
DROP TRIGGER IF EXISTS `trg_review_before_insert`;
-- 历史触发器：属于已移除的餐饮/洗衣业务线，保留 DROP 以便旧库升级后不留残留
DROP TRIGGER IF EXISTS `trg_laundry_before_update`;
DROP TRIGGER IF EXISTS `trg_dining_item_before_insert`;
DROP TRIGGER IF EXISTS `trg_dining_item_after_insert`;
DROP TRIGGER IF EXISTS `trg_dining_item_after_update`;
DROP TRIGGER IF EXISTS `trg_dining_item_after_delete`;

DELIMITER $$

-- ---------------------------------------------------------------------
--  T1. 客房订单插入前：服务端重算晚数与总金额
--
--  原系统由界面算好晚数再塞进数据库，日期格式非法就抛 ValueError 崩溃，
--  且界面算错没人能发现。改为数据库按当前房价重算，界面传什么都不影响账目。
--
--  同时校验团体一致性：团体成员的入住/离店日期必须与团体单完全一致，
--  否则团体结账时按团体汇总的金额与实际住宿不一致。
-- ---------------------------------------------------------------------
CREATE TRIGGER `trg_room_order_before_insert`
BEFORE INSERT ON `room_order`
FOR EACH ROW
BEGIN
    DECLARE v_price DECIMAL(10,2);
    DECLARE v_g_in DATE DEFAULT NULL;
    DECLARE v_g_out DATE DEFAULT NULL;

    SELECT rt.price INTO v_price
    FROM room r
    JOIN room_type rt ON rt.type_id = r.type_id
    WHERE r.room_id = NEW.room_id;

    IF v_price IS NULL THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = '房间不存在或房型缺失，无法下单';
    END IF;

    IF NEW.group_id IS NOT NULL THEN
        SELECT check_in_date, check_out_date INTO v_g_in, v_g_out
        FROM guest_group WHERE group_id = NEW.group_id;

        IF v_g_in IS NULL THEN
            SIGNAL SQLSTATE '45000'
                SET MESSAGE_TEXT = '团体单不存在，无法登记团体房间';
        END IF;

        IF NEW.check_in_date <> v_g_in OR NEW.check_out_date <> v_g_out THEN
            SIGNAL SQLSTATE '45000'
                SET MESSAGE_TEXT = '团体成员的入住/离店日期必须与团体单一致';
        END IF;
    END IF;

    SET NEW.nights = DATEDIFF(NEW.check_out_date, NEW.check_in_date);
    SET NEW.total_price = v_price * NEW.nights;
END$$

-- ---------------------------------------------------------------------
--  T2. 客房订单插入后：让房间状态跟随订单
--
--  只有"入住日已到且尚未离店"的订单才把房间置为 occupied，
--  远期预订不会提前占用房间，否则今天的可用房查询会被未来订单污染。
-- ---------------------------------------------------------------------
CREATE TRIGGER `trg_room_order_after_insert`
AFTER INSERT ON `room_order`
FOR EACH ROW
BEGIN
    IF NEW.status IN ('confirmed', 'checked_in')
       AND NEW.check_in_date <= CURDATE()
       AND NEW.check_out_date > CURDATE() THEN
        UPDATE room
           SET status = 'occupied'
         WHERE room_id = NEW.room_id
           AND status = 'available';
    END IF;
END$$

-- ---------------------------------------------------------------------
--  T3. 客房订单状态变更后：房间状态自动流转
--
--  checked_in  -> occupied （有客在住）
--  checked_out -> cleaning （待打扫，前台打扫完成后置回 available）
--  cancelled   -> 若该房间已无其他有效订单，则回置 available
-- ---------------------------------------------------------------------
CREATE TRIGGER `trg_room_order_after_update`
AFTER UPDATE ON `room_order`
FOR EACH ROW
BEGIN
    DECLARE v_other_active INT DEFAULT 0;

    IF NEW.status <> OLD.status THEN

        IF NEW.status = 'checked_in' THEN
            UPDATE room SET status = 'occupied' WHERE room_id = NEW.room_id;

        ELSEIF NEW.status = 'checked_out' THEN
            UPDATE room SET status = 'cleaning' WHERE room_id = NEW.room_id;

        ELSEIF NEW.status = 'cancelled' THEN
            SELECT COUNT(*) INTO v_other_active
            FROM room_order
            WHERE room_id = NEW.room_id
              AND order_id <> NEW.order_id
              AND status IN ('confirmed', 'checked_in');

            IF v_other_active = 0 THEN
                UPDATE room SET status = 'available'
                 WHERE room_id = NEW.room_id
                   AND status = 'occupied';
            END IF;
        END IF;

    END IF;
END$$

-- ---------------------------------------------------------------------
--  T4. 评价插入前：校验被评价订单真实存在且属于该用户
--
--  review.order_id 存的是订单表的业务主键（订单号），无法用外键表达
--  （这一设计权衡已写入 README）。用触发器补上存在性校验，
--  重复评价由 uk_review_order 唯一约束拦截。
-- ---------------------------------------------------------------------
CREATE TRIGGER `trg_review_before_insert`
BEFORE INSERT ON `review`
FOR EACH ROW
BEGIN
    DECLARE v_exists INT DEFAULT 0;

    CASE NEW.order_type
        WHEN 'room' THEN
            SELECT COUNT(*) INTO v_exists FROM room_order
             WHERE order_id = NEW.order_id AND user_id = NEW.user_id;
        ELSE
            SET v_exists = 0;
    END CASE;

    IF v_exists = 0 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = '被评价的订单不存在，或不属于当前用户';
    END IF;
END$$

-- ---------------------------------------------------------------------
--  T5. 客房订单变更前：已结账的订单不允许直接取消
--
--  结账单是不可变的账目凭据：订单一旦被结账（settlement_no 非空），
--  直接置为 cancelled 会让结账单金额与订单状态互相矛盾。
--  正确做法是先办理「结账单退款」（app/service.py 的 refund_settlement），
--  退款时会把 settlement_no 置回 NULL，之后才允许取消。
-- ---------------------------------------------------------------------
CREATE TRIGGER `trg_room_order_before_update`
BEFORE UPDATE ON `room_order`
FOR EACH ROW
BEGIN
    IF OLD.settlement_no IS NOT NULL
       AND NEW.status = 'cancelled' AND OLD.status <> 'cancelled' THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = '该订单已包含在结账单中，不能直接取消，请先办理结账单退款';
    END IF;
END$$

DELIMITER ;
