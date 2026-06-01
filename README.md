# SuperBizAgent / Jucheng AI Assistant

基于 FastAPI、LangChain/LangGraph、DashScope、PostgreSQL 和 Milvus 的企业智能助手后端，包含 Web 对话界面、短信登录、用户管理、RAG 知识库问答、图片理解/生图和 AIOps 智能运维诊断。

## 当前能力

- Web 页面：`/` 对话首页，`/login` 用户登录，`/admin/login` 后台登录，`/admin/users` 用户管理。
- 登录认证：中国大陆手机号验证码登录，支持阿里云短信或本地 mock code。
- 用户与后台：普通用户、管理员、超级管理员，支持积分、状态和登录会话管理。
- RAG 问答：基于 DashScope/Qwen、Milvus 向量库和本地知识库文件进行检索增强回答。
- 流式对话：`/api/chat_stream` 使用 SSE 返回模型输出、工具调用和检索结果。
- 图片能力：图片理解接口和 DashScope 文生图接口。
- 文档索引：支持上传 `.txt`、`.md` 文件并写入向量索引。
- AIOps：基于 Plan-Execute-Replan 工作流，通过 MCP 工具查询日志和监控数据，生成诊断报告。

## 技术栈

- Python：`>=3.11,<3.14`
- Web 框架：FastAPI、Uvicorn、SSE Starlette
- Agent/RAG：LangChain、LangGraph、LangChain Milvus
- 大模型：阿里云 DashScope 兼容 OpenAI 协议接口
- 向量库：Milvus standalone
- 关系库：PostgreSQL，使用 `psycopg` 和 `psycopg_pool`
- 配置管理：Pydantic Settings，读取 `.env`
- 日志：Loguru，输出到 `logs/`

## 目录结构

```text
super_biz_agent_py/
  app/
    api/                  FastAPI 路由：认证、聊天、文件、AIOps、后台
    agent/                AIOps agent 与 MCP client
    core/                 PostgreSQL、Milvus、迁移、LLM 工厂
    models/               Pydantic 请求/响应模型
    services/             认证、聊天历史、RAG、图片、向量索引等业务服务
    tools/                Agent 工具
    utils/                日志等通用工具
    config.py             全局配置
    main.py               FastAPI 入口与启动生命周期
  database/
    migrations/           PostgreSQL 迁移 SQL
    README.md             数据库说明
  docs/knowledge_base/    内置 RAG 知识库目录
  aiops-docs/             AIOps 示例知识文档
  mcp_servers/            CLS 与 Monitor MCP 服务
  static/                 前端静态页面
  uploads/                上传文件与聊天图片
  logs/                   运行日志
  vector-database.yml     Milvus/etcd/minio/attu Docker Compose
  start-windows.bat       Windows 辅助启动脚本
  stop-windows.bat        Windows 辅助停止脚本
  pyproject.toml          依赖和工具配置
```

## 环境准备

必需：

- Python 3.11+
- PostgreSQL
- DashScope API Key

需要 RAG 或 AIOps 时还需要：

- Docker Desktop
- Milvus：通过 `vector-database.yml` 启动
- MCP 服务：`mcp_servers/cls_server.py` 和 `mcp_servers/monitor_server.py`

需要真实短信时还需要：

- 阿里云短信签名、模板和 AccessKey

## 安装依赖

Windows PowerShell：

```powershell
cd E:\juchengai\super_biz_agent_py
python -m venv .venv
.\.venv\Scripts\activate
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .
```

如果已经有 `.venv`，直接激活后安装即可：

```powershell
.\.venv\Scripts\activate
.\.venv\Scripts\python.exe -m pip install -e .
```

## 配置 `.env`

复制示例配置：

```powershell
Copy-Item .env.example .env
notepad .env
```

本地开发建议至少确认这些配置：

```env
APP_NAME=
APP_ENV=development
DEBUG=True
HOST=0.0.0.0
PORT=9900
DOCS_ENABLED=True
CORS_ALLOWED_ORIGINS=http://localhost:9900,http://127.0.0.1:9900

AUTH_SECRET_KEY=change-me-in-production
AUTH_COOKIE_NAME=jucheng_session
AUTH_COOKIE_SECURE=False
AUTH_SESSION_TTL_HOURS=168

SMS_PROVIDER=aliyun
SMS_MOCK_CODE=123456

DATABASE_HOST=localhost
DATABASE_PORT=
DATABASE_NAME=
DATABASE_USER=
DATABASE_PASSWORD=
DATABASE_POOL_ENABLED=True
DATABASE_VALIDATE_MIGRATIONS_ON_STARTUP=True
DATABASE_AUTO_MIGRATE_ON_STARTUP=False
DATABASE_ALLOW_UNTRACKED_SCHEMA_ENSURE=False

DASHSCOPE_API_KEY=your-dashscope-api-key
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
DASHSCOPE_TASK_BASE_URL=https://dashscope.aliyuncs.com/api/v1
DASHSCOPE_MODEL=qwen-max
DASHSCOPE_VISION_MODEL=qwen-vl-plus
DASHSCOPE_IMAGE_GENERATION_MODEL=wanx2.1-t2i-turbo
DASHSCOPE_EMBEDDING_MODEL=text-embedding-v4

MILVUS_HOST=localhost
MILVUS_PORT=19530
MILVUS_ALLOW_DESTRUCTIVE_SCHEMA_RESET=False

RAG_TOP_K=3
RAG_GROUNDING_TOP_K=5
KNOWLEDGE_BASE_PATH=./docs/knowledge_base
```

注意：当前代码里 `is_production` 会在 `DEBUG=False` 时触发生产安全校验。本地开发请保持 `APP_ENV=development` 且 `DEBUG=True`。如果使用生产模式，必须配置 HTTPS CORS 域名、强随机 `AUTH_SECRET_KEY`、安全 Cookie 和真实短信服务。

## 启动 PostgreSQL

后台启动时会初始化 PostgreSQL 连接池，并检查 `database/migrations` 是否已应用。如果 PostgreSQL 没启动，应用会在启动阶段失败。

先检查端口：

```powershell
Test-NetConnection localhost -Port 5432
Test-NetConnection localhost -Port 5433
```

哪个端口返回 `TcpTestSucceeded : True`，`.env` 里的 `DATABASE_PORT` 就填哪个。

如果本机没有 PostgreSQL，可以用 Docker 启动一个本地库：

```powershell
docker run --name xxx `
  -e POSTGRES_PASSWORD= xxx`
  -e POSTGRES_DB= xxx`
  -p 5432:5432 `
  -d postgres:16
```

如果你把宿主机端口映射到 `5433`，则 `.env` 改成：

```env
DATABASE_PORT=5433
```

## 执行数据库迁移

首次启动前执行：

```powershell
.\.venv\Scripts\python.exe scripts\manage_migrations.py status
.\.venv\Scripts\python.exe scripts\manage_migrations.py apply
.\.venv\Scripts\python.exe scripts\manage_migrations.py check
```

迁移文件当前包括：

- `001_initial_schema.sql`
- `002_membership_levels_no_overlap.sql`
- `003_user_points_logs.sql`
- `004_chat_history.sql`
- `005_chat_attachments.sql`
- `006_auth_login_rate_limits.sql`

## 启动 Milvus

RAG 检索和文档索引依赖 Milvus。先启动 Docker Desktop，然后执行：

```powershell
docker compose -f vector-database.yml up -d
```

服务端口：

- Milvus：`localhost:19530`
- MinIO：`localhost:9000`
- MinIO Console：`localhost:9001`
- Attu：`http://localhost:8000`

## 启动 MCP 服务

AIOps 诊断依赖两个 MCP 服务。分别打开两个 PowerShell 窗口：

```powershell
.\.venv\Scripts\python.exe mcp_servers\cls_server.py
```

```powershell
.\.venv\Scripts\python.exe mcp_servers\monitor_server.py
```

默认配置：

```env
MCP_CLS_URL=http://localhost:8003/mcp
MCP_MONITOR_URL=http://localhost:8004/mcp
```

## 启动后台

完整依赖准备好后执行：

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 9900
```

访问：

- Web 首页：http://localhost:9900
- 用户登录：http://localhost:9900/login
- 后台登录：http://localhost:9900/admin/login
- API 文档：http://localhost:9900/docs
- 健康检查：http://localhost:9900/health

## Windows 辅助脚本

项目包含：

```powershell
.\start-windows.bat
.\stop-windows.bat
```

`start-windows.bat` 会尝试同步依赖、启动 Milvus、启动 MCP 服务和 Uvicorn。它不会替你创建或启动 PostgreSQL，所以运行脚本前仍然需要先确认 PostgreSQL 可连接并完成迁移。

## 主要 API

公开页面：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/` | 对话首页 |
| GET | `/login` | 用户登录页 |
| GET | `/admin/login` | 后台登录页 |
| GET | `/admin/users` | 用户管理页 |
| GET | `/health` | 健康检查 |

认证：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/auth/send-code` | 发送用户登录验证码 |
| POST | `/api/auth/login` | 用户验证码登录 |
| GET | `/api/auth/me` | 获取当前用户 |
| POST | `/api/auth/logout` | 退出登录 |
| POST | `/api/admin/auth/send-code` | 发送后台登录验证码 |
| POST | `/api/admin/auth/login` | 后台登录 |
| GET | `/api/admin/auth/me` | 获取当前后台用户 |
| POST | `/api/admin/auth/logout` | 后台退出 |

聊天与图片：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/chat/sessions` | 查询会话列表 |
| POST | `/api/chat/sessions` | 创建会话 |
| GET | `/api/chat/sessions/{session_id}/messages` | 查询会话消息 |
| POST | `/api/chat/sessions/{session_id}/messages` | 追加原始消息 |
| DELETE | `/api/chat/sessions/{session_id}` | 删除会话 |
| POST | `/api/chat` | 普通 RAG 对话 |
| POST | `/api/chat_stream` | SSE 流式 RAG 对话 |
| POST | `/api/chat_vision` | 上传图片并进行视觉问答 |
| POST | `/api/images/generate` | 文生图 |
| POST | `/api/chat/clear` | 清空会话 |
| GET | `/api/chat/session/{session_id}` | 查询会话信息 |
| GET | `/api/chat/attachments/{attachment_id}/content` | 下载聊天附件 |

知识库与 AIOps：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/upload` | 上传 `.txt` 或 `.md` 并建立向量索引，仅超级管理员 |
| POST | `/api/index_directory` | 索引 `uploads` 或知识库目录，仅超级管理员 |
| POST | `/api/index_knowledge_base` | 索引内置知识库，仅超级管理员 |
| POST | `/api/aiops` | AIOps SSE 诊断，仅超级管理员 |

后台用户：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/admin/users` | 用户列表 |
| GET | `/api/admin/users/{user_id}` | 用户详情 |
| PUT | `/api/admin/users/{user_id}` | 更新用户资料 |
| PATCH | `/api/admin/users/{user_id}/status` | 修改用户状态 |
| POST | `/api/admin/users/{user_id}/points` | 调整用户积分 |
| GET | `/api/admin/users/{user_id}/points-logs` | 用户积分流水 |

## API 示例

发送验证码：

```powershell
curl -X POST "http://localhost:9900/api/auth/send-code" `
  -H "Content-Type: application/json" `
  -d "{\"phone\":\"13800138000\"}"
```

登录：

```powershell
curl -X POST "http://localhost:9900/api/auth/login" `
  -H "Content-Type: application/json" `
  -d "{\"phone\":\"13800138000\",\"code\":\"123456\"}" `
  -c cookies.txt
```

普通对话：

```powershell
curl -X POST "http://localhost:9900/api/chat" `
  -H "Content-Type: application/json" `
  -b cookies.txt `
  -d "{\"Id\":\"session-001\",\"Question\":\"介绍一下系统能力\"}"
```

流式对话：

```powershell
curl -X POST "http://localhost:9900/api/chat_stream" `
  -H "Content-Type: application/json" `
  -b cookies.txt `
  -d "{\"Id\":\"session-001\",\"Question\":\"根据知识库回答问题\"}" `
  --no-buffer
```

上传文档并索引：

```powershell
curl -X POST "http://localhost:9900/api/upload" `
  -b cookies.txt `
  -F "file=@aiops-docs/disk_high_usage.md"
```

AIOps 诊断：

```powershell
curl -X POST "http://localhost:9900/api/aiops" `
  -H "Content-Type: application/json" `
  -b cookies.txt `
  -d "{\"session_id\":\"aiops-001\"}" `
  --no-buffer
```

## 常见启动问题

### CORS_ALLOWED_ORIGINS 报错

现象：

```text
Unsafe production configuration: CORS_ALLOWED_ORIGINS must list the production web origin(s)
```

原因：当前代码在 `DEBUG=False` 时会进入生产配置校验。本地启动请改 `.env`：

```env
APP_ENV=development
DEBUG=True
CORS_ALLOWED_ORIGINS=http://localhost:9900,http://127.0.0.1:9900
```

生产环境则需要配置真实 HTTPS 前端域名：

```env
APP_ENV=production
DEBUG=False
CORS_ALLOWED_ORIGINS=https://your-domain.com
AUTH_COOKIE_SECURE=True
```

### PostgreSQL 连接池超时

现象：

```text
connection timeout expired
psycopg_pool.PoolTimeout: pool initialization incomplete after 5.0 sec
Application startup failed
```

原因：`.env` 指向的 `DATABASE_HOST:DATABASE_PORT` 没有 PostgreSQL 在监听。

检查：

```powershell
Test-NetConnection localhost -Port 5432
Test-NetConnection localhost -Port 5433
```

处理：

- 确认 PostgreSQL 已启动。
- 确认 `.env` 中 `DATABASE_PORT` 写的是实际监听端口。
- 确认 `DATABASE_NAME`、`DATABASE_USER`、`DATABASE_PASSWORD` 正确。
- 首次启动前执行 `scripts\manage_migrations.py apply`。

只想临时把后台壳启动起来时可以关闭启动期数据库检查：

```env
DATABASE_POOL_ENABLED=False
DATABASE_VALIDATE_MIGRATIONS_ON_STARTUP=False
```

这只适合临时排查。登录、用户、聊天历史等依赖数据库的功能仍然不能正常使用。

### Milvus 不可用

现象：启动日志提示 Milvus unavailable，或上传文档后无法建立向量索引。

处理：

```powershell
docker compose -f vector-database.yml up -d
docker ps
```

确认 `.env`：

```env
MILVUS_HOST=localhost
MILVUS_PORT=19530
```

### DashScope 报错

检查 `.env`：

```env
DASHSCOPE_API_KEY=your-dashscope-api-key
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
```

如果图片理解或生图失败，还需要检查：

```env
DASHSCOPE_VISION_MODEL=qwen-vl-plus
DASHSCOPE_IMAGE_GENERATION_MODEL=wanx2.1-t2i-turbo
```

## 开发命令

```powershell
# 启动 API
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 9900

# 数据库迁移
.\.venv\Scripts\python.exe scripts\manage_migrations.py status
.\.venv\Scripts\python.exe scripts\manage_migrations.py apply
.\.venv\Scripts\python.exe scripts\manage_migrations.py check

# 启动 Milvus
docker compose -f vector-database.yml up -d

# 停止 Milvus
docker compose -f vector-database.yml down

# 启动 MCP 服务
.\.venv\Scripts\python.exe mcp_servers\cls_server.py
.\.venv\Scripts\python.exe mcp_servers\monitor_server.py
```

## 运行顺序建议

1. 配好 `.env`。
2. 启动 PostgreSQL，并确认端口可连接。
3. 执行数据库迁移。
4. 启动 Docker Desktop。
5. 启动 Milvus。
6. 启动两个 MCP 服务。
7. 启动 Uvicorn 后台。
8. 打开 `http://localhost:9900` 或 `http://localhost:9900/docs` 验证。
