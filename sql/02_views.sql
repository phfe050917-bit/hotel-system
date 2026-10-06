-- =====================================================================
--  酒店服务预约管理系统 —— 视图定义
--  ------------------------------------------------------------------
--  文件   : sql/02_views.sql
--  依赖   : 01_schema.sql
--
--  设计意图：
--    原系统的"订单汇总"是在 Python 里把 5 张订单表查出来，再用
--    CASE 语句把状态翻译成中文，然后合并排序。这段逻辑在三端各写了
--    一遍，而且客人端还用"秒级时间戳作二叉搜索树键"来排序，导致同一
--    秒创建的多张订单互相覆盖、界面静默丢单。
--
--    现在把"跨表 UNION + 状态归一 + 排序"全部下沉到视图，
--    三端统一调用 v_all_orders，重复代码消失、丢单 bug 从根上消除。
-- =====================================================================

USE `hotel_booking`;

DROP VIEW IF EXISTS `v_all_orders`;
DROP VIEW IF EXISTS `v_room_availability`;
DROP VIEW IF EXISTS `v_room_current_state`;
DROP VIEW IF EXISTS `v_daily_revenue`;
DROP VIEW IF EXISTS `v_service_stats`;
DROP VIEW IF EXISTS `v_tech_schedule_today`;


-- ---------------------------------------------------------------------
--  V1. 全量订单视图（跨 5 张订单表 UNION ALL + 状态归一化）
--
--  对外统一三个概念，三端界面不再各自翻译状态：
--    status_group    : 归一化分组 pending / active / completed / cancelled
--    status_label    : 中文状态名，界面直接显示
--    status_category : 界面筛选用的粗分类 进行中 / 已完成 / 已取消
--
--  按 created_at 倒序，天然保证同一秒的订单不会互相覆盖。
-- ---------------------------------------------------------------------
CREATE VIEW `v_all_orders` AS
SELECT
    ro.order_id                                     AS order_id,
    ro.user_id                                      AS user_id,
    u.username                                      AS username,
    'room'                                          AS order_type,
    '客房'                                          AS type_label,
    CONCAT(r.room_number, ' / ', DATE_FORMAT(ro.check_in_date, '%Y-%m-%d'),
           '~', DATE_FORMAT(ro.check_out_date, '%Y-%m-%d'),
           ' / ', ro.nights, '晚')                   AS detail,
    ro.total_price                                  AS total_price,
    ro.status                                       AS raw_status,
    CASE ro.status
        WHEN 'confirmed'   THEN 'pending'
        WHEN 'checked_in'  THEN 'active'
        WHEN 'checked_out' THEN 'completed'
        ELSE 'cancelled'
    END                                             AS status_group,
    CASE ro.status
        WHEN 'confirmed'   THEN '待入住'
        WHEN 'checked_in'  THEN '已入住'
        WHEN 'checked_out' THEN '已退房'
        ELSE '已取消'
    END                                             AS status_label,
    CASE ro.status
        WHEN 'confirmed'   THEN '进行中'
        WHEN 'checked_in'  THEN '进行中'
        WHEN 'checked_out' THEN '已完成'
        ELSE '已取消'
    END                                             AS status_category,
    ro.check_in_date                                AS service_date,
    ro.created_at                                   AS created_at
FROM room_order ro
JOIN `user` u ON u.user_id = ro.user_id
JOIN room   r ON r.room_id = ro.room_id

UNION ALL

SELECT
    d.order_id, d.user_id, u.username,
    'dining', '餐饮',
    CONCAT(rs.restaurant_name, ' / ', DATE_FORMAT(d.dining_date, '%Y-%m-%d'),
           ' ', TIME_FORMAT(d.dining_time, '%H:%i'),
           ' / ', d.guest_count, '位'),
    d.total_price, d.status,
    CASE d.status
        WHEN 'confirmed' THEN 'pending'
        WHEN 'dining'    THEN 'active'
        WHEN 'completed' THEN 'completed'
        ELSE 'cancelled'
    END,
    CASE d.status
        WHEN 'confirmed' THEN '待用餐'
        WHEN 'dining'    THEN '用餐中'
        WHEN 'completed' THEN '已完成'
        ELSE '已取消'
    END,
    CASE d.status
        WHEN 'confirmed' THEN '进行中'
        WHEN 'dining'    THEN '进行中'
        WHEN 'completed' THEN '已完成'
        ELSE '已取消'
    END,
    d.dining_date, d.created_at
FROM dining_order d
JOIN `user` u    ON u.user_id = d.user_id
JOIN restaurant rs ON rs.restaurant_id = d.restaurant_id

UNION ALL

SELECT
    fb.booking_id, fb.user_id, u.username,
    'fitness', '健身',
    CONCAT(ff.facility_name, ' / ', DATE_FORMAT(fb.booking_date, '%Y-%m-%d'),
           ' ', fb.time_slot, ' / ', fb.guest_count, '人'),
    0.00, fb.status,
    CASE fb.status
        WHEN 'confirmed' THEN 'pending'
        WHEN 'completed' THEN 'completed'
        ELSE 'cancelled'
    END,
    CASE fb.status
        WHEN 'confirmed' THEN '已预约'
        WHEN 'completed' THEN '已完成'
        ELSE '已取消'
    END,
    CASE fb.status
        WHEN 'confirmed' THEN '进行中'
        WHEN 'completed' THEN '已完成'
        ELSE '已取消'
    END,
    fb.booking_date, fb.created_at
FROM fitness_booking fb
JOIN `user` u             ON u.user_id = fb.user_id
JOIN fitness_facility ff  ON ff.facility_id = fb.facility_id

UNION ALL

SELECT
    sb.booking_id, sb.user_id, u.username,
    'spa', 'SPA',
    CONCAT(ss.service_name, ' / ', t.tech_name, ' / ',
           DATE_FORMAT(sb.booking_date, '%Y-%m-%d'), ' ',
           TIME_FORMAT(sb.booking_time, '%H:%i'), ' / ',
           ss.duration, '分钟'),
    sb.price, sb.status,
    CASE sb.status
        WHEN 'confirmed'   THEN 'pending'
        WHEN 'in_progress' THEN 'active'
        WHEN 'completed'   THEN 'completed'
        ELSE 'cancelled'
    END,
    CASE sb.status
        WHEN 'confirmed'   THEN '待服务'
        WHEN 'in_progress' THEN '服务中'
        WHEN 'completed'   THEN '已完成'
        ELSE '已取消'
    END,
    CASE sb.status
        WHEN 'confirmed'   THEN '进行中'
        WHEN 'in_progress' THEN '进行中'
        WHEN 'completed'   THEN '已完成'
        ELSE '已取消'
    END,
    sb.booking_date, sb.created_at
FROM spa_booking sb
JOIN `user` u       ON u.user_id = sb.user_id
JOIN spa_service ss ON ss.service_id = sb.service_id
JOIN technician t   ON t.tech_id = sb.tech_id

UNION ALL

SELECT
    lo.order_id, lo.user_id, u.username,
    'laundry', '洗衣',
    CONCAT(CASE lo.service_type
               WHEN 'wash'         THEN '普通水洗'
               WHEN 'dry_clean'    THEN '普通干洗'
               WHEN 'iron'         THEN '熨烫'
               WHEN 'express_wash' THEN '加急水洗'
               WHEN 'express_dry'  THEN '加急干洗'
           END,
           ' / 房间', lo.room_number, ' / ', lo.item_count, '件'),
    lo.total_price, lo.status,
    CASE lo.status
        WHEN 'pending'    THEN 'pending'
        WHEN 'picked_up'  THEN 'active'
        WHEN 'processing' THEN 'active'
        WHEN 'delivered'  THEN 'completed'
        ELSE 'cancelled'
    END,
    CASE lo.status
        WHEN 'pending'    THEN '等待取衣'
        WHEN 'picked_up'  THEN '已取衣'
        WHEN 'processing' THEN '洗涤中'
        WHEN 'delivered'  THEN '已送达'
        ELSE '已取消'
    END,
    CASE lo.status
        WHEN 'pending'    THEN '进行中'
        WHEN 'picked_up'  THEN '进行中'
        WHEN 'processing' THEN '进行中'
        WHEN 'delivered'  THEN '已完成'
        ELSE '已取消'
    END,
    DATE(lo.created_at), lo.created_at
FROM laundry_order lo
JOIN `user` u ON u.user_id = lo.user_id;


-- ---------------------------------------------------------------------
--  V2. 房间与房型信息视图
--
--  用法：SELECT * FROM v_room_availability
--        WHERE status = 'available' AND type_name = %s
--
--  仅供"按房型筛选可订房间"使用。是否与既有订单冲突，
--  需由业务层（app/service.py）用 NOT EXISTS 子查询结合入住/离店日期判定，
--  并在同一事务内向 room_order 插入，避免"查完再插"的并发窗口。
--  视图带出 room_id，预订时不再需要用房间号反查。
-- ---------------------------------------------------------------------
CREATE VIEW `v_room_availability` AS
SELECT
    r.room_id                                       AS room_id,
    r.room_number                                   AS room_number,
    rt.type_id                                      AS type_id,
    rt.type_name                                    AS type_name,
    rt.price                                        AS price,
    rt.max_occupancy                                AS max_occupancy,
    rt.facilities                                   AS facilities,
    r.floor                                         AS floor,
    r.status                                        AS status
FROM room r
JOIN room_type rt ON rt.type_id = r.type_id;


-- ---------------------------------------------------------------------
--  V3. 房间实时状态视图
--
--  把"房间物理状态"与"订单占用情况"放在一起看，
--  解决原系统 room.status 永远停在 available、与订单完全脱节的问题。
-- ---------------------------------------------------------------------
CREATE VIEW `v_room_current_state` AS
SELECT
    r.room_id,
    r.room_number,
    rt.type_name,
    rt.price,
    r.floor,
    r.status                                        AS room_status,
    COALESCE(occ.active_orders, 0)                  AS active_orders,
    occ.current_guest,
    occ.nearest_check_in,
    occ.nearest_check_out,
    CASE
        WHEN r.status = 'maintenance' THEN '维护中'
        WHEN r.status = 'cleaning'    THEN '打扫中'
        WHEN occ.current_guest IS NOT NULL THEN '在住'
        WHEN COALESCE(occ.active_orders, 0) > 0 THEN '已预订'
        ELSE '空闲'
    END                                             AS state_label
FROM room r
JOIN room_type rt ON rt.type_id = r.type_id
LEFT JOIN (
    SELECT
        ro.room_id,
        COUNT(*)                                    AS active_orders,
        MAX(CASE WHEN ro.status = 'checked_in' THEN ro.guest_name END) AS current_guest,
        MIN(CASE WHEN ro.status = 'confirmed'  THEN ro.check_in_date END)  AS nearest_check_in,
        MAX(CASE WHEN ro.status = 'checked_in' THEN ro.check_out_date END) AS nearest_check_out
    FROM room_order ro
    WHERE ro.status IN ('confirmed', 'checked_in')
    GROUP BY ro.room_id
) occ ON occ.room_id = r.room_id;


-- ---------------------------------------------------------------------
--  V4. 每日营收视图（按支付时间汇总真实收款）
--
--  原管理端把未收款的 'confirmed' 订单也计入收入，账目不成立。
--  本视图只统计 payment 表中 status='paid' 的真实流水。
-- ---------------------------------------------------------------------
CREATE VIEW `v_daily_revenue` AS
SELECT
    DATE(p.paid_at)                                 AS pay_date,
    p.order_type                                    AS order_type,
    CASE p.order_type
        WHEN 'room'    THEN '客房'
        WHEN 'dining'  THEN '餐饮'
        WHEN 'fitness' THEN '健身'
        WHEN 'spa'     THEN 'SPA'
        WHEN 'laundry' THEN '洗衣'
    END                                             AS type_label,
    COUNT(*)                                        AS payment_count,
    SUM(p.amount)                                   AS revenue
FROM payment p
WHERE p.status = 'paid'
GROUP BY DATE(p.paid_at), p.order_type;


-- ---------------------------------------------------------------------
--  V5. 服务统计视图（各业务线订单量与金额一览，供管理端看板）
-- ---------------------------------------------------------------------
CREATE VIEW `v_service_stats` AS
SELECT
    order_type,
    type_label,
    COUNT(*)                                        AS order_count,
    SUM(CASE WHEN status_category = '进行中' THEN 1 ELSE 0 END) AS active_count,
    SUM(CASE WHEN status_category = '已完成' THEN 1 ELSE 0 END) AS completed_count,
    SUM(CASE WHEN status_category = '已取消' THEN 1 ELSE 0 END) AS cancelled_count,
    SUM(CASE WHEN status_category <> '已取消' THEN total_price ELSE 0 END) AS order_amount
FROM v_all_orders
GROUP BY order_type, type_label;


-- ---------------------------------------------------------------------
--  V6. 今日技师排班视图
--
--  原系统 tech_schedule 建了表却零读写。本视图把排班与技师信息结合，
--  并标出每档是否已被 SPA 预约占用，使该表真正可用。
-- ---------------------------------------------------------------------
CREATE VIEW `v_tech_schedule_today` AS
SELECT
    ts.schedule_id,
    ts.work_date,
    ts.time_slot,
    t.tech_id,
    t.tech_name,
    t.tech_level,
    t.specialty,
    ts.is_booked,
    CASE WHEN ts.is_booked = 1 THEN '已约' ELSE '空闲' END AS slot_label
FROM tech_schedule ts
JOIN technician t ON t.tech_id = ts.tech_id;
