# Changelog

本文件记录 Reverie Link 每个版本的主要变更。  
格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)。

---

## [Unreleased] - Phase 3 开发中

> Phase 3 核心架构（记忆系统与视觉感知）已实装。

### 新增（Phase 3）

**三阶混合记忆架构**
- **底层聊天数据库 (SQLite)**：独立按 `session_id` 和 `character_id` 实现数据隔离，开启 WAL 模式保障并发读写性能，新增分页与全文检索 API。
- **核心档案自动提取**：后台监听对话，每 10 轮触发一次。利用 LLM 和标签系统进行「双层去重（粗筛+精判）」，将用户新增信息自动以角色口吻记入日记本（自动区）。
- **长期摘要记忆 (ChromaDB)**：支持向量数据库，当记录被移出滑动窗口时，自动压缩成 1~2 句摘要并向量化存储。用户交互时根据语义相似度进行检索召回（Layer 2 注入）。
- **角色数据管理系统**：提供指定角色卡全量数据（聊天、日记本、向量摘要）的打包导出，以及不可逆的一键彻底删除接口。

**视觉感知与主动发言系统**
- **智能截屏预筛**：放弃传统直方图比较，采用 6x4 分块比较 RGB 均值差异算法，可精准捕获极小范围内的局部 HUD 数值、UI 与准星变化，显著提升游戏画面变化感知度。
- **双轨视觉大模型 (VLM) 调度**：首选主干模型的原生多模态能力（如 gpt-4o 等），若不支持则平滑降级至独立配置的视觉大模型（如 GLM-4V），保证图像分析能力。
- **结构化 JSON 容错解析**：引入括号嵌套深度配对算法，彻底解决 VLM 生成复杂嵌套对象（如 `scene_description`）时导致的 JSON 截断和崩溃问题。
- **主动发言决策引擎**：实装兴趣分累积机制，提供 3 档话痨程度（话少/适中/话多）调整；具备并发冲突保护（用户交互时挂起）和静默时间兜底触发机制。
- **意图穿透触发**：前置拦截正则匹配，当用户发送“看看屏幕”、“你看到了什么”等关键词，强制唤起视觉流捕获与分析。

---

## [Unreleased] - Phase 2 开发中

> Phase 2 开发进行中，尚未发布正式版本号。

### 新增（Phase 2）

**Live2D 渲染系统**
- 接入 pixi.js + pixi-live2d-display，实现 Live2D 模型渲染（透明背景，无闪烁）
- 双缓冲渲染架构（RenderTexture 离屏渲染 + WebGL 双缓冲），彻底解决 DWM 截帧闪烁问题
- 模型管理系统：用户将模型文件夹放入 `public/live2d/` 即可自动识别，无需任何配置
- 设置界面「全局设置」Tab 提供模型列表，点击即时切换，无需重启
- 每个模型独立存储 zoom/Y 偏移显示配置，设置界面可可视化调节
- 多状态手臂部件自动归位（`setPartOpacityById` 处理 PartArmA/PartArmB 等）
- VTS 免费模型兼容支持（`animations/` 文件夹自动识别）

**情绪表情系统**
- 6 种情绪标签：`[happy]` `[sad]` `[angry]` `[shy]` `[surprised]` `[neutral]`
- AI 回复携带情绪标签，前端正则提取后剥离，标签不显示在气泡、不被 TTS 读出
- 双模式兼容：有表情文件（exp3.json）走官方接口；无表情文件自动用标准参数（ParamMouthForm / ParamBrowLY 等）回退，覆盖绝大多数标准模型
- 表情触发 3 秒后自动归位 neutral
- 为 MO 模型内置 6 个 exp3.json 表情文件

**语音合成系统**
- 双引擎架构：ElevenLabs 云端 / 本地 RVC v2，在设置界面一键切换
- ElevenLabs：`eleven_flash_v2_5` 模型，最低延迟，API Key + Voice ID 本地存储
- 本地 RVC v2：用户将 `.pth` + `.index` 放入 `public/rvc/`，自动扫描识别
  - 命名规范强制：同名配对（`Hibiki.pth` + `Hibiki.index`），不匹配时界面显示黄色警告
  - 底层 TTS 使用 Windows SAPI（pyttsx3，完全离线）
  - 推理参数：rmvpe 算法，index_rate=0.75，protect=0.33
- 唇音同步：`AudioContext.createAnalyser()` 实时提取音量，映射至 `ParamMouthOpenY`

**设置界面扩展**
- 新增「全局设置」Tab（第三个 Tab）：
  - Live2D 模型列表与切换
  - 模型显示调节（zoom / Y 偏移滑条，每模型独立配置）
  - 窗口尺寸三档（小 200×270 / 中 280×380 / 大 380×510）
- AI 模型 Tab 新增语音配置区：ElevenLabs / 本地 RVC 引擎选择器 + 各自配置字段
- 角色卡切换即时生效（通过 Tauri 事件通知主窗口，经持久 WS 连接同步到后端）
- 前端启动时自动从 localStorage 恢复并发送配置到后端，无需手动重新保存

**后端新增接口**
- `GET /api/live2d/models`：扫描 `public/live2d/` 返回模型列表
- `GET /api/rvc/voices`：扫描 `public/rvc/` 返回音色列表（含同名 index 配对检测）
- `POST /api/tts`：ElevenLabs TTS 代理接口
- `POST /api/tts/local`：本地 RVC 语音合成接口（pyttsx3 → RVC v2 → WAV）

### 技术依赖（新增）

| 层 | 新增依赖 |
|----|---------|
| Node | `pixi.js@^6.5.10`、`pixi-live2d-display@^0.4.0` |
| Python | `httpx`、`pyttsx3`、`rvc-python`、`torch`（rvc-python 依赖） |
| 系统 | `FFmpeg`（RVC 音频处理依赖，需加入系统 PATH） |
| 外部服务 | `ElevenLabs API`（可选，云端语音） |

### 已知问题 / 待优化

- 本地 RVC 推理在 CPU 模式下较慢（无 NVIDIA GPU 时自动回退）
- ElevenLabs 延迟约 2 秒（受海外网络影响），流式优化规划至 Phase 4
- 锁定状态解锁按钮的出现/消失时机和动画仍有瑕疵
- API Key 目前存储在 localStorage，Phase 3 将迁移至 Tauri Rust 加密存储
- 音量按钮为占位，全双工语音系统（Phase 2 后续）接入后实现真实音量控制
- MO 黑白线条模型在透明窗口下与 pixi-live2d-display 存在兼容性问题（已挂起，VTS 免费模型不受影响）

---

## [Unreleased] - Phase 1 完成存档

> Phase 1 开发完成。

### 新增（Phase 1）

**窗口与系统层**
- 透明无边框置顶窗口，支持鼠标穿透切换
- 动态窗口尺寸缩放（输入框展开/气泡显示时自动扩展，以右下角为锚点）
- 窗口拖拽，位置跨会话记忆（localStorage 存储锚点坐标）
- 系统托盘菜单：锁定/解锁穿透、打开设置、退出
- 锁定状态下鼠标悬停角色区域 1.5 秒后浮现解锁按钮（Rust 轮询线程实现）
- 控制栏：鼠标悬停角色区域时逐个滑入显示（锁定/设置/音量/输入四个按钮）

**对话与 AI**
- Python FastAPI + WebSocket 后端（端口 18000）
- OpenAI 兼容层统一接入，支持任意兼容厂商（base_url + api_key + model）
- 三层 Prompt 架构：角色设定层 + 记忆注入层（预留）+ 对话历史滑动窗口
- 漫画风对话气泡：打字机逐字动效、思考中三点跳动动画、8 秒后自动消失
- 发送超时保护（30 秒无响应自动重置 thinking 状态）
- LLM 错误友好提示（区分 API Key 无效、模型不存在、网络超时、频率限制等）

**设置窗口**
- 独立设置窗口（520×620，水蓝水粉二次元配色）
- LLM 配置 Tab：15 家厂商预设，各厂商 API Key 独立存储，官网直达链接
- 角色设定 Tab：最多 10 个角色预设，卡片式列表，头像上传，激活预设即时同步后端
- Toast 顶部通知（成功/警告两种样式）

**内置内容**
- 默认角色 Rei：傲娇猫娘，Reverie Link 吉祥物，内置完整角色设定与对话示例

### 技术依赖（Phase 1）

| 层 | 依赖 |
|----|------|
| Rust | `tauri 2`、`tauri-plugin-opener 2`、`enigo 0.2`、`serde`、`serde_json` |
| Node | `vue 3.5`、`@tauri-apps/api 2`、`@tauri-apps/plugin-opener 2`、`vite 6`、`vue-tsc` |
| Python | `fastapi`、`uvicorn[standard]`、`openai`、`python-dotenv` |

---

*更早的变更未单独记录，可参考 git 提交历史。*