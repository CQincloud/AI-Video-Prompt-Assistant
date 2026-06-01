# PostgreSQL 数据库笔记

> 更新时间：2026-05-18  
> 数据库：`jucheng_ai_user`  
> 默认开发连接：`localhost:5433`

## 1. 当前数据库定位

当前 PostgreSQL 主要承载三类能力：

1. 用户账户与角色
2. 手机验证码登录与会话
3. 基于积分的会员等级规则

当前共有 5 张业务表：

```text
users
membership_levels
sms_codes
sessions
user_points_logs
```

## 2. 表关系总览

```text
users
  ├─ 1 : N → sessions
  ├─ 1 : N → user_points_logs
  └─ points → membership_levels（按积分区间匹配，不是外键）

sms_codes
  └─ 独立保存验证码发送与使用记录
```

说明：

- `users` 是用户主表
- `sessions.user_id` 外键关联 `users.id`
- `user_points_logs.user_id` 外键关联 `users.id`
- `user_points_logs.operator_id` 可选外键关联 `users.id`
- `membership_levels` 不直接外键关联用户，而是通过 `users.points` 落在哪个积分区间来判断当前等级
- `sms_codes` 只保存验证码哈希，不保存明文验证码

---

## 3. 表结构说明

### 3.1 `users` 用户表

用途：保存用户基础信息、角色、状态和当前积分。

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | `BIGSERIAL` | 主键 |
| `mobile` | `VARCHAR(20)` | 手机号，唯一 |
| `nickname` | `VARCHAR(50)` | 昵称，默认空字符串 |
| `avatar_url` | `TEXT` | 头像地址 |
| `role` | `VARCHAR(20)` | 角色：`user` / `admin` / `super_admin` |
| `status` | `SMALLINT` | 状态：`1` 正常，`0` 禁用 |
| `last_login_at` | `TIMESTAMPTZ` | 最近登录时间 |
| `last_login_ip` | `VARCHAR(45)` | 最近登录 IP |
| `created_at` | `TIMESTAMPTZ` | 创建时间 |
| `updated_at` | `TIMESTAMPTZ` | 更新时间 |
| `points` | `INTEGER` | 当前积分 |

关键约束：

- `mobile` 唯一
- `role` 只能取 `user / admin / super_admin`
- `status` 只能取 `0 / 1`
- `points >= 0`

关键索引：

- 主键索引：`users_pkey`
- 手机号唯一索引：`users_mobile_key`

触发器：

- `trigger_users_updated_at`
- 每次更新用户时自动刷新 `updated_at`

---

### 3.2 `membership_levels` 会员等级规则表

用途：定义“多少积分属于哪个等级”。

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | `BIGSERIAL` | 主键 |
| `code` | `VARCHAR(20)` | 等级编码，唯一 |
| `name` | `VARCHAR(50)` | 等级名称 |
| `min_points` | `INTEGER` | 区间下限，包含 |
| `max_points` | `INTEGER` | 区间上限，不包含；`NULL` 表示无上限 |
| `sort_order` | `INTEGER` | 排序 |
| `created_at` | `TIMESTAMPTZ` | 创建时间 |
| `updated_at` | `TIMESTAMPTZ` | 更新时间 |

当前规则：

| 编码 | 名称 | 积分范围 |
|---|---|---|
| `normal` | 普通会员 | `0 <= points < 100` |
| `premium` | 高级会员 | `100 <= points < 1000` |
| `super` | 超级会员 | `1000 <= points` |

关键约束：

- `code` 唯一
- `min_points >= 0`
- `max_points IS NULL OR max_points > min_points`
- `membership_levels_points_no_overlap`：任何积分区间都不能互相重叠

关键索引：

- `idx_membership_levels_points(min_points, max_points)`

触发器：

- `trigger_membership_levels_updated_at`
- 每次更新规则时自动刷新 `updated_at`

---

### 3.3 `sms_codes` 短信验证码表

用途：保存验证码发送记录，支撑登录、限流和风控。

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | `BIGSERIAL` | 主键 |
| `mobile` | `VARCHAR(20)` | 手机号 |
| `code_hash` | `TEXT` | 验证码哈希 |
| `used` | `BOOLEAN` | 是否已使用 |
| `expires_at` | `TIMESTAMPTZ` | 过期时间 |
| `created_at` | `TIMESTAMPTZ` | 创建时间 |
| `ip` | `VARCHAR(45)` | 请求 IP |

关键索引：

- `idx_sms_codes_mobile_created_at(mobile, created_at DESC)`
- `idx_sms_codes_mobile_used_expires(mobile, used, expires_at)`

设计说明：

- 不保存明文验证码
- 通过手机号、使用状态、过期时间快速定位可用验证码
- 可按手机号/IP 做发送频控

---

### 3.4 `sessions` 会话表

用途：保存用户登录态。

| 字段 | 类型 | 说明 |
|---|---|---|
| `token_hash` | `TEXT` | 主键，保存 token 哈希 |
| `user_id` | `BIGINT` | 用户 ID，外键关联 `users.id` |
| `created_at` | `TIMESTAMPTZ` | 创建时间 |
| `expires_at` | `TIMESTAMPTZ` | 过期时间 |
| `last_seen_at` | `TIMESTAMPTZ` | 最近活跃时间 |
| `ip` | `VARCHAR(45)` | 登录 IP |
| `user_agent` | `TEXT` | 设备 / 浏览器信息 |

关键约束：

- `user_id` 外键关联 `users.id`

关键索引：

- `idx_sessions_user_id(user_id)`
- `idx_sessions_expires_at(expires_at)`

---

### 3.5 `user_points_logs` 用户积分流水表

用途：记录用户积分每一次变化的原因和前后余额。

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | `BIGSERIAL` | 主键 |
| `user_id` | `BIGINT` | 被调整积分的用户 |
| `change_type` | `VARCHAR(20)` | 变化类型：`add` / `subtract` / `adjust` |
| `change_amount` | `INTEGER` | 本次变化分值，必须大于 0 |
| `before_points` | `INTEGER` | 变化前积分 |
| `after_points` | `INTEGER` | 变化后积分 |
| `reason` | `TEXT` | 调整原因 |
| `operator_id` | `BIGINT` | 操作人；系统自动变更时可为空 |
| `created_at` | `TIMESTAMPTZ` | 创建时间 |

关键约束：

- `user_id` 外键关联 `users.id`
- `operator_id` 可选外键关联 `users.id`
- `change_type` 只能取 `add / subtract / adjust`
- `change_amount > 0`
- `before_points >= 0`
- `after_points >= 0`
- `add` 时必须满足：`after_points = before_points + change_amount`
- `subtract` 时必须满足：`after_points = before_points - change_amount`

关键索引：

- `idx_user_points_logs_user_created(user_id, created_at DESC)`
- `idx_user_points_logs_operator_created(operator_id, created_at DESC)`

设计说明：

- `users.points` 表示当前余额
- `user_points_logs` 表示每一笔来龙去脉
- 后台以后做“调整积分”时，应先更新 `users.points`，再同步写入一条流水

---

## 4. 会员等级查询方式

当前等级不是直接存回 `users` 表，而是根据积分实时匹配：

```sql
SELECT
    u.id,
    u.mobile,
    u.points,
    ml.code AS level_code,
    ml.name AS level_name
FROM users u
JOIN membership_levels ml
    ON u.points >= ml.min_points
   AND (ml.max_points IS NULL OR u.points < ml.max_points)
WHERE u.id = 1;
```

这样设计的好处：

- 积分和等级不会出现互相打架
- 调整等级规则时，不需要批量改每个用户
- 后台列表可以按 `users.points` 直接计算会员等级

---

## 5. 当前默认数据

### 5.1 默认会员等级

```text
normal   普通会员   0 ~ 99
premium  高级会员   100 ~ 999
super    超级会员   1000+
```

### 5.2 默认超级管理员

```text
mobile: 18372086442
role: super_admin
status: 1
points: 0
```

---

## 6. 已有数据库函数与触发器

### 函数

```text
update_updated_at_column()
```

用途：在更新数据时自动写入新的 `updated_at`。

### 触发器

```text
trigger_users_updated_at
trigger_membership_levels_updated_at
```

---

## 7. 当前设计约定

1. 时间字段统一使用 `TIMESTAMPTZ`
2. 用户当前积分存放在 `users.points`
3. 会员等级由 `membership_levels` 规则实时计算
4. 验证码只保存哈希
5. 登录 token 只保存哈希
6. 管理员与普通用户共用 `users` 表，通过 `role` 区分
7. 第一版后台如果展示会员等级，应通过积分区间查询得出，不应再单独保存一份等级字段

---

## 8. 目前还缺的表

当前数据库已经能支撑：

- 用户登录
- 会话管理
- 基础会员等级判断

但如果继续开发后台管理，后续建议补：

### 8.1 `admin_operation_logs`

用途：记录管理员修改用户、禁用用户、调整积分等操作。

建议字段：

```text
id
operator_id
action
target_type
target_id
detail
ip
created_at
```

---

## 9. 相关代码文件

| 文件 | 作用 |
|---|---|
| `app/core/database.py` | PostgreSQL 统一连接入口 |
| `app/services/auth_service.py` | 用户、验证码、会话的数据库读写 |
| `app/config.py` | 数据库配置读取 |
| `.env` | 本地真实配置 |
| `.env.example` | 配置模板 |
| `database/migrations/001_initial_schema.sql` | 初始表结构 |
| `database/migrations/002_membership_levels_no_overlap.sql` | 会员区间防重叠约束 |
| `database/migrations/003_user_points_logs.sql` | 用户积分流水表 |

---

## 10. 常用 SQL

### 查看所有用户及其会员等级

```sql
SELECT
    u.id,
    u.mobile,
    u.nickname,
    u.role,
    u.status,
    u.points,
    ml.name AS membership_level,
    u.last_login_at,
    u.created_at
FROM users u
JOIN membership_levels ml
    ON u.points >= ml.min_points
   AND (ml.max_points IS NULL OR u.points < ml.max_points)
ORDER BY u.id;
```

### 查看当前会员规则

```sql
SELECT code, name, min_points, max_points, sort_order
FROM membership_levels
ORDER BY sort_order;
```

### 查看未过期会话

```sql
SELECT *
FROM sessions
WHERE expires_at >= CURRENT_TIMESTAMP
ORDER BY created_at DESC;
```

### 查看某个用户的积分流水

```sql
SELECT
    id,
    user_id,
    change_type,
    change_amount,
    before_points,
    after_points,
    reason,
    operator_id,
    created_at
FROM user_points_logs
WHERE user_id = 1
ORDER BY created_at DESC;
```
