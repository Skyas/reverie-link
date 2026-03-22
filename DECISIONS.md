# 开发决策记录 (DECISIONS.md)

## Reverie Link 设置界面配色方案

### 主色调
- 水蓝色：#A8D8EA（渐变起点，标题栏左侧）
- 水粉色：#FFB7C5（渐变终点，标题栏右侧）

### 背景色
- 页面底色：#FEF6FA（极浅粉白）
- 卡片/输入框：#FFFFFF（纯白）

### 强调色
- 薄荷绿：#B5EAD7（添加按钮边框）
- 薰衣草紫：#D4B8E0（边框线、分割线）
- 浅蓝：#C5E8F4（输入框聚焦光晕）
- 浅粉：#FFE4EC（Tab激活背景、删除按钮背景）

### 文字色
- 主文字：#4A4A6A（深紫灰）
- 次要文字/占位符：#9B8FB0（中紫灰）
- 绿色提示：#5BAD8F（保存成功提示）
- 必填星号：#FFAABB（粉红）

### 保存按钮
- 渐变：从 #A8D8EA 到 #FFB7C5（左上到右下）

### 整体风格关键词
圆角（10-20px）、毛玻璃感、柔和阴影、无强对比、二次元少女风

---

## [Phase 1] 窗口控制入口

- **已实现**：系统托盘（Tray）菜单，提供锁定/解锁鼠标穿透、退出等基础操作。
- **Phase 4 待实现**：在 Live2D 角色旁边添加悬浮"把手"按钮（不穿透），
  点击后切换整个窗口的穿透状态，与托盘菜单功能并行共存。
  参考风格：类似音乐软件歌词面板的边缘控制条。
  对应说明书：模块1「控制机制：方案B」。

## [Phase 1] 后端消息结构

WebSocket 传输格式：
- 前端 → 后端：`{"type": "chat", "message": "用户输入"}`
- 后端 → 前端：`{"type": "chat_response", "message": "AI回复"}`

## [Phase 1] LLM 接入方式

统一使用 OpenAI 兼容层，用户只需配置：base_url、api_key、model_name。
支持：DeepSeek、Gemini、OpenAI、硅基流动、Ollama 本地部署、任意兼容厂商。

## [Phase 1] System Prompt 三层架构

- Layer 1：角色设定（每次必带，固定）
- Layer 2：记忆注入（Phase 3 实现，暂空）
- Layer 3：对话历史滑动窗口

## [Phase 1] 角色模板字段

必填：name / identity / personality / address / style
选填：examples（1-3组对话示例，进阶用）

酒馆卡片 (chara_card_v2) 导入功能已降低优先级，规划至 Phase 4 实现。
动态角色状态切换不通过多卡实现，由 Phase 3 记忆模块自然体现。

## [待优化] 锁定状态解锁按钮

功能已跑通，解锁按钮出现/消失的时机和动画仍有瑕疵，待后续优化。

---

## [Phase 2] Python 便携包（绿色环境）时机

**决策：Phase 3 再实现。**
理由：Phase 2 将新增大量 Python 依赖（FunASR、Silero-VAD、音频处理库等），现在打包等于白打一次。
等 Phase 3 功能冻结、依赖列表稳定后，一次性打包最干净。开发期间继续使用 `start_dev.bat`。

## [Phase 2] 语音技术选型

- **VAD**：Silero-VAD（本地，Python 后端，语言无关，完全离线，低延迟）
- **STT**：FunASR（本地流式，中文优化，原生支持实时流式输出，低延迟）
- **语音触发方式**：唤醒词（主要）+ 全局快捷键按住说话（兜底），共用同一条语音处理管线，快捷键可用户自定义

## [Phase 2] 设置界面全局设置 Tab

Phase 2 纳入的配置项：唤醒词、全局快捷键"按住说话"、音量大小、开机自启。
Phase 3 占位（界面先留位，逻辑后实现）：游戏感知开关、记忆流跨度滑动条。

## [Phase 2] Live2D 情绪表情系统

### 实现方案
每种情绪创建标准 `.exp3.json` 表情文件，在 `model3.json` 的 `Expressions` 字段注册。
与 pixi-live2d-display 官方 API 完全兼容，用户替换模型时无需改代码。

### 情绪标签列表（6个）

| 标签 | 含义 |
|------|------|
| `[happy]` | 开心/笑 |
| `[sad]` | 难过 |
| `[angry]` | 生气 |
| `[shy]` | 害羞/脸红 |
| `[surprised]` | 惊讶 |
| `[neutral]` | 平静（默认） |

### 无表情模型的参数回退方案（已实现）
加载时检测 `expressionManager.definitions.length > 0`：
- **有表情文件**：走 `model.expression(emotion)` 官方接口
- **无表情文件**：自动用 `setParameterValueById` 操控 Live2D 官方标准参数，覆盖绝大多数模型

### 情绪标签过滤
AI 回复中的情绪标签不在气泡显示、不被 TTS 读出，由前端正则提取后剥离，仅用于驱动 Live2D 表情。

## [Phase 2] LipSync 实现方式

前端使用 `AudioContext.createAnalyser()` 实时提取播放音量，
映射至 Live2D 的 `ParamMouthOpenY` 参数实现唇音同步，不依赖音素对齐。

## [Phase 2] ElevenLabs TTS 集成

- **API Key 和 Voice ID**：用户在设置界面「AI 模型」Tab 配置，存 localStorage，后端不持久化
- **调用方式**：前端读取配置 → 传给后端 `/api/tts` → 后端代理请求 ElevenLabs → 返回 MP3 → 前端播放
- **模型**：`eleven_flash_v2_5`（最低延迟，适合对话场景）
- **voice_settings**：stability=0.45 / similarity_boost=0.80 / style=0.35
- **当前延迟**：约 2 秒，为 ElevenLabs 海外服务器正常范围，流式优化规划至 Phase 4

## [Phase 2] Live2D 模型管理

- 用户将模型文件夹放入 `public/live2d/` 即可自动识别，无需任何配置
- 后端扫描时自动修复缺少 Motions 字段的模型（`_auto_fix_motions`，当前已暂停调用，待 Phase 4 待机动画系统启用时重新开启）
- 每个模型独立存储 zoom/y 显示配置，以模型路径为 key 存于 `rl-model-settings`
- 多状态手臂部件（如 hiyori 的 PartArmA/PartArmB）在模型加载后通过 `setPartOpacityById` 直接归位，不依赖动画

---

## [Phase 3] 已规划内容

详见《AI桌宠项目：产品需求与技术架构说明书》Phase 3 章节，主要包括：
- 游戏感知系统（CS2/LOL API 状态集成、日志解析、视觉流）
- 三阶记忆架构（滑动窗口 + 核心档案 JSON + 向量数据库）
- RVC v2 本地语音引擎集成
- 最终打包优化（一键安装包 + 新手引导）

---

## [Phase 4] 待实现功能清单

以下功能需求和方案已确认，统一规划到 Phase 4 实现。

### 4-1. emotion_map.json 可视化编辑入口
**背景**：用户模型有表情但名称与系统标签不匹配时，目前自动走参数回退方案，无法利用模型自带的高质量表情。
**方案**：在「全局设置」Tab 的模型卡片旁提供「情绪映射」按钮，弹出编辑器让用户为每个标签
指定对应的模型表情名称，写入 `public/live2d/{模型文件夹}/emotion_map.json`。
`emotion_map.json` 格式：
```json
{
  "happy":     "expr_smile",
  "sad":       "表情03",
  "angry":     "expr_angry",
  "shy":       "表情02",
  "surprised": "expr_wow",
  "neutral":   null
}
```
`null` 表示该情绪无对应表情，回退到参数控制方案。

### 4-2. 模型装扮面板（参数滑条控制）
**背景**：MO 等高度自定义模型有 60+ 外观参数（发型/眼形/腮红/装饰物等），目前程序内无法调整。
**方案**：在设置界面新增「装扮」入口，读取模型 `cdi3.json` 参数列表，为每个参数渲染滑条，
实时预览效果，保存至 `public/live2d/{模型文件夹}/appearance.json`，程序启动时自动加载还原。

### 4-3. 待机动画系统
**背景**：模型加载后一直静止，缺乏生命感。目前只实现了 PartOpacity 归位，动画本身未接入。
**已讨论的三种方案**（最终实现方式待 Phase 4 讨论决定）：
- **方案 A（定时随机）**：每隔 30~60 秒随机触发一个非 Idle 的动作动画
- **方案 B（AI 控制）**：AI 回复时携带动作标签如 `[motion:03]`，前端解析后触发
- **方案 C（两者结合）**：平时定时随机，AI 回复时优先执行 AI 指定动作

**注意**：实现前需确保 `_auto_fix_motions` 重新启用，为缺少 Motions 注册的模型自动补全动作文件路径。

### 4-4. ElevenLabs TTS 流式播放优化
**背景**：当前等待完整音频生成后再播放，延迟约 2 秒。
**方案**：改用 ElevenLabs 流式 API，前端通过 `fetch` + `ReadableStream` + Web Audio API
边接收 MP3 chunks 边解码播放，将体感延迟降至 500ms 以内。
可同步调整打字机动画节奏，使文字显示与语音在视觉上同步。

### 4-5. 酒馆角色卡（chara_card_v2）导入
**背景**：说明书规划了兼容 SillyTavern 角色卡格式，Phase 1 已降低优先级推迟。
**方案**：在「角色设定」Tab 提供 JSON 文件上传入口，解析 `description / personality / scenario`
等字段组装为 System Prompt，支持一键导入为新角色预设。

### 4-6. 悬浮"把手"窗口控制按钮
**背景**：Phase 1 已有托盘菜单，说明书模块1 方案B 规划了更直观的边缘把手按钮。
**方案**：在 Live2D 角色旁添加不穿透的悬浮控制条，点击切换穿透状态，参考音乐软件歌词面板风格。