# 宝塔面板部署指南

本文按当前项目结构编写，适用于把 `super_biz_agent_py` 部署到云服务器，并通过宝塔 Nginx 反向代理绑定域名。

当前截图中的状态：

- 服务器公网 IP：`47.94.37.145`
- 域名：`jucheng-ai.com`
- DNS：`@` 和 `www` 都已解析到 `47.94.37.145`
- 宝塔反向代理：`jucheng-ai.com` 已代理到 `http://127.0.0.1:9900`
- 项目目录：`/www/wwwroot/super_biz_agent_py`

## 推荐架构

```text
浏览器
  |
  | https://jucheng-ai.com
  v
宝塔 Nginx + SSL
  |
  | http://127.0.0.1:9900
  v
FastAPI / Uvicorn
  |
  +-- PostgreSQL：用户、登录、聊天记录、后台管理
  +-- Milvus：RAG 向量检索
  +-- DashScope：大模型、Embedding、视觉、文生图
  +-- MCP 服务：AIOps 日志和监控工具
```

Uvicorn 建议只监听 `127.0.0.1:9900`，不要把 `9900` 直接开放到公网。

## 1. 检查域名和安全组

阿里云 DNS 已配置：

```text
jucheng-ai.com      A    47.94.37.145
www.jucheng-ai.com  A    47.94.37.145
```

云服务器安全组和宝塔防火墙建议只开放：

```text
80/tcp
443/tcp
宝塔面板端口，仅允许可信 IP 访问
```

不要对公网开放：

```text
9900/tcp
5432/tcp
19530/tcp
9000/tcp
9001/tcp
```

如果服务器在中国大陆，域名正式对外访问通常还需要完成 ICP 备案。

## 2. 上传或更新最新代码

进入宝塔：文件 -> `/www/wwwroot/super_biz_agent_py`。

不要上传本地这些目录：

```text
.venv/
logs/
uploads/
volumes/
__pycache__/
*.pyc
```

也不要直接用本地 `.env` 覆盖服务器 `.env`，服务器上的 `.env` 应该单独维护生产配置和密钥。

如果服务器目录是 Git 仓库，可在宝塔终端执行：

```bash
cd /www/wwwroot/super_biz_agent_py
git pull
```

如果不是 Git 仓库，就在本地打包项目源码，上传 zip 后解压覆盖。覆盖前建议先备份服务器当前目录：

```bash
cd /www/wwwroot
cp -a super_biz_agent_py super_biz_agent_py_backup_$(date +%Y%m%d_%H%M%S)
```

## 3. 安装 Python 依赖

进入宝塔终端：

```bash
cd /www/wwwroot/super_biz_agent_py
python3 --version
```

项目要求 Python `>=3.11,<3.14`。如果系统 Python 版本太低，请在宝塔软件商店安装 Python 3.11/3.12，或使用系统包管理器安装。

创建虚拟环境并安装依赖：

```bash
cd /www/wwwroot/super_biz_agent_py
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

如果已经有 `.venv`，更新代码后执行：

```bash
cd /www/wwwroot/super_biz_agent_py
. .venv/bin/activate
python -m pip install -e .
```

## 4. 配置生产 `.env`

在宝塔文件管理器编辑：

```text
/www/wwwroot/super_biz_agent_py/.env
```

生产环境建议配置：

```env
APP_NAME=JuchengAIAssistant
APP_ENV=production
DEBUG=False
HOST=127.0.0.1
PORT=9900
DOCS_ENABLED=False
CORS_ALLOWED_ORIGINS=https://jucheng-ai.com,https://www.jucheng-ai.com

AUTH_SECRET_KEY=替换为至少32位的强随机字符串
AUTH_COOKIE_NAME=jucheng_session
AUTH_COOKIE_SECURE=True
AUTH_SESSION_TTL_HOURS=168
AUTH_TRUSTED_PROXY_IPS=127.0.0.1,::1

SMS_PROVIDER=aliyun
SMS_CODE_LENGTH=6
SMS_CODE_TTL_MINUTES=5
SMS_RESEND_INTERVAL_SECONDS=60
SMS_DAILY_LIMIT_PER_PHONE=10
SMS_HOURLY_LIMIT_PER_IP=30
ALIYUN_SMS_SIGN_NAME=你的短信签名
ALIYUN_SMS_TEMPLATE_CODE=你的短信模板CODE
ALIYUN_SMS_ENDPOINT=dysmsapi.aliyuncs.com
ALIYUN_SMS_ACCESS_KEY_ID=你的阿里云AccessKeyId
ALIYUN_SMS_ACCESS_KEY_SECRET=你的阿里云AccessKeySecret

DATABASE_HOST=127.0.0.1
DATABASE_PORT=5432
DATABASE_NAME=jucheng_ai_user
DATABASE_USER=postgres
DATABASE_PASSWORD=你的数据库密码
DATABASE_POOL_ENABLED=True
DATABASE_VALIDATE_MIGRATIONS_ON_STARTUP=True
DATABASE_AUTO_MIGRATE_ON_STARTUP=False
DATABASE_ALLOW_UNTRACKED_SCHEMA_ENSURE=False

DASHSCOPE_API_KEY=你的DashScopeKey
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
DASHSCOPE_TASK_BASE_URL=https://dashscope.aliyuncs.com/api/v1
DASHSCOPE_MODEL=qwen-max
DASHSCOPE_VISION_MODEL=qwen-vl-plus
DASHSCOPE_IMAGE_GENERATION_MODEL=wanx2.1-t2i-turbo
DASHSCOPE_EMBEDDING_MODEL=text-embedding-v4

MILVUS_HOST=127.0.0.1
MILVUS_PORT=19530
MILVUS_TIMEOUT=10000
MILVUS_ALLOW_DESTRUCTIVE_SCHEMA_RESET=False

MCP_CLS_TRANSPORT=streamable-http
MCP_CLS_URL=http://127.0.0.1:8003/mcp
MCP_MONITOR_TRANSPORT=streamable-http
MCP_MONITOR_URL=http://127.0.0.1:8004/mcp
```

生成 `AUTH_SECRET_KEY`：

```bash
openssl rand -hex 32
```

## 5. 准备 PostgreSQL

方式一：使用宝塔数据库面板安装 PostgreSQL，然后创建：

```text
数据库：jucheng_ai_user
用户：postgres 或单独创建业务用户
密码：写入 .env 的 DATABASE_PASSWORD
端口：5432
```

方式二：使用 Docker 启动 PostgreSQL：

```bash
docker run --name jucheng-postgres \
  -e POSTGRES_PASSWORD=你的数据库密码 \
  -e POSTGRES_DB=jucheng_ai_user \
  -p 127.0.0.1:5432:5432 \
  -v /www/server/data/postgres/jucheng:/var/lib/postgresql/data \
  -d postgres:16
```

检查连接：

```bash
cd /www/wwwroot/super_biz_agent_py
. .venv/bin/activate
python scripts/manage_migrations.py status
```

首次部署执行迁移：

```bash
python scripts/manage_migrations.py apply
python scripts/manage_migrations.py check
```

## 6. 启动 Milvus

先确认 Docker 服务正常，然后执行：

```bash
cd /www/wwwroot/super_biz_agent_py
docker compose -f vector-database.yml up -d
docker ps
```

至少需要看到：

```text
milvus-etcd
milvus-minio
milvus-standalone
```

如果服务器内存较小，Milvus 可能启动较慢，等待 1 到 3 分钟再启动后端。

## 7. 启动 MCP 服务

创建 systemd 服务：

```bash
cat >/etc/systemd/system/jucheng-cls-mcp.service <<'EOF'
[Unit]
Description=Jucheng CLS MCP Server
After=network.target

[Service]
Type=simple
User=www
Group=www
WorkingDirectory=/www/wwwroot/super_biz_agent_py
ExecStart=/www/wwwroot/super_biz_agent_py/.venv/bin/python mcp_servers/cls_server.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

cat >/etc/systemd/system/jucheng-monitor-mcp.service <<'EOF'
[Unit]
Description=Jucheng Monitor MCP Server
After=network.target

[Service]
Type=simple
User=www
Group=www
WorkingDirectory=/www/wwwroot/super_biz_agent_py
ExecStart=/www/wwwroot/super_biz_agent_py/.venv/bin/python mcp_servers/monitor_server.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now jucheng-cls-mcp
systemctl enable --now jucheng-monitor-mcp
systemctl status jucheng-cls-mcp --no-pager
systemctl status jucheng-monitor-mcp --no-pager
```

## 8. 启动 FastAPI 后台

先设置目录权限：

```bash
cd /www/wwwroot/super_biz_agent_py
mkdir -p logs uploads
chown -R www:www /www/wwwroot/super_biz_agent_py
```

创建 systemd 服务：

```bash
cat >/etc/systemd/system/jucheng-ai.service <<'EOF'
[Unit]
Description=Jucheng AI FastAPI Service
After=network.target docker.service
Wants=docker.service

[Service]
Type=simple
User=www
Group=www
WorkingDirectory=/www/wwwroot/super_biz_agent_py
Environment=PYTHONUNBUFFERED=1
ExecStart=/www/wwwroot/super_biz_agent_py/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 9900
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now jucheng-ai
systemctl status jucheng-ai --no-pager
```

查看实时日志：

```bash
journalctl -u jucheng-ai -f
```

本机验证：

```bash
curl -I http://127.0.0.1:9900/health
curl -I http://127.0.0.1:9900/
```

## 9. 配置宝塔反向代理

宝塔面板：

```text
网站 -> 反向代理 -> jucheng-ai.com -> 设置
```

代理地址：

```text
http://127.0.0.1:9900
```

建议在反向代理配置里确保有这些参数，避免 SSE 流式接口被缓冲：

```nginx
proxy_set_header Host $host;
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Proto $scheme;
proxy_http_version 1.1;
proxy_set_header Connection "";
proxy_buffering off;
proxy_cache off;
proxy_read_timeout 3600s;
proxy_send_timeout 3600s;
```

如果要支持 `www.jucheng-ai.com`，需要在宝塔网站域名里也添加：

```text
www.jucheng-ai.com
```

并把 SSL 证书同时签发给 `jucheng-ai.com` 和 `www.jucheng-ai.com`。

## 10. 配置 SSL

宝塔面板：

```text
网站 -> jucheng-ai.com -> SSL
```

建议：

- 申请 Let's Encrypt 证书。
- 勾选强制 HTTPS。
- 证书域名包含 `jucheng-ai.com` 和 `www.jucheng-ai.com`。

## 11. 发布新版本流程

每次更新项目：

```bash
cd /www/wwwroot/super_biz_agent_py

# 如果用 Git
git pull

# 更新依赖
. .venv/bin/activate
python -m pip install -e .

# 如有数据库变更，执行迁移
python scripts/manage_migrations.py apply
python scripts/manage_migrations.py check

# 重启服务
systemctl restart jucheng-ai
systemctl restart jucheng-cls-mcp
systemctl restart jucheng-monitor-mcp

# 看日志
journalctl -u jucheng-ai -n 100 --no-pager
```

访问验证：

```bash
curl -I https://jucheng-ai.com/health
curl -I https://jucheng-ai.com/
```

## 常见问题

### 502 Bad Gateway

说明宝塔 Nginx 连不上 `127.0.0.1:9900`。

检查：

```bash
systemctl status jucheng-ai --no-pager
journalctl -u jucheng-ai -n 100 --no-pager
curl -I http://127.0.0.1:9900/health
```

### 数据库连接超时

日志示例：

```text
psycopg_pool.PoolTimeout: pool initialization incomplete after 5.0 sec
connection timeout expired
```

处理：

```bash
ss -lntp | grep 5432
cat /www/wwwroot/super_biz_agent_py/.env | grep DATABASE_
```

确认 PostgreSQL 已启动、端口正确、账号密码正确。

### 生产配置校验失败

日志示例：

```text
Unsafe production configuration
```

生产环境必须满足：

```env
APP_ENV=production
DEBUG=False
CORS_ALLOWED_ORIGINS=https://jucheng-ai.com,https://www.jucheng-ai.com
AUTH_COOKIE_SECURE=True
AUTH_SECRET_KEY=至少32位强随机字符串
```

### 流式对话卡住或一次性返回

检查宝塔反向代理是否关闭缓冲：

```nginx
proxy_buffering off;
proxy_cache off;
proxy_read_timeout 3600s;
```

### www 域名打不开

DNS 有 `www` 解析还不够，还需要在宝塔网站里把 `www.jucheng-ai.com` 加到同一个站点，并重新申请包含 `www` 的 SSL 证书。
