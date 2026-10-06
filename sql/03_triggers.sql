-- =====================================================================
--  酒店服务预约管理系统 —— 触发器定义
--  ------------------------------------------------------------------
--  文件   : sql/03_triggers.sql
--  依赖   : 01_schema.sql
--
--  设计意图：
--    原系统的业务约束全部写在 Python 界面里，数据库本身几乎不设防：
--      · room.status 与订单完全脱节，永远停在 available；
--      · laundry_order 的 pickup_time / delivery_time 建了列却从不写入；
--      · review.order_id 是多态引用，没有外键，可以评价任意不存在的订单；
--      · dining_order.total_price 恒为 0，没有明细也没有汇总。
--    以下触发器把"必须成立的不变量"交给数据库保证 —— 即使有人绕过
--    界面直接执行 SQL，数据依然自洽。
-- =====================================================================

USE `hotel_booking`;

DROP TRIGGER IF EXISTS `trg_room_order_before_insert`;
DROP TRIGGER IF EXISTS `trg_room_order_after_insert`;
DROP TRIGGER IF EXISTS `trg_room_order_after_update`;
DROP TRIGGER IF EXISTS `trg_review_before_insert`;
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
-- ---------------------------------------------------------------------
CREATE TRIGGER `trg_room_order_before_insert`
BEFORE INSERT ON `room_order`
FOR EACH ROW
BEGIN
    DECLARE v_price DECIMAL(10,2);

    SELECT rt.price INTO v_price
    FROM room r
    JOIN room_type rt ON rt.type_id = r.type_id
    WHERE r.room_id = NEW.room_id;

    IF v_price IS NULL THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = '房间不存在或房型缺失，无法下单';
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
--  review.order_id 是跨 5 张订单表的多态引用，无法用外键表达
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
        WHEN 'dining' THEN
            SELECT COUNT(*) INTO v_exists FROM dining_order
             WHERE order_id = NEW.order_id AND user_id = NEW.user_id;
        WHEN 'fitness' THEN
            SELECT COUNT(*) INTO v_exists FROM fitness_booking
             WHERE booking_id = NEW.order_id AND user_id = NEW.user_id;
        WHEN 'spa' THEN
            SELECT COUNT(*) INTO v_exists FROM spa_booking
             WHERE booking_id = NEW.order_id AND user_id = NEW.user_id;
        WHEN 'laundry' THEN
            SELECT COUNT(*) INTO v_exists FROM laundry_order
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
--  T5. 洗衣订单状态变更前：校验流转合法性并自动记录时间戳
--
--  原系统直接把 status 改成任意值，可以从"等待取衣"一跳变成"已送达"。
--  这里用状态机约束合法流转，并在取衣/送达时自动补齐
--  pickup_time / delivery_time（原设计这两列从未被写入过）。
-- ---------------------------------------------------------------------
CREATE TRIGGER `trg_laundry_before_update`
BEFORE UPDATE ON `laundry_order`
FOR EACH ROW
BEGIN
    IF NEW.status <> OLD.status THEN

        IF OLD.status = 'cancelled' THEN
            SIGNAL SQLSTATE '45000'
                SET MESSAGE_TEXT = '已取消的洗衣订单不可再变更状态';
        END IF;

        IF NEW.status = 'picked_up' AND OLD.status <> 'pending' THEN
            SIGNAL SQLSTATE '45000'
                SET MESSAGE_TEXT = '只有待取衣的订单才能标记为已取衣';
        END IF;

        IF NEW.status = 'processing' AND OLD.status <> 'picked_up' THEN
            SIGNAL SQLSTATE '45000'
                SET MESSAGE_TEXT = '订单需先取衣才能进入洗涤中';
        END IF;

        IF NEW.status = 'delivered' AND OLD.status NOT IN ('processing', 'picked_up') THEN
            SIGNAL SQLSTATE '45000'
                SET MESSAGE_TEXT = '订单需先取衣或洗涤中才能标记为已送达';
        END IF;

        IF NEW.status = 'picked_up' AND NEW.pickup_time IS NULL THEN
            SET NEW.pickup_time = NOW();
        END IF;

        IF NEW.status = 'delivered' AND NEW.delivery_time IS NULL THEN
            SET NEW.delivery_time = NOW();
        END IF;

    END IF;
END$$

-- ---------------------------------------------------------------------
--  T6. 餐饮明细插入前：写入小计
--      （AFTER 触发器不能修改 NEW，因此小计必须在 BEFORE 里写）
-- ---------------------------------------------------------------------
CREATE TRIGGER `trg_dining_item_before_insert`
BEFORE INSERT ON `dining_order_item`
FOR EACH ROW
BEGIN
    SET NEW.subtotal = NEW.quantity * NEW.unit_price;
END$$

-- ---------------------------------------------------------------------
--  T7~T9. 餐饮明细增删改后：自动重算订单总金额
--
--  原系统餐饮订单的 total_price 恒为 0（没有明细表），管理端统计出的
--  "餐饮收入"因此永远是 0。现在金额由数据库自动汇总，任何写法都不会不一致。
-- ---------------------------------------------------------------------
CREATE TRIGGER `trg_dining_item_after_insert`
AFTER INSERT ON `dining_order_item`
FOR EACH ROW
BEGIN
    UPDATE dining_order
       SET total_price = (
           SELECT COALESCE(SUM(quantity * unit_price), 0)
           FROM dining_order_item WHERE order_id = NEW.order_id
       )
     WHERE order_id = NEW.order_id;
END$$

CREATE TRIGGER `trg_dining_item_after_update`
AFTER UPDATE ON `dining_order_item`
FOR EACH ROW
BEGIN
    UPDATE dining_order
       SET total_price = (
           SELECT COALESCE(SUM(quantity * unit_price), 0)
           FROM dining_order_item WHERE order_id = NEW.order_id
       )
     WHERE order_id = NEW.order_id;
END$$

CREATE TRIGGER `trg_dining_item_after_delete`
AFTER DELETE ON `dining_order_item`
FOR EACH ROW
BEGIN
    UPDATE dining_order
       SET total_price = (
           SELECT COALESCE(SUM(quantity * unit_price), 0)
           FROM dining_order_item WHERE order_id = OLD.order_id
       )
     WHERE order_id = OLD.order_id;
END$$

DELIMITER ;
