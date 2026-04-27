# AGENTS.md — Reverie Link 项目开发指南

> 本文件面向 AI 编程助手。假设阅读者对本项目一无所知，所有信息均基于实际代码与配置，不做假设性推断。

### 项目要求

任何时候，都是中文回答
1.在该项目的实施过程中，应在保证严谨的前提下，富有足够的创新精神。
2.一般情况下，不允许自行修改或偏离《AI桌宠项目：产品需求与技术架构说明书》中提到的内容。除非由我提出并确认修改。
3.在开发过程中，要严格按照从重要到次要，从紧急到一般，从直观到间接的顺序进行。
4.《AI桌宠项目：产品需求与技术架构说明书》为概要说明书，若其中涉及到详细内容，需要和我讨论后，逐一确认。
5.根据第4条规则确认后的内容，若有你认为与《AI桌宠项目：产品需求与技术架构说明书》中提到的技术路线或架构更好的实现方式，必须提出来讨论。
6.在开发过程中，若你已经无法确认当前代码的情况，或者你需要完整确认某部分代码时，直接告知我，我会提供。
7.开发过程中的任何时候，都不要想当然、凭感觉或凭经验。要实事求是、认真调查、逐一确认后方可继续。
8.遇到需要查看代码的问题，可以优先查看知识库中的代码片段。若你判断代码片段不足以支持理解、开发和修改的情况下，可以直接向我索要最新代码。比如，当前main.py App.vue SettingsApp.vue等文件已经较大，就可以不查看知识库，直接向我索要。
9.编写或修改代码时，要在关键位置留下log输出，以便于测试使用。即使到了正式上线，也要保留log输出，以便于今后查找问题所用。
10.在遇到关于信息、资讯或是新闻时，必须优先联网查询最新消息，不能以现有知识直接判断。包括但不限于以下情况：a.配置某厂商模型时，实现查询一下当前的支持模型和最新模型。b.语音模型列表的新旧。c.api链接还是否有效，是否有更新。
11.需求、设计文档为开发指南，并非圣经。需要遵守，但不能死板。
12.开发时要时刻注意分模块开发，充分利用面向对象语言的特性，做到功能模块之间互不影响。也能避免单文件代码过长的问题。
13.开发时一般情况下，不对特例做覆盖，不做过度设计。算法和功能主要以大众化，一般化为目的。若有个别特例须要覆盖再做讨论。

---

## 1. 项目概述

**Reverie Link（遐想链接）** 是一款开源桌面 AI 桌宠系统，旨在为用户提供拥有"真实交流感"的数字生命陪伴体验。项目采用"兴趣使然"的开发理念，结合现代 AI 技术与 Live2D 渲染，为用户创造一个在工作、游戏或发呆时提供恰到好处陪伴的数字伙伴。

- **当前阶段**：Phase 3 核心架构已实装（版本 0.3.3），处于重构与 Bug 修复阶段
- **开发理念**：尽可能使用 AI 进行开发，打破传统工具冰冷感
- **目标平台**：Windows（当前主要开发平台），Tauri 2 理论上支持跨平台
- **语言**：所有代码注释、文档、UI 文案均为中文

---

## 2. 技术栈与运行时架构

### 2.1 整体架构

```
┌─────────────────────────────────────────┐
│            Tauri (Rust)                 │  ← 窗口管理、置顶、穿透、系统托盘
│  ┌───────────────────────────────────┐  │
│  │     前端 (Vue 3 + Vite + TS)      │  │  ← UI、Live2D、Web Audio、WebSocket 客户端
│  │   Pixi.js + pixi-live2d-display   │  │
│  └──────────────┬────────────────────┘  │
└─────────────────┼───────────────────────┘
                  │ WebSocket / HTTP
┌─────────────────┴───────────────────────┐
│       Python 后端 (sidecar/)            │  ← LLM 对话、TTS、记忆、视觉感知
│  FastAPI + WebSocket  │  SQLite + ChromaDB  │
└─────────────────────────────────────────┘
```

### 2.2 各层技术选型

| 层级 | 技术 | 说明 |
|------|------|------|
| 窗口容器 | Tauri 2 (Rust) | 轻量级跨平台桌面框架，透明无边框置顶窗口 |
| 前端框架 | Vue 3 + Vite 6 + TypeScript 5.6 | 响应式组件化开发，`strict: true` |
| 2D 渲染 | Pixi.js 6.5 + pixi-live2d-display 0.4 | Live2D Cubism 模型渲染 |
| 后端框架 | Python FastAPI + WebSocket | AI 逻辑与数据中枢，版本 0.3.3 |
| 数据库 | SQLite (WAL 模式) + ChromaDB | 聊天记录/日记本 + 向量长期摘要 |
| 语音合成 | MiniMax / ElevenLabs / 阿里云 CosyVoice（在线） | 多引擎 TTS，流式输出 |
| 视觉感知 | 自研 VLM 视觉流系统 | 屏幕捕获 + VLM 解析 + 主动发言决策 |

### 2.3 关键运行时端口

- **前端开发服务器**：`localhost:17420`
- **Python 后端**：`localhost:18000`
- **WebSocket 端点**：`ws://localhost:18000/ws/chat`

---

## 3. 目录结构与代码组织

```
reverie-link/
├── src/                          # 前端源码（Vue 3 + TypeScript）
│   ├── components/               # UI 组件
│   │   └── settings/             # 设置界面 Tab 子组件
│   ├── composables/              # Vue 组合式函数
│   │   ├── useLive2D.ts          # Live2D 渲染管理（~30KB）
│   │   ├── useWebSocket.ts       # WebSocket 连接
│   │   ├── useTTS.ts             # TTS 语音播放
│   │   ├── useWindowManager.ts   # 窗口状态管理
│   │   ├── useSizePreset.ts      # 尺寸档位（small/medium/large）
│   │   └── utils/emotion.ts      # 情绪标签解析
│   ├── App.vue                   # 主窗口（桌宠 UI，~894 行）
│   ├── SettingsApp.vue           # 设置窗口
│   ├── HistoryApp.vue            # 记忆/聊天记录窗口
│   ├── AppearanceApp.vue         # 装扮窗口（Phase 4）
│   ├── main.ts                   # 主窗口挂载入口
│   ├── settings-main.ts          # 设置窗口入口
│   ├── history-main.ts           # 记忆窗口入口
│   └── appearance-main.ts        # 装扮窗口入口
│
├── src-tauri/                    # Rust 容器
│   ├── src/
│   │   ├── lib.rs                # Tauri 命令、托盘菜单、悬停检测（~514 行）
│   │   └── main.rs               # 入口点
│   ├── Cargo.toml                # Rust 依赖
│   └── tauri.conf.json           # Tauri 核心配置（透明/置顶/无边框/多窗口）
│
├── sidecar/                      # Python 后端（版本 0.3.3）
│   ├── main.py                   # FastAPI 主入口 + WebSocket（~503 行）
│   ├── prompt_builder.py         # Prompt 组装（遗留，Phase 3 重构后仍保留）
│   ├── routers/                  # API 路由模块
│   │   ├── live2d.py             # Live2D 模型管理 API
│   │   ├── tts.py                # TTS 全流式路由
│   │   └── memory_api.py         # 记忆系统 API
│   ├── prompt/                   # Prompt 管理子包
│   │   ├── constants.py
│   │   ├── system_prompt.py
│   │   └── messages.py
│   ├── memory/                   # 三阶混合记忆系统
│   │   ├── models.py             # 数据模型
│   │   ├── db_chat.py            # SQLite 聊天记录
│   │   ├── db_notebook.py        # SQLite 日记本
│   │   ├── vector_store.py       # ChromaDB 向量存储
│   │   └── extractor.py          # 记忆提取器（SessionExtractor）
│   ├── vision/                   # 视觉感知系统
│   │   ├── vision_system.py      # 主系统编排器
│   │   ├── screen_capture.py     # 屏幕截图（6x4 分块 RGB 比较）
│   │   ├── vlm_client.py         # VLM 客户端（双轨调度 + JSON 容错）
│   │   ├── game_detector.py      # 游戏检测
│   │   ├── event_buffer.py       # 事件缓冲区
│   │   ├── scene_manager.py      # 场景管理
│   │   ├── speech_engine.py      # 主动发言引擎（兴趣分累积）
│   │   ├── activity_monitor.py   # 活动监控
│   │   └── capture_strategy.py   # 捕获策略
│   ├── tts/                      # 语音合成系统
│   │   ├── manager.py            # TTSManager 路由层
│   │   ├── base.py               # TTSEngineBase 抽象基类
│   │   └── online/               # 在线 TTS 引擎
│   │       ├── minimax.py
│   │       ├── elevenlabs.py
│   │       └── aliyun.py
│   ├── ws/                       # WebSocket 扩展处理
│   │   └── vision_speech.py      # 视觉主动发言
│   ├── utils/                    # 工具函数
│   │   ├── emotion.py            # 情绪标签提取
│   │   └── dedup.py              # 退化重复检测
│   ├── requirements.txt          # Python 依赖清单
│   └── .env.example              # 环境变量模板
│
├── public/                       # 静态资源（构建时复制到 dist）
│   ├── live2d/                   # Live2D 模型目录（用户自行放置）
│   ├── rvc/                      # RVC 音色目录（Phase 4 实现）
│   └── avatar.png                # 默认角色头像
│
├── data/                         # 本地数据存储（程序自动生成，不纳入版本控制）
│   ├── chat_history.db           # SQLite 聊天记录
│   ├── notebook.db               # SQLite 日记本
│   └── vector_db/                # ChromaDB 向量数据库
│
├── venv/                         # Python 虚拟环境（不纳入版本控制）
├── index.html                    # 主窗口 HTML 入口
├── settings.html                 # 设置窗口 HTML 入口
├── history.html                  # 记忆窗口 HTML 入口
├── appearance.html               # 装扮窗口 HTML 入口
├── vite.config.ts                # Vite 多页面构建配置
├── package.json                  # Node 依赖
├── tsconfig.json                 # TypeScript 配置
├── start.bat                     # Windows 开发环境一键启动脚本
├── README.md                     # 项目说明
├── PROJECT_SUMMARY.md            # 项目完整总结文档
├── DECISIONS.md                  # 开发决策记录
├── CHANGELOG.md                  # 版本更新记录
├── TTS_DESIGN.md                 # TTS 模块详细设计说明书
└── VOICE_INPUT_DESIGN.md         # 语音输入系统详细设计说明书
```

### 3.1 多窗口前端架构

Vite 配置为**多页面应用**（MPA）：
- `index.html` → 主窗口（桌宠，160×185，透明无边框）
- `settings.html` → 设置窗口（520×620，不可调整大小）
- `history.html` → 记忆窗口（700×560，可调整大小）
- `appearance.html` → 装扮窗口（520×620，可调整大小）

Rust 侧通过 `open_settings` / `open_history` / `open_appearance` 命令动态创建或复用窗口。开发模式下使用外部 URL (`localhost:17420/*.html`)，生产模式下使用 App URL。

---

## 4. 构建与运行命令

### 4.1 环境要求

- **Node.js** `v18+`
- **Rust**（通过 [rustup](https://rustup.rs/) 安装）
- **Windows**：需安装 [Visual Studio Build Tools 2022](https://aka.ms/vs/17/release/vs_BuildTools.exe)，勾选「使用 C++ 的桌面开发」
- **Python** `3.10+`（必须使用 `venv` 虚拟环境）
- **FFmpeg**（RVC 本地语音功能依赖，需加入系统 PATH；`winget install ffmpeg`）

### 4.2 初始化（首次）

```powershell
# 1. 安装前端依赖
npm install

# 2. 初始化 Python 虚拟环境
python -m venv venv
.\venv\Scripts\activate
cd sidecar
pip install -r requirements.txt

# 3. 配置环境变量
copy sidecar\.env.example sidecar\.env
# 编辑 sidecar/.env 填写 LLM 配置

# 4. 验证 Tauri 环境
npm run tauri info
```

### 4.3 日常开发命令

```powershell
# 终端 1：启动 Python 后端（venv 激活状态下）
.\venv\Scripts\activate
cd sidecar
uvicorn main:app --reload --port 18000

# 终端 2：启动 Tauri 前端开发模式
npm run tauri dev
```

> ⚠️ **必须先启动后端，再启动前端**。

### 4.4 一键启动脚本

Windows 开发者可使用 `start.bat`，它会自动：
1. 检查并安装 `node_modules`
2. 检查并创建 `venv`（优先探测 `py -3.10`）
3. 安装/锁定 pip 及 Python 依赖
4. 启动 Python 后端（端口 18000）
5. 启动 Tauri 开发模式

### 4.5 生产构建

```bash
# 前端静态资源构建（含 TypeScript 类型检查）
npm run build

# Tauri 生产打包（生成安装程序）
npm run tauri build
```

### 4.6 可用 npm Scripts

| 命令 | 作用 |
|------|------|
| `npm run dev` | 启动 Vite 开发服务器（端口 17420） |
| `npm run build` | 生产构建（`vue-tsc --noEmit && vite build`） |
| `npm run preview` | 预览生产构建产物 |
| `npm run tauri` | Tauri CLI 入口 |

---

## 5. 代码风格与开发约定

### 5.1 语言与注释

- **所有注释、文档、提交信息、UI 文案使用中文**。
- 代码中允许中英混用，但注释和文档必须以中文为主。
- 关键逻辑节点必须保留带日期/版本号的变更注释，例如：
  ```python
  # 【2026-04-09 Bug Fix】不论 vision_system 是新建还是复用...
  ```

### 5.2 前端（Vue / TypeScript）

- 使用 `<script setup lang="ts">` 组合式 API。
- 复杂逻辑拆分为 `composables/` 中的组合式函数，禁止在 `.vue` 文件中堆砌过多业务逻辑。
- `App.vue` 作为协调层，职责是组合各个 composable，不应包含具体实现。
- 类型安全：`tsconfig.json` 启用 `strict: true`、`noUnusedLocals: true`、`noUnusedParameters: true`。
- 模块导入顺序：Vue 核心 → Tauri API → 项目 composables → 组件。
- Vite 开发服务器忽略以下目录的变更监听：`src-tauri/`、`venv/`、`sidecar/`、`public/live2d/`。

### 5.3 后端（Python）

- **模块化优先**：新功能优先放入 `routers/`、`utils/` 或新建子包，禁止在 `main.py` 中堆积业务逻辑。
- 日志格式统一：`logging.basicConfig(level=logging.DEBUG, format="%(asctime)s | %(levelname)-5s | %(name)s | %(message)s")`。
- 第三方库日志级别抑制：`openai`、`httpx`、`httpcore`、`websocket` 统一设为 `WARNING`。
- 环境变量通过 `python-dotenv` 加载，`sidecar/.env` 为本地配置文件（已 gitignore）。
- FastAPI 生命周期使用 `@asynccontextmanager` 管理资源初始化与销毁。

### 5.4 Rust

- 使用 `Mutex` 管理全局状态（`AppState`）。
- Tauri 命令函数命名采用蛇形命名法，`async` 命令用于涉及窗口创建的操作。
- Windows 专属 API 调用放在 `#[cfg(target_os = "windows")]` 块内。

### 5.5 配置文件规范

- **LLM 配置**：15 家厂商预设（DeepSeek、OpenAI、千问、豆包、硅基流动、Gemini、OpenRouter、MiniMax、Kimi、智谱、腾讯混元、百川、启航AI、Ollama、自定义）。
- **角色模板字段**：必填 `name` / `identity` / `personality` / `address` / `style`；选填 `examples`。
- **情绪标签系统**（6 种）：`[happy]`、`[sad]`、`[angry]`、`[shy]`、`[surprised]`、`[neutral]`。AI 回复携带标签，前端提取后剥离，不显示在气泡、不被 TTS 读出。

### 5.6 资源放置规范

- **Live2D 模型**：放入 `public/live2d/模型名/`，需包含 `模型名.model3.json` 和 `模型名.moc3`。
- **RVC 音色**：放入 `public/rvc/`，`.pth` 与 `.index` 必须同名配对。
- `data/` 目录为程序自动生成，不纳入版本控制。

---

## 6. 测试策略

**当前项目没有正式的自动化测试套件**。

- 无单元测试、无集成测试、无 CI/CD 流水线。
- 测试依赖**手动验证**和**开发模式下的实时调试**。
- 关键 Bug 修复后，需在 `CHANGELOG.md` 中记录修复详情，并在相关代码处保留带日期的修复注释。

**如果你需要新增测试**：
- 前端：可引入 Vitest（项目当前未配置）。
- Python：可使用 `pytest`，在 `sidecar/` 下创建 `tests/` 目录。
- Rust：标准 `cargo test`。

---

## 7. 安全注意事项

### 7.1 当前已知风险

| 风险 | 现状 | 计划 |
|------|------|------|
| API Key 存储 | 目前存储在浏览器 `localStorage` | Phase 4 迁移至 Tauri Rust 加密本地存储 |
| CORS 策略 | FastAPI 开放 `allow_origins=["*"]` | 生产环境应限制为前端 origin |
| 输入验证 | 基础 JSON 格式校验，无深度 sanitization | 按需加强 |
| 环境变量泄漏 | `.env` 已 gitignore，但 `.env.example` 包含示例值 | 确保用户不将真实 `.env` 提交 |

### 7.2 开发安全守则

- **严禁**将真实 API Key、密码写入代码或提交到仓库。
- `sidecar/.env` 和 `data/` 已加入 `.gitignore`，请勿移除。
- 涉及系统调用（Rust 的 `enigo`、Python 的 `psutil`、屏幕捕获）的代码，需谨慎处理权限与异常。
- Windows 截屏排除 API（`SetWindowDisplayAffinity`）已启用，防止桌宠窗口被录屏软件捕获，修改相关代码时需确认行为。

---

## 8. 通信协议与接口规范

### 8.1 WebSocket 消息格式（`/ws/chat`）

| 方向 | 类型 | 说明 |
|------|------|------|
| 前端 → 后端 | `chat` | 用户发送消息：`{"type": "chat", "message": "..."}` |
| 前端 → 后端 | `configure` | 配置更新（LLM / 角色 / 记忆窗口 / Vision / TTS） |
| 后端 → 前端 | `chat_response` | AI 回复（含情绪标签，如 `……[happy]`） |
| 后端 → 前端 | `vision_proactive_speech` | 视觉主动发言 |
| 后端 → 前端 | `configure_ack` | 配置确认 |
| 后端 → 前端 | `error` | 错误信息 |

### 8.2 Tauri 事件（前端 ↔ Rust）

- `passthrough-changed`：穿透状态切换通知
- `mascot-hover`：鼠标悬停检测（Rust 轮询线程 → 前端）
- `tray-switch-character` / `tray-switch-model`：托盘菜单切换
- `toggle-mute`：静音切换
- `reset-position`：位置重置

### 8.3 Tauri Commands（前端调用 Rust）

- `set_cursor_passthrough`：设置窗口鼠标穿透
- `toggle_lock`：切换锁定状态
- `open_settings` / `open_history` / `open_appearance`：打开子窗口
- `update_menu_data`：同步角色/模型列表到托盘菜单
- `open_devtools`：打开 DevTools（开发模式）

---

## 9. 关键外部依赖与限制

- **Pixi.js 6.5**：当前锁定在 v6，`pixi-live2d-display` 尚未适配 Pixi v7/v8，升级需谨慎。
- **Live2D Cubism Core**：`public/live2dcubismcore.min.js` 为官方闭源运行时，不可修改。
- **ChromaDB**：首次启动会自动下载 embedding 模型，需联网。
- **ElevenLabs / MiniMax / 阿里云**：在线 TTS 引擎依赖外部 API 可用性与网络延迟。

---

## 10. 相关文档索引

| 文件 | 内容 |
|------|------|
| `README.md` | 用户面向的项目介绍、快速启动、模型配置指南 |
| `PROJECT_SUMMARY.md` | 项目完整技术总结（含代码行数、接口详情、架构图） |
| `DECISIONS.md` | 设计决策记录（配色方案、技术选型、Phase 规划） |
| `CHANGELOG.md` | 版本更新记录（Keep a Changelog 格式） |
| `TTS_DESIGN.md` | TTS 模块详细设计说明书（Phase 4 实施参考） |
| `VOICE_INPUT_DESIGN.md` | 语音输入系统详细设计说明书（场景语义驱动版 v2.1） |

---

*本文档基于项目实际代码与配置文件生成，最后更新于 2026-04-27。*
