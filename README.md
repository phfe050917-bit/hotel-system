# 酒店服务预约管理系统

数据库课程设计 · Tkinter + MySQL 8.0

一套覆盖**客房预订、餐饮、健身、SPA、洗衣**五条业务线的酒店服务预约系统，
含客人 / 前台 / 管理员三种角色的桌面客户端。

本次重构针对原版本已确认的 14 项缺陷做了系统性修复，并把
**数据库结构收敛为唯一来源**（`sql/*.sql`），补齐了视图、触发器、
索引、约束与事务边界。

---

## 一、快速开始

```bash
# 1. 安装依赖（仅需 PyMySQL）
pip install -r requirements.txt

# 2. 配置数据库连接（二选一）
#    方式 A：复制模板并修改密码
copy config.local.example.py config.local.py
#    方式 B：设置环境变量
set HOTEL_DB_PASSWORD=你的密码

# 3. 启动（首次运行会自动建库、建表、建视图/触发器并写入基础数据）
python main.py
```

其他常用命令：

```bash
python tools/init_db.py --yes         # 手动重建数据库（会清空数据）
python tools/seed_demo_orders.py      # 生成订单类演示数据
python tools/smoke_test.py            # 端到端自检（75 项）
```

### 演示账号

| 角色 | 用户名 | 密码 |
|---|---|---|
| 管理员 | `admin` | `admin123` |
| 前台 | `reception` | `recep123` |
| 客人 | `guest01` | `guest123` |

> 密码在数据库中存的是 `PBKDF2-HMAC-SHA256` 加盐哈希，不是明文。

---

## 二、项目结构

```
hotel_system/
├── main.py                     程序入口（含首次运行自动初始化）
├── requirements.txt
├── config.local.example.py     本地配置模板（复制为 config.local.py）
├── README.md
│
├── sql/                        ★ 数据库结构唯一来源
│   ├── 01_schema.sql           18 张表 + 索引 + 主外键 + CHECK 约束
│   ├── 02_views.sql            6 个视图
│   ├── 03_triggers.sql         9 个触发器
│   └── 04_seed.sql             基础数据（账号/房型/房间/菜单/设施/SPA/技师）
│
├── app/
│   ├── config.py               配置（环境变量 > config.local.py > 默认值）
│   ├── db.py                   数据访问层：连接、事务、回滚、异常封装
│   ├── security.py             密码加盐哈希与校验
│   ├── ids.py                  业务单号生成（抗碰撞 + 兜底重试）
│   ├── bootstrap.py            执行 sql/*.sql（含 MySQL DELIMITER 解析）
│   ├── service.py              ★ 业务规则层：状态机、容量校验、并发控制
│   ├── stats.py                统计与看板查询
│   └── ui/
│       ├── widgets.py          通用控件与对话框
│       ├── base.py             窗口基类（统一异常处理、状态栏）
│       ├── login.py            登录 / 注册 / 修改密码
│       ├── guest.py            客人端主窗口
│       ├── guest_tabs.py       客人端六个标签页
│       ├── reception.py        前台端主窗口
│       ├── reception_tabs.py   前台端六个标签页
│       ├── admin.py            管理端主窗口
│       └── admin_tabs.py       管理端五个标签页
│
└── tools/
    ├── init_db.py              建库工具
    ├── seed_demo_orders.py     演示订单生成
    └── smoke_test.py           端到端自检
```

**分层原则**：界面只负责「收集输入 + 渲染结果」，所有业务规则集中在
`app/service.py`，所有 SQL 集中在 `app/db.py` / `app/service.py` / `app/stats.py`。
`app/ui/` 目录下**不含任何 SQL 语句**（可用
`rg "SELECT |INSERT INTO|UPDATE |DELETE FROM" app/ui` 验证，应无命中）。
基础资源维护这类需要动态表名的功能，也通过 `service.RESOURCE_CATALOG`
白名单注册表在服务层完成，界面不再直接触碰数据库。

---

## 三、数据库设计

### 3.1 数据表（18 张）

| 分组 | 表 |
|---|---|
| 用户 | `user` |
| 客房 | `room_type`、`room`、`room_order` |
| 餐饮 | `restaurant`、`dish_category`、`dish`、`dining_order`、`dining_order_item` |
| 健身 | `fitness_facility`、`fitness_booking` |
| SPA | `spa_service`、`technician`、`tech_schedule`、`spa_booking` |
| 洗衣 | `laundry_order` |
| 财务 / 反馈 | `payment`、`review` |

### 3.2 视图（6 个）

| 视图 | 作用 |
|---|---|
| `v_all_orders` | 跨 5 张订单表 `UNION ALL` + 状态归一化 + 倒序。三端订单列表统一走它 |
| `v_room_availability` | 房间与房型信息（带 `room_id`，预订无需按房号反查） |
| `v_room_current_state` | 房间物理状态 + 有效订单数 + 在住客人，解决状态与订单脱节 |
| `v_daily_revenue` | 按日、按业务线汇总真实收款流水 |
| `v_service_stats` | 各业务线订单量与状态分布 |
| `v_tech_schedule_today` | 技师排班与占用情况 |

### 3.3 触发器（9 个）

| 触发器 | 保障的不变量 |
|---|---|
| `trg_room_order_before_insert` | 晚数与总金额由数据库按当前房价重算，界面无法篡改账目 |
| `trg_room_order_after_insert` | 当日到店的订单自动把房间置为「在住」 |
| `trg_room_order_after_update` | 入住→在住、退房→打扫中、取消→按剩余订单回置空闲 |
| `trg_review_before_insert` | 被评价订单必须存在且属于该用户 |
| `trg_laundry_before_update` | 洗衣状态流转合法性校验，并自动记录取衣/送达时间 |
| `trg_dining_item_before_insert` | 明细小计 = 数量 × 单价 |
| `trg_dining_item_after_insert/update/delete` | 订单总金额随明细自动重算 |

### 3.4 约束与索引

- **20 个外键**：订单类表全部使用 `ON DELETE RESTRICT`，
  删除房型/房间不会连带删除历史订单（原版是 `CASCADE`，误删即丢账目）。
- **17 个 CHECK 约束**：价格、容量、评分的取值域，例如
  `CHECK (check_out_date > check_in_date)`、`CHECK (rating BETWEEN 1 AND 5)`。
- **唯一约束**：`review(user_id, order_id, order_type)` 防重复评价；
  `tech_schedule(tech_id, work_date, time_slot)` 防技师撞单。
- **复合索引**：`room_order(room_id, status, check_in_date, check_out_date)`
  直接服务最高频的"查某时段可用房"查询。

### 3.5 关于多态引用（设计权衡）

`review.order_id` 可以指向 5 张不同的订单表，属于典型的**多态引用**，
无法用外键表达。本项目采用两个手段替代：

1. `trg_review_before_insert` 触发器校验订单存在性与归属；
2. `order_type` 用 `ENUM` 限定取值范围。

这是有意为之的取舍：若要彻底消除多态引用，需要引入
`order` 主表 + 各子类型表（类表继承），改动面较大。此处选择
「触发器校验 + 枚举约束」，并在报告中说明该权衡。

---

## 四、本次重构修复的问题

### 致命问题

| # | 问题 | 修复方式 |
|---|---|---|
| 1 | `setup_database.sql` 建表用 `level`、插入写 `tech_level`，脚本必然报错；且缺少 `CREATE DATABASE` / `USE` | Schema 收敛到 `sql/01_schema.sql` 单一来源，列名统一为 `tech_level`，Python 侧不再内嵌 DDL |
| 2 | 「我的订单」用 `created_at` **秒级时间戳**作二叉搜索树键，同一秒的多张订单互相覆盖、静默丢单（实测 4 单只剩 1 单） | 删除 BST 排序，改为 `v_all_orders` 视图 + SQL `ORDER BY`；`tools/smoke_test.py` 含回归测试 |

### 数据安全

| # | 问题 | 修复方式 |
|---|---|---|
| 3 | 密码明文存库 | `PBKDF2-HMAC-SHA256` 加盐哈希（20 万次迭代），支持参数升级自动重算 |
| 4 | 全项目无 `rollback`，异常后连接残留脏事务 | `Database.transaction()` 上下文管理器，多步操作原子化 |
| 5 | 订单号 = 时间戳 + 2 位随机数，主键碰撞无重试 | 毫秒级时间戳 + 4 位随机字符 + `uniqueness_guard` 冲突重试 |
| 6 | 外键全部 `ON DELETE CASCADE`，删房型会清空订单 | 订单类外键改 `RESTRICT`，并给出可读的拒绝原因 |
| 7 | 管理端「禁用/启用」按钮实际执行 `DELETE FROM user`，因级联会删掉该用户全部订单 | 改为 `is_active` 软禁用，历史订单完整保留 |
| 8 | 客人端洗衣队列查到**所有住客**的订单与房间号 | 查询强制带 `user_id` 过滤 |

### 业务正确性

| # | 问题 | 修复方式 |
|---|---|---|
| 9 | 洗衣状态可任意跳转（等待取衣 → 已送达） | 状态机 + 数据库触发器双重校验 |
| 10 | 订房"先查后插"存在并发窗口，同一房间可被重复预订 | 同一事务内 `SELECT ... FOR UPDATE` 复查冲突 |
| 11 | 健身容量校验不在事务内，可超卖 | 事务内锁定设施行并复查 |
| 12 | 餐饮订单 `total_price` 恒为 0（没有菜品明细表） | 新增 `dining_order_item`，金额由触发器自动汇总 |
| 13 | 同一订单可无限重复评价，且不校验归属 | 唯一约束 + 服务层校验 + 触发器校验 |
| 14 | 日期手输格式错误直接抛 `ValueError` 崩溃 | `parse_date` 统一转换异常为友好提示，日期控件提供快捷按钮 |
| 15 | `room.status` 永远停在 `available`，与订单完全脱节 | 由触发器随订单流转；「在住」不允许人工设置 |
| 16 | `tech_schedule` 是空表且零读写，纯摆设 | SPA 预约时真实占用档期，并可查询技师当日档期 |
| 17 | `laundry_order.pickup_time` / `delivery_time` 建了列从不写入 | 触发器在取衣/送达时自动写入 |
| 18 | 「收入」按订单状态求和，未收款订单也计入 | 新增 `payment` 流水表，收入只统计 `status='paid'` 的真实收款 |
| 19 | 三端各自重复实现订单汇总与状态翻译 | 统一走 `v_all_orders` 视图与 `service.list_orders()` |
| 20 | `models.py` 的 `Queue` 零调用、`PriorityQueue` 同优先级顺序不稳定 | 移除无用的自建数据结构，排序交给 SQL，结果确定且可解释 |

---

## 五、操作流程速览

### 客人端（6 个标签页）

1. **客房预订** — 选日期 → 查询可用房 → 填入住人 → 确认预订
   （金额由数据库按当前房价计算）
2. **餐饮预约** — 选餐厅 → 看菜单 → 加入菜品到订单 → 提交
   （金额随明细自动汇总）
3. **健身设施** — 按日期查看各设施各时段余量 → 预约
4. **SPA 服务** — 选服务 → 选技师（显示该技师当日档期）→ 预约
5. **洗衣服务** — 实时报价 → 预约取衣时间 → 只看自己的订单
6. **我的订单** — 统一列表，可查看详情、取消、支付、评价

### 前台端（6 个标签页）

- **今日概览** — 到店/在住/离店、各业务线量、房间状态、待收款
- **客房管理** — 按楼层/状态/房号筛选，查看预订日历，更改房间物理状态
- **入住 / 退房** — 办理入住（房间自动转在住）、办理退房（自动转打扫）、登记收款
- **订单管理** — 按状态机推进、取消、登记收款、查看详情
- **洗衣服务** — 加急优先的处理队列，推进取衣/洗涤/送达
- **客户评价** — 查看评分与内容

### 管理端（5 个标签页）

- **数据统计** — 按时间范围统计实收/退款/净收入、按业务线与支付方式分布
- **用户管理** — 添加账号、重置密码、**软禁用**（不删数据）
- **资源管理** — 房型/房间/餐厅/菜品/设施/SPA/技师增删改
- **订单总览** — 全量订单与支付流水
- **关于系统** — 直观展示数据库对象清单（表/视图/触发器/索引/外键/CHECK）

---

## 六、自检

`tools/smoke_test.py` 覆盖 91 项断言，包含：

- 数据库对象清单（18 表 / 6 视图 / 9 触发器 / 20 外键 / 17 CHECK）
- 密码哈希：明文不入库、错误密码被拒、加盐生效、禁用账号无法登录
- 客房：金额由触发器重算、日期校验、同期重复预订被拒、状态机流转、退房联动房间
- **订单汇总回归测试**：同一秒连续创建 5 单，列表条数正确、5 单全部可见
- 洗衣：隐私过滤、状态跳转被拒、时间戳自动写入
- 餐饮：明细写入后金额自动汇总
- 评价：存在性 / 归属 / 重复三重校验
- 健身：容量不超卖
- SPA：同技师同时间不重复、排班表被占用
- 支付：重复支付被拒、营收来自流水、取消订单同步退款
- 基础资源维护：白名单拦截非法表、拒绝改主键、类型校验、外键 RESTRICT 保护

```bash
python tools/smoke_test.py
```

输出末尾应显示 `通过 N 项，失败 0 项`。

---

## 七、环境要求

- Python 3.9+（开发环境 3.14）
- MySQL 8.0+（使用了 CHECK 约束与 `INSERT ... ON DUPLICATE KEY UPDATE`）
- PyMySQL 1.1+
- Tkinter（Python 官方安装包默认自带）
