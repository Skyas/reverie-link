# 🌟 Reverie Link

> *连接三次元现实与二次元遐想的数字生命羁绊。*

一款"兴趣使然"的开源桌面伴侣系统。它不是冰冷的效率工具，而是一场数字世界里的白日梦。☕🎮

本项目采用 **Tauri (Rust)** 作为轻量级窗口容器，配合 **Python (FastAPI)** 作为 AI 与游戏数据中枢，致力于在桌面上养一只拥有"真实交流感"的数字生命——在你工作、发呆或激烈游戏时，提供一份恰到好处的陪伴。

> ⚠️ **开发声明**：本项目旨在打破「两大安全协议」的第二协议：*机器人不能修改自己，也不能修改或参与制造其他机器人。（A robot may not alter itself, or others.）* 所以开发请尽可能使用 AI 进行开发。

---

## ✨ 核心特性

| 特性 | 说明 |
|------|------|
| 🪟 **极低占用 & 原生体验** | 基于 Tauri，起步内存仅需 20-50MB；支持鼠标穿透与透明异形窗口，安静陪伴，绝不卡顿 |
| 🎭 **Live2D 模型渲染** | 拖入模型文件夹即用，支持情绪表情联动与唇音同步，任意 Live2D 模型无缝兼容 |
| 🗣️ **双语音引擎** | ElevenLabs 云端拟真语音 与 本地 RVC v2 自训练音色，一键切换，唇音实时同步 |
| 🌸 **角色卡系统** | 最多 10 个角色预设，即时切换，支持自定义人设、头像与对话示例 |
| 🤖 **多厂商 LLM 接入** | 内置 15 家厂商预设，支持 DeepSeek / OpenAI / Gemini / Ollama 等任意兼容厂商 |
| 🗣️ **全双工拟真语音交互** | WebRTC 硬件级回声消除、VAD 防吞字、打断机制与动态倾听窗口（开发中） |
| 🎮 **沉浸式游戏态势感知** | 通过 GSI / 本地 API / 轻量 CV 三策略实现零延迟战况感知（规划中） |
| 🧠 **三阶混合记忆架构** | 滑动窗口短期记忆 + 核心档案 JSON + 向量数据库长期摘要（规划中） |

---

## 🛠️ 开发环境要求

> 对于普通用户，最终发布版为**零环境依赖**的一键安装包。以下仅面向开发者。

### 前端（Tauri）
- Node.js `v18+`
- Rust（通过 [rustup](https://rustup.rs/) 安装）
- Windows：需安装 [Visual Studio Build Tools 2022](https://aka.ms/vs/17/release/vs_BuildTools.exe)，勾选「使用 C++ 的桌面开发」

### 后端（Python）
- Python `3.10+`
- `venv` 虚拟环境（必须）：确保开发依赖与最终便携包保持一致

### 系统依赖
- FFmpeg（RVC 本地语音功能依赖，需加入系统 PATH）
  ```powershell
  winget install ffmpeg
  ```

---

## 🚀 快速启动（开发环境）

### 步骤 1：克隆并安装前端依赖

```bash
git clone https://github.com/Skyas/reverie-link.git
cd reverie-link
npm install
```

### 步骤 2：初始化 Python 虚拟环境

```bash
python -m venv venv

# 激活虚拟环境
.\venv\Scripts\activate          # Windows
# source venv/bin/activate       # macOS / Linux

cd sidecar
pip install -r requirements.txt
```

### 步骤 3：配置环境变量

```bash
copy sidecar\.env.example sidecar\.env
# 用编辑器打开 sidecar/.env，填写你的 LLM 配置
# 也可以在启动后通过设置界面配置
```

### 步骤 4：验证 Tauri 环境

```bash
npm run tauri info
```

所有关键项显示 ✔ 后继续。

### 步骤 5：一键启动开发环境

```bash
# 终端 1：启动 Python 后端（在 venv 激活状态下）
.\venv\Scripts\activate
cd sidecar
uvicorn main:app --reload --port 18000

# 终端 2：启动 Tauri 前端
npm run tauri dev
```

> **注意**：请先启动后端，再启动前端。后端运行在 `localhost:18000`，前端运行在 `localhost:17420`。

---

## 🎭 模型文件配置

### Live2D 模型

将模型文件夹放入 `public/live2d/`，程序启动后自动识别，在设置界面「全局设置」中选择：

```
public/live2d/
└── 你的模型名/
    ├── 模型名.model3.json
    ├── 模型名.moc3
    ├── 贴图文件夹/
    └── animations/ 或 motion/（可选，有则自动注册）
```

### RVC 音色

将音色文件放入 `public/rvc/`，**`.pth` 与 `.index` 文件名必须一致**（如 `Hibiki.pth` + `Hibiki.index`），程序自动扫描识别，不匹配时界面会给出提示：

```
public/rvc/
├── Hibiki.pth      ← 模型权重
└── Hibiki.index    ← 特征索引（同名配对）
```

> 首次使用 RVC 时，程序会自动下载 `hubert_base.pt` 和 `rmvpe.pt`（合计约数百 MB）。

---

## 📂 项目目录结构

```
📦 reverie-link/
 ┣ 📂 sidecar/              # Python 后端：LLM、TTS、RVC、记忆与视觉引擎
 ┃ ┣ 📂 memory/             # 三阶混合记忆架构（SQLite + ChromaDB + 核心提取）
 ┃ ┣ 📂 vision/             # 视觉感知系统（截屏预筛 + VLM 解析 + 决策引擎）
 ┃ ┣ 📜 main.py             # FastAPI + WebSocket 主入口
 ┃ ┣ 📜 prompt_builder.py   # Prompt 组装模块（Layer 1 & 2 记忆注入）
 ┃ ┣ 📜 .env.example        # 环境变量模板（复制为 .env 后填写）
 ┃ ┗ 📜 requirements.txt    # Python 依赖清单
 ┣ 📂 src/                  # 前端源码
 ┃ ┣ 📜 App.vue             # 主窗口：桌宠 UI、Live2D、气泡、语音
 ┃ ┣ 📜 SettingsApp.vue     # 设置窗口：LLM / 角色 / 全局配置
 ┃ ┣ 📜 HistoryApp.vue      # 记忆窗口：聊天记录、日记本、摘要管理
 ┃ ┣ 📜 main.ts             # 主窗口挂载入口
 ┃ ┣ 📜 settings-main.ts    # 设置窗口挂载入口
 ┃ ┗ 📜 history-main.ts     # 记忆窗口挂载入口
 ┣ 📂 src-tauri/            # Rust 容器：窗口穿透、置顶、系统托盘
 ┃ ┣ 📜 tauri.conf.json     # Tauri 核心配置
 ┃ ┗ 📜 Cargo.toml          # Rust 依赖清单
 ┣ 📂 public/               # 静态资源
 ┃ ┣ 📂 live2d/             # Live2D 模型目录（用户自行放置）
 ┃ ┣ 📂 rvc/                # RVC 音色目录（用户自行放置）
 ┃ ┗ 📜 avatar.png          # 默认角色头像（Rei）
 ┣ 📂 data/                 # 本地数据存储（程序自动生成，不纳入版本控制）
 ┃ ┣ 📂 vector_db/          # ChromaDB 向量长期摘要数据库
 ┃ ┗ 📜 chat_history.db     # SQLite 聊天记录与日记本数据库
 ┣ 📂 venv/                 # Python 虚拟环境（不纳入版本控制）
 ┣ 📜 index.html            # 主窗口 HTML 入口
 ┣ 📜 settings.html         # 设置窗口 HTML 入口
 ┣ 📜 history.html          # 记忆窗口 HTML 入口
 ┣ 📜 vite.config.ts        # Vite 多页面构建配置
 ┣ 📜 DECISIONS.md          # 开发决策记录
 ┣ 📜 CHANGELOG.md          # 版本更新记录
 ┗ 📜 README.md
 ```

---

## 🗺️ 开发路线图

### Phase 1：基建与核心交互层 ✅ *已完成*

- [x] Tauri + Vue 前端骨架：透明无边框窗口、动态尺寸缩放、位置记忆
- [x] 鼠标穿透切换（托盘菜单控制 + 锁定状态悬停解锁按钮）
- [x] 窗口拖拽
- [x] 控制栏（悬停显示、逐个滑入动画）：锁定/解锁、设置、音量占位、输入
- [x] Python FastAPI + WebSocket 后端，OpenAI 兼容层统一接入所有 LLM 厂商
- [x] 漫画风对话气泡 + 打字机动效 + 思考中三点动画
- [x] 设置独立窗口（水蓝水粉二次元配色）
  - LLM 配置：15 家厂商预设、各厂商 API Key 独立存储、官网直达链接
  - 角色预设管理：最多 10 个预设、卡片式展示、头像上传、生效中标识
  - 保存确认弹框（支持填写一句话简介）
- [x] 内置默认角色 Rei（傲娇猫娘）
- [x] LLM 错误友好提示（API Key 无效、模型不存在、网络超时等）
- [x] 发送超时保护（30 秒无响应自动重置）

### Phase 2：表现层与进阶语音层 🚧 *进行中*

- [x] Live2D 模型渲染（pixi-live2d-display，双缓冲无闪烁）
- [x] 模型管理系统（拖入即用，设置界面列表切换）
- [x] 每模型独立 zoom/Y 偏移配置，可视化调节
- [x] 多状态手臂部件自动归位（PartOpacity 处理）
- [x] 6 种情绪表情系统（AI 标签驱动，双模式兼容：exp3.json / 参数回退）
- [x] ElevenLabs 云端语音合成
- [x] 本地 RVC v2 语音合成（pyttsx3 底层 + RVC 变声）
- [x] 唇音同步（AudioContext Analyser 实时驱动 ParamMouthOpenY）
- [x] 角色卡即时切换（Tauri 事件通知，无需重启）
- [x] 全局设置 Tab（模型管理 / 尺寸档位 / 语音配置）
- [ ] 全双工语音系统：Silero-VAD + FunASR 流式 STT
- [ ] 唤醒词 + 全局快捷键按住说话
- [ ] 打断机制 + 动态免唤醒倾听窗口

### Phase 3：高级感知与硬核底层 🚧 *进行中*

- [x] 游戏态势感知：局部视觉流策略（分块像素检测预筛 + VLM 动态解析 + 决策引擎）
- [x] 三阶混合记忆架构：短期滑动窗口 + 核心档案自动提取 + ChromaDB 向量长期检索
- [x] 后端代码模块化重构（main.py → routers / utils / prompt 子包）
- [x] 前端代码组件化重构（App.vue → composables；SettingsApp.vue → Tab 子组件）
- [x] Prompt 架构重构与优化（正向引导、约束尾部放置、dedup 退化检测）
- [x] 重大 Bug 修复：主动发言复读 / 抢话 / 记忆断层
- [x] 系统托盘动态菜单（角色 & 模型列表同步、隐藏/显示桌宠、静音切换）
- [x] 设置界面文件夹快捷入口（live2d / rvc 目录一键打开）
- [ ] API Key 迁移至 Tauri Rust 加密本地存储
- [ ] RVC v2 便携式绿色环境：静默下载、隔离解压
- [ ] Tauri Build 最终打包，发布 v1.0 零环境依赖整合包

### Phase 4：打磨与扩展 📅 *计划中*

- [ ] ElevenLabs 流式播放（体感延迟 < 500ms）
- [ ] emotion_map.json 可视化编辑入口（模型表情名称映射）
- [ ] 待机动画系统（定时随机 / AI 标签控制）
- [ ] 模型装扮面板（参数滑条，cdi3.json 读取）
- [ ] 酒馆角色卡（chara_card_v2）导入

---

## 🏗️ 技术架构概览

```
┌─────────────────────────────────────────┐
│            Tauri (Rust)                 │  ← 窗口管理、置顶、穿透、系统托盘
│  ┌───────────────────────────────────┐  │
│  │     前端 (Vue 3 + Vite)           │  │  ← UI、Live2D、Web Audio
│  │   Pixi.js + pixi-live2d-display   │  │
│  └──────────────┬────────────────────┘  │
└─────────────────┼───────────────────────┘
                  │ WebSocket / HTTP
┌─────────────────┴───────────────────────┐
│       Python 后端 (sidecar/)            │
│  LLM 对话 │ ElevenLabs │ RVC v2 变声   │
│  记忆架构 │ VAD / STT  │ 游戏感知      │
└─────────────────────────────────────────┘
```

---

## 📄 License

MIT