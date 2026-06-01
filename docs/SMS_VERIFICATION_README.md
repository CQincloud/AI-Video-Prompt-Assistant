# 手机号验证码登录实现说明

本文档说明当前项目中“手机号 + 短信验证码登录”的实现逻辑，包含验证码发送、阿里云短信接入、验证码校验、登录态创建、前端交互和常见排错。

## 1. 功能目标

用户在登录页输入手机号后，点击“获取验证码”，系统会生成一个随机 6 位数字验证码，通过阿里云短信发送给用户。

用户必须输入收到的验证码，且验证码未过期、未使用、与当前手机号匹配，才能完成登录。

## 2. 相关文件

| 文件 | 作用 |
|---|---|
| `static/login.html` | 普通用户手机号验证码登录页面 |
| `static/login.js` | 普通用户登录页交互逻辑 |
| `static/admin-login.js` | 后台登录页验证码交互逻辑 |
| `app/api/auth.py` | 普通用户登录认证接口 |
| `app/api/admin_auth.py` | 后台用户登录认证接口 |
| `app/models/auth.py` | 登录和发送验证码请求模型 |
| `app/services/auth_service.py` | 验证码生成、短信发送、验证码校验、登录态创建核心逻辑 |
| `app/config.py` | 短信、登录态、阿里云配置 |
| `database/migrations/001_initial_schema.sql` | `sms_codes`、`users`、`sessions` 表结构 |
| `.env.example` | 环境变量示例 |

## 3. 环境变量配置

正式使用阿里云短信时，`.env` 推荐配置如下：

```env
SMS_PROVIDER=aliyun
SMS_CODE_LENGTH=6
SMS_CODE_TTL_MINUTES=5
SMS_RESEND_INTERVAL_SECONDS=60
SMS_DAILY_LIMIT_PER_PHONE=10
SMS_HOURLY_LIMIT_PER_IP=30

ALIYUN_SMS_SIGN_NAME=武汉炬成科技
ALIYUN_SMS_TEMPLATE_CODE=SMS_333837184
ALIYUN_SMS_ENDPOINT=dysmsapi.aliyuncs.com

ALIBABA_CLOUD_ACCESS_KEY_ID=你的AccessKeyId
ALIBABA_CLOUD_ACCESS_KEY_SECRET=你的AccessKeySecret
```

也兼容下面这种本应用专用配置：

```env
ALIYUN_SMS_ACCESS_KEY_ID=你的AccessKeyId
ALIYUN_SMS_ACCESS_KEY_SECRET=你的AccessKeySecret
```

本地调试如果不想真实发短信，可以临时使用：

```env
SMS_PROVIDER=mock
SMS_MOCK_CODE=123456
```

注意：正式环境不要使用 `mock`。

## 4. 数据库表设计

验证码记录保存在 `sms_codes` 表中：

```sql
CREATE TABLE IF NOT EXISTS sms_codes (
    id BIGSERIAL PRIMARY KEY,
    mobile VARCHAR(20) NOT NULL,
    code_hash TEXT NOT NULL,
    used BOOLEAN NOT NULL DEFAULT FALSE,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ip VARCHAR(45)
);
```

关键点：

- 数据库不保存明文验证码，只保存验证码哈希。
- `mobile` 保存手机号。
- `code_hash` 保存验证码哈希。
- `used` 表示验证码是否已使用。
- `expires_at` 表示验证码过期时间。
- `ip` 用于发送频率限制。

## 5. 验证码发送流程

接口：

```http
POST /api/auth/send-code
Content-Type: application/json

{
  "phone": "18372086442"
}
```

核心流程在 `app/services/auth_service.py` 的 `send_code()`：

1. 校验手机号格式，必须是中国大陆 11 位手机号。
2. 检查发送频率限制：
   - 同一手机号发送间隔默认 60 秒。
   - 同一手机号每天默认最多 10 次。
   - 同一 IP 每小时默认最多 30 次。
3. 使用安全随机数生成 6 位数字验证码。
4. 使用 `AUTH_SECRET_KEY` 对 `手机号 + 验证码` 做 HMAC-SHA256 哈希。
5. 将同手机号旧的未使用验证码标记为已使用。
6. 插入新的验证码记录到 `sms_codes`。
7. 调用阿里云短信 SDK 发送验证码。
8. 返回发送成功信息。

成功响应：

```json
{
  "code": 200,
  "message": "验证码已发送",
  "data": {
    "sent": true,
    "expires_in": 300
  }
}
```

## 6. 阿里云短信发送逻辑

核心逻辑在 `app/services/auth_service.py` 的 `_deliver_sms()`。

正式环境使用：

```python
from alibabacloud_dysmsapi20170525.client import Client as DysmsapiClient
from alibabacloud_tea_openapi import models as open_api_models
from alibabacloud_tea_util import models as util_models
```

发送参数：

```python
phone_numbers=phone
sign_name=config.aliyun_sms_sign_name
template_code=config.aliyun_sms_template_code
template_param=json.dumps({"code": code}, ensure_ascii=False)
```

当前默认配置：

```env
ALIYUN_SMS_SIGN_NAME=武汉炬成科技
ALIYUN_SMS_TEMPLATE_CODE=SMS_333837184
ALIYUN_SMS_ENDPOINT=dysmsapi.aliyuncs.com
```

如果配置了 `ALIYUN_SMS_ACCESS_KEY_ID` / `ALIYUN_SMS_ACCESS_KEY_SECRET`，优先使用这组应用内配置。

否则使用 `.env` 中的 `ALIBABA_CLOUD_ACCESS_KEY_ID` / `ALIBABA_CLOUD_ACCESS_KEY_SECRET`。

当前代码会显式传入 AccessKey 初始化阿里云短信客户端，不再依赖 `CredentialClient()` 凭据链，避免部分 SDK 版本组合出现 `CredentialModel` 属性兼容问题。

## 7. 登录校验流程

接口：

```http
POST /api/auth/login
Content-Type: application/json

{
  "phone": "18372086442",
  "code": "123456"
}
```

核心流程在 `app/services/auth_service.py` 的 `login_with_code()`：

1. 校验手机号格式。
2. 校验验证码格式，必须是 6 位数字。
3. 使用手机号和用户输入的验证码生成哈希。
4. 查询该手机号最新一条：
   - 未使用
   - 未过期
   - 手机号匹配
   的验证码记录。
5. 使用 `hmac.compare_digest()` 安全比较验证码哈希。
6. 如果验证码错误或过期，返回 401。
7. 验证通过后，将该验证码标记为已使用。
8. 查询用户是否存在：
   - 不存在则自动创建用户。
   - 存在则更新最近登录时间和 IP。
   - 如果账号被禁用，则拒绝登录。
9. 创建随机登录 token。
10. 数据库只保存 token 哈希。
11. 通过 HTTP Only Cookie 写入登录态。

成功响应：

```json
{
  "code": 200,
  "message": "登录成功",
  "data": {
    "user": {
      "id": 1,
      "phone": "18372086442",
      "mobile": "18372086442",
      "role": "user",
      "status": 1
    }
  }
}
```

## 8. 前端交互流程

普通登录页逻辑在 `static/login.js`。

用户操作流程：

1. 用户输入手机号。
2. 点击“获取验证码”。
3. 前端调用 `/api/auth/send-code`。
4. 发送成功后：
   - 清空验证码输入框。
   - 聚焦验证码输入框。
   - 按钮进入 59 秒倒计时。
5. 用户输入 6 位验证码。
6. 点击“立即进入”。
7. 前端调用 `/api/auth/login`。
8. 登录成功后跳转到目标页面。

前端只做格式校验，真正的安全校验在后端。

## 9. 安全设计

当前验证码逻辑包含以下安全措施：

- 验证码随机生成，不使用固定验证码。
- 正式登录必须匹配数据库验证码记录。
- 验证码只保存哈希，不保存明文。
- 新验证码发送后，同手机号旧验证码自动作废。
- 验证码使用一次后立即作废。
- 验证码有过期时间，默认 5 分钟。
- 同手机号、同 IP 有发送频率限制。
- 登录 token 随机生成，数据库只保存 token 哈希。
- 登录 Cookie 使用 `HttpOnly`，前端 JavaScript 无法读取。

## 10. 常见问题

### 10.1 提示“短信签名或模板未配置”

检查 `.env`：

```env
ALIYUN_SMS_SIGN_NAME=武汉炬成科技
ALIYUN_SMS_TEMPLATE_CODE=SMS_333837184
ALIYUN_SMS_ENDPOINT=dysmsapi.aliyuncs.com
```

### 10.2 提示“短信 SDK 未安装”

确认依赖已安装：

```powershell
.\.venv\Scripts\activate
uv pip install -e .
```

或：

```powershell
pip install -e .
```

### 10.3 阿里云返回短信发送失败

检查以下内容：

- AccessKey 是否正确。
- RAM 用户是否有短信服务权限，例如 `AliyunDysmsFullAccess`。
- 短信签名是否审核通过。
- 短信模板是否审核通过。
- 模板变量是否为 `code`。
- 手机号是否符合大陆手机号格式。

如果日志中出现：

```text
code: 403, You are not authorized to perform this action
NoPermission
```

说明请求已经到达阿里云短信服务，但当前 AccessKey 所属的 RAM 用户没有调用短信接口的权限。请在阿里云 RAM 控制台给该 RAM 用户授权 `AliyunDysmsFullAccess`，或至少授权 `dysms:SendSms`。

### 10.4 登录提示“验证码错误或已过期”

可能原因：

- 输入的验证码不正确。
- 验证码超过 5 分钟。
- 重新获取验证码后，旧验证码已经作废。
- 验证码已经被使用过。
- 当前手机号和接收验证码的手机号不一致。

### 10.5 本地不想发真实短信

可以在 `.env` 临时切换：

```env
SMS_PROVIDER=mock
SMS_MOCK_CODE=123456
```

此时接口会返回调试验证码，方便本地开发。

## 11. 测试建议

### 11.1 本地 mock 测试

1. `.env` 设置：

```env
SMS_PROVIDER=mock
SMS_MOCK_CODE=123456
```

2. 启动服务。
3. 打开 `http://localhost:9900/login`。
4. 输入手机号并获取验证码。
5. 输入返回的调试验证码。
6. 确认可以登录。

### 11.2 阿里云真实短信测试

1. `.env` 设置：

```env
SMS_PROVIDER=aliyun
ALIBABA_CLOUD_ACCESS_KEY_ID=你的AccessKeyId
ALIBABA_CLOUD_ACCESS_KEY_SECRET=你的AccessKeySecret
ALIYUN_SMS_SIGN_NAME=武汉炬成科技
ALIYUN_SMS_TEMPLATE_CODE=SMS_333837184
```

2. 重启服务。
3. 打开 `http://localhost:9900/login`。
4. 输入真实手机号。
5. 点击获取验证码。
6. 收到短信后输入验证码。
7. 确认登录成功。

## 12. 生产环境注意事项

- 必须修改 `AUTH_SECRET_KEY`，不要使用默认值。
- 正式环境不要使用 `SMS_PROVIDER=mock`。
- 推荐使用 RAM 子用户，不要使用主账号 AccessKey。
- RAM 子用户只授予短信发送所需权限。
- AccessKey 不要提交到 Git。
- `.env` 应保存在服务器本地，并加入 `.gitignore`。
- 如果启用 HTTPS，建议设置：

```env
AUTH_COOKIE_SECURE=True
```
