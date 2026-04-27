设计的本质，是消除一切不必要的差异后，那个不得不存在的差异。
# 语音输入系统（场景语义驱动版）— 详细设计说明书 v2.1

> 本文档基于用户确认的 10 项决策及深度工程分析修订，对齐现有 Reverie Link 代码架构。  
> 作为开发实施的唯一权威参考，任何变更需经用户确认后更新本文档。  
> 创建日期：2026-04-24 · 修订日期：2026-04-27

---

## 目录

1. [核心定位与架构概览](#1-核心定位与架构概览)
2. [与现有系统的衔接关系](#2-与现有系统的衔接关系)
3. [技术选型决策](#3-技术选型决策)
4. [数据流与状态机](#4-数据流与状态机)
5. [前端：音频采集模块](#5-前端音频采集模块)
6. [WebSocket 协议扩展](#6-websocket-协议扩展)
7. [后端：语音处理模块](#7-后端语音处理模块)
8. [对话窗口与意图判断](#8-对话窗口与意图判断)
9. [打断与自循环防护](#9-打断与自循环防护)
10. [前端接线与状态管理](#10-前端接线与状态管理)
11. [模块文件布局](#11-模块文件布局)
12. [实施步骤](#12-实施步骤)
13. [附录 A：预留但未实装的设计](#13-附录-a预留但未实装的设计)
14. [附录 B：环形缓冲备用方案（详细记录）](#14-附录-b环形缓冲备用方案详细记录)

---

## 1. 核心定位与架构概览

### 核心定位

语音输入系统使桌宠能够**自然倾听**用户的日常说话，无需唤醒词，只在确认用户是在对桌宠说话时才回应。桌宠主动发言后，用户在对话窗口内的直接回复无需再次判断。用户发送文字消息后，接下来短时间内的语音也大概率是对桌宠说话的延续。

### 设计原则

- **无唤醒词**：用户不需要喊桌宠名字再说话，桌宠通过对话窗口和语义判断自行识别。
- **静默倾听**：未触发时无任何可见 UI 反馈（不显示字幕、不显示识别文字）。
- **对话窗口驱动**：桌宠发言后开启 15 秒窗口（用户可配置 5~60 秒），窗口内用户语音直接视为回复。**用户发送文字消息后同样开启窗口**。
- **预窗口覆盖延迟**：视觉/主动发言在 LLM 生成完成后、TTS 发送前开启 3 秒预窗口，覆盖生成延迟期间用户的语音。
- **意图过滤**：窗口外时由 LLM 结合人设判断用户是否在对桌宠说话，避免打扰日常对话。
- **全本地 STT**：语音识别离线完成，音频不离开设备。
- **打断自由**：用户可随时打断桌宠 TTS 播放，桌宠立即闭嘴并准备接收新语音。
- **记忆共通**：语音输入的识别文本与普通文字聊天共享同一条 `history` 与 `session_messages`，LLM 与记忆系统无感知差异。
- **不获取系统音频**：仅通过麦克风采集，依赖 WebView2 AEC3 消除回声，不引入系统音频捕获（避免耳机用户听歌等场景的隐私与体验问题）。

### 架构总览

```
[前端 · Tauri WebView]
  getUserMedia (echoCancellation: true)
        │  16kHz 单声道 Float32
        ▼
  @ricky0123/vad-web (Silero VAD, preSpeechPadFrames=15)
        │  onSpeechStart → 打断TTS + 发送 voice_interrupt
        │  onSpeechEnd   → 整段音频（含 ~1.4s 预缓冲）
        ▼
  Float32 → Int16 PCM 转换
        │
        ▼
  1-byte type marker(0x01) + Int16 PCM → WebSocket binary frame
        │
        ▼
[后端 · Python sidecar · FastAPI WebSocket]
  WebSocket /ws/chat
        │
        ├── text frame → 现有 configure / chat / voice_interrupt 处理
        │
        └── binary frame → VoiceProcessor.process(pcm_bytes)
              │
              ▼
        VoiceProcessor
              │
              ├── TextSanitizer        # 纯语气词/短句/乱码过滤
              │
              ├── STTEngine (SenseVoice-Small int8, ~70ms)
              │     输出：{ text, emotion, language }
              │
              ├── ConversationContext  # 窗口管理（含 3s 预窗口）
              │     状态：IDLE / PRE_WINDOW / CONVERSATION_WINDOW
              │
              ├── IntentFilter         # 窗口外意图判断
              │     → 复用 llm_client.chat.completions.create()
              │     → prompt 中注入 current_character 人设信息
              │     → 输出：[OK] / [NOT_FOR_ME]
              │
              ├── WindowQuickCheck     # 窗口内轻量规则（仅日志，不阻断）
              │
              └── InterruptHandler     # 打断 + 任务取消
              │
              ▼
        识别文本通过 → 复用现有 handle_chat_round()
              │
              ▼
        chat_response / vision_proactive_speech 发送后
              │
              ▼
        ConversationContext.open_window()  // 开启/延续 15s 窗口
        用户文字消息时
              │
              ▼
        ConversationContext.on_user_interaction()  // 同样开启窗口
              │
              ▼
  [前端] 显示气泡 + TTS播放 + Live2D表情（复用现有逻辑）
```

---

## 2. 与现有系统的衔接关系

### 2.1 人设系统衔接

现有 `prompt/constants.py` 中的 `DEFAULT_CHARACTER` 数据结构：

```python
{
    "name": "Rei",
    "identity": "你是用户身边的猫娘伙伴，平时住在一起",
    "personality": "傲娇，表面高冷不在乎，实际上很在意用户...",
    "address": "主人",
    "style": "简短干脆，傲娇别扭，不会主动示好...",
    "examples": [...],
}
```

语音模块消费方式：
- `IntentFilter` 持有 `character` dict 引用（非拷贝），`configure` 更新时同步更新。
- 意图判断 prompt 直接注入 `name`、`identity`、`personality`、`address`、`style` 字段，让 LLM 从角色第一人称视角判断边界。
- **活泼度由人设自然表达**：角色性格中的"不会主动示好"/"粘人"等描述即为主动度提示，不引入独立量化字段。

### 2.2 Prompt 构建层衔接

现有 `prompt/system_prompt.py` 的 `build_system_prompt()` 负责 Layer 1 角色定义组装。  
语音模块**不调用** `build_system_prompt()`，而是独立构建轻量意图判断 prompt（仅含角色核心信息，不含记忆层、时间注记、硬性约束），避免污染 chat flow 的 system prompt 组装逻辑。

### 2.3 Messages 构建层衔接

现有 `prompt/messages.py` 提供 `build_messages()` / `build_vision_speech_messages()` 等函数。  
语音触发的对话**复用** `build_messages()` 进入 chat flow，语音输入的识别文本与普通 `user_msg` 完全一致进入 messages 列表。

### 2.4 记忆系统衔接

现有 `memory` 子包提供 `TimelineMessage.create()` / `save_message()` / `session_messages`。  
语音输入触发回复时，识别文本作为 user content 写入 `history` 与 `session_messages`，msg_type 沿用 `MessageType.USER_TEXT`（不新增 USER_VOICE 类型，减少记忆系统改动）。

`_source` 标记（可选）：
```python
history.append({
    "role": "user",
    "content": text,
    "timestamp": time.time(),
    "_source": "voice",  # 可选，不影响现有 trim_history / build_messages
})
```

### 2.5 情绪标签系统衔接

根据 `EMOTION_TAG_DESIGN.md`，系统采用**单一标签空间**，默认 8 标签：
`neutral`、`happy`、`sad`、`angry`、`surprised`、`shy`、`worried`、`playful`。

SenseVoice-Small 输出情绪：`angry`、`happy`、`neutral`、`sad`。

衔接策略：
- STT 输出的 `emotion` **原样透传**，不做映射翻译。
- `voice_result` 消息携带 `emotion` 字段，由项目**现有情绪识别算法**按需消费。
- SenseVoice 没有 `surprised`/`shy`/`worried`/`playful` 时，`emotion` 字段为 `null`。

### 2.6 视觉主动发言衔接

现有 `ws/vision_speech.py` 的 `_drain_vision_speech()` 在桌宠主动发言后发送 `vision_proactive_speech`。  
语音模块需要在桌宠主动发言后**开启对话窗口**，同时覆盖 LLM 生成延迟期间的语音输入。

**修改 `_drain_vision_speech()`**：
- LLM 生成完成、清洗回复后、**发送 `vision_proactive_speech` 前**：调用 `voice_processor.open_pre_window()` 开启 3 秒预窗口。
- 发送 `vision_proactive_speech` 完成后：调用 `voice_processor.on_pet_response_sent()` 开启正式 15 秒窗口（自动覆盖预窗口）。

---

## 3. 技术选型决策

### 3.1 音频采集：前端 WebView getUserMedia

**保留原决策**。Tauri WebView2 底层为 Edge 141+，支持 `echoCancellation: "all"` 模式，可消除包括 TTS 在内的所有系统播放音频的回声，不引入系统音频捕获。

```typescript
additionalAudioConstraints: {
    echoCancellation: true,   // WebView2 等价于 "all"
    noiseSuppression: true,
    autoGainControl: true,
}
```

**不引入 `getDisplayMedia` 获取系统音频**：产品体验上不可行（需用户每次手动选择共享源），且信噪比差。耳机用户听歌场景通过 AEC3 自然处理。

### 3.2 VAD：Silero VAD（前端 WASM）

**保留原决策**，参数按新需求调整：

| 参数 | 最终值 | 默认值 | 调整理由 |
|------|--------|--------|---------|
| `preSpeechPadFrames` | **15** | 1 | ~1.44s 预缓冲，缓解快速说话开头丢失（非完美方案，详见附录 B） |
| `positiveSpeechThreshold` | **0.4** | 0.5 | 降低阈值，IDLE 状态下更灵敏 |
| `redemptionFrames` | **10** | 8 | 增加句中停顿容忍，减少句内截断 |
| `negativeSpeechThreshold` | 0.35 | 0.35 | 不变 |
| `minSpeechFrames` | 3 | 3 | 不变 |

**关于 `preSpeechPadFrames` 的真实行为**：MicVAD 在 VAD 状态机从 SILENT → SPEECH 转换时回溯抓取 `preSpeechPadFrames` 个帧的数据拼接在 speech 开头。如果 VAD 触发延迟（开头音量低），回溯的 15 帧也只是"触发点之前"的音频，而非"用户实际开口前"的音频。**这是当前方案的已知局限**，若 Step 8 实测丢失严重，升级到附录 B 的环形缓冲方案。

### 3.3 STT：SenseVoice-Small（sherpa-onnx）

**保留原决策**。非流式整段识别，10s 音频 ~70ms 推理。

**情绪字段**：透传至 `voice_result.emotion`，由项目现有情绪识别算法消费，STT 模块不做映射。

### 3.4 意图判断：复用 LLM + 人设嵌入 prompt

**决策理由**：零额外模型依赖，人设提供稳定判断锚点，LLM 从角色第一人称视角判断边界。

**调用方式**：
```python
await llm_client.chat.completions.create(
    model=LLM_MODEL,
    messages=[{"role": "system", "content": intent_prompt}],
    max_tokens=10,
    temperature=0.1,
)
```

### 3.5 协议：WebSocket binary frame + 1-byte 类型标记

**用户确认增加类型标记**。格式：
- Byte 0: `0x01` = 语音 PCM 数据（预留 `0x02` 及以后供未来扩展）
- Byte 1~N: Int16 little-endian mono PCM @ 16kHz

---

## 4. 数据流与状态机

### 4.1 完整数据流

```
用户说话
  │
  ▼
[前端] getUserMedia（echoCancellation: true）
  │  16kHz 单声道 Float32
  ▼
[前端] Silero VAD (WASM)
  │  preSpeechPadFrames=15 → 预缓冲 ~1.4s
  │  onSpeechStart → 若 TTS 播放中：
  │     stopTTS() + websocket.send_voice_interrupt()
  │  onSpeechEnd → 整段音频
  ▼
[前端] Float32 → Int16 转换 → 加 1-byte type(0x01)
  │
  ▼
[后端] WebSocket receive() → binary frame
  │  验证 Byte0 == 0x01
  │  过短音频（<300ms）直接丢弃
  ▼
[后端] VoiceProcessor.process(pcm_bytes)
  │
  ├── 1. TextSanitizer.is_degradation(text)?
  │     → YES → 静默丢弃
  │
  ├── 2. STTEngine.recognize(pcm_bytes)
  │     输出：{ text, emotion, language }
  │
  ├── 3. ConversationContext 状态检查
  │     ├── PRE_WINDOW 有效? → YES → triggered=True
  │     ├── CONVERSATION_WINDOW 有效? → YES → triggered=True
  │     └── 窗口外 → IntentFilter.should_respond(text)
  │         ├── [NOT_FOR_ME] → triggered=False
  │         └── [OK] → triggered=True
  │
  ├── 4. WindowQuickCheck（仅窗口内执行，仅日志不阻断）
  │
  └── 5. 发送 voice_result 给前端
        │
        ├── triggered=False → 结束（前端完全静默）
        └── triggered=True
              │
              ▼
        复用现有 handle_chat_round(user_msg=text, source="voice")
              │
              ▼
        [后端] LLM 生成回复 → 发送 chat_response
              │
              ▼
        ConversationContext.open_window()  // 开启 15s 窗口
              │
              ▼
  [前端] 显示气泡 + TTS播放（复用现有逻辑）
```

### 4.2 后端状态机

```
                              ┌──────────────────────────────┐
                              │          PRE_WINDOW          │
                              │           (3s)               │
                              │  视觉/主动发言 LLM 生成完成后  │
   ┌─────────┐      文字消息   │        开启，覆盖延迟        │
   │  IDLE   │◄───────────────┤                              │
   │ 静默待机 │                │  超时 → 回到 IDLE            │
   └────┬────┘                │  正式窗口开启 → 覆盖为 WINDOW│
        │                     └──────────────┬───────────────┘
        │                                    │
        │        ┌───────────────────────────┘
        │        │
        │        ▼
        │   ┌──────────────────────────────┐
        │   │      CONVERSATION_WINDOW       │
        └───┤       (默认 15s，用户可配)      │
            │                              │
            │  触发条件：                     │
            │    · chat_response 发送完成   │
            │    · vision_proactive_speech   │
            │      发送完成                  │
            │    · 用户文字消息              │
            │    · 用户在窗口内回复          │
            │      (extend_window)           │
            │                              │
            │  退出条件：                     │
            │    · 窗口到期无新语音          │
            └──────────────────────────────┘
```

### 4.3 前端状态

| 状态 | 类型 | 说明 |
|------|------|------|
| `isListening` | `Ref<boolean>` | 麦克风是否已激活 |
| `isUserSpeaking` | `Ref<boolean>` | VAD 是否检测到用户正在说话 |
| `isPetsSpeaking` | `Ref<boolean>` | 桌宠 TTS 是否正在播放 |
| `isThinking` | `Ref<boolean>` | 已有，等待 AI 回复中 |

### 4.4 UI 反馈逻辑

| 场景 | 前端显示 |
|------|---------|
| 麦克风已激活、静默等待 | 仅微小状态点表示功能开启，无显眼提示 |
| VAD 检测到说话 | **不显示任何提示**，静默处理 |
| 收到 `voice_result` 且 `triggered=true` | 设置 `isThinking=true`，显示思考动画 |
| 收到 `voice_result` 且 `triggered=false` | **完全静默**，无任何可见操作 |
| 收到 `chat_response` | 显示气泡 + TTS（复用现有逻辑） |

---

## 5. 前端：音频采集模块

### 5.1 文件：`src/composables/useVoiceInput.ts`

### 5.2 依赖

```
@ricky0123/vad-web  — Silero VAD 浏览器 WASM 封装
```

### 5.3 接口

```typescript
export interface VoiceInputCallbacks {
    onSpeechStart: () => void;
    onSpeechEnd: (audio: Float32Array, durationMs: number) => void;
    onError: (message: string) => void;
}

export function useVoiceInput(callbacks: VoiceInputCallbacks) {
    const isListening    = ref(false);
    const isUserSpeaking = ref(false);
    const isPetsSpeaking = ref(false);

    async function startListening(): Promise<void>;
    function stopListening(): void;
    function destroyVoiceInput(): void;
    function setPetsSpeaking(value: boolean): void;  // TTS 模块调用

    return {
        isListening, isUserSpeaking,
        startListening, stopListening, destroyVoiceInput,
        setPetsSpeaking,
    };
}
```

### 5.4 VAD 参数

```typescript
const vad = await MicVAD.new({
    additionalAudioConstraints: {
        echoCancellation: true,    // WebView2 等价于 "all"
        noiseSuppression: true,
        autoGainControl: true,
    },
    positiveSpeechThreshold: 0.4,
    negativeSpeechThreshold: 0.35,
    minSpeechFrames: 3,
    preSpeechPadFrames: 15,     // ~1.44s 预缓冲
    redemptionFrames: 10,       // 句中停顿容忍
    onSpeechStart: () => { callbacks.onSpeechStart(); },
    onSpeechEnd: (audio) => {
        const durationMs = (audio.length / 16000) * 1000;
        callbacks.onSpeechEnd(audio, durationMs);
    },
});
```

### 5.5 音频格式转换

```typescript
/**
 * Float32 (-1.0 ~ 1.0) → Int16 PCM (-32768 ~ 32767)
 * 前加 1-byte type marker (0x01)
 */
function encodeVoiceFrame(float32Array: Float32Array): ArrayBuffer {
    const int16 = new Int16Array(float32Array.length);
    for (let i = 0; i < float32Array.length; i++) {
        const s = Math.max(-1, Math.min(1, float32Array[i]));
        int16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
    }
    const result = new Uint8Array(1 + int16.length * 2);
    result[0] = 0x01;  // 类型标记：语音数据
    result.set(new Uint8Array(int16.buffer), 1);
    return result.buffer;
}
```

---

## 6. WebSocket 协议扩展

### 6.1 设计原则

现有协议均为 JSON text frame。语音数据使用 binary frame，1-byte 类型标记区分，零解析开销。

### 6.2 前端 → 后端

| 类型 | 帧格式 | 说明 |
|------|--------|------|
| 文字聊天 | text JSON: `{ type: "chat", message: "..." }` | 不变 |
| 配置推送 | text JSON: `{ type: "configure", ... }` | 不变 |
| 语音打断 | text JSON: `{ type: "voice_interrupt" }` | **新增** |
| 语音数据 | **binary**: `[1-byte type=0x01] + [Int16 PCM bytes]` | **新增** |

### 6.3 后端 → 前端

| 类型 | 格式 | 说明 |
|------|------|------|
| 语音识别结果 | `{ type: "voice_result", text, emotion, language, triggered, reason }` | **新增** |
| 打断确认 | `{ type: "interrupted", clear_lip_sync: true }` | **新增** |
| AI 回复 | `{ type: "chat_response", message }` | 不变 |
| 视觉主动发言 | `{ type: "vision_proactive_speech", message }` | 不变 |
| 错误 | `{ type: "error", message }` | 不变 |

### 6.4 `voice_result` 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `text` | string | STT 原始识别文本 |
| `emotion` | string \| null | SenseVoice 输出（angry/happy/neutral/sad），透传至情绪识别模块 |
| `language` | string | 语种 |
| `triggered` | boolean | 是否触发对话 |
| `reason` | string | `"conversation_window"` / `"pre_window"` / `"intent_ok"` / `"not_triggered"` |

### 6.5 `useWebSocket.ts` 修改要点

```typescript
// 新增发送方法
function sendVoiceAudio(audio: Float32Array): void {
    const buffer = encodeVoiceFrame(audio);
    websocket.send(buffer);  // binary frame
}

function sendVoiceInterrupt(): void {
    websocket.send(JSON.stringify({ type: "voice_interrupt" }));
}

// 新增回调接口
let onVoiceResult: ((result: VoiceResult) => void) | null = null;
let onInterrupted: (() => void) | null = null;

// 消息分发增加 voice_result / interrupted 分支
function handleMessage(raw: string) {
    const data = JSON.parse(raw);
    if (data.type === "voice_result") {
        onVoiceResult?.(data);
    } else if (data.type === "interrupted") {
        onInterrupted?.();
    }
    // ... 现有分支不变
}
```

### 6.6 后端 WebSocket handler 修改要点

现有 `main.py` 中 `websocket_chat()` 使用 `receive_text()` 并设置 1 秒超时用于轮询视觉主动发言。修改为 `receive()` 以支持 binary frame：

```python
# 修改前
raw = await asyncio.wait_for(websocket.receive_text(), timeout=1.0)

# 修改后
message = await asyncio.wait_for(websocket.receive(), timeout=1.0)

if "text" in message:
    raw = message["text"]
    data = json.loads(raw)
    msg_type = data.get("type")
    
    if msg_type == "voice_interrupt":
        await voice_processor.handle_interrupt(websocket)
        continue
    elif msg_type == "chat":
        # 用户发送文字消息 → 触发对话窗口
        voice_processor.on_user_interaction()
        # ... 现有 chat 处理不变
    # ... 现有 configure 等处理不变
    
elif "bytes" in message:
    pcm_bytes = message["bytes"]
    if pcm_bytes[0:1] != b'\x01':
        continue  # 未知类型，丢弃
    pcm_payload = pcm_bytes[1:]
    result = await voice_processor.process(pcm_payload)
    if result:
        await websocket.send_text(json.dumps(result, ensure_ascii=False))
        if result.get("triggered"):
            # 复用 chat flow 处理识别文本
            user_msg = result["text"]
            # ... 进入现有 chat 处理逻辑
            # chat 完成后：voice_processor.on_pet_response_sent()
```

---

## 7. 后端：语音处理模块

### 7.1 模块结构

```
sidecar/
  voice/
    __init__.py
    stt_engine.py           # SenseVoice STT 封装
    text_sanitizer.py       # 文本消歧层（纯语气词/短句/乱码过滤）
    interrupt_handler.py    # 打断 + 任务取消 + 状态清理
    conversation_context.py # 对话窗口管理（含 3s 预窗口）
    intent_filter.py        # 意图判断 + 人设接入
    window_quick_check.py   # 窗口内轻量规则（仅日志，不阻断）
    processor.py            # 对外统一接口 VoiceProcessor
```

### 7.2 STTEngine（`stt_engine.py`）

**职责**：加载 sherpa-onnx SenseVoice 模型，接收 PCM bytes → 返回 `{ text, emotion, language }`。

**关键设计**：
- 模型路径：`models/sense-voice-small-int8/`
- API：`sherpa_onnx.OfflineRecognizer.from_sense_voice()`
- `recognize()` 同步方法，上层通过 `asyncio.to_thread()` 调用
- emotion / language 字段名需首次实测确认（开发 Step 1 验证）

**返回格式**：
```python
{
    "text": "用户说的话",
    "emotion": "happy",    # angry / happy / neutral / sad / null
    "language": "zh",       # 语种代码
}
```

### 7.3 TextSanitizer（`text_sanitizer.py`）

**职责**：STT 输出后的文本质量消歧层，过滤无意义的误识别结果。

```python
import re

class TextSanitizer:
    """
    文本消歧层：过滤 VAD 误触发产生的无意义识别结果。
    执行时间 < 1ms，不影响整体延迟。
    """
    
    FILLER_WORDS = {"嗯", "啊", "哦", "呃", "哈", "唔", "哎", "嘛", "呢", "吧"}
    
    @staticmethod
    def is_degradation(text: str) -> bool:
        """
        判断识别文本是否为无意义的误触发结果。
        返回 True → 静默丢弃，不进入后续流程。
        """
        stripped = text.strip()
        
        # 1. 过短（1 字以内）
        if len(stripped) <= 1:
            return True
        
        # 2. 纯语气词
        chars = set(stripped)
        if chars.issubset(TextSanitizer.FILLER_WORDS):
            return True
        
        # 3. 可读字符占比过低（噪音识别出的乱码）
        readable = re.findall(r'[\u4e00-\u9fff\u3000-\u303fa-zA-Z0-9\s]', stripped)
        if len(readable) / len(stripped) < 0.5:
            return True
        
        return False
```

### 7.4 InterruptHandler（`interrupt_handler.py`）

**职责**：管理打断信号，取消正在进行的 LLM 生成任务，清理前后端状态。

```python
class InterruptHandler:
    def __init__(self):
        self._current_task: asyncio.Task | None = None
    
    def register_task(self, task: asyncio.Task):
        """chat flow 开始时注册当前 LLM 任务"""
        self._current_task = task
    
    async def handle_interrupt(self, websocket):
        """
        用户打断时调用：
        1. 取消 LLM 生成任务
        2. 发送打断确认给前端（清理 Live2D 口型等）
        3. 清理本地任务引用
        """
        if self._current_task and not self._current_task.done():
            self._current_task.cancel()
            try:
                await self._current_task
            except asyncio.CancelledError:
                pass
        
        # 发送打断确认，前端据此清理口型动画等状态
        await websocket.send_text(json.dumps({
            "type": "interrupted",
            "clear_lip_sync": True,
        }, ensure_ascii=False))
        
        self._current_task = None
    
    def clear(self):
        self._current_task = None
```

**打断后的对话状态处理**：
- 被打断的回复如果尚未写入 `history`/`session_messages`，不做任何事。
- 如果已经写入了 user turn（但 assistant 未写入），保留 user turn。
- **不删除已完成的 user turn**，只丢弃未完成的 assistant turn。
- `isThinking` 在前端保持 `true`（新语音已在处理中），直到新流程自然重置。

### 7.5 ConversationContext（`conversation_context.py`）

**含 3 秒预窗口设计**。

```python
class ConversationContext:
    """
    管理桌宠与用户的对话状态。
    - PRE_WINDOW: 3 秒预窗口（视觉/主动发言 LLM 生成完成后开启）
    - CONVERSATION_WINDOW: 正式对话窗口（桌宠发言/用户文字消息后开启）
    - IDLE: 静默待机
    """
    
    def __init__(self, default_window_sec: float = 15.0):
        self._default_duration = max(5.0, min(60.0, default_window_sec))
        self._pre_window_expiry: float = 0.0
        self._window_expiry: float = 0.0
        self._state = "IDLE"
    
    # ── 预窗口 ──
    def open_pre_window(self, duration_sec: float = 3.0):
        """视觉/主动发言 LLM 生成完成后调用"""
        self._pre_window_expiry = time.time() + duration_sec
        self._state = "PRE_WINDOW"
    
    def is_in_pre_window(self) -> bool:
        if self._state == "PRE_WINDOW":
            if time.time() > self._pre_window_expiry:
                self._state = "IDLE"
                return False
            return True
        return False
    
    # ── 正式窗口 ──
    def open_window(self):
        """桌宠发言/用户文字消息后调用"""
        self._state = "CONVERSATION_WINDOW"
        self._window_expiry = time.time() + self._default_duration
        # 预窗口被正式窗口覆盖
        self._pre_window_expiry = 0.0
    
    def extend_window(self):
        """用户在窗口内回复，延续窗口"""
        if self._state in ("PRE_WINDOW", "CONVERSATION_WINDOW"):
            self._state = "CONVERSATION_WINDOW"
            self._window_expiry = time.time() + self._default_duration
    
    def close_window(self):
        self._state = "IDLE"
        self._window_expiry = 0.0
        self._pre_window_expiry = 0.0
    
    def is_in_window(self) -> bool:
        """检查是否在任何有效窗口内（预窗口或正式窗口）"""
        # 先检查预窗口
        if self.is_in_pre_window():
            return True
        # 再检查正式窗口
        if self._state == "CONVERSATION_WINDOW":
            if time.time() > self._window_expiry:
                self._state = "IDLE"
                return False
            return True
        return False
    
    def on_user_interaction(self):
        """
        抽象接口：任意用户交互触发对话窗口。
        当前触发点：桌宠发言后、用户文字消息后。
        """
        self.open_window()
    
    def update_window_duration(self, seconds: float):
        """用户设置更新窗口时长"""
        self._default_duration = max(5.0, min(60.0, seconds))
```

### 7.6 IntentFilter（`intent_filter.py`）

**职责**：仅对 IDLE 状态下的语音输入做意图判断。窗口内直接通过。

```python
class IntentFilter:
    def __init__(self, llm_client, llm_model: str, character: dict | None = None):
        self._llm = llm_client
        self._model = llm_model
        self._character = character or {}
    
    def update_character(self, character: dict):
        self._character = character
    
    async def should_respond(self, text: str, context: ConversationContext) -> bool:
        """
        判断是否应该对这段语音文本做出回应。
        窗口内（含预窗口）直接通过；窗口外交由 LLM 结合人设判断。
        """
        if context.is_in_window():
            context.extend_window()
            return True
        
        # 窗口外：LLM 结合人设判断
        prompt = self._build_prompt(text)
        response = await self._llm.chat.completions.create(
            model=self._model,
            messages=[{"role": "system", "content": prompt}],
            max_tokens=10,
            temperature=0.1,
        )
        content = response.choices[0].message.content.strip()
        return "[NOT_FOR_ME]" not in content
    
    def _build_prompt(self, text: str) -> str:
        c = self._character
        name = c.get("name", "桌宠")
        identity = c.get("identity", "")
        personality = c.get("personality", "")
        address = c.get("address", "你")
        style = c.get("style", "")
        
        return (
            f"你现在扮演「{name}」，{identity}。\n"
            f"性格：{personality}\n"
            f"称呼用户为：{address}\n"
            f"说话风格：{style}\n\n"
            f"请判断用户是否在对你说：\n"
            f"- 如果用户在自言自语、打电话、约朋友、工作开会、对第三方说话，"
            f"只输出 [NOT_FOR_ME]\n"
            f"- 如果用户在跟你分享、请求、感叹、回应、闲聊，只输出 [OK]\n\n"
            f"用户说的话：\" {text} \"\n"
            f"只输出 [NOT_FOR_ME] 或 [OK]。"
        )
```

### 7.7 WindowQuickCheck（`window_quick_check.py`）

**职责**：窗口内语音的轻量规则筛检。**仅日志记录，不阻断流程**。

```python
import re
import logging

logger = logging.getLogger(__name__)

class WindowQuickCheck:
    """
    窗口内语音的轻量规则筛检。
    仅用于日志记录和后续统计分析，不阻断语音进入 chat flow。
    """
    
    # 可能指向与他人通话的模式
    PHONE_PATTERNS = [
        r'(喂|哪位|你是谁|找.+?吗|今晚.+?吃饭|几点.+?见|在哪.+?等)',
        r'(我.+?过来|你.+?过来|等我|马上到|路上)',
    ]
    
    @classmethod
    def check(cls, text: str) -> str | None:
        """
        检测窗口内语音是否包含可能的"与他人对话"信号。
        返回：提示字符串 或 None（无异常）。
        """
        for pattern in cls.PHONE_PATTERNS:
            if re.search(pattern, text):
                return "possible_external_conversation"
        return None
    
    @classmethod
    def log_if_suspicious(cls, text: str, source: str = "voice"):
        """仅在检测到可疑模式时记录日志"""
        flag = cls.check(text)
        if flag:
            logger.info(
                f"[WindowQuickCheck] 窗口内语音标记为可疑 | "
                f"flag={flag} text={text[:40]!r} source={source}"
            )
```

### 7.8 VoiceProcessor（`processor.py`）

**职责**：对外唯一入口。串联所有子模块。

```python
class VoiceProcessor:
    def __init__(
        self,
        stt_engine: STTEngine,
        llm_client,
        llm_model: str,
        character: dict | None = None,
        window_sec: float = 15.0,
    ):
        self.stt = stt_engine
        self.context = ConversationContext(window_sec)
        self.filter = IntentFilter(llm_client, llm_model, character)
        self.interrupt = InterruptHandler()
        self.sanitizer = TextSanitizer()
    
    async def process(self, pcm_bytes: bytes) -> dict | None:
        """
        处理一段语音 PCM 数据。
        返回 voice_result dict，或 None（音频无效/被过滤）。
        """
        # 1. STT
        result = await self.stt.recognize(pcm_bytes)
        text = result.get("text", "").strip()
        
        # 2. 文本消歧层
        if self.sanitizer.is_degradation(text):
            return None
        
        # 3. 对话窗口 / 意图判断
        in_window = self.context.is_in_window()
        should_reply = await self.filter.should_respond(text, self.context)
        
        # 4. 窗口内轻量规则（仅日志，不阻断）
        if in_window:
            WindowQuickCheck.log_if_suspicious(text)
        
        reason = (
            "pre_window" if self.context.is_in_pre_window()
            else "conversation_window" if in_window
            else "intent_ok" if should_reply
            else "not_triggered"
        )
        
        return {
            "type": "voice_result",
            "text": text,
            "emotion": result.get("emotion"),
            "language": result.get("language"),
            "triggered": should_reply,
            "reason": reason,
        }
    
    async def handle_interrupt(self, websocket):
        """用户打断时调用"""
        await self.interrupt.handle_interrupt(websocket)
    
    def on_pet_response_sent(self):
        """桌宠发送回复（chat_response 或 vision_proactive_speech）后调用"""
        self.context.open_window()
    
    def on_user_interaction(self):
        """用户发送文字消息后调用"""
        self.context.on_user_interaction()
    
    def open_pre_window(self):
        """视觉/主动发言 LLM 生成完成后调用"""
        self.context.open_pre_window()
    
    def update_character(self, character: dict):
        self.filter.update_character(character)
    
    def update_window_duration(self, seconds: float):
        self.context.update_window_duration(seconds)
    
    def register_llm_task(self, task: asyncio.Task):
        """chat flow 开始时注册 LLM 任务，供打断时取消"""
        self.interrupt.register_task(task)
    
    def clear_llm_task(self):
        """chat flow 结束时清理"""
        self.interrupt.clear()
```

---

## 8. 对话窗口与意图判断

### 8.1 对话窗口机制

| 触发条件 | 调用的方法 | 窗口类型 | 时长 |
|---------|-----------|---------|------|
| 桌宠发送 `chat_response` | `on_pet_response_sent()` | CONVERSATION_WINDOW | 15s（可配置） |
| 桌宠发送 `vision_proactive_speech` | `on_pet_response_sent()` | CONVERSATION_WINDOW | 15s |
| 用户发送文字消息 | `on_user_interaction()` | CONVERSATION_WINDOW | 15s |
| 用户在窗口内说话 | `extend_window()` | CONVERSATION_WINDOW | 延续 15s |
| 视觉/主动发言 LLM 生成完成 | `open_pre_window()` | PRE_WINDOW | 3s |

**窗口退出条件**：
- PRE_WINDOW：3 秒超时，自动回到 IDLE（或被正式窗口覆盖）
- CONVERSATION_WINDOW：15 秒（可配置）超时无新语音，自动回到 IDLE

### 8.2 窗口时长配置

- **默认值**：15 秒
- **用户可调范围**：5 秒 ~ 60 秒
- **配置同步**：前端设置界面修改 → `configure` 消息 → `voice_processor.update_window_duration()`

### 8.3 意图判断策略（IDLE 状态下）

**流程**：
1. 窗口外语音 → `IntentFilter.should_respond(text, context)`
2. 构造含人设信息的 prompt
3. LLM 调用 `chat.completions.create(max_tokens=10, temperature=0.1)`
4. `[OK]` → 进 chat flow
5. `[NOT_FOR_ME]` → 静默丢弃

**兜底策略**：若 LLM 未返回预期格式（既无 `[OK]` 也无 `[NOT_FOR_ME]`），保守处理为 `return False`（静默丢弃）。

---

## 9. 打断与自循环防护

### 9.1 打断触发

| 场景 | 前端行为 | 后端行为 |
|------|---------|---------|
| 桌宠 TTS 播放中，VAD 检测到 `onSpeechStart` | `stopTTS()` + 发送 `voice_interrupt` | `InterruptHandler.handle_interrupt()` 取消 LLM 任务 + 发送 `interrupted` 确认 |
| TTS 刚结束（500ms 冷却期内） | 忽略 VAD 触发，不发送音频 | 无 |

### 9.2 打断后状态清理

**前端收到 `interrupted` 消息后**：
```typescript
websocket.onInterrupted = () => {
    stopTTS();           // 停止音频播放
    resetLipSync();      // 重置 Live2D 口型动画
    isPetsSpeaking.value = false;
    // isThinking 保持 true（新语音已在处理中），直到新流程自然重置
};
```

**后端打断处理**：
- 取消正在进行的 LLM 生成任务
- 未完成的 assistant turn **不写入** `history` / `session_messages`
- 已完成的 user turn **保留**

### 9.3 自循环防护

| 层级 | 机制 | 说明 |
|------|------|------|
| 第一层 | WebView2 AEC3 `"all"` 模式 | Edge 141+ 消除所有系统播放音频的回声 |
| 第二层 | 500ms 冷却期 | TTS 结束后前端进入冷却期，丢弃 VAD 触发 |
| 第三层 | 文本消歧层 | `TextSanitizer` 过滤回声残留的短句/语气词 |
| 第四层 | 对话窗口过滤 | 窗口外语音需过 LLM 意图判断，回声残留文本通常会被判定为 `[NOT_FOR_ME]` |

**不引入 `getDisplayMedia` 系统音频捕获**：产品体验不可行，且耳机用户听歌场景无需系统音频介入。

---

## 10. 前端接线与状态管理

### 10.1 App.vue 接线

```typescript
// ── 语音输入 ──
const { isListening, isUserSpeaking, startListening, setPetsSpeaking } = useVoiceInput({
    onSpeechStart: () => {
        if (ttsStore.isPlaying) {
            stopTTS();                         // 立即停止音频播放
            websocket.sendVoiceInterrupt();    // 通知后端取消 LLM 任务
        }
    },
    onSpeechEnd: (audio, durationMs) => {
        if (durationMs < 300) return;        // 过滤咳嗽等极短噪声
        if (isCooldownActive()) return;      // TTS 结束后 500ms 冷却期
        websocket.sendVoiceAudio(audio);       // 发送 binary frame
    },
    onError: (msg) => console.error("[VoiceInput]", msg),
});

// ── TTS 播放状态同步到语音模块 ──
watch(() => ttsStore.isPlaying, (val) => {
    setPetsSpeaking(val);
    if (!val) onTTSEnd();  // TTS 结束触发冷却期
});

// ── 冷却期实现 ──
let cooldownTimer: ReturnType<typeof setTimeout> | null = null;
const COOLDOWN_MS = 500;

function onTTSEnd() {
    cooldownTimer = setTimeout(() => { cooldownTimer = null; }, COOLDOWN_MS);
}
function isCooldownActive(): boolean {
    return cooldownTimer !== null;
}

// ── WebSocket 语音结果回调 ──
websocket.onVoiceResult = (result) => {
    if (result.triggered) {
        isThinking.value = true;  // 显示思考动画，等待 chat_response
    }
    // triggered=false 时：完全静默，无任何可见操作
};

// ── 打断确认回调 ──
websocket.onInterrupted = () => {
    stopTTS();
    resetLipSync();  // 重置 Live2D 口型动画
    isPetsSpeaking.value = false;
    // isThinking 保持 true
};
```

### 10.2 `isThinking` 设置时机

| 流程 | `isThinking` 设置时机 | 清除时机 |
|------|---------------------|---------|
| 文字流程 | `sendMessage()` 内部设置 | 收到 `chat_response` |
| 语音流程 | 收到 `voice_result` 且 `triggered=true` 时设置 | 收到 `chat_response` |
| 打断后 | 保持 `true`（新语音处理中） | 新流程收到 `chat_response` 或窗口超时 |

### 10.3 语音功能开关

- 设置界面提供：**语音输入开关** + **对话窗口时长滑块（5~60 秒）**
- 关闭语音时：`stopListening()`，麦克风停止采集
- 开关状态通过 `configure` 消息同步到后端
- 语音关闭时不影响文字聊天功能

---

## 11. 模块文件布局

### 前端新增/修改

```
src/composables/
  useVoiceInput.ts          # 音频采集 + VAD（新增）
  useWebSocket.ts           # 修改：新增 sendVoiceAudio + sendVoiceInterrupt +
                            #       onVoiceResult + onInterrupted
```

### 后端新增

```
sidecar/
  voice/
    __init__.py
    stt_engine.py           # SenseVoice STT 封装
    text_sanitizer.py       # 文本消歧层
    interrupt_handler.py    # 打断 + 任务取消 + 状态清理
    conversation_context.py # 对话窗口管理（含 3s 预窗口）
    intent_filter.py        # 意图判断 + 人设接入
    window_quick_check.py   # 窗口内轻量规则（仅日志）
    processor.py            # 对外统一接口 VoiceProcessor
```

### 后端修改

```
sidecar/
  main.py                   # 修改：WebSocket 接收循环支持 binary frame
                            #       增加 voice_interrupt / interrupted 处理分支
                            #       用户 chat 消息时调用 on_user_interaction()
                            #       chat flow 完成后调用 on_pet_response_sent()
                            #       chat flow 开始时注册 LLM 任务
  ws/
    vision_speech.py        # 修改：LLM 生成完成后调用 open_pre_window()
                            #       发送完成后调用 on_pet_response_sent()
```

### 模型文件

```
models/
  sense-voice-small-int8/
    model.int8.onnx
    tokens.txt
```

---

## 12. 实施步骤

按"先打地基，后搭支架，再建楼层"的顺序推进。每步独立可验证。

| 步骤 | 模块 | 目标 | 验收标准 |
|------|------|------|---------|
| **Step 1** | `stt_engine.py` + 环境 | 验证 SenseVoice API，确认 emotion/lang 字段名 | 独立测试脚本：音频 → `{text, emotion, language}` |
| **Step 2** | `text_sanitizer.py` | 消歧层可用 | 单元测试："嗯"→True；"快看我"→False；乱码→True |
| **Step 3** | `conversation_context.py` | 窗口管理可用（含预窗口） | 单元测试：open/extend/close/pre_window 状态转换 |
| **Step 4** | `interrupt_handler.py` | 打断机制可用 | 单元测试：register → cancel → 确认 task 被取消；interrupted 消息发送 |
| **Step 5** | `intent_filter.py` | LLM 意图判断可用 | mock 人设数据测试："好累啊"→`[OK]`；"今晚出去吃饭"→`[NOT_FOR_ME]` |
| **Step 6** | `window_quick_check.py` | 轻量规则可用 | 单元测试："今晚吃饭吗"→"possible_external_conversation" |
| **Step 7** | `processor.py` + `main.py` 修改 | 后端完整语音链路可用 | 手动发送 binary frame → 验证完整流程 |
| **Step 8** | `useVoiceInput.ts` | 前端 VAD 采集可用 | 独立测试：麦克风→VAD→console 输出音频时长 |
| **Step 9** | `useWebSocket.ts` + 打断接线 | 前端打断可用 | TTS 播放时说话 → TTS 立即停止，后端 LLM 任务取消 |
| **Step 10** | App.vue 接线 + 前后端联调 | 端到端流程跑通 | 说话→STT→意图判断→LLM 回复→TTS 播放→窗口延续 |
| **Step 11** | 设置界面 | 用户可配置 | 语音开关、窗口时长滑块生效，配置同步到后端 |
| **Step 12** | `vision_speech.py` 衔接 | 视觉主动发言开启预窗口 | 桌宠 LLM 生成期间，用户语音直接视为回复 |

---

## 13. 附录 A：预留但未实装的设计

以下设计已确认需求，但本次开发不实装，待后续迭代：

### A.1 规则预过滤（`SKIP_PATTERNS`）

已确认本次不做。窗口外所有语音直接送 LLM 意图判断，不经过规则层。待 LLM 意图判断实测后，若发现特定误报模式可批量覆盖，再评估是否引入轻量规则层。

### A.2 Live2D 微表情反馈

已确认本次不做。待 Live2D 模型开发完成后，在以下时机接入：
- VAD 检测到说话但未触发回复 → 耳朵微动 / 头微偏
- `voice_result` triggered=true → 眼睛亮起来，进入"思考"表情
- `triggered=false` → 轻轻歪头困惑（"好像不是跟我说话"）

### A.3 延迟掩盖（语气词预播）

已确认本次不做。STT 完成后 LLM 生成期间桌宠保持静默。待 TTS 模块重构后，可配合预存语气词（"嗯~" / 吸气声）降低感知延迟。

### A.4 免唤醒窗口扩展触发条件

当前触发点：桌宠发言后、用户文字消息后。

后续可扩展：
- 桌宠主动提问后延长窗口
- 游戏事件后开启窗口
- 用户特定行为（如切换窗口、打开特定应用）后开启窗口

### A.5 情绪信息深入利用

当前 SenseVoice 输出的 `emotion` 仅透传至 `voice_result`，由项目现有情绪识别算法消费。

后续可考虑：
- 将用户情绪传入 LLM prompt（"用户看起来很开心，回应可以活泼些"）
- 用户情绪直接驱动 Live2D 表情（用户开心 → 桌宠也表现出开心）

### A.6 端侧轻量意图分类模型

若 LLM 意图判断在特定模型/网络环境下效果不稳定，可引入本地 Qwen2-0.5B-int4（~300MB）专做二分类，脱离主 LLM 的不可控因素。本次不实装，作为降级预案保留。

---

## 14. 附录 B：环形缓冲备用方案（详细记录）

### B.1 问题背景

`@ricky0123/vad-web` 的 `preSpeechPadFrames` 在 VAD 状态机从 SILENT → SPEECH 转换时回溯抓取历史帧，拼接在 speech 开头。但其回溯窗口是"触发点之前"的固定帧数，而非"用户实际开口前"的持续环形缓冲。

**实测风险**：如果用户说话极快且开头音量极低，VAD 可能延迟 3~5 帧才触发状态转换。此时 `preSpeechPadFrames=15` 能回溯的也只是"VAD 触发点之前"的音频，而"用户实际开口到 VAD 触发"之间的音频可能仍丢失。

### B.2 方案设计：前端持续环形缓冲 + 手动 VAD 帧处理

取代 `MicVAD` 便捷封装，前端自行维护音频处理管道：

```typescript
/**
 * 环形缓冲 + 手动 VAD 帧处理方案
 * 备用：若 preSpeechPadFrames=15 实测仍频繁丢失前几个字，启用此方案。
 */

const SAMPLE_RATE = 16000;
const RING_BUFFER_MS = 3000;                    // 3 秒环形缓冲
const RING_BUFFER_SAMPLES = (RING_BUFFER_MS / 1000) * SAMPLE_RATE;
const VAD_FRAME_SAMPLES = 512;                  // Silero VAD 每帧 512 samples
const POST_SPEECH_MS = 500;                     // 句尾追加缓冲
const POST_SPEECH_SAMPLES = (POST_SPEECH_MS / 1000) * SAMPLE_RATE;

class RingBufferVoiceInput {
    private ringBuffer: Float32Array;
    private ringWriteIdx: number = 0;
    private vadInstance: any;                   // Silero VAD ONNX 实例
    private isSpeechActive: boolean = false;
    private speechChunks: Float32Array[] = [];
    private postBuffer: Float32Array[] = [];
    
    constructor() {
        this.ringBuffer = new Float32Array(RING_BUFFER_SAMPLES);
    }
    
    async init() {
        // 加载 Silero VAD v5 ONNX 模型（非 MicVAD 封装）
        this.vadInstance = await SileroVAD.create();
        
        // 启动麦克风采集
        const stream = await navigator.mediaDevices.getUserMedia({
            audio: {
                echoCancellation: true,
                noiseSuppression: true,
                autoGainControl: true,
                sampleRate: SAMPLE_RATE,
                channelCount: 1,
            }
        });
        
        const audioContext = new AudioContext({ sampleRate: SAMPLE_RATE });
        const source = audioContext.createMediaStreamSource(stream);
        const processor = audioContext.createScriptProcessor(VAD_FRAME_SAMPLES, 1, 1);
        
        processor.onaudioprocess = (e) => {
            const frame = e.inputBuffer.getChannelData(0);
            this.processFrame(new Float32Array(frame));
        };
        
        source.connect(processor);
        processor.connect(audioContext.destination);
    }
    
    private processFrame(frame: Float32Array) {
        // 1. 写入环形缓冲
        for (let i = 0; i < frame.length; i++) {
            this.ringBuffer[this.ringWriteIdx] = frame[i];
            this.ringWriteIdx = (this.ringWriteIdx + 1) % RING_BUFFER_SAMPLES;
        }
        
        // 2. 喂给 VAD
        const prob = this.vadInstance.process(frame);
        
        // 3. 状态机转换
        if (!this.isSpeechActive && prob > 0.5) {
            // SILENT → SPEECH：捕获 ring buffer 作为 prefix
            this.isSpeechActive = true;
            this.speechChunks = [this.captureRingBuffer()];
            this.onSpeechStart();
        } else if (this.isSpeechActive && prob < 0.35) {
            // SPEECH → SILENT：进入尾部缓冲收集
            this.postBuffer.push(new Float32Array(frame));
            // 若尾部缓冲超过阈值，正式结束
            const postLen = this.postBuffer.reduce((s, c) => s + c.length, 0);
            if (postLen >= POST_SPEECH_SAMPLES) {
                this.finalizeSpeech();
            }
        } else if (this.isSpeechActive) {
            // 持续收集
            this.speechChunks.push(new Float32Array(frame));
        }
    }
    
    private captureRingBuffer(): Float32Array {
        // 按写入顺序从 ring buffer 提取最近 3 秒音频
        const result = new Float32Array(RING_BUFFER_SAMPLES);
        for (let i = 0; i < RING_BUFFER_SAMPLES; i++) {
            const idx = (this.ringWriteIdx + i) % RING_BUFFER_SAMPLES;
            result[i] = this.ringBuffer[idx];
        }
        return result;
    }
    
    private finalizeSpeech() {
        // 拼接：prefix ring buffer + speech chunks + post buffer
        const totalLen = this.speechChunks.reduce((s, c) => s + c.length, 0)
                       + this.postBuffer.reduce((s, c) => s + c.length, 0);
        
        const fullAudio = new Float32Array(totalLen);
        let offset = 0;
        
        for (const chunk of this.speechChunks) {
            fullAudio.set(chunk, offset);
            offset += chunk.length;
        }
        for (const chunk of this.postBuffer) {
            fullAudio.set(chunk, offset);
            offset += chunk.length;
        }
        
        const durationMs = (totalLen / SAMPLE_RATE) * 1000;
        this.onSpeechEnd(fullAudio, durationMs);
        
        // 重置状态
        this.isSpeechActive = false;
        this.speechChunks = [];
        this.postBuffer = [];
    }
    
    onSpeechStart() {
        // 触发打断：stopTTS() + sendVoiceInterrupt()
    }
    
    onSpeechEnd(audio: Float32Array, durationMs: number) {
        // 发送完整音频段（含 3s prefix + 实时 + 500ms postfix）
        // sendVoiceAudio(audio)
    }
}
```

### B.3 方案对比

| 维度 | MicVAD + preSpeechPadFrames=15 | 环形缓冲方案 |
|------|-------------------------------|-------------|
| 开发周期 | 1 天 | 3~5 天 |
| 前几个字丢失风险 | 中（VAD 触发延迟时） | 极低（3s prefix 覆盖） |
| 句尾吞音风险 | 低（redemptionFrames=10） | 极低（500ms postfix） |
| 代码复杂度 | 低（库封装） | 中（手动 AudioWorklet） |
| 内存占用 | 低 | 中（3s Float32 buffer ≈ 192KB） |
| 兼容性风险 | 低 | 中（需验证 ScriptProcessorNode / AudioWorklet） |

### B.4 启用条件

在 **Step 10（前后端联调）** 阶段实测以下指标：
- 快速说话（"快看我厉害吧"）前 2~3 个字丢失频率 > 20%
- 句尾吞音（以"呢"、"吧"、"啊"结尾）频率 > 10%

若满足任一条件，升级到环形缓冲方案。

---

*文档版本：v2.1 · 场景语义驱动版 · 2026-04-27*
