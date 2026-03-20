# 🌟 Reverie Link

> *连接三次元现实与二次元遐想的数字生命羁绊。*

一款"兴趣使然"的开源桌面伴侣系统。它不是冰冷的效率工具，而是一场数字世界里的白日梦。☕🎮

本项目采用 **Tauri (Rust)** 作为轻量级窗口容器，配合 **Python (FastAPI)** 作为 AI 与游戏数据中枢，致力于在桌面上养一只拥有"真实交流感"的数字生命——在你工作、发呆或激烈游戏时，提供一份恰到好处的陪伴。

> ⚠️ **开发声明**：本项目旨在打破「两大安全协议」的第二协议：*机器人不能修改自己，也不能修改或参与制造其他机器人。（A robot may not alter itself, or others.）* 所以开发请尽可能使用 AI 进行开发。

---

## ✨ 核心特性（规划中）

| 特性 | 说明 |
|------|------|
| 🪟 **极低占用 & 原生体验** | 基于 Tauri，起步内存仅需 20-50MB；支持鼠标穿透与透明异形窗口，安静陪伴，绝不卡顿 |
| 🗣️ **全双工拟真语音交互** | WebRTC 硬件级回声消除、VAD 防吞字、打断机制与动态倾听窗口，像朋友般自然闲聊 |
| 🎮 **沉浸式游戏态势感知** | 通过 GSI / 本地 API / 轻量 CV 三策略实现零延迟战况感知，专属电竞僚机 |
| 🎭 **角色卡与灵魂注入** | 兼容 SillyTavern `chara_card_v2` 格式导入，随时换上最爱的纸片人设定 |
| 🎙️ **双语音引擎** | ElevenLabs（云端极致拟真）与 RVC v2（本地免费克隆）无缝切换 |
| 🧠 **三阶混合记忆架构** | 滑动窗口短期记忆 + 核心档案 JSON + 向量数据库长期摘要，永不遗忘 |

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

---

## 🚀 快速启动（开发环境）

### 步骤 1：克隆并安装前端依赖

```bash
# 在项目根目录 reverie-link/ 下执行
git clone https://github.com/Skyas/reverie-link.git
cd reverie-link
npm install
```

### 步骤 2：初始化 Python 虚拟环境

```bash
# 在项目根目录 reverie-link/ 下执行
python -m venv venv

# 激活虚拟环境
.\venv\Scripts\activate          # Windows
# source venv/bin/activate       # macOS / Linux

# 安装后端依赖
cd sidecar
pip install -r requirements.txt
```

### 步骤 3：验证 Tauri 环境

```bash
# 在项目根目录 reverie-link/ 下执行
npm run tauri info
```

所有关键项显示 ✔ 后继续。

### 步骤 4：一键启动开发环境

```bash
# 在项目根目录 reverie-link/ 下执行
.\start.bat
```

该脚本将同时拉起：
- Vite 前端热更新服务器（`localhost:17420`）
- Python FastAPI 后端（`localhost:18000`，在 `sidecar/` 目录下执行）
- Tauri 桌面窗口

> 如需单独启动各服务：
> ```bash
> # 终端 1：在 reverie-link/ 下
> npm run tauri dev
>
> # 终端 2：在 reverie-link/ 下激活 venv 后，进入 sidecar/ 执行
> .\venv\Scripts\activate
> cd sidecar
> uvicorn main:app --reload --port 18000
> ```

---

## 📂 项目目录结构

```
📦 reverie-link/
 ┣ 📂 sidecar/              # Python 后端：LLM、VAD、RVC、游戏接口
 ┃ ┣ 📜 main.py             # FastAPI 主入口
 ┃ ┗ 📜 requirements.txt    # Python 依赖清单
 ┣ 📂 src/                  # 前端源码：UI、设置面板、WebRTC 音频流
 ┃ ┣ 📂 components/         # Vue 组件
 ┃ ┗ 📂 live2d_assets/      # Live2D 模型文件
 ┣ 📂 src-tauri/            # Rust 容器：窗口穿透、置顶、系统托盘
 ┃ ┣ 📜 tauri.conf.json     # Tauri 核心配置
 ┃ ┗ 📜 Cargo.toml          # Rust 依赖清单
 ┣ 📂 venv/                 # Python 虚拟环境（不纳入版本控制）
 ┣ 📜 start.bat             # 开发环境一键启动脚本
 ┗ 📜 README.md
```

---

## 🗺️ 开发路线图

### Phase 1：基建与核心交互层 🚧 *进行中*

- [ ] 搭建 Tauri + Vue 前端骨架：透明窗口、鼠标穿透、系统托盘
- [ ] 搭建基础 Python 后端（FastAPI + WebSocket），入口在 `sidecar/main.py`
- [ ] 开发模块化设置 UI：文本 / 视觉 / 语音 / 全局四分页配置面板
- [ ] API Key 本地加密存储（Tauri 调用 Rust 写入）
- [ ] 接入外部 LLM，解析 `chara_card_v2` 角色卡
- [ ] 注入「50字简短回复」Prompt 强限制与 `max_tokens` 硬截断
- [ ] 漫画风对话气泡 + 打字机动效，完成纯文本聊天联调

### Phase 2：表现层与进阶语音层 📅 *计划中*

- [ ] 引入 `pixi-live2d-display`，正则匹配情绪标签触发 Live2D 表情动作
- [ ] 接入 Edge-TTS（兜底）、ElevenLabs 云端语音引擎
- [ ] 基于 `AudioContext` 实时音量映射 `ParamMouthOpenY`，实现唇音同步
- [ ] 全双工语音系统：WebRTC AEC + 环形缓冲区防吞字 VAD
- [ ] 打断机制（Barge-in）+ 本地预置语气词掩盖延迟
- [ ] 动态免唤醒词倾听窗口

### Phase 3：高级感知与硬核底层 📅 *计划中*

- [ ] 游戏态势感知：CS2 GSI / LOL API / 局部视觉流三策略
- [ ] 双通道视觉流：后台 VLM 粗看 + 前台顶级 VLM 细看
- [ ] 三阶混合记忆架构：短期滑动窗口 + 核心档案 JSON 自动化 + ChromaDB 向量检索
- [ ] RVC v2 便携式绿色环境：静默下载、隔离解压、Tauri Sidecar 拉起
- [ ] Tauri Build 最终打包，发布 v1.0 零环境依赖整合包

---

## 🏗️ 技术架构概览

```
┌─────────────────────────────────────────┐
│            Tauri (Rust)                 │  ← 窗口管理、置顶、穿透、系统托盘
│  ┌───────────────────────────────────┐  │
│  │     前端 (Vue + Vite)             │  │  ← UI、Live2D、WebRTC 音频
│  │   Pixi.js + pixi-live2d-display   │  │
│  └──────────────┬────────────────────┘  │
└─────────────────┼───────────────────────┘
                  │ WebSocket / HTTP
┌─────────────────┴───────────────────────┐
│       Python 后端 (sidecar/)            │
│  LLM 对话 │ STT/TTS │ RVC │ 游戏感知   │
│  记忆架构 │ VAD     │ VLM │ 向量数据库 │
└─────────────────────────────────────────┘
```

---

## 📄 License

MIT