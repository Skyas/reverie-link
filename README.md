🌟 Reverie Link

连接三次元现实与二次元遐想的数字生命羁绊。

一款“兴趣使然”的开源桌面伴侣系统。它不是冰冷的效率工具，而是一场数字世界里的白日梦。☕🎮

本项目采用 Tauri (Rust) 作为轻量级容器，配合 Python 作为 AI 与游戏数据中枢。致力于在你的桌面上养一只拥有“真实交流感”的数字生命，在你工作发呆或激烈游戏时，提供一份恰到好处的陪伴。

✨ 核心特性

🪟 极低占用 & 原生体验：得益于 Tauri，起步内存极低，支持纯净的鼠标穿透与异形透明窗口，安静陪伴，绝不卡顿。

🗣️ 全双工拟真语音交互：支持 WebRTC 硬件级回声消除、VAD 防吞字、打断机制 (Barge-in) 与动态倾听窗口。告别生硬的对讲机，实现像朋友般的自然闲聊。

🎮 沉浸式游戏态势感知：看似安静，实则硬核。通过 GSI (如 CS2)、本地接口 (如 LOL) 及轻量级 CV 实现零延迟战况吐槽，做你的专属电竞僚机。

🎭 多模态与灵魂注入：兼容酒馆 (SillyTavern) 角色卡片导入，支持 API Key 隔离管理，随时换上你最爱的纸片人设定。

🎙️ 双发语音引擎：同时支持 ElevenLabs (云端极致拟真) 与 RVC v2 (本地免费克隆) 无缝切换，赋予虚拟生命真实的声带。

🛠️ 环境需求 (仅限开发环境)

对于普通用户，最终发布的包将是“零环境依赖”的一键安装程序。但如果你希望参与开发，请确保本地安装了以下环境：

**注意：本项目旨在打破“两大安全协议”的第二协议：机器人不能修改自己，也不能修改或参与制造其他机器人。（A robot may not alter itself, or others.）所以开发情尽可能使用AI进行开发。**

1. 前端环境 (Tauri)

Node.js (推荐 v18+)

Rust (需配置好 C++ 构建工具，如 Visual Studio Build Tools)

2. 后端环境 (Python)

Python 3.10 或更高版本

(可选但推荐) Conda 或 Python venv 虚拟环境

🚀 快速启动

步骤 1：克隆项目并初始化

git clone [https://github.com/Skyas/reverie-link.git](https://github.com/Skyas/reverie-link.git)
cd Reverie Link

# 安装前端依赖
npm install

# 初始化 Python 虚拟环境并安装依赖
python -m venv venv
.\venv\Scripts\activate   # Windows
# source venv/bin/activate # macOS/Linux
pip install -r core-python/requirements.txt


步骤 2：一键启动开发环境

我们在根目录提供了便捷的批处理脚本。双击运行或在终端输入：

./start_dev.bat


(该脚本将同时启动前端 Vite 热更新服务器与 Python FastAPI 后端，并打开 Tauri 桌面窗口)

📂 项目目录结构

📦 reverie-link
 ┣ 📂 core-python        # Python 后端：负责 LLM、VAD、RVC及游戏接口监控
 ┃ ┣ 📜 main.py          # FastAPI 主入口
 ┃ ┗ 📜 requirements.txt # Python 依赖清单
 ┣ 📂 src                # 前端源码：负责 UI、设置面板与 WebRTC 音频流
 ┃ ┣ 📂 components       # Vue/React 组件
 ┃ ┗ 📂 live2d_assets    # Live2D 模型文件存放处
 ┣ 📂 src-tauri          # Rust 容器：负责窗口穿透、置顶及系统托盘
 ┃ ┣ 📜 tauri.conf.json  # Tauri 核心配置
 ┃ ┗ 📜 Cargo.toml       # Rust 依赖清单
 ┣ 📜 start_dev.bat      # 开发环境一键启动脚本
 ┗ 📜 README.md          # 项目说明文档


🗺️ 实施进度追踪 (Roadmap)

Phase 1：基建与核心交互层 (进行中 🚧)

[ ] 搭建 Tauri + Web 前端骨架，实现无边框透明窗口与鼠标穿透。

[ ] 搭建基础 Python 后端 (FastAPI + WebSocket)。

[ ] 开发模块化设置 UI：文本/视觉/语音分离的配置面板与 API Key 安全存储。

[ ] 实现基础 LLM 对话逻辑：接入外部大模型，并解析 chara_card_v2 (酒馆格式) 角色卡。

[ ] 注入“50字简短回复” Prompt 强限制。

[ ] 前后端联调，打通纯文本形式的“气泡对话框”与打字机效果。

Phase 2：表现层与进阶语音层 (计划中 📅)

[ ] 引入 pixi-live2d-display 渲染模型，通过正则匹配 LLM 输出的情绪标签触发 Live2D 动作。

[ ] 接入 Edge-TTS (兜底) 与 ElevenLabs 语音引擎。

[ ] 基于 AudioContext 实时获取音量，映射至 ParamMouthOpenY 实现完美动嘴 (Lip-sync)。

[ ] 构建全双工语音系统：WebRTC 回声消除 (AEC) + 环形缓冲区 (防吞字 VAD)。

[ ] 实现“打断机制”与“本地语气词掩盖延迟”策略。

[ ] 实装免唤醒词的“动态倾听窗口”机制。

Phase 3：高级感知与环境隔离层 (计划中 📅)

[ ] 开发双通道视觉流：后台 VLM 粗看 + 前台顶级 VLM 细看。

[ ] 搭建“游戏态势感知系统”：以特定游戏 (如 CS2 GSI 或 LOL API) 为基础，实现 0 延迟读取。

[ ] 构建“短期动作记忆流” (3分钟时间戳日志上下文)。

[ ] 编写 Python 环境“便携式绿色隔离下载”脚本，确保小白用户通过 Tauri Sidecar 一键使用 RVC v2。

[ ] 最终构建与测试 (Tauri Build)，发布 v1.0 零环境依赖整合包。
