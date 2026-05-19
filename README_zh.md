# Argos

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111+-green.svg)](https://fastapi.tiangolo.com)

**[English](README.md) | [Chinese](README_zh.md)**

> AI + RAG = 1+1>2

Argos 是一个基于 FastAPI 的每日科技简报应用。它从多种来源（RSS、Hacker News、Reddit、GitHub 或纯 LLM）聚合内容，使用任意 OpenAI 兼容 LLM 策划结构化摘要，并提供文章级 RAG 对话与反馈驱动的个性化推荐。

## 功能特性

- **多源聚合** - RSS 订阅源、Hacker News 热门故事、Reddit 帖子、GitHub 事件/发布，或纯 LLM 生成内容
- **看板系统** - 创建自定义分区（看板），每个看板拥有独立的来源类型、系统提示词和角色设定
- **看板向导** - AI 引导的交互式向导，帮助配置新看板
- **LLM 驱动的每日简报** - 包含分类、要点和标签的结构化摘要
- **文章级 RAG 问答** - 混合检索（Bi-Encoder + BM25）配合 Cross-Encoder 重排序
- **个性化推荐** - 显式的喜欢/不喜欢反馈，实现定制化内容推荐
- **跨源去重** - URL 规范化 + AI 语义去重
- **多渠道推送** - 通过邮件、Webhook、Bark (iOS)、Telegram 推送简报
- **MCP Server** - 通过 Model Context Protocol 向 AI 助手暴露全部能力
- **本地持久化** - SQLite、ChromaDB 和 Redis 缓存，支持离线优先设计

## 演示

<!-- 在此处添加截图或 GIF -->
```
即将推出...
```

## 快速开始

### 环境要求

- Python 3.11+
- [Redis](https://redis.io/)（用于缓存）
- 任意 OpenAI 兼容 LLM API Key（如 [DeepSeek](https://platform.deepseek.com/)、OpenAI 等）

### Docker（推荐）

```bash
# 1. 克隆仓库
git clone https://github.com/KarasFlowers/Argos.git
cd Argos

# 2. 配置环境变量
cp .env.template .env
# 编辑 .env，设置 LLM_API_KEY（或兼容的 DEEPSEEK_API_KEY）

# 3. 启动服务栈
docker compose up -d

# 4. 浏览器访问
# 打开 http://127.0.0.1:8000
```

### 一键启动（本地推荐）

项目自带启动脚本，自动处理 **虚拟环境创建、依赖安装、.env 配置、Redis 启动、模型下载、打开浏览器** 全流程：

```bash
# macOS / Linux
chmod +x scripts/start.sh
./scripts/start.sh

# Windows — 双击或运行：
scripts\Open_Web_Dashboard.bat
```

首次运行时脚本会自动：
1. 创建虚拟环境并安装依赖
2. 引导你输入 LLM API Key（自动生成 `.env`）
3. 检查/启动 Redis
4. 预下载 RAG 嵌入模型（~650 MB，仅首次）
5. 启动后端并在浏览器中打开仪表板

### 手动部署

<details>
<summary>点击展开详细步骤</summary>

```bash
# 1. 克隆仓库
git clone https://github.com/KarasFlowers/Argos.git
cd Argos

# 2. 创建并激活虚拟环境
python -m venv venv

# Windows
venv\Scripts\activate

# Linux / macOS
source venv/bin/activate

# 3. 安装依赖
pip install -r requirements.txt

# 4. 配置环境变量
cp .env.template .env
# 编辑 .env，设置 LLM_API_KEY（或兼容的 DEEPSEEK_API_KEY）

# 5.（可选）预下载 RAG 模型，避免首次请求延迟
python scripts/download_models.py

# 6. 启动 Redis（如未运行）
# Windows：.bat 启动器会自动处理
# Linux / macOS：redis-server --daemonize yes

# 7. 启动应用
uvicorn main:app --reload

# 8. 浏览器打开 http://127.0.0.1:8000
```

</details>

## 配置

复制 `.env.template` 为 `.env` 并配置你的设置。至少需要设置 `LLM_API_KEY`（或旧版 `DEEPSEEK_API_KEY`）。

### 环境变量

| 变量 | 必需 | 默认值 | 描述 |
|------|------|--------|------|
| `LLM_API_KEY` | **是** | - | 任意 OpenAI 兼容 LLM 提供商的 API 密钥 |
| `LLM_MODEL` | 否 | `deepseek-chat` | 所有 LLM 调用使用的模型名 |
| `LLM_BASE_URL` | 否 | `https://api.deepseek.com/v1` | LLM API 的基础 URL |
| `LLM_TIMEOUT` | 否 | `180` | 请求超时（秒） |
| `LLM_MAX_RETRIES` | 否 | `1` | 瞬态失败最大重试次数 |
| `DEEPSEEK_API_KEY` | 否 | - | 旧版别名 — 当 `LLM_API_KEY` 未设置时作为回退 |
| `API_KEY` | 否 | - | API 认证密钥，设置后所有 `/api/v1/*` 请求需携带 `X-API-Key` 请求头。不设置则无需认证 |
| `SQLALCHEMY_DATABASE_URI` | 否 | `sqlite+aiosqlite:///./data/sqlite/argos.db` | 异步 SQLite 数据库路径 |
| `CHROMA_DB_DIR` | 否 | `./data/chroma` | ChromaDB 持久化存储路径 |
| `CORS_ORIGINS` | 否 | `http://localhost:5173,...` | 逗号分隔的前端允许来源 |
| `GITHUB_TOKEN` | 否 | - | GitHub 个人访问令牌（将速率限制提升至 5000 次/小时） |
| `HN_FETCH_TOP_STORIES` | 否 | `30` | 获取的 Hacker News 热门故事数量 |
| `HN_MIN_SCORE` | 否 | `100` | Hacker News 最低分数阈值 |
| `REDDIT_FETCH_COMMENTS` | 否 | `5` | 每个 Reddit 帖子包含的热门评论数 |
| `SMTP_HOST` | 否 | - | 邮件推送的 SMTP 服务器 |
| `SMTP_USER` | 否 | - | SMTP 用户名 |
| `SMTP_PASSWORD` | 否 | - | SMTP 密码 |
| `EMAIL_SUBSCRIBERS` | 否 | `[]` | 订阅者邮箱地址的 JSON 列表 |
| `DAILY_PUSH_TIME` | 否 | `08:00` | 每日邮件发送时间（HH:MM 格式） |
| `NOTIFY_CHANNELS` | 否 | `email` | 通知渠道（逗号分隔）：`email,webhook,bark,telegram` |
| `WEBHOOK_URL` | 否 | - | 通用 Webhook URL（POST JSON） |
| `WEBHOOK_SECRET` | 否 | - | Webhook HMAC-SHA256 签名密钥 |
| `BARK_URL` | 否 | - | Bark iOS 推送 URL（如 `https://api.day.app/KEY`） |
| `TELEGRAM_BOT_TOKEN` | 否 | - | Telegram Bot Token |
| `TELEGRAM_CHAT_ID` | 否 | - | Telegram 接收消息的用户/群组 ID |

## 看板来源类型

每个看板都有一个 `source_type`，决定了内容的获取方式：

| 来源类型 | 描述 | 示例 `source_config` |
|----------|------|----------------------|
| `rss` | 从 RSS 订阅源拉取 | `{"feeds": ["https://hnrss.org/frontpage"]}` |
| `hackernews` | 获取 HN 热门故事和评论 | `{"fetch_top_stories": 30, "min_score": 100}` |
| `reddit` | 获取 Reddit 子版块/用户帖子 | `{"subreddits": [{"subreddit": "LocalLLaMA"}], "fetch_comments": 5}` |
| `github` | 获取 GitHub 用户事件和仓库发布 | `{"users": ["openai"], "repos": [{"owner": "openai", "repo": "whisper"}]}` |
| `multi` | 并行组合多种来源类型 | `{"sources": {"rss": {"feeds": [...]}, "hackernews": {"min_score": 50}}}` |
| `pure_llm` | LLM 生成原创内容（无外部数据） | `{"items_per_day": 5, "style": "fun facts"}` |

## MCP Server（AI 助手集成）

Argos 通过 [MCP (Model Context Protocol)](https://modelcontextprotocol.io/) 协议暴露核心能力，让 Claude、Cursor、Windsurf 等 AI 助手可以直接查询简报、提问文章、管理偏好。

> ⚠️ **SQLite 限制**：使用默认 SQLite 数据库时，**不要**同时运行 MCP Server 和 FastAPI Web 服务器。两个进程共享同一 SQLite 文件，并发写入可能导致 `database is locked` 错误或数据损坏。请先停止 Web 服务器，或切换到 PostgreSQL 以支持并发访问。

### 可用工具

| 工具 | 描述 |
|------|------|
| `get_daily_summary` | 获取指定看板的每日简报 |
| `generate_summary` | 触发简报生成 |
| `ask_article` | 基于 RAG 的文章问答 |
| `search_news` | 关键词搜索历史新闻 |
| `list_boards` | 列出所有看板 |
| `add_feedback` | 点赞/踩文章以个性化推荐 |
| `get_user_interests` | 查看当前兴趣/偏好 |
| `get_system_status` | 系统健康状态 |

### 使用方式

```bash
# stdio 传输（适用于 Cursor/Windsurf 等 IDE 集成）
python mcp_server.py

# 或添加到 MCP 客户端配置（如 claude_desktop_config.json）：
{
  "mcpServers": {
    "argos": {
      "command": "python",
      "args": ["path/to/Argos/mcp_server.py"]
    }
  }
}
```

## 架构设计

服务层采用**外观模式（Facade Pattern）**，保持导入向后兼容的同时，允许大型模块在内部拆分：

### 服务外观

| 外观 | 位置 | 导出内容 |
|------|------|----------|
| `llm_service.py` | `app/services/llm/` | `LLMService`, `llm_service` |
| `rag_service.py` | `app/services/rag/_core.py` | 所有公共 RAG 函数 |
| `db_service.py` | `app/services/repositories/` | `DBService`, `db_service` |

### 内部结构

- **LLM 服务**：`ScoringMixin`、`SummaryMixin`、`WeeklyMixin`、`WizardMixin`
- **RAG 服务**：混合检索管道，使用 Bi-Encoder + BM25 + Cross-Encoder 重排序
- **数据库服务**：`SummaryRepo`、`PersonaRepo`、`BoardRepo`

> **注意**：新代码应从具体子包导入（例如 `from app.services.llm import LLMService`），而非从外观导入。

## 项目结构

```text
.
├── app/
│   ├── api/                    # FastAPI 路由（主路由 + RAG）
│   ├── core/                   # 配置、数据库、HTTP 客户端、调度器
│   ├── models/                 # SQLModel + Pydantic 模型
│   ├── scrapers/               # HN / Reddit / GitHub 爬虫
│   ├── services/
│   │   ├── source_adapters/    # 可插拔的看板来源适配器
│   │   ├── llm/                # LLM 评分、摘要、向导
│   │   ├── rag/                # RAG 管道
│   │   ├── repositories/      # 数据库仓库
│   │   ├── chat_history_service.py
│   │   ├── dedup_service.py
│   │   ├── email_service.py
│   │   ├── learning_service.py
│   │   ├── metrics_service.py
│   │   └── rss_service.py
│   └── web/                    # Jinja 模板 + 静态资源
├── data/
│   ├── chroma/                 # 本地向量存储
│   └── sqlite/                 # 本地 SQLite 数据库
├── docs/                      # 项目文档
├── logs/                      # 运行日志
├── scripts/                   # Windows 启动器 + Redis 引导
├── tests/                     # 测试套件
└── tools/                     # 打包工具（Redis 等）
```

## 关键文件

| 路径 | 描述 |
|------|------|
| `main.py` | 应用入口 |
| `app/` | 主应用包 |
| `app/web/static/` | 前端静态资源 |
| `app/web/templates/` | Jinja2 HTML 模板 |
| `data/sqlite/argos.db` | SQLite 数据库 |
| `data/chroma/` | ChromaDB 向量存储 |
| `scripts/Open_Web_Dashboard.bat` | Windows 一键启动器 |
| `scripts/start.sh` | macOS / Linux 一键启动器 |
| `scripts/download_models.py` | 预下载 RAG 嵌入模型 |

## 技术栈

- **后端**：FastAPI、SQLModel、APScheduler
- **LLM**：任意 OpenAI 兼容 API，通过可配置的 `LLMClient`（DeepSeek、OpenAI 等）
- **RAG**：Sentence Transformers、ChromaDB、BM25
- **数据库**：SQLite（异步）、Redis（缓存）
- **爬虫**：httpx、feedparser、BeautifulSoup、trafilatura

## 贡献指南

欢迎贡献代码！请随时提交 Pull Request。

1. Fork 本仓库
2. 创建你的特性分支 (`git checkout -b feature/amazing-feature`)
3. 提交你的修改 (`git commit -m 'Add some amazing feature'`)
4. 推送到分支 (`git push origin feature/amazing-feature`)
5. 提交一个 Pull Request

## 许可证

本项目采用 MIT 许可证 - 详情请查看 [LICENSE](LICENSE) 文件。


