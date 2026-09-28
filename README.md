<div align="center">

# 🛡️ 智能问询笔录平台 · Intelligent Inquiry Record Platform

<img src="https://img.shields.io/badge/FastAPI-0.141.1-009688?logo=fastapi&logoColor=white" alt="FastAPI"/>
<img src="https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white" alt="Python"/>
<img src="https://img.shields.io/badge/SQLAlchemy-2.0-E23838?logo=sqlalchemy&logoColor=white" alt="SQLAlchemy"/>
<img src="https://img.shields.io/badge/Pydantic-2.12-E92063?logo=pydantic&logoColor=white" alt="Pydantic"/>
<img src="https://img.shields.io/badge/JWT-HS256-000000?logo=jsonwebtokens&logoColor=white" alt="JWT"/>
<img src="https://img.shields.io/badge/LLM-qwen3%3A8b-FF6F00?logo=openai&logoColor=white" alt="LLM"/>
<img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License"/>
<img src="https://img.shields.io/badge/PRs-welcome-brightgreen.svg" alt="PRs"/>
<img src="https://img.shields.io/badge/docs-Swagger%20%2F%20ReDoc-85EA2D?logo=swagger&logoColor=black" alt="Docs"/>
<img src="https://img.shields.io/badge/status-production%20ready-success" alt="Status"/>

**面向公安执法与电信网络诈骗侦查场景的智能问询笔录平台**

**An AI-powered inquiry-record platform for public-security law enforcement & anti-telecom-fraud investigation**

[中文文档](#-中文说明) · [English](#-english) · [API 文档 / Docs](http://localhost:8000/docs)

</div>

---

<div align="center">

<img src="https://img.shields.io/badge/模块-MODULES-8" alt="Modules"/>
<img src="https://img.shields.io/badge/案由模板-19%20类-orange" alt="Templates"/>
<img src="https://img.shields.io/badge/五流要素-5%20flows-blueviolet" alt="FiveFlow"/>
<img src="https://img.shields.io/badge/角色-3%20roles-green" alt="Roles"/>

</div>

<a name="-中文说明"></a>
## 🇨🇳 中文说明

### ✨ 项目简介

智能问询笔录平台是一套面向**公安执法办案**与**电信网络诈骗侦查**场景的专业化笔录制作系统。平台以「**四阶段笔录生命周期**」为主线，融合**五流要素分析**（人员流 / 通信流 / 网络流 / 资金流 / 寄递流）、**AI 研判推荐**与**红头文书导出**能力，帮助办案民警在规范、高效、可追溯的前提下完成高质量问询笔录。

系统采用**「大模型优先 + 规则算法降级」的混合 AI 架构**：接入内网私有化大模型（OpenAI 兼容接口，默认 `qwen3:8b`）时由 LLM 提供语义能力；模型不可达或未启用时，自动降级到确定性的字符 bigram 余弦相似度算法，**保证在完全离线环境下也能稳定运行**。

### 🚀 核心特性

| 能力 | 说明 |
| :--- | :--- |
| 🔐 **认证与权限** | JWT 登录、会话超时、连续失败锁定、RBAC 三级角色权限矩阵 |
| 📝 **笔录生命周期** | 接报录入 → 模板选择 → 问询进行 → 完成，支持断点续问与状态机流转 |
| 🔗 **外部系统集成** | 智研判 / 智案管**只读**检索回填（严禁回写，物理隔离） |
| 📚 **模板配置** | 19 类案由模板库，多模板按标准章节自动归并装配大纲 |
| 🤖 **AI 研判推荐** | 模板匹配、侦查研判建议、重点缺口追问、一键采纳 |
| 🌊 **五流要素分析** | 要素定义目录、覆盖度计算、核心要素缺口识别 |
| 📎 **材料与文书** | 辅助材料上传 / 病毒扫描 / 物理隔离，红头 DOCX 笔录预览与导出 |
| 🧾 **操作审计** | 全量敏感操作留痕，日志只增不删不改，支持按机构检索 |

### 🏗️ 技术架构

平台后端采用清晰的**分层架构**：

```
API 层 (api/v1)  →  服务层 (services)  →  模型层 (models)  →  数据库
     ↑                    ↑
  Schemas (Pydantic v2) 校验/序列化
```

- **Web 框架**：FastAPI + Uvicorn (ASGI)
- **ORM**：SQLAlchemy 2.x（演示环境 SQLite，生产可切 PostgreSQL / MySQL）
- **数据校验**：Pydantic v2 + pydantic-settings
- **认证安全**：PyJWT + bcrypt
- **文书生成**：python-docx
- **大模型接入**：httpx 直连 OpenAI 兼容接口，适配 Ollama / vLLM / Xinference，不引入任何厂商 SDK

### 📦 快速开始

**1. 克隆仓库**

```bash
git clone https://github.com/xxxlsls/IntelligentInquiryRecordPlatform.git
cd 智能问询笔录平台
```

**2. 创建虚拟环境并安装依赖**

```bash
python -m venv .venv
# Windows PowerShell
.venv\Scripts\Activate.ps1
# Linux / macOS
source .venv/bin/activate

pip install -r backend/requirements.txt
```

**3. 配置环境变量（可选）**

```bash
cd backend
copy .env.example .env   # Windows
# cp .env.example .env   # Linux / macOS
```

**4. 启动服务**

```bash
cd backend
python run.py
# 或：uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

启动后访问：

- 📖 Swagger 文档：<http://localhost:8000/docs>
- 📘 ReDoc 文档：<http://localhost:8000/redoc>
- ❤️ 健康检查：<http://localhost:8000/health>

> 首次启动会自动初始化数据库表结构与幂等种子数据（五流要素 / 三级机构 / 演示账号 / 19 类模板）。

### 👤 演示账号

| 角色 | 账号 | 密码 |
| :--- | :--- | :--- |
| 办案民警 | `minjing` | `123456` |
| 反诈研判员 | `panduan` | `123456` |
| 系统管理员 | `guanliyuan` | `123456` |

### ⚙️ 大模型私有化接入

平台默认关闭大模型（`LLM_ENABLED=False`），此时全部 AI 能力走确定性规则算法，**零外部依赖即可运行**。如需启用内网大模型：

```ini
LLM_ENABLED=True
LLM_BASE_URL=http://127.0.0.1:11434/v1   # Ollama / vLLM / Xinference
LLM_CHAT_MODEL=qwen3:8b
LLM_EMBEDDING_MODEL=bge-m3
```

四项分能力可独立开关与降级：语义匹配推荐、侦查研判建议、五流要素抽取、历史笔录解析导入。任一能力超时 / 异常 / 校验失败时，自动降级到规则链路。

### 📁 目录结构

```
智能问询笔录平台/
├── backend/                  # 后端服务
│   ├── app/
│   │   ├── api/v1/           # 八大模块 REST 接口
│   │   ├── core/             # 配置 / 数据库 / 安全 / 枚举 / 异常
│   │   ├── models/           # SQLAlchemy ORM 模型
│   │   ├── schemas/          # Pydantic 校验模型
│   │   ├── services/         # 业务逻辑（含 llm/ 基础设施层）
│   │   └── seed/             # 幂等种子数据
│   ├── requirements.txt
│   └── run.py                # 开发启动脚本
├── 设计文档/                  # 需求文档与私有化接入方案
└── 页面原型图/                # UI 原型
```

---

<a name="-english"></a>
## 🇬🇧 English

### ✨ Overview

The **Intelligent Inquiry Record Platform** is a professional record-taking system designed for **public-security law enforcement** and **anti-telecom-fraud investigation**. Built around a **four-stage record lifecycle**, it combines **five-flow element analysis** (Person / Communication / Network / Fund / Delivery), **AI-assisted investigation recommendations**, and **official red-header document export**, enabling officers to produce high-quality inquiry records that are standardized, efficient, and fully auditable.

The system adopts a hybrid **"LLM-first + rule-based fallback"** AI architecture. When connected to an on-premise private LLM (OpenAI-compatible API, `qwen3:8b` by default), the LLM powers semantic capabilities; when the model is unreachable or disabled, it gracefully degrades to a deterministic character-bigram cosine-similarity algorithm — **guaranteeing stable operation in a fully offline environment**.

### 🚀 Key Features

| Capability | Description |
| :--- | :--- |
| 🔐 **Auth & RBAC** | JWT login, session timeout, lockout on repeated failures, 3-role permission matrix |
| 📝 **Record Lifecycle** | Intake → Templates → Inquiry → Completed, with breakpoint resumption & state machine |
| 🔗 **External Integration** | Read-only retrieval from ZhiYanPan / ZhiAnGuan (write-back strictly forbidden) |
| 📚 **Template Config** | 19 case-type templates, auto-merged outlines by standard chapters |
| 🤖 **AI Recommendations** | Template matching, investigation guidance, key-gap follow-ups, one-click adoption |
| 🌊 **Five-Flow Analysis** | Element catalog, coverage computation, core-element gap detection |
| 📎 **Materials & Docs** | Material upload / virus scan / isolation, red-header DOCX preview & export |
| 🧾 **Audit Logging** | Full trail of sensitive operations, append-only & immutable, org-scoped query |

### 🏗️ Architecture

```
API Layer (api/v1)  →  Service Layer (services)  →  Model Layer (models)  →  Database
       ↑                        ↑
   Schemas (Pydantic v2) validation / serialization
```

- **Web Framework**: FastAPI + Uvicorn (ASGI)
- **ORM**: SQLAlchemy 2.x (SQLite for demo; PostgreSQL / MySQL for production)
- **Validation**: Pydantic v2 + pydantic-settings
- **Security**: PyJWT + bcrypt
- **Documents**: python-docx
- **LLM Access**: httpx against OpenAI-compatible APIs (Ollama / vLLM / Xinference), no vendor SDK

### 📦 Quick Start

```bash
# 1. Clone
git clone https://github.com/xxxlsls/IntelligentInquiryRecordPlatform.git
cd 智能问询笔录平台

# 2. Virtual environment & dependencies
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\Activate.ps1
pip install -r backend/requirements.txt

# 3. (Optional) environment config
cd backend && cp .env.example .env

# 4. Run
python run.py                    # or: uvicorn app.main:app --reload --port 8000
```

Then open:

- 📖 Swagger UI: <http://localhost:8000/docs>
- 📘 ReDoc: <http://localhost:8000/redoc>
- ❤️ Health check: <http://localhost:8000/health>

### 👤 Demo Accounts

| Role | Username | Password |
| :--- | :--- | :--- |
| Case Officer | `minjing` | `123456` |
| Anti-Fraud Analyst | `panduan` | `123456` |
| System Admin | `guanliyuan` | `123456` |

### ⚙️ Private LLM Integration

LLM is disabled by default (`LLM_ENABLED=False`); all AI features run on deterministic rules with **zero external dependencies**. To enable an on-premise model:

```ini
LLM_ENABLED=True
LLM_BASE_URL=http://127.0.0.1:11434/v1   # Ollama / vLLM / Xinference
LLM_CHAT_MODEL=qwen3:8b
LLM_EMBEDDING_MODEL=bge-m3
```

Each of the four capabilities (semantic matching, investigation analysis, five-flow extraction, historical-record parsing) can be toggled and degraded independently on timeout / error / validation failure.

---

<div align="center">

**⭐ 如果这个项目对你有帮助，欢迎点个 Star！ / If this project helps you, please give it a Star!**

<img src="https://img.shields.io/badge/Made%20with-FastAPI%20%2B%20%E2%9D%A4%EF%B8%8F-009688" alt="Made with"/>
<img src="https://img.shields.io/badge/Built%20for-Law%20Enforcement-1E3A8A" alt="Built for"/>

</div>
