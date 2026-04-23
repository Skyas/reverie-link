# Reverie Link 项目完整总结文档

> 生成日期：2026-04-23
> 后端版本：0.3.3（Phase 3 开发后期阶段）

---

## 一、项目概述

### 1.1 项目定位

**Reverie Link**（中文名：遐想链接）是一款开源的桌面 AI 桌宠系统，旨在为用户提供一个拥有"真实交流感"的数字生命陪伴体验。项目采用"兴趣使然"的开发理念，结合现代 AI 技术与 Live2D 渲染，为用户创造一个在工作、游戏或发呆时提供恰到好处陪伴的数字伙伴。

### 1.2 核心目标

- 打破传统桌面工具的冰冷感，创造有温度的数字交互体验
- 实现低资源占用的原生桌面应用体验（20-50MB 起步内存）
- 支持多厂商 LLM 接入，提供灵活的 AI 对话能力
- 整合语音合成、情绪表情、记忆系统，打造"活"的数字生命

### 1.3 技术栈概览

| 层级 | 技术选型 | 说明 |
|------|----------|------|
| 窗口容器 | Tauri 2 (Rust) | 轻量级跨平台桌面框架 |
| 前端框架 | Vue 3 + Vite + TypeScript | 响应式组件化开发 |
| 2D渲染 | Pixi.js + pixi-live2d-display | Live2D 模型渲染 |
| 后端框架 | Python FastAPI + WebSocket | AI 逻辑与数据中枢 |
| 数据库 | SQLite + ChromaDB | 聊天记录与向量记忆 |
| 语音合成 | **当前：MiniMax / ElevenLabs / 阿里云 CosyVoice（在线）** | 多引擎 TTS |
| 视觉感知 | 自研 VLM 视觉流系统 | 游戏态势感知 |

---

## 二、项目架构

### 2.1 整体架构图

```
┌─────────────────────────────────────────────────────────┐
│                    Tauri (Rust)                         │  ← 窗口管理、置顶、穿透、系统托盘
│  ┌─────────────────────────────────────────────────┐   │
│  │              前端 (Vue 3 + Vite)                │   │  ← UI、Live2D、Web Audio
│  │           Pixi.js + pixi-live2d-display          │   │
│  └─────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
                           │ WebSocket / HTTP
┌─────────────────────────────────────────────────────────┐
│                  Python 后端 (sidecar/)                 │  版本 0.3.3
│  ┌──────────────┬──────────────┬──────────────────┐    │
│  │  LLM 对话    │  语音合成    │  记忆系统        │    │
│  ├──────────────┼──────────────┼──────────────────┤    │
│  │  情绪处理    │  视觉感知    │  VLM 客户端      │    │
│  └──────────────┴──────────────┴──────────────────┘    │
└─────────────────────────────────────────────────────────┘
```

### 2.2 目录结构

```
reverie-link/
├── 📂 src/                      # 前端源码（Vue 3 + TypeScript）
│   ├── 📂 components/            # UI 组件
│   │   └── 📂 settings/        # 设置界面组件
│   │       ├── CharacterTab.vue  # 角色管理 Tab
│   │       ├── LLMTab.vue        # LLM 配置 Tab（15家厂商预设）
│   │       ├── GlobalTab.vue     # 全局设置 Tab
│   │       ├── Live2DTab.vue     # Live2D 模型管理
│   │       ├── TTSTab.vue        # TTS 语音设置（当前仅在线引擎）
│   │       ├── AppearancePanel.vue  # 装扮面板
│   │       ├── NotebookModal.vue    # 日记本弹窗
│   │       └── DeleteCharDialog.vue # 删除确认对话框
│   ├── 📂 composables/         # Vue 组合式函数
│   │   ├── useLive2D.ts          # Live2D 渲染管理
│   │   ├── useSizePreset.ts      # 尺寸预设管理（200×270/280×380/380×510）
│   │   ├── useTTS.ts             # TTS 语音播放（流式）
│   │   ├── useWebSocket.ts       # WebSocket 连接
│   │   ├── useWindowManager.ts   # 窗口状态管理
│   │   └── 📂 utils/
│   │       └── emotion.ts        # 情绪标签解析
│   ├── App.vue                  # 主窗口（桌宠 UI）
│   ├── SettingsApp.vue          # 设置窗口
│   ├── HistoryApp.vue            # 记忆窗口
│   └── AppearanceApp.vue        # 装扮窗口（Phase 4）
│
├── 📂 src-tauri/                 # Rust 容器
│   ├── src/
│   │   ├── lib.rs               # Tauri 命令与事件处理（含托盘菜单动态构建）
│   │   └── main.rs              # 入口点
│   ├── Cargo.toml              # Rust 依赖
│   └── tauri.conf.json         # Tauri 配置（透明/置顶/无边框）
│
├── 📂 sidecar/                   # Python 后端（版本 0.3.3）
│   ├── main.py                  # FastAPI 主入口 + WebSocket
│   ├── prompt_builder.py        # Prompt 组装（遗留，Phase 3 重构后仍保留）
│   ├── 📂 routers/              # API 路由
│   │   ├── live2d.py            # Live2D 模型管理 API
│   │   ├── tts.py               # TTS 语音合成 API（全流式重构）
│   │   └── memory_api.py        # 记忆系统 API
│   ├── 📂 prompt/               # Prompt 管理子包
│   │   ├── constants.py         # 常量定义
│   │   ├── system_prompt.py     # 系统提示词构建
│   │   └── messages.py          # 消息处理
│   ├── 📂 memory/               # 三阶记忆系统
│   │   ├── __init__.py          # 记忆系统初始化
│   │   ├── models.py            # 数据模型定义
│   │   ├── db_chat.py           # 聊天数据库（SQLite WAL模式）
│   │   ├── db_notebook.py       # 日记本数据库
│   │   ├── vector_store.py      # ChromaDB 向量存储
│   │   └── extractor.py         # 记忆提取器（SessionExtractor）
│   ├── 📂 vision/               # 视觉感知系统
│   │   ├── vision_system.py     # 主系统编排器
│   │   ├── screen_capture.py    # 屏幕截图（6x4分块RGB比较）
│   │   ├── vlm_client.py        # VLM 客户端（双轨调度+JSON容错）
│   │   ├── game_detector.py     # 游戏检测
│   │   ├── event_buffer.py      # 事件缓冲区
│   │   ├── scene_manager.py     # 场景管理
│   │   ├── speech_engine.py     # 主动发言引擎（兴趣分累积）
│   │   ├── activity_monitor.py  # 活动监控
│   │   ├── capture_strategy.py  # 捕获策略
│   │   └── speech_engine.py     # 发言引擎
│   ├── 📂 tts/                  # 语音合成系统
│   │   ├── manager.py           # TTSManager 路由层
│   │   ├── base.py              # TTSEngineBase 抽象基类
│   │   ├── __init__.py          # 导出
│   │   └── 📂 online/           # 在线 TTS 引擎（当前已实现）
│   │       ├── minimax.py      # MiniMax Speech 2.6
│   │       ├── elevenlabs.py    # ElevenLabs
│   │       └── aliyun.py        # 阿里云 CosyVoice API
│   │   # 📋 offline/ 目录预留（Phase 4 Fish Speech/GPT-SoVITS/CosyVoice3）
│   ├── 📂 ws/                   # WebSocket 处理
│   │   └── vision_speech.py     # 视觉主动发言
│   ├── 📂 utils/                # 工具函数
│   │   ├── emotion.py           # 情绪标签提取
│   │   └── dedup.py             # 退化重复检测
│   ├── requirements.txt         # Python 依赖
│   └── .env.example             # 环境变量模板
│
├── 📂 public/                    # 静态资源
│   ├── 📂 live2d/               # Live2D 模型目录（用户放置）
│   ├── 📂 rvc/                   # RVC 音色目录（📋 Phase 4 实现）
│   └── avatar.png              # 默认头像
│
├── 📂 data/                     # 数据存储（程序生成）
│   ├── chat_history.db         # SQLite 聊天记录
│   ├── notebook.db              # SQLite 日记本
│   └── 📂 vector_db/            # ChromaDB 向量数据库
│
├── 📂 venv/                     # Python 虚拟环境
│
├── index.html                   # 主窗口 HTML
├── settings.html               # 设置窗口 HTML
├── history.html                # 记忆窗口 HTML
├── appearance.html             # 装扮窗口 HTML
├── vite.config.ts             # Vite 多页面配置
├── package.json               # Node 依赖
├── tsconfig.json              # TypeScript 配置
├── README.md                  # 项目说明
├── CHANGELOG.md               # 变更日志
├── DECISIONS.md               # 设计决策记录
└── TTS_DESIGN.md              # TTS 设计文档（Phase 4 实施计划）
```

---

## 三、核心功能模块详解

### 3.1 窗口与系统层（Rust）

**实现状态：✅ 已完成**

| 功能 | 实现方式 | 代码位置 |
|------|----------|----------|
| 透明无边框窗口 | tauri.conf.json | `transparent: true, decorations: false` |
| 鼠标穿透切换 | Rust + set_ignore_cursor_events | lib.rs |
| 窗口置顶 | tauri.conf.json | `alwaysOnTop: true` |
| 窗口拖拽 | 前端 CSS + Tauri 事件 | useWindowManager.ts |
| 位置记忆 | localStorage | useWindowManager.ts |
| 动态尺寸缩放 | 前端计算 | useSizePreset.ts（200×270/280×380/380×510） |
| 系统托盘 | tauri tray-icon | lib.rs `TrayIconBuilder` |
| 托盘动态菜单 | Rust `update_tray_menu()` | lib.rs 动态构建角色/模型切换 |
| 截屏排除 | Windows API | lib.rs `SetWindowDisplayAffinity` |
| 悬停检测 | Rust 轮询线程（100ms间隔） | lib.rs `thread::spawn` |
| 隐藏/显示桌宠 | 托盘菜单项 | lib.rs `toggle_visibility` |
| 静音切换 | 托盘菜单项 | lib.rs `toggle_mute` |

**关键 Rust 特性：**
- `AppState` 结构：管理穿透状态、静音状态、角色/模型列表
- `update_tray_menu()`：动态重建托盘菜单，支持勾选标记当前激活项
- `hover_frames` 计数：100ms 轮询，15帧（约1.5秒）触发悬停事件
- 角色切换时自动清空 WebSocket in-memory 历史

### 3.2 前端 UI 层（Vue 3）

**实现状态：✅ 已完成**

#### 3.2.1 主窗口组件（App.vue）

**核心 composables 组合：**
```typescript
// 尺寸系统
const { sizePreset, sizeConfig, BASE_W, BASE_H, INPUT_W, BUBBLE_H } = useSizePreset();

// Live2D 渲染
const { live2dReady, live2dError, initLive2D, setEmotion, setMouthOpen } = useLive2D();

// TTS 语音
const { speakText, stopTTS, syncConfigToBackend } = useTTS({ setMouthOpen });

// WebSocket 连接
const { isConnected, isThinking, sendMessage,sendConfigure } = useWebSocket({
    onChatResponse: (cleanText, emotion) => { /* 处理回复 */ },
    onVisionSpeech: (cleanText, emotion) => { /* 处理视觉主动发言 */ },
    onError: (message) => { /* 处理错误 */ }
});

// 窗口管理
const { inputOpen, userInput, bubbleText, isLocked, showControls, 
        showUnlock, toggleLock, unlockFromButton, startDrag } = useWindowManager();
```

#### 3.2.2 设置窗口（SettingsApp.vue + Tab 组件）

**配色方案：**
- 水蓝色 #A8D8EA / 水粉色 #FFB7C5 渐变
- 页面底色 #FEF6FA
- 强调色 #B5EAD7（薄荷绿）、#D4B8E0（薰衣草紫）

**LLM 厂商预设（15家）：**
1. DeepSeek
2. OpenAI
3. 千问（阿里云）
4. 豆包（火山引擎）
5. 硅基流动
6. Gemini（Google）
7. OpenRouter
8. MiniMax
9. 月之暗面（Kimi）
10. 智谱AI
11. 腾讯混元
12. 百川AI
13. 启航AI
14. Ollama（本地）
15. 自定义

#### 3.2.3 尺寸档位（useSizePreset.ts）

```typescript
export const SIZE_PRESETS = {
    small:  { baseW: 200, baseH: 270,  inputW: 210, bubbleH: 130 },
    medium: { baseW: 280, baseH: 380,  inputW: 240, bubbleH: 160 },
    large:  { baseW: 380, baseH: 510,  inputW: 300, bubbleH: 200 },
};
```

### 3.3 Live2D 渲染系统

**实现状态：✅ 已完成（Phase 2）**

#### 3.3.1 渲染架构

- pixi-live2d-display（官方渲染器）
- 双缓冲渲染（解决 Windows DWM 截帧闪烁）
- 表情系统：6种情绪标签 → exp3.json 或参数回退
- 唇音同步：AudioContext Analyser 实时音量 → ParamMouthOpenY
- 多状态部件：setPartOpacityById 处理 PartArmA/PartArmB

#### 3.3.2 情绪表情系统（6种）

| 标签 | 含义 |
|------|------|
| `[happy]` | 开心/笑 |
| `[sad]` | 难过 |
| `[angry]` | 生气 |
| `[shy]` | 害羞/脸红 |
| `[surprised]` | 惊讶 |
| `[neutral]` | 平静（默认） |

**情绪触发 3 秒后自动归位 neutral**

### 3.4 语音合成系统（TTS）

**实现状态：🚧 部分完成（Phase 2-3 在线引擎）**

#### 3.4.1 当前已实现的在线引擎

| 引擎 | 状态 | 说明 |
|------|------|------|
| **MiniMax Speech** | ✅ 已完成 | api_key + group_id + proxy 支持 |
| **ElevenLabs** | ✅ 已完成 | api_key + model + proxy 支持 |
| **阿里云 CosyVoice API** | ✅ 已完成 | api_key + proxy 支持 |

#### 3.4.2 TTS 管理器架构（tts/manager.py）

```python
class TTSManager:
    def configure(self, config: dict) -> None:
        # mode: "disabled" | "online" | "offline"
        # provider: "minimax" | "elevenlabs" | "aliyun_cosyvoice"
        # 支持 proxy 字段
        # 支持 model 字段透传
```

**流式合成接口：**
```python
async def synthesize(
    self,
    text: str,
    emotion: str = "neutral",
    voice_id: str = "",
) -> AsyncGenerator[bytes, None]:
    """流式合成语音，无语音模式下返回空迭代"""
```

#### 3.4.3 TTS 路由层（routers/tts.py）

**接口列表：**
- `POST /tts/config` - 更新 TTS 配置
- `GET /tts/status` - 查询引擎状态
- `GET /tts/voices` - 获取音色列表
- `POST /tts/synthesize` - 流式合成语音
- `POST /tts/test` - 测试连通性

**特点：**
- 全流式架构（Transfer-Encoding: chunked）
- 无语音模式下返回 204
- 详细的错误日志输出

#### 3.4.4 未实现功能（Phase 4 计划）

| 功能 | 说明 |
|------|------|
| RVC v2 本地变声 | 待实现 |
| Fish Speech S1-mini | 待实现 |
| GPT-SoVITS v4 | 待实现 |
| CosyVoice3 离线 | 待实现 |
| Worker 子进程架构 | TTS_DESIGN.md 有详细设计 |

### 3.5 后端 WebSocket 服务（Python）

**实现状态：✅ 已完成（版本 0.3.3）**

#### 3.5.1 主入口（main.py）

**FastAPI 版本：** 0.3.3

**核心功能：**
- WebSocket 端点：`/ws/chat`
- LLM 对话处理（OpenAI 兼容层）
- 视觉感知系统调度
- 记忆系统集成
- 退化输出检测
- 配置热更新（无需重启）

#### 3.5.2 消息类型

| 方向 | 类型 | 说明 |
|------|------|------|
| 前端→后端 | `chat` | 用户发送消息 |
| 前端→后端 | `configure` | 配置更新（LLM/角色/记忆窗口/Vision/TTS） |
| 后端→前端 | `chat_response` | AI 回复 |
| 后端→前端 | `vision_proactive_speech` | 视觉主动发言 |
| 后端→前端 | `configure_ack` | 配置确认 |
| 后端→前端 | `error` | 错误信息 |

#### 3.5.3 WebSocket 消息处理流程

```python
async def websocket_chat(websocket: WebSocket):
    # 1. 初始化 VisionSystem
    # 2. 创建 SessionExtractor 和 SummaryQueue
    # 3. 循环处理消息
    #    - configure: 更新 LLM/角色/记忆/Vision/TTS 配置
    #    - chat: 对话处理（含退化检测、标签清理）
    #    - timeout: 处理视觉主动发言
```

**退化检测（dedup.py）：**
- 检测到退化重复输出时，降级为 "……[neutral]"
- 不写入 history，避免污染下一轮
- 仍写入数据库供用户查看

### 3.6 三阶混合记忆系统

**实现状态：✅ 已完成（Phase 3）**

#### 3.6.1 架构设计

```
Layer 1: 短期滑动窗口 → SQLite（prompt_builder.py）
Layer 2: 核心档案 → SQLite 日记本（db_notebook.py + extractor.py）
Layer 3: 长期摘要 → ChromaDB 向量数据库（vector_store.py）
```

#### 3.6.2 记忆模块文件（memory/__init__.py 导出）

```python
from .models import (
    MessageType, NotebookSource, TimelineMessage, NotebookEntry,
    WindowPreset, WINDOW_PRESETS, DEFAULT_WINDOW_INDEX,
    generate_msg_id, generate_session_id, generate_entry_id,
    generate_summary_id, now_iso,
)

from .db_chat import (
    init_chat_db, save_message, save_messages_batch,
    get_messages_page, get_sessions, get_recent_messages,
    search_messages, delete_messages_by_character, export_messages_by_character,
)

from .db_notebook import (
    init_notebook_db, add_entry, add_entries_batch, update_entry,
    delete_entry, get_entries_page, get_all_entries, get_all_entries_for_prompt,
    count_entries, delete_entries_by_character, export_entries_by_character,
)

from .extractor import (
    SessionExtractor, extract_and_save, EXTRACT_EVERY_N_ROUNDS,
)

from .vector_store import (
    SummaryQueue, summarize_and_store, retrieve_relevant_summaries,
    delete_summaries_by_character, export_summaries_by_character,
)
```

#### 3.6.3 数据库设计

**chat_history.db：**
- `messages` 表：session_id, character_id, role, content, timestamp
- WAL 模式支持并发读写

**notebook.db：**
- `notes` 表：character_id, content, source_type, created_at
- 支持自动区和手动区

**ChromaDB collections：**
- `reverie_summaries`：长期摘要向量

### 3.7 视觉感知系统

**实现状态：✅ 已完成（Phase 3）**

#### 3.7.1 系统架构

```python
class VisionSystem:
    def __init__(self, speech_queue: asyncio.Queue):
        self.vlm_client       = VLMClient()      # 双轨VLM调度
        self.game_detector    = GameDetector()   # 游戏检测
        self.event_buffer     = EventBuffer()     # 事件缓冲
        self.scene_manager    = SceneManager()    # 场景管理
        self.speech_engine    = SpeechEngine()   # 主动发言
        self.activity_monitor = ActivityMonitor() # 活动监控
        self.capture_strategy = CaptureStrategy() # 捕获策略
```

#### 3.7.2 核心模块

| 模块 | 文件 | 职责 |
|------|------|------|
| 屏幕捕获 | screen_capture.py | 6x4分块RGB比较、空白检测、截图压缩 |
| VLM客户端 | vlm_client.py | 双轨调度、JSON容错解析、主模型同步 |
| 游戏检测 | game_detector.py | 前台进程检测、手动游戏模式 |
| 事件缓冲 | event_buffer.py | 视觉事件累积与评分 |
| 场景管理 | scene_manager.py | 场景状态追踪 |
| 发言引擎 | speech_engine.py | 兴趣分累积、话痨程度、静默兜底 |
| 活动监控 | activity_monitor.py | 用户活动检测 |
| 捕获策略 | capture_strategy.py | VLM预算控制 |

#### 3.7.3 智能截屏预筛

**6x4 分块 RGB 比较算法（screen_capture.py）：**
```python
def compute_pixel_diff(prev: bytes, curr: bytes) -> float:
    """计算两帧之间的像素差异，可捕获局部HUD/准星变化"""
```

#### 3.7.4 主动发言决策引擎

**兴趣分累积机制：**
```python
def on_user_message(self):
    """用户消息时增加驱动力"""
    self.interest_score += 5

def on_vision_event(self):
    """视觉事件时增加驱动力"""
    self.interest_score += 10

def should_speak(self) -> bool:
    """根据话痨程度判断是否主动发言"""
    threshold = self.get_threshold()  # 话少30/适中20/话多10
    return self.interest_score >= threshold
```

#### 3.7.5 意图穿透触发

**关键字正则（main.py）：**
```python
_SCREENSHOT_KEYWORDS = re.compile(
    r"(看看屏幕|屏幕上|画面|你看到了什么|帮我看看|看一眼|看一下|"
    r"屏幕怎么了|你看到什么|现在在干什么|帮我看|屏幕里)",
    re.IGNORECASE,
)
```

---

## 四、开发路线图

### Phase 1：基建与核心交互层 ✅ 已完成

- [x] Tauri + Vue 前端骨架
- [x] 鼠标穿透切换
- [x] 窗口拖拽与位置记忆
- [x] 控制栏动画
- [x] Python FastAPI + WebSocket 后端
- [x] 漫画风对话气泡
- [x] 设置独立窗口（15家 LLM 厂商预设）
- [x] 内置默认角色 Rei
- [x] LLM 错误友好提示
- [x] 发送超时保护（30秒）

### Phase 2：表现层与进阶语音层 ✅ 已完成

- [x] Live2D 模型渲染（双缓冲无闪烁）
- [x] 模型管理系统
- [x] 6 种情绪表情系统
- [x] ElevenLabs 云端语音
- [x] 唇音同步
- [x] 角色卡即时切换
- [x] 全局设置 Tab
- [ ] **RVC v2 本地语音** → 推迟至 Phase 4

### Phase 3：高级感知与硬核底层 ✅ 已完成（核心架构）

- [x] 游戏态势感知（视觉流策略）
- [x] 三阶混合记忆架构
- [x] 后端代码模块化重构
- [x] 前端代码组件化重构
- [x] Prompt 架构优化
- [x] Bug 修复（复读、抢话、记忆断层）
- [x] 系统托盘动态菜单
- [x] 文件夹快捷入口
- [x] 退化检测与降级机制
- [ ] **API Key 迁移至 Rust 加密存储** → Phase 4
- [ ] **RVC v2 便携式绿色环境** → Phase 4
- [ ] **Tauri Build 最终打包** → Phase 4

### Phase 4：打磨与扩展 📅 计划中

- [ ] ElevenLabs 流式播放（<500ms 延迟）
- [ ] emotion_map.json 可视化编辑
- [ ] 待机动画系统
- [ ] 模型装扮面板（cdi3.json 参数滑条）
- [ ] 酒馆角色卡（chara_card_v2）导入
- [ ] **MiniMax Speech / 阿里云 CosyVoice 在线引擎完善**
- [ ] **RVC v2 本地语音合成**
- [ ] **Fish Speech S1-mini / GPT-SoVITS v4 / CosyVoice3 离线引擎**
- [ ] 摘要模型可配置
- [ ] 悬浮"把手"窗口控制按钮

---

## 五、技术依赖清单

### 5.1 Node.js 依赖（package.json）

```json
{
  "@tauri-apps/api": "^2",
  "@tauri-apps/plugin-opener": "^2.5.3",
  "pixi-live2d-display": "^0.4.0",
  "pixi.js": "^6.5.10",
  "vue": "^3.5.13"
}
```

### 5.2 Rust 依赖（Cargo.toml）

```toml
[dependencies]
tauri = { version = "2", features = ["tray-icon", "devtools"] }
tauri-plugin-opener = "2"
serde = { version = "1", features = ["derive"] }
serde_json = "1"
enigo = "0.2"

[target.'cfg(windows)'.dependencies]
windows-sys = { version = "0.59", features = ["Win32_UI_WindowsAndMessaging"] }
```

### 5.3 Python 依赖（sidecar/requirements.txt）

主要依赖：
- `fastapi` + `uvicorn[standard]`
- `openai`（OpenAI 兼容层）
- `python-dotenv`
- `httpx`（HTTP 客户端，含代理支持）
- `chromadb`（向量数据库）
- `numpy`, `opencv-python`（图像处理）

---

## 六、关键代码文件索引

### 6.1 Rust 源码（src-tauri/src/）

| 文件 | 行数 | 说明 |
|------|------|------|
| lib.rs | 514 | Tauri 命令、托盘菜单、悬停检测、截屏排除 |

### 6.2 Python 后端（sidecar/）

| 文件 | 行数 | 说明 |
|------|------|------|
| main.py | 503 | FastAPI 主入口、WebSocket、对话处理 |
| routers/live2d.py | ~14KB | Live2D 模型管理 API |
| routers/tts.py | 169 | TTS 全流式路由 |
| routers/memory_api.py | ~8KB | 记忆系统 API |
| tts/manager.py | 225 | TTSManager 路由层 |
| tts/online/*.py | - | MiniMax/ElevenLabs/阿里云适配器 |
| memory/__init__.py | 97 | 记忆系统导出 |
| memory/models.py | ~9KB | 数据模型 |
| memory/db_chat.py | ~12KB | 聊天数据库 |
| memory/db_notebook.py | ~12KB | 日记本数据库 |
| memory/vector_store.py | ~14KB | ChromaDB 向量存储 |
| memory/extractor.py | ~18KB | 记忆提取器 |
| vision/vision_system.py | ~573 | 视觉感知主系统 |
| vision/vlm_client.py | ~20KB | VLM 客户端 |
| vision/screen_capture.py | ~5KB | 屏幕截图 |
| vision/speech_engine.py | ~5KB | 主动发言引擎 |
| vision/activity_monitor.py | ~12KB | 活动监控 |
| utils/dedup.py | ~3KB | 退化检测 |

### 6.3 前端源码（src/）

| 文件 | 行数 | 说明 |
|------|------|------|
| App.vue | 894 | 主窗口协调组件 |
| SettingsApp.vue | ~18KB | 设置窗口 |
| HistoryApp.vue | ~24KB | 记忆窗口 |
| composables/useLive2D.ts | ~30KB | Live2D 渲染管理 |
| composables/useWebSocket.ts | 166 | WebSocket 连接 |
| composables/useTTS.ts | ~8KB | TTS 语音播放 |
| composables/useWindowManager.ts | ~8KB | 窗口管理 |
| composables/useSizePreset.ts | 33 | 尺寸档位（small/medium/large） |
| components/settings/LLMTab.vue | ~228 | 15家厂商预设 |
| components/settings/TTSTab.vue | ~46KB | TTS 设置（当前仅在线引擎） |

---

## 七、已知问题与待优化

| 问题 | 状态 | 说明 |
|------|------|------|
| 锁定状态解锁按钮动画 | 待优化 | 出现/消失时机有瑕疵 |
| ElevenLabs 延迟 | 约2秒 | 海外网络影响，Phase 4 流式优化 |
| RVC v2 本地语音 | 待实现 | Phase 4 计划 |
| 离线 TTS 引擎 | 待实现 | Phase 4 Fish Speech/GPT-SoVITS/CosyVoice3 |
| API Key 存储 | localStorage | Phase 4 迁移至 Rust 加密存储 |
| 音量按钮 | 占位 | 待实现真实音量控制 |
| MO 模型兼容性 | 已挂起 | VTS 免费模型不受影响 |

---

## 八、快速启动指南

### 8.1 开发环境安装

```bash
# 1. 克隆并安装前端依赖
git clone https://github.com/Skyas/reverie-link.git
cd reverie-link
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

# 5. 启动后端（终端1，venv激活状态）
cd sidecar
uvicorn main:app --reload --port 18000

# 6. 启动前端（终端2）
npm run tauri dev
```

### 8.2 模型文件配置

**Live2D 模型：**
```
public/live2d/
└── 你的模型名/
    ├── 模型名.model3.json
    ├── 模型名.moc3
    ├── 贴图文件夹/
    └── animations/ 或 motion/
```

### 8.3 端口配置

- 后端：localhost:18000
- 前端：localhost:17420

---

## 九、总结

Reverie Link 是一个功能完整的桌面 AI 桌宠项目，**Phase 3 核心架构已实装**（版本 0.3.3），当前处于重构与 Bug 修复阶段。

### 已完成的核心功能：

1. **轻量级跨平台桌面应用**：基于 Tauri 2（Rust），透明无边框置顶窗口
2. **Live2D 模型渲染**：双缓冲无闪烁、6种情绪表情、唇音同步
3. **多引擎语音合成**：MiniMax / ElevenLabs / 阿里云 CosyVoice 在线引擎
4. **多厂商 LLM 接入**：15家厂商预设，通过 OpenAI 兼容层支持任意兼容厂商
5. **三阶混合记忆系统**：短期滑动窗口 + 核心档案 + 向量长期摘要
6. **视觉感知主动发言**：智能截屏预筛、VLM 双轨分析、兴趣分决策引擎
7. **丰富的 UI 交互**：设置窗口、记忆窗口、动态托盘菜单

### Phase 4 计划功能：

- ElevenLabs 流式播放优化
- RVC v2 本地语音合成
- Fish Speech / GPT-SoVITS / CosyVoice3 离线引擎
- API Key 加密存储
- 待机动画系统
- 模型装扮面板
- emotion_map.json 可视化编辑

---

*文档版本：v2.0 | 2026-04-23 | 以代码为准*
