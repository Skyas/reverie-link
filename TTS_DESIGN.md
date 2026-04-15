# 语音合成模块（TTS）— 详细设计说明书

> 本文档记录语音合成模块的所有已确认设计决策。  
> 作为开发实施的唯一权威参考，任何变更需经用户确认后更新本文档。  
> 前置依赖：Phase 3 视觉感知系统已实施完成。  
> 创建日期：2026-04-14

---

## 目录

1. [整体定位与架构概览](#1-整体定位与架构概览)
2. [引擎分类与选型决策](#2-引擎分类与选型决策)
3. [在线 API 引擎](#3-在线-api-引擎)
4. [离线引擎规格](#4-离线引擎规格)
5. [Worker 进程架构](#5-worker-进程架构)
6. [音色管理](#6-音色管理)
7. [情感驱动接口](#7-情感驱动接口)
8. [兜底策略](#8-兜底策略)
9. [安装与卸载管理](#9-安装与卸载管理)
10. [前端设置界面设计](#10-前端设置界面设计)
11. [数据文件与模块布局](#11-数据文件与模块布局)
12. [实施步骤](#12-实施步骤)

---

## 1. 整体定位与架构概览

### 核心定位

TTS 模块负责将 LLM 生成的文本（含情绪标签）转化为语音输出，驱动 Live2D 口型同步。模块对上层完全透明：对话生成流程只调用统一 TTS 接口，不感知底层使用的是哪个引擎。

### 设计原则

- **按需启用**：用户未配置任何 TTS 引擎时，语音功能自动禁用，不存在任何兜底输出；文字气泡正常运作不受影响。
- **单引擎原则**：同一时刻只能激活一个引擎（在线 API 或某个离线引擎）。
- **统一接口**：所有引擎（在线/离线）实现相同的抽象接口，上层零感知切换。
- **用户自带模型**：支持用户导入已训练好的角色音色模型，应用不提供训练或克隆功能。

### 架构总览

```
对话生成流程（LLM 输出）
        │
        ▼
  [TTS 路由层 · sidecar]
  TTSManager.synthesize(text, emotion, voice_id)
        │
        ├─── 在线引擎（直接调用 HTTP API）
        │       ├── MiniMax Speech
        │       ├── 阿里云 CosyVoice API
        │       └── ElevenLabs
        │
        └─── 离线引擎（本地 HTTP → TTS Worker 子进程）
                ├── Fish Speech S1-mini
                ├── GPT-SoVITS v4
                └── CosyVoice3
                        │
                 [独立 TTS venv]
                 [常驻内存，应用启动时加载]
```

---

## 2. 引擎分类与选型决策

### 为什么选这几个

| 引擎 | 类型 | 选入理由 |
|------|------|---------|
| **MiniMax Speech 2.6** | 在线 API | 国内可用、全球 TTS 评测第一、延迟 <250ms、情感自适应 |
| **阿里云 CosyVoice API** | 在线 API | 国内可用、中文质量高、首包延迟 ~400ms |
| **ElevenLabs** | 在线 API | 面向国际用户、情感表现顶尖 |
| **Fish Speech S1-mini** | 离线 | 音质主观评测最优、体积轻量（~1.5GB）、动漫/游戏声音社区活跃 |
| **GPT-SoVITS v4** | 离线 | 动漫/游戏圈最大的预训练模型生态，存量用户自带 .pth 模型 |
| **CosyVoice3** | 离线 | 中文自然度高、阿里开源、情感指令控制 |

### 排除项及原因

| 引擎 | 排除原因 |
|------|---------|
| Fish Speech S2 Pro | 发布时间极新（2026/03），生态尚未成熟；GGUF 推理引擎 s2.cpp 社区早期、不稳定；**迁移路径已预留**，待生态成熟后升级替换 S1-mini |
| Qwen3-TTS | 推理依赖 vLLM-Omni，集成门槛过高，待生态简化后重新评估 |
| pyttsx3 / MeloTTS | 实测情感效果差，已淘汰 |

---

## 3. 在线 API 引擎

### 3.1 统一配置字段

每个在线供应商在 Settings 中需要配置：

| 字段 | 说明 |
|------|------|
| `provider` | 供应商标识（minimax / aliyun_cosyvoice / elevenlabs） |
| `api_key` | 用户填写的 API Key |
| `voice_id` | 选用的音色 ID（从供应商音色列表选择或手动填写） |
| `base_url` | 可选，自定义 API 地址（供高级用户使用） |

### 3.2 各供应商规格

**MiniMax Speech 2.6（推荐，国内首选）**
- 接口风格：REST，与 OpenAI TTS 兼容层接近
- 首包延迟：<250ms
- 情感控制：文本语义自适应，支持自定义情绪参数
- 计费：按字符数，中文场景价格有竞争力
- 国内直连：✅

**阿里云 CosyVoice API**
- 接口风格：阿里云 DashScope SDK
- 首包延迟：~400ms
- 情感控制：自然语言指令（"用开心的语气"）
- 计费：¥2 / 万字符
- 国内直连：✅

**ElevenLabs**
- 接口风格：REST，官方 Python SDK
- 首包延迟：~200ms
- 情感控制：情感表现顶尖，英文场景最优
- 计费：免费额度 10,000 字符/月，付费计划起步 $5/月
- 国内直连：❌（需代理）

### 3.3 在线引擎接口实现

```python
class OnlineTTSEngine(TTSEngineBase):
    async def synthesize(self, text: str, voice_id: str, emotion: str) -> bytes
    async def list_voices(self) -> list[VoiceInfo]
    async def test_connection(self) -> bool
```

在线引擎直接在主 sidecar 进程内运行，无需子进程。

---

## 4. 离线引擎规格

### 4.1 Fish Speech S1-mini

| 项目 | 数值 |
|------|------|
| 参数量 | 0.5B |
| 磁盘体积 | ~1.5GB |
| 推荐显存 | 12GB VRAM（可低至 4-6GB） |
| CPU 推理 | 支持（`--device cpu`，速度降低） |
| 首包延迟（GPU） | ~200ms |
| Python 版本 | 3.12（推荐）/ 3.10+ |
| torch 版本 | 2.8.0 |
| 情感控制 | 参考音频驱动（零样本）|
| 音色输入 | 10-30 秒参考音频（WAV/MP3） |
| 许可证 | Apache 2.0 ✅ |
| 模型来源 | HuggingFace: `fishaudio/openaudio-s1-mini` |

**用户自带模型格式**：提供参考音频文件即可，无需训练文件。如有基于 Fish Speech finetune 的 `.ckpt` checkpoint，也可直接导入。

### 4.2 GPT-SoVITS v4

| 项目 | 数值 |
|------|------|
| 推理最小体积 | ~2-2.5GB（含 CNHuBERT + 中文 RoBERTa） |
| 推荐显存 | 6GB VRAM |
| CPU 推理 | 支持（速度慢） |
| RTF（RTX 4060Ti） | ~0.028（极快） |
| Python 版本 | 3.10 |
| torch 版本 | 2.x（不固定） |
| transformers 版本 | >=4.43, <=4.50 |
| 情感控制 | 参考音频驱动 |
| 音色输入 | 成对 `.pth` 文件（GPT 模型 + SoVITS 模型）+ 参考音频 |
| 许可证 | MIT ✅ |
| 模型来源 | HuggingFace: `lj1995/GPT-SoVITS`（仅 v4 相关文件） |

**用户自带模型格式**：社区分发的标准格式，通常包含 `xxx_gpt.ckpt` + `xxx_sovits.pth` + 参考音频。应用直接识别此格式，无需转换。

### 4.3 CosyVoice3

| 项目 | 数值 |
|------|------|
| 参数量 | 0.5B（含多个子模型） |
| 磁盘体积 | ~9.75GB |
| 推荐显存 | 未精确测试，估计 4-8GB |
| CPU 推理 | 支持 |
| 首包延迟 | ~97ms（流式） |
| Python 版本 | 3.10 |
| torch 版本 | 2.3.1（硬钉） |
| transformers 版本 | 4.51.3（硬钉） |
| 情感控制 | 自然语言指令（文本语义自适应） |
| 音色输入 | 3-10 秒参考音频（零样本克隆） |
| 许可证 | Apache 2.0 ✅ |
| 模型来源 | ModelScope: `FunAudioLLM/Fun-CosyVoice3-0.5B-2512` |

**注意**：CosyVoice3 体积约 10GB，在安装前应向用户明确提示下载大小。

### 4.4 依赖隔离说明

三个引擎的依赖树存在**硬冲突**，无法共存于同一 Python 环境：

| 冲突项 | Fish Speech | GPT-SoVITS | CosyVoice3 |
|--------|-------------|------------|------------|
| torch | `==2.8.0` | 2.x 不固定 | `==2.3.1` |
| transformers | `<=4.57.3` | `<=4.50` | `==4.51.3` |
| lightning | `>=2.1.0` | `>=2.4` | `==2.2.4` |
| pydantic | `==2.9.2` | `<=2.10.6` | `==2.7.0` |

因此，**同一时刻只能安装一个离线引擎**。切换引擎时必须完全卸载当前引擎（删除 venv + 模型权重），再安装新引擎。此限制在 UI 上明确告知用户。

---

## 5. Worker 进程架构

### 5.1 总体设计

离线引擎运行在独立的 TTS Worker 子进程中，拥有专属 Python venv，与主 sidecar 进程完全隔离。两者通过本地 HTTP 通信。

```
主 sidecar（FastAPI，轻依赖）
        │
        │  HTTP  localhost:18080
        ▼
TTS Worker 子进程
  ├── 独立 TTS venv（含 torch 等重型依赖）
  ├── 模型已加载至内存（常驻）
  └── FastAPI 服务端，提供 /synthesize /voices /status 接口
```

### 5.2 进程生命周期

| 阶段 | 行为 |
|------|------|
| **应用启动** | 检测到已安装离线引擎 → 后台自动拉起 Worker 进程 → 加载模型至内存 |
| **加载中** | Worker 返回 `status: loading`，期间 TTS 输出静默跳过（文字气泡不受影响） |
| **就绪后** | Worker 返回 `status: ready`，sidecar 切换至离线引擎 |
| **应用退出** | sidecar 发送 shutdown 信号 → Worker 正常退出 → 内存释放 |
| **Worker 崩溃** | sidecar 检测到连接断开 → 自动重启 Worker → 期间 TTS 输出静默跳过 |

### 5.3 Worker HTTP 接口

```
POST /synthesize
  Body: { text, voice_id, emotion }
  Response: audio/wav binary

GET  /voices
  Response: [{ id, name, engine, ref_audio_path }]

GET  /status
  Response: { status: "loading" | "ready" | "error", message }

POST /shutdown
```

### 5.4 冷启动延迟处理

模型加载耗时约 5-15 秒（因引擎和硬件而异），此期间：
- Settings 界面显示"语音引擎启动中…"状态
- 对话中若 TTS 尚未就绪，静默跳过当次语音输出（不影响文字气泡），即进入无语音模式
- 模型加载完成后 Worker 主动通知 sidecar，sidecar 推送状态更新至前端

---

## 6. 音色管理

### 6.1 音色输入模式

三个离线引擎均支持多种音色输入方式，用户可按自身拥有的资源选择：

| 引擎 | 仅参考音频 | 仅模型文件 | 模型文件 + 参考音频 |
|------|-----------|-----------|------------------|
| Fish Speech S1-mini | ✅ 零样本推理 | ✅ finetune .ckpt | ✅ 模型优先，参考音频辅助 |
| GPT-SoVITS v4 | ✅ 零样本推理 | ✅ .ckpt + .pth（社区标准格式） | ✅ 模型优先 |
| CosyVoice3 | ✅ 零样本推理 | ✅ finetune checkpoint | ✅ 模型优先 |

推理时的优先级：**模型文件 > 参考音频**。若两者都存在，使用模型文件推理；若只有参考音频，走零样本推理。

**分情绪参考音频**：对于仅使用参考音频的场景，可为同一音色提供多段分情绪参考音频，系统按当前情感标签自动选取对应音频。命名规范见目录结构。

### 6.2 目录结构

```
{app_data}/tts/
├── engine/                    ← Worker venv 及引擎文件（程序管理）
│   ├── venv/
│   ├── weights/               ← 引擎基础模型权重
│   └── engine_type.txt
│
└── voices/                    ← 用户音色库（用户管理，切换引擎时保留）
    │
    ├── fish_speech/
    │   ├── hutao/             ← 仅参考音频模式
    │   │   ├── ref.wav            ← 默认参考音频（neutral 情绪）
    │   │   ├── ref.txt            ← 参考音频对应文字（可选）
    │   │   ├── ref_happy.wav      ← 分情绪参考音频（可选）
    │   │   ├── ref_sad.wav
    │   │   └── ref_excited.wav
    │   └── zhongli/           ← 模型文件模式
    │       ├── zhongli.ckpt       ← finetune checkpoint（必须）
    │       ├── ref.wav            ← 参考音频（可选，提升质量）
    │       └── ref.txt
    │
    ├── gpt_sovits/
    │   ├── nahida/            ← 模型文件模式（社区标准格式）
    │   │   ├── nahida_gpt.ckpt    ← GPT 模型文件（必须）
    │   │   ├── nahida_sovits.pth  ← SoVITS 模型文件（必须）
    │   │   ├── ref.wav            ← 参考音频（必须，用于零样本/推理参考）
    │   │   └── ref.txt
    │   └── fischl/            ← 仅参考音频模式（零样本）
    │       ├── ref.wav
    │       ├── ref_happy.wav
    │       └── ref_sad.wav
    │
    └── cosyvoice/
        ├── ganyu/             ← 仅参考音频模式
        │   ├── ref.wav            ← 参考音频（3-10 秒）
        │   ├── ref_happy.wav
        │   └── ref_sad.wav
        └── keqing/            ← 模型文件模式
            ├── keqing.ckpt        ← finetune checkpoint
            └── ref.wav            ← 可选
```

### 6.3 音色导入规则

- 应用提供"导入音色"按钮，用户选择本地文件夹，应用自动识别输入模式（模型文件 / 参考音频 / 混合）并复制到 voices 目录。
- 格式验证：按模式检查必要文件是否存在，不满足时给出明确错误提示（如"GPT-SoVITS 模型文件模式需要 .ckpt 和 .pth 文件"）。
- 分情绪参考音频识别规则：文件名包含 `_` + 标准情感标签（如 `ref_happy.wav`），自动关联对应情绪。
- 应用**不提供**训练、微调或语音克隆功能，仅支持使用已训练好的模型。

### 6.4 音色切换

同一引擎内切换音色：直接更换 `voice_id`，无需重启 Worker，也无需重新加载基础模型。

---

## 7. 情感驱动接口

### 7.1 统一情感标签系统

LLM 输出的情感标签与 TTS 引擎的情感参数之间，存在一个**统一标签层**作为中间桥梁。LLM 只输出标准标签，TTS 模块负责将标签翻译为各引擎的具体参数。

#### 标准情感标签表

标签分为三组，覆盖角色扮演场景的主要表达需求：

**基础情绪（9种）**

| 标签 | 含义 | 适用场景 |
|------|------|---------|
| `neutral` | 平静、默认语气 | 日常陈述、叙事 |
| `happy` | 开心、愉快 | 轻松对话、好消息 |
| `sad` | 悲伤、低沉 | 安慰、失落场景 |
| `angry` | 生气、强硬 | 激烈争论、不满 |
| `fearful` | 害怕、紧张 | 惊吓、危险场景 |
| `surprised` | 惊讶 | 意外信息、突发事件 |
| `disgusted` | 厌恶、嫌弃 | 负面评价 |
| `excited` | 兴奋、激动 | 游戏高潮、重大发现 |
| `gentle` | 温柔、体贴 | 安慰、关怀场景 |

**角色风格（7种）**

| 标签 | 含义 | 适用场景 |
|------|------|---------|
| `playful` | 俏皮、调侃 | 玩笑、逗趣 |
| `shy` | 害羞、拘谨 | 被夸奖、尴尬场景 |
| `proud` | 自豪、得意 | 成就展示 |
| `worried` | 担忧、焦虑 | 关心用户状态 |
| `confused` | 困惑、不解 | 不理解指令或信息 |
| `cold` | 冷淡、疏离 | 角色特定风格 |
| `serious` | 严肃、正经 | 重要信息、警告 |

**说话方式（5种）**

| 标签 | 含义 | 备注 |
|------|------|------|
| `whisper` | 悄悄话、低语 | 引擎支持时生效 |
| `shout` | 大喊、高亢 | 引擎支持时生效 |
| `cry` | 哽咽、哭泣 | 引擎支持时生效 |
| `laugh` | 笑着说 | 引擎支持时生效 |
| `sigh` | 叹气、疲惫 | 引擎支持时生效 |

共 **21 个标准标签**。LLM System Prompt 中只注入上述标签，不允许 LLM 自由发明情感标签。

#### 引擎能力与降级策略

不同引擎对情感标签的支持程度不同，不支持的标签**向最近的基础情绪降级**，而非报错或忽略：

| 引擎 | 支持等级 | 说明 |
|------|---------|------|
| MiniMax Speech | ★★★★★ | API 参数直接对应，全部标签有效 |
| ElevenLabs | ★★★★☆ | voice_settings 控制，说话方式组部分降级 |
| 阿里云 CosyVoice API | ★★★★☆ | 转自然语言指令，覆盖绝大多数标签 |
| CosyVoice3（离线） | ★★★★☆ | 同上，文本语义自适应 |
| Fish Speech S1-mini | ★★☆☆☆ | 无显式情感指令，全部标签通过参考音频隐式表达；若音色包含分情绪参考音频则提升至★★★★ |
| GPT-SoVITS v4 | ★★☆☆☆ | 同 Fish Speech，参考音频驱动 |

**针对参考音频驱动引擎的增强方案**：若用户为某个音色提供了多段分情绪参考音频（如 `ref_happy.wav`、`ref_sad.wav`），系统优先按情感标签选取对应参考音频，从而实现情感切换。格式见第 6 节音色目录结构。

### 7.2 情感标签与 LLM Prompt 的关联

现有 LLM System Prompt 中的情感标签需同步扩展至上述 21 个标准标签。Prompt 中明确列出允许使用的标签列表，并说明使用规则（每句话最多一个情感标签，放在句首）。

### 7.3 统一接口定义

```python
class TTSEngineBase:
    async def synthesize(
        self,
        text: str,
        voice_id: str,
        emotion: str = "neutral"   # 标准情感标签，见 7.1
    ) -> bytes                     # 返回 WAV 音频二进制

    async def list_voices(self) -> list[VoiceInfo]
    async def is_ready(self) -> bool
```

情感标签到各引擎参数的映射逻辑封装在各引擎 Adapter 的 `_map_emotion()` 方法中，上层只传递标准标签。

---

## 8. 无语音模式

当满足以下任一条件时，TTS 模块进入**无语音模式**，语音输出完全静默，文字气泡和其他功能正常运作：

- 用户未配置任何在线 API Key
- 用户未安装任何离线引擎
- 离线 Worker 加载中尚未就绪
- Worker 崩溃正在重启
- 在线 API 请求失败（网络错误、额度耗尽等）

无语音模式对用户透明：顶部状态栏显示"语音未启用"或"语音引擎加载中"，不弹出错误提示，不影响任何其他功能。

---

## 9. 安装与卸载管理

### 9.1 安装流程

用户在 Settings 中选择一个离线引擎并点击"安装"后：

```
Step 1  检查并创建 TTS 专用 venv（Python 3.10 或 3.12，按引擎要求）
Step 2  pip install 引擎依赖（来源：PyPI）
          · Fish Speech：torch 2.8.0 等，~3-4GB 下载
          · GPT-SoVITS：torch 2.x 等，~3-4GB 下载
          · CosyVoice3：torch 2.3.1 等，~3-4GB 下载
Step 3  下载模型权重文件
          · Fish Speech：HuggingFace / ModelScope，~1.5GB
          · GPT-SoVITS：HuggingFace / ModelScope，~2-2.5GB
          · CosyVoice3：ModelScope（优先），~9.75GB
Step 4  验证安装完整性（checksum 或 smoke test）
Step 5  写入 engine_type.txt，标记当前引擎类型
Step 6  自动启动 Worker 进程
```

**模型下载源策略**：ModelScope 对国内用户更友好，HuggingFace 面向国际用户。Settings 中提供下载源切换选项（自动 / HuggingFace / ModelScope），默认自动（按网络延迟判断）。

### 9.2 卸载流程

```
Step 1  向 Worker 发送 shutdown 信号，等待进程退出
Step 2  删除 TTS venv 目录
Step 3  删除模型权重目录（engine/ 下的权重文件，保留 voices/ 用户音色）
Step 4  删除 engine_type.txt
Step 5  通知前端引擎已卸载
```

注意：卸载时**保留用户音色库**（voices/ 目录），避免用户重新安装时需要重新导入音色。

### 9.3 切换引擎流程

切换 = 完整卸载当前引擎 + 安装新引擎，两步连续执行，中间有明确的确认弹窗告知用户。

---

## 10. 前端设置界面设计

### 10.1 TTS 设置 Tab 整体结构

```
语音合成
├── 当前引擎状态（顶部状态栏）
├── 在线 API 配置
│   ├── 供应商选择（MiniMax / 阿里云 / ElevenLabs）
│   └── API Key、Voice ID 输入
├── 离线引擎
│   ├── 当前安装状态
│   ├── 引擎选择与安装/卸载操作
│   └── 安装进度面板（安装时展开）
└── 音色管理
    ├── 音色列表
    └── 导入 / 删除操作
```

### 10.2 顶部状态栏

显示当前激活的引擎及其状态：

```
● 就绪  Fish Speech S1-mini   [切换引擎]
```

状态颜色：绿色（就绪）/ 黄色（加载中）/ 红色（错误）/ 灰色（未配置）

### 10.3 离线引擎选择卡片

用户点击"安装离线引擎"时，首先展示三个引擎的选择卡片，安装操作在用户选择后才触发。每张卡片布局如下：

```
┌─────────────────────────────────────────────┐
│  Fish Speech S1-mini              [推荐]     │
│  ─────────────────────────────────────────  │
│  音质出色、体积轻量，动漫/游戏角色声音社区    │
│  生态活跃，支持参考音频及 finetune 模型。    │
│                                             │
│  依赖下载    ~3-4 GB    （PyPI，需联网）     │
│  模型文件    ~1.5 GB    （HuggingFace/MS）   │
│  总计        ~5 GB                          │
│  推荐显存    12 GB（最低 4 GB）              │
│  情感控制    参考音频驱动                    │
│                                              │
│                          [安装此引擎]        │
└─────────────────────────────────────────────┘

┌─────────────────────────────────────────────┐
│  GPT-SoVITS v4                              │
│  ─────────────────────────────────────────  │
│  动漫/游戏圈最大预训练模型社区，推理速度极   │
│  快，支持用户直接导入社区 .pth 模型文件。    │
│                                             │
│  依赖下载    ~3-4 GB                        │
│  模型文件    ~2-2.5 GB                      │
│  总计        ~6 GB                          │
│  推荐显存    6 GB                           │
│  情感控制    参考音频驱动                    │
│                                              │
│                          [安装此引擎]        │
└─────────────────────────────────────────────┘

┌─────────────────────────────────────────────┐
│  CosyVoice3                                 │
│  ─────────────────────────────────────────  │
│  阿里开源，中文自然度高，支持自然语言情感    │
│  指令控制，首包延迟极低（97ms）。            │
│                                             │
│  依赖下载    ~3-4 GB                        │
│  模型文件    ~9.75 GB   ⚠ 体积较大          │
│  总计        ~13 GB                         │
│  推荐显存    4-8 GB（估算）                  │
│  情感控制    自然语言指令                    │
│                                              │
│                          [安装此引擎]        │
└─────────────────────────────────────────────┘
```

卡片底部统一附注：
> "每次只能安装一个离线引擎。切换引擎时需先卸载当前引擎，你的音色文件不受影响。"

### 10.5 安装进度面板

安装过程中展开，包含：

- **阶段标题**："正在安装 Fish Speech S1-mini"
- **进度条**：整体进度百分比
- **当前步骤描述**："正在下载模型文件（1.2 GB / 1.5 GB）…"
- **下载速度 + 预计剩余时间**："3.2 MB/s · 剩余约 1 分 40 秒"
- **警告提示**（醒目展示）："安装过程中请勿关闭应用"
- **详细日志**（默认折叠，出错时自动展开）：逐行显示 pip 输出和下载日志，错误行红色高亮

### 10.6 卸载确认弹窗

切换或卸载时弹出：

```
确认卸载 Fish Speech S1-mini？

此操作将删除：
  · Fish Speech 运行环境（约 4GB）
  · Fish Speech 模型文件（约 1.5GB）

以下内容将被保留：
  · 你导入的所有角色音色文件

确认卸载      取消
```

### 10.7 离线引擎单次限制提示

首次进入离线引擎安装界面时，显示一次性提示：

> "Reverie Link 每次只能安装一个离线语音引擎。如需切换引擎，需先卸载当前引擎并重新安装。你导入的角色音色文件不会受到影响。"

---

## 11. 数据文件与模块布局

### 11.1 后端模块结构

```
sidecar/
└── tts/
    ├── __init__.py
    ├── manager.py          ← TTSManager，路由层，对话流程调用入口
    ├── base.py             ← TTSEngineBase 抽象接口定义
    ├── online/
    │   ├── minimax.py      ← MiniMax 适配器
    │   ├── aliyun.py       ← 阿里云 CosyVoice 适配器
    │   └── elevenlabs.py   ← ElevenLabs 适配器
    ├── offline/
    │   ├── worker_client.py  ← 主 sidecar 侧 HTTP 客户端（调用 Worker）
    │   └── installer.py      ← 安装 / 卸载 / 下载管理逻辑
    └── worker/               ← TTS Worker 子进程代码（运行在独立 venv 中）
        ├── main.py           ← Worker FastAPI 入口
        ├── fish_speech.py    ← Fish Speech 引擎实现
        ├── gpt_sovits.py     ← GPT-SoVITS 引擎实现
        └── cosyvoice.py      ← CosyVoice3 引擎实现
```

### 11.2 数据目录（用户数据）

```
{app_data}/tts/
├── engine/
│   ├── venv/              ← TTS 专用 Python venv
│   ├── weights/           ← 模型权重文件
│   └── engine_type.txt    ← 当前引擎标识（fish_speech / gpt_sovits / cosyvoice3）
└── voices/
    ├── fish_speech/       ← 用户导入的 Fish Speech 音色
    ├── gpt_sovits/        ← 用户导入的 GPT-SoVITS 音色
    └── cosyvoice/         ← 用户导入的 CosyVoice 音色
```

### 11.3 新增 API 路由

```
POST /tts/synthesize          ← 合成语音（对话流程内部调用）
GET  /tts/status              ← 当前引擎状态
GET  /tts/voices              ← 音色列表
POST /tts/voices/import       ← 导入音色
DELETE /tts/voices/{id}       ← 删除音色
POST /tts/engine/install      ← 开始安装离线引擎（SSE 流式返回进度）
POST /tts/engine/uninstall    ← 卸载当前离线引擎
GET  /tts/engine/install/progress  ← 安装进度查询
```

---

## 12. 实施步骤

按照从重要到次要、从基础到进阶的顺序：

**Step 1：接口抽象层 + 无语音模式**
- 定义 `TTSEngineBase` 抽象接口
- `TTSManager` 路由层，替换原有硬编码 ElevenLabs 调用
- 实现无语音模式（未配置时静默跳过，状态栏显示"语音未启用"）
- 实现 21 个标准情感标签定义及 LLM Prompt 同步更新

**Step 2：在线 API 引擎接入**
- 实现 MiniMax 适配器（国内首选，优先）
- 实现 ElevenLabs 适配器（复用现有逻辑，适配新接口）
- 实现阿里云 CosyVoice 适配器
- Settings UI：在线 API 供应商选择 + API Key 配置

**Step 3：离线 Worker 进程框架**
- Worker 子进程启动 / 关闭 / 崩溃重启机制
- Worker HTTP 接口定义与 sidecar 侧客户端
- 进程生命周期管理（应用启动自动拉起，退出自动停止）

**Step 4：Fish Speech S1-mini 离线引擎**
- installer.py：Fish Speech venv 创建 + 依赖安装 + 模型下载
- worker/fish_speech.py：推理实现
- 音色管理：参考音频导入 + 切换
- Settings UI：安装进度面板 + 音色管理 UI

**Step 5：GPT-SoVITS v4 离线引擎**
- installer.py 扩展：GPT-SoVITS 支持
- worker/gpt_sovits.py：推理实现，兼容社区 .pth 模型格式
- 音色管理：.ckpt + .pth 模型对导入

**Step 6：CosyVoice3 离线引擎**
- installer.py 扩展：CosyVoice3 支持（含 9.75GB 大体积提示）
- worker/cosyvoice.py：推理实现
- 情感指令映射（情绪标签 → 自然语言指令）

**Step 7：情感驱动完善**
- 各引擎 emotion → 引擎参数的映射表
- 与 LLM 情绪标签输出的联调测试

---

*文档版本：v1.0 · 2026-04-14*
