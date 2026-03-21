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

### 步骤 3：配置环境变量

```bash
# 复制配置模板
copy sidecar\.env.example sidecar\.env

# 用编辑器打开 sidecar/.env，填写你的 LLM 配置
# 也可以在启动后通过设置界面配置
```

### 步骤 4：验证 Tauri 环境

```bash
# 在项目根目录 reverie-link/ 下执行
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

## 📂 项目目录结构

```
📦 reverie-link/
 ┣ 📂 sidecar/              # Python 后端：LLM、VAD、RVC、游戏接口
 ┃ ┣ 📜 main.py             # FastAPI + WebSocket 主入口
 ┃ ┣ 📜 prompt_builder.py   # Prompt 组装模块（三层架构）
 ┃ ┣ 📜 .env.example        # 环境变量模板（复制为 .env 后填写）
 ┃ ┗ 📜 requirements.txt    # Python 依赖清单
 ┣ 📂 src/                  # 前端源码
 ┃ ┣ 📜 App.vue             # 主窗口：桌宠 UI、气泡、控制栏
 ┃ ┣ 📜 SettingsApp.vue     # 设置窗口：LLM 配置 + 角色预设管理
 ┃ ┣ 📜 main.ts             # 主窗口挂载入口
 ┃ ┗ 📜 settings-main.ts    # 设置窗口挂载入口
 ┣ 📂 src-tauri/            # Rust 容器：窗口穿透、置顶、系统托盘
 ┃ ┣ 📜 tauri.conf.json     # Tauri 核心配置
 ┃ ┗ 📜 Cargo.toml          # Rust 依赖清单
 ┣ 📂 public/               # 静态资源
 ┃ ┗ 📜 avatar.png          # 默认角色头像（Rei）
 ┣ 📂 venv/                 # Python 虚拟环境（不纳入版本控制）
 ┣ 📜 index.html            # 主窗口 HTML 入口
 ┣ 📜 settings.html         # 设置窗口 HTML 入口
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
- [x] 内置默认角色 Rei
- [x] LLM 错误友好提示（API Key 无效、模型不存在、网络超时等）
- [x] 发送超时保护（30 秒无响应自动重置）

### Phase 2：表现层与进阶语音层 📅 *计划中*

- [ ] 引入 `pixi-live2d-display`，正则匹配情绪标签触发 Live2D 表情动作
- [ ] Live2D 角色旁悬浮把手按钮（穿透切换，与托盘并行）
- [ ] 接入 Edge-TTS（兜底）、ElevenLabs 云端语音引擎
- [ ] 基于 `AudioContext` 实时音量映射 `ParamMouthOpenY`，实现唇音同步
- [ ] 全双工语音系统：WebRTC AEC + 环形缓冲区防吞字 VAD
- [ ] 打断机制（Barge-in）+ 本地预置语气词掩盖延迟
- [ ] 动态免唤醒词倾听窗口
- [ ] 全局快捷键（Ctrl+Space）触发输入框

### Phase 3：高级感知与硬核底层 📅 *计划中*

- [ ] 游戏态势感知：CS2 GSI / LOL API / 局部视觉流三策略
- [ ] 双通道视觉流：后台 VLM 粗看 + 前台顶级 VLM 细看
- [ ] 三阶混合记忆架构：短期滑动窗口 + 核心档案 JSON 自动化 + ChromaDB 向量检索
- [ ] 酒馆卡片（`chara_card_v2`）导入支持
- [ ] API Key 迁移至 Tauri Rust 加密本地存储
- [ ] RVC v2 便携式绿色环境：静默下载、隔离解压、Tauri Sidecar 拉起
- [ ] 全局设置：记忆跨度滑动条、唤醒词、音量、开机自启、游戏感知开关
- [ ] Tauri Build 最终打包，发布 v1.0 零环境依赖整合包

---

## 🏗️ 技术架构概览

```
┌─────────────────────────────────────────┐
│            Tauri (Rust)                 │  ← 窗口管理、置顶、穿透、系统托盘
│  ┌───────────────────────────────────┐  │
│  │     前端 (Vue 3 + Vite)           │  │  ← UI、Live2D、WebRTC 音频
│  │   Pixi.js + pixi-live2d-display   │  │
│  └──────────────┬────────────────────┘  │
└─────────────────┼───────────────────────┘
                  │ WebSocket
┌─────────────────┴───────────────────────┐
│       Python 后端 (sidecar/)            │
│  LLM 对话 │ STT/TTS │ RVC │ 游戏感知   │
│  记忆架构 │ VAD     │ VLM │ 向量数据库 │
└─────────────────────────────────────────┘
```

---

## 📄 License

MIT