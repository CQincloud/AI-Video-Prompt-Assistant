# AI-Video-Prompt-Assistant

AI-Video-Prompt-Assistant is a FastAPI-based AI assistant for video prompt creation, RAG knowledge-base retrieval, image understanding, image generation, and admin-managed user workflows. It integrates DashScope/Qwen, LangChain/LangGraph, PostgreSQL, and Milvus, with a static web chat interface and streaming responses.

## Features

- AI video prompt assistant with template-driven prompt generation.
- RAG chat powered by DashScope/Qwen, LangChain, and a local knowledge base.
- SSE streaming chat endpoint for model output, tool events, and retrieval results.
- Image understanding and text-to-image generation through DashScope models.
- User login with mainland China phone verification code support.
- Admin user management with roles, account status, sessions, and points.
- Document upload and vector indexing for `.txt` and `.md` files.
- AIOps diagnosis workflow based on Plan-Execute-Replan and MCP tools.

## Tech Stack

- Python `>=3.11,<3.14`
- FastAPI, Uvicorn, SSE Starlette
- LangChain, LangGraph, LangChain Milvus
- DashScope/Qwen compatible with the OpenAI-style API
- PostgreSQL with `psycopg` and `psycopg_pool`
- Milvus standalone for vector search
- Pydantic Settings for `.env` configuration
- Loguru for application logs

## Project Structure

```text
super_biz_agent_py/
  app/
    api/                  FastAPI routes for auth, chat, files, AIOps, and admin
    agent/                AIOps agent and MCP client
    core/                 PostgreSQL, Milvus, migrations, and LLM factory
    models/               Pydantic request and response models
    services/             Auth, chat history, RAG, image, vector, and admin services
    tools/                Agent tools
    utils/                Shared utilities
    config.py             Application settings
    main.py               FastAPI entrypoint
  aiops-docs/             Example AIOps knowledge documents
  database/
    migrations/           PostgreSQL migration SQL files
  docs/knowledge_base/    Built-in RAG knowledge base
  mcp_servers/            CLS and monitor MCP services
  static/                 Frontend static pages and assets
  vector-database.yml     Milvus, etcd, MinIO, and Attu Docker Compose file
  start-windows.bat       Windows startup helper
  stop-windows.bat        Windows stop helper
  pyproject.toml          Dependencies and tool configuration
```

## Requirements

Required:

- Python 3.11+
- PostgreSQL
- DashScope API key

Required for RAG and AIOps:

- Docker Desktop
- Milvus, started with `vector-database.yml`
- MCP services in `mcp_servers/`

Required for real SMS login:

- Aliyun SMS signature, template, AccessKey ID, and AccessKey secret

## Installation

Windows PowerShell:

```powershell
cd E:\juchengai\super_biz_agent_py
python -m venv .venv
.\.venv\Scripts\activate
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .
```

If `.venv` already exists:

```powershell
.\.venv\Scripts\activate
.\.venv\Scripts\python.exe -m pip install -e .
```

## Configuration

Copy the example environment file:

```powershell
Copy-Item .env.example .env
notepad .env
```

Minimum local development settings:

```env
APP_NAME=AI-Video-Prompt-Assistant
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
DATABASE_PORT=5432
DATABASE_NAME=your_database
DATABASE_USER=your_user
DATABASE_PASSWORD=your_password
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

For local development, keep `APP_ENV=development` and `DEBUG=True`. Production mode requires HTTPS CORS origins, a strong random `AUTH_SECRET_KEY`, secure cookies, and real SMS service configuration.

## Database Setup

Check the PostgreSQL port:

```powershell
Test-NetConnection localhost -Port 5432
Test-NetConnection localhost -Port 5433
```

Use the port that returns `TcpTestSucceeded : True` in `.env`.

Run migrations before the first startup:

```powershell
.\.venv\Scripts\python.exe scripts\manage_migrations.py status
.\.venv\Scripts\python.exe scripts\manage_migrations.py apply
.\.venv\Scripts\python.exe scripts\manage_migrations.py check
```

## Vector Database

Start Milvus:

```powershell
docker compose -f vector-database.yml up -d
```

Default ports:

- Milvus: `localhost:19530`
- MinIO: `localhost:9000`
- MinIO Console: `localhost:9001`
- Attu: `http://localhost:8000`

Stop Milvus:

```powershell
docker compose -f vector-database.yml down
```

## MCP Services

AIOps diagnosis depends on two MCP services. Start them in separate PowerShell windows:

```powershell
.\.venv\Scripts\python.exe mcp_servers\cls_server.py
```

```powershell
.\.venv\Scripts\python.exe mcp_servers\monitor_server.py
```

Default MCP URLs:

```env
MCP_CLS_URL=http://localhost:8003/mcp
MCP_MONITOR_URL=http://localhost:8004/mcp
```

## Run the App

Start the backend:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 9900
```

Open:

- Web app: `http://localhost:9900`
- User login: `http://localhost:9900/login`
- Admin login: `http://localhost:9900/admin/login`
- Admin users: `http://localhost:9900/admin/users`
- API docs: `http://localhost:9900/docs`
- Health check: `http://localhost:9900/health`

## Windows Helper Scripts

```powershell
.\start-windows.bat
.\stop-windows.bat
```

`start-windows.bat` attempts to sync dependencies, start Milvus, start MCP services, and run Uvicorn. PostgreSQL still needs to be available before startup.

## Main API Endpoints

### Public Pages

| Method | Path | Description |
| --- | --- | --- |
| GET | `/` | Chat homepage |
| GET | `/login` | User login page |
| GET | `/admin/login` | Admin login page |
| GET | `/admin/users` | Admin user management page |
| GET | `/health` | Health check |

### Authentication

| Method | Path | Description |
| --- | --- | --- |
| POST | `/api/auth/send-code` | Send user login verification code |
| POST | `/api/auth/login` | User verification-code login |
| GET | `/api/auth/me` | Get current user |
| POST | `/api/auth/logout` | User logout |
| POST | `/api/admin/auth/send-code` | Send admin login verification code |
| POST | `/api/admin/auth/login` | Admin login |
| GET | `/api/admin/auth/me` | Get current admin user |
| POST | `/api/admin/auth/logout` | Admin logout |

### Chat and Images

| Method | Path | Description |
| --- | --- | --- |
| GET | `/api/chat/sessions` | List chat sessions |
| POST | `/api/chat/sessions` | Create a chat session |
| GET | `/api/chat/sessions/{session_id}/messages` | List session messages |
| POST | `/api/chat` | Non-streaming RAG chat |
| POST | `/api/chat_stream` | SSE streaming RAG chat |
| POST | `/api/chat_vision` | Image upload and visual QA |
| POST | `/api/images/generate` | Text-to-image generation |
| POST | `/api/chat/clear` | Clear chat session |
| GET | `/api/chat/attachments/{attachment_id}/content` | Download chat attachment |

### Knowledge Base and AIOps

| Method | Path | Description |
| --- | --- | --- |
| POST | `/api/upload` | Upload `.txt` or `.md` files and index vectors |
| POST | `/api/index_directory` | Index uploads or knowledge-base directories |
| POST | `/api/index_knowledge_base` | Index the built-in knowledge base |
| POST | `/api/aiops` | SSE AIOps diagnosis |

## API Examples

Send verification code:

```powershell
curl -X POST "http://localhost:9900/api/auth/send-code" `
  -H "Content-Type: application/json" `
  -d "{\"phone\":\"13800138000\"}"
```

Login:

```powershell
curl -X POST "http://localhost:9900/api/auth/login" `
  -H "Content-Type: application/json" `
  -d "{\"phone\":\"13800138000\",\"code\":\"123456\"}" `
  -c cookies.txt
```

Streaming chat:

```powershell
curl -X POST "http://localhost:9900/api/chat_stream" `
  -H "Content-Type: application/json" `
  -b cookies.txt `
  -d "{\"Id\":\"session-001\",\"Question\":\"Generate a cinematic AI video prompt.\"}" `
  --no-buffer
```

Upload and index a document:

```powershell
curl -X POST "http://localhost:9900/api/upload" `
  -b cookies.txt `
  -F "file=@aiops-docs/disk_high_usage.md"
```

## Troubleshooting

### CORS production validation error

If startup reports unsafe CORS production configuration, use development settings locally:

```env
APP_ENV=development
DEBUG=True
CORS_ALLOWED_ORIGINS=http://localhost:9900,http://127.0.0.1:9900
```

For production:

```env
APP_ENV=production
DEBUG=False
CORS_ALLOWED_ORIGINS=https://your-domain.com
AUTH_COOKIE_SECURE=True
```

### PostgreSQL connection timeout

Check:

```powershell
Test-NetConnection localhost -Port 5432
Test-NetConnection localhost -Port 5433
```

Then confirm `DATABASE_HOST`, `DATABASE_PORT`, `DATABASE_NAME`, `DATABASE_USER`, and `DATABASE_PASSWORD` in `.env`.

### Milvus unavailable

Restart the vector database:

```powershell
docker compose -f vector-database.yml up -d
docker ps
```

Confirm:

```env
MILVUS_HOST=localhost
MILVUS_PORT=19530
```

### DashScope errors

Confirm:

```env
DASHSCOPE_API_KEY=your-dashscope-api-key
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
DASHSCOPE_MODEL=qwen-max
```

For image features, also confirm:

```env
DASHSCOPE_VISION_MODEL=qwen-vl-plus
DASHSCOPE_IMAGE_GENERATION_MODEL=wanx2.1-t2i-turbo
```

## Development Commands

```powershell
# Start API
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 9900

# Database migrations
.\.venv\Scripts\python.exe scripts\manage_migrations.py status
.\.venv\Scripts\python.exe scripts\manage_migrations.py apply
.\.venv\Scripts\python.exe scripts\manage_migrations.py check

# Start Milvus
docker compose -f vector-database.yml up -d

# Stop Milvus
docker compose -f vector-database.yml down
```

## Recommended Startup Order

1. Configure `.env`.
2. Start PostgreSQL and confirm the port is reachable.
3. Run database migrations.
4. Start Docker Desktop.
5. Start Milvus.
6. Start the two MCP services if AIOps is needed.
7. Start Uvicorn.
8. Open `http://localhost:9900` or `http://localhost:9900/docs`.
