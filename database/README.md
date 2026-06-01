# PostgreSQL 目录说明

这个目录保存项目的 PostgreSQL 结构来源，不再让数据库定义只存在于某一台机器里。

## 文件

- `migrations/001_initial_schema.sql`：当前系统的基础表结构、触发器和初始化数据
- `migrations/002_membership_levels_no_overlap.sql`：防止会员积分区间互相重叠
- `migrations/003_user_points_logs.sql`：用户积分流水表
- `migrations/004_chat_history.sql`：AI 对话会话表和原始消息表
- `migrations/005_chat_attachments.sql`：对话图片附件表

## 当前数据库

- 数据库名：`jucheng_ai_user`
- 运行环境：本地 PostgreSQL
- 默认开发端口：`5433`

## 手动执行迁移

在项目根目录执行：

```powershell
psql -h localhost -p 5433 -U postgres -d jucheng_ai_user -f database/migrations/001_initial_schema.sql
psql -h localhost -p 5433 -U postgres -d jucheng_ai_user -f database/migrations/002_membership_levels_no_overlap.sql
psql -h localhost -p 5433 -U postgres -d jucheng_ai_user -f database/migrations/003_user_points_logs.sql
psql -h localhost -p 5433 -U postgres -d jucheng_ai_user -f database/migrations/004_chat_history.sql
psql -h localhost -p 5433 -U postgres -d jucheng_ai_user -f database/migrations/005_chat_attachments.sql
```

## 设计约定

- 用户当前积分保存在 `users.points`
- 当前会员等级由 `membership_levels` 的积分区间规则计算得出
- 区间采用左闭右开：`min_points <= points < max_points`
- `max_points IS NULL` 表示没有上限
- 登录态保存在 `sessions`
- 验证码只保存 `code_hash`，不保存明文验证码
- 当前积分保存在 `users.points`，每次积分变化记录在 `user_points_logs`
- AI 对话原始记录保存在 `chat_sessions` 和 `chat_messages`，按 `user_id` 做用户隔离
- 图片识别和生图结果的附件元数据保存在 `chat_attachments`

## 受控迁移流程

生产环境不要在应用启动时自动建表或改表。发布前先显式执行：

```powershell
python scripts/manage_migrations.py status
python scripts/manage_migrations.py apply
python scripts/manage_migrations.py check
```

迁移状态会记录在 `schema_migrations` 表中，包括版本号、文件名、SHA-256 校验和和执行时间。
已经应用过的迁移文件不能再修改；需要变更结构时，新建下一个递增编号的 SQL 文件。

生产配置要求：

```env
DATABASE_VALIDATE_MIGRATIONS_ON_STARTUP=True
DATABASE_AUTO_MIGRATE_ON_STARTUP=False
DATABASE_ALLOW_UNTRACKED_SCHEMA_ENSURE=False
```
