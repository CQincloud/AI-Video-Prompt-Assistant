# 炬成 AI 视频提示词助手后台管理系统架构 V1

> 状态：正式定稿  
> 原则：这一版作为后台管理系统 V1 的唯一实现依据，不再反复调整架构。

## 一、整体架构

```text
一个项目
一个域名
同域名不同路径
前后台共用同一个后端
后台接口统一使用 /api/admin 前缀
数据库统一使用 PostgreSQL
```

访问路径：

```text
前台：
/login
/chat
/profile

后台：
/admin/login
/admin/users
```

第一版后台只开放：

```text
后台管理
└─ 用户管理
```

不要提前展示会员等级、操作日志、系统设置等尚未完成的入口。

---

## 二、当前数据库结构

后台 V1 主要依赖以下表：

```text
users
sms_codes
sessions
membership_levels
user_points_logs
```

作用：

```text
users                用户基础信息、角色、状态、积分
sms_codes            短信验证码
sessions             登录会话
membership_levels    会员等级规则
user_points_logs     积分变动流水
```

当前会员等级规则：

```text
0 <= points < 100       普通会员
100 <= points < 1000    高级会员
1000 <= points          超级会员
```

会员等级不是手动编辑字段，而是根据：

```text
users.points
```

匹配：

```text
membership_levels
```

计算得到。

---

## 三、后台页面

### 1. 后台登录页

路径：

```text
/admin/login
```

页面内容：

```text
炬成 AI 视频提示词后台管理系统

手机号输入框
验证码输入框
获取验证码按钮
登录按钮
```

登录逻辑：

```text
1. 输入手机号
2. 获取验证码
3. 输入验证码登录
4. 后端校验手机号和验证码
5. 后端检查 users.role
6. 只有 admin / super_admin 可以进入后台
7. 普通 user 拒绝进入后台
```

后台登录可以复用现有短信登录逻辑，但后台接口必须额外校验角色。

### 2. 用户管理页

路径：

```text
/admin/users
```

页面结构：

```text
顶部栏：
- 炬成 AI 视频提示词后台管理系统
- 当前管理员昵称
- 退出登录

左侧菜单：
- 用户管理

主内容区：
- 筛选区
- 用户表格
- 分页
- 详情抽屉
- 编辑弹窗
- 调整积分弹窗
- 积分流水弹窗 / 抽屉
```

---

## 四、用户管理功能

### 1. 筛选区

```text
手机号搜索
角色筛选：全部 / 普通用户 / 管理员 / 超级管理员
状态筛选：全部 / 正常 / 禁用
会员等级筛选：全部 / 普通会员 / 高级会员 / 超级会员
查询按钮
重置按钮
```

### 2. 表格字段

```text
ID
手机号
昵称
角色
积分
会员等级
状态
最近登录时间
注册时间
操作
```

会员等级展示逻辑：

```text
积分 = users.points
会员等级 = users.points 匹配 membership_levels 得出
```

### 3. 操作列

```text
查看
编辑
调整积分
启用 / 禁用
查看积分流水
```

第一版不做真删除。

删除用户先不要做，使用：

```text
禁用用户
```

代替删除。

---

## 五、详情、编辑、积分调整

### 1. 查看用户

建议使用右侧抽屉。

内容：

```text
基础信息
- 用户 ID
- 手机号
- 昵称
- 头像
- 角色
- 状态

会员信息
- 当前积分
- 当前会员等级

登录信息
- 注册时间
- 最近登录时间
- 最近登录 IP
```

### 2. 编辑用户

编辑字段按权限控制。

#### admin

```text
可改：
- 普通用户 nickname
- 普通用户 status

不可改：
- role
- 管理员用户
- 超级管理员用户
```

#### super_admin

```text
可改：
- nickname
- role
- status
```

注意：

```text
积分不要在编辑用户里直接改
会员等级也不要手动改
```

### 3. 调整积分

使用单独弹窗。

字段：

```text
当前积分
当前会员等级

调整类型：
- add：增加积分
- subtract：扣减积分
- adjust：直接调整到指定积分

调整数值
调整原因
确认按钮
取消按钮
```

#### 增加积分请求

```json
{
  "change_type": "add",
  "change_amount": 100,
  "reason": "后台手动赠送"
}
```

#### 扣减积分请求

```json
{
  "change_type": "subtract",
  "change_amount": 100,
  "reason": "违规扣减"
}
```

#### 直接调整到指定积分请求

```json
{
  "change_type": "adjust",
  "target_points": 500,
  "reason": "人工修正"
}
```

后端判断：

```text
add       使用 change_amount
subtract  使用 change_amount
adjust    使用 target_points
```

不要让 `adjust` 也使用 `change_amount`，避免语义混乱。

后端处理逻辑：

```text
1. 查询用户当前 points
2. 根据 change_type 计算新 points
3. 校验积分不能小于 0
4. 更新 users.points
5. 写入 user_points_logs
6. 返回最新积分和最新会员等级
```

不要相信前端传来的最终积分，最终积分必须由后端计算。

---

## 六、后台接口设计

### 1. 后台认证接口

```text
POST /api/admin/auth/send-code
POST /api/admin/auth/login
POST /api/admin/auth/logout
GET  /api/admin/auth/me
```

说明：

```text
send-code 和 login 可以复用现有短信验证码 service
但 admin login 必须额外判断 role 是否为 admin / super_admin
```

### 2. 用户管理接口

```text
GET    /api/admin/users
GET    /api/admin/users/{id}
PUT    /api/admin/users/{id}
PATCH  /api/admin/users/{id}/status
POST   /api/admin/users/{id}/points
GET    /api/admin/users/{id}/points-logs
```

---

## 七、接口返回格式

保持当前项目风格：

```json
{
  "code": 200,
  "message": "success",
  "data": {}
}
```

用户列表返回示例：

```json
{
  "code": 200,
  "message": "success",
  "data": {
    "list": [
      {
        "id": 1,
        "mobile": "18372086442",
        "nickname": "超级管理员",
        "role": "super_admin",
        "status": 1,
        "points": 1200,
        "membership_level": {
          "code": "super",
          "name": "超级会员"
        },
        "last_login_at": "2026-05-15 16:30:00",
        "created_at": "2026-05-15 15:00:00"
      }
    ],
    "total": 1,
    "page": 1,
    "page_size": 10
  }
}
```

---

## 八、核心 SQL

会员等级边界必须使用：

```sql
u.points >= ml.min_points
AND (
    ml.max_points IS NULL
    OR u.points < ml.max_points
)
```

完整查询：

```sql
SELECT
    u.id,
    u.mobile,
    u.nickname,
    u.avatar_url,
    u.role,
    u.status,
    u.points,
    u.last_login_at,
    u.last_login_ip,
    u.created_at,
    ml.code AS membership_code,
    ml.name AS membership_name
FROM users u
LEFT JOIN membership_levels ml
    ON u.points >= ml.min_points
   AND (
        ml.max_points IS NULL
        OR u.points < ml.max_points
   )
ORDER BY u.created_at DESC;
```

---

## 九、权限规则

### user

```text
不能进入后台
不能访问 /api/admin/*
```

### admin

```text
可以查看普通用户
可以编辑普通用户昵称
可以启用 / 禁用普通用户
可以调整普通用户积分
不能修改 role
不能管理 admin / super_admin
```

### super_admin

```text
可以查看全部用户
可以修改角色
可以启用 / 禁用用户
可以调整积分
可以管理管理员
```

权限必须由后端校验，前端隐藏按钮只是辅助。

---

## 十、第一版开发顺序

```text
1. 后台登录页 /admin/login
2. 后台登录接口
3. 后台鉴权中间件
4. 用户列表接口
5. 用户列表页面
6. 搜索 / 筛选 / 分页
7. 用户详情抽屉
8. 编辑用户弹窗
9. 启用 / 禁用
10. 调整积分
11. 积分流水查看
```

第一版目标：

```text
管理员能登录后台
能看到用户
能搜索筛选用户
能查看用户详情
能按权限编辑昵称、状态、角色
能调整积分
能查看积分流水
普通用户不能进入后台
```

---

## 十一、最终架构确定

```text
一个项目
一个域名
同域名不同路径
前后台共用后端
后台接口统一 /api/admin
第一版后台只开放用户管理
```

页面：

```text
/admin/login
/admin/users
```

数据库核心：

```text
users
sms_codes
sessions
membership_levels
user_points_logs
```

后台核心能力：

```text
后台登录
用户列表
用户筛选
用户详情
按权限编辑用户
启用 / 禁用用户
调整积分
查看积分流水
```

这份文档即为后台管理系统 V1 最终设计稿。
