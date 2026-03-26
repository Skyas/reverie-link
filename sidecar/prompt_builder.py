"""
Prompt 组装模块（改进版，直接替换原 prompt_builder.py）

改进点：
  1. build_vision_speech_messages 改为 v2 版本：
     - 注入最近对话历史（消除主动发言时的"失忆"）
     - 防重复机制（传入最近发言，指令 AI 不要重复）
     - 视觉上下文独立注入（不再和角色定义挤在一条 system 里）
     - 触发消息随机化（打破固定回复模式）
     - 融入 activity_context（用户活动状态）
     - 融入 player_state（区分用户在操作还是观战）
  2. 原有函数（build_system_prompt / trim_history / build_messages /
     build_screenshot_messages / _build_memory_layer）保持不变
"""

import random
import time
import sys
import os
# 允许从 prompt_builder 访问 memory 模块（两者同在 sidecar/ 下）
_SIDECAR_DIR = os.path.dirname(os.path.abspath(__file__))
if _SIDECAR_DIR not in sys.path:
    sys.path.insert(0, _SIDECAR_DIR)
from datetime import datetime
from typing import Optional


# ── 默认角色模板（与 SettingsApp.vue 的 DEFAULT_PRESET 保持一致）──────────
DEFAULT_CHARACTER = {
    "name": "Rei",
    "identity": "你是用户身边的猫娘伙伴，平时住在一起",
    "personality": "傲娇，表面高冷不在乎，实际上很在意用户，被关心时会别扭地否认，偶尔情绪激动时会不自觉说出一个「喵」",
    "address": "你",
    "style": "简短干脆，傲娇别扭，不会主动示好但会用绕弯子的方式表达关心，被夸会立刻否认，偶尔一个字的「喵」，绝对不叠用",
    "examples": [
        {
            "user": "今天辛苦了",
            "char": "哼，谁要你说这种话。……自己注意点身体就行了。[sad]"
        },
        {
            "user": "你在担心我吗？",
            "char": "想什么呢。只是觉得你这样下去会给我添麻烦而已。[angry]"
        },
        {
            "user": "你真可爱",
            "char": "……闭嘴。说什么蠢话。喵。[shy]"
        }
    ]
}


# ── 5 档滑动窗口配置 ──────────────────────────────────────────────────────
# 每档：(档位名称, 时间窗口秒数, 最大轮数)
# 「轮数」指对话轮，1 轮 = 1 条 user + 1 条 assistant，故 history 条目数 = 轮数 × 2
WINDOW_PRESETS = [
    ("极速省流",    3 * 60,   5),   # index 0
    ("均衡（默认）", 8 * 60,  12),  # index 1  ← 默认
    ("沉浸",       15 * 60,  20),   # index 2
    ("深度",       20 * 60,  28),   # index 3
    ("极限",       25 * 60,  35),   # index 4
]

DEFAULT_WINDOW_INDEX = 1  # 均衡档


# ── 主动发言触发短语池（改进：随机化，打破 LLM 固定回复模式）────────────

_TRIGGER_GAME_PHRASES = [
    "你看到画面上发生了什么？用你的方式说几句。",
    "刚才画面里好像有点意思，你怎么看？",
    "你一直在旁边看着呢，说说你观察到的。",
    "对刚才屏幕上的内容，有什么想法？",
    "画面有变化，随便聊聊你看到的。",
    "有什么想吐槽的吗？",
    "你觉得刚才那波怎么样？",
]

_TRIGGER_IDLE_PHRASES = [
    "好安静啊，你想说点什么吗？",
    "已经好一会儿没动静了，你在想什么？",
    "有点无聊了吧？",
    "你还在吗？",
    "好像很久没动了呢。",
]

_TRIGGER_GENERAL_PHRASES = [
    "你注意到什么了吗？随便说说。",
    "你在旁边看了一会儿了，有什么想说的？",
    "说说你的感受吧。",
    "有什么想说的吗？",
]


# ══════════════════════════════════════════════════════════════════
# 以下函数与原版完全一致，未做任何改动
# ══════════════════════════════════════════════════════════════════


def build_system_prompt(character: dict) -> str:
    """
    Layer 1：将角色模板字段组装为 System Prompt。
    Layer 2（记忆注入）在 Phase 3 后续步骤接入，此处预留位置。
    """
    name        = character.get("name", "Assistant")
    identity    = character.get("identity", "")
    personality = character.get("personality", "")
    address     = character.get("address", "你")
    style       = character.get("style", "")
    examples    = character.get("examples", [])

    prompt_parts = []

    # ── 角色核心定义 ──────────────────────────────────────────
    prompt_parts.append(
        f"你现在扮演「{name}」，{identity}。\n"
        f"性格：{personality}\n"
        f"称呼用户为：{address}\n"
        f"说话风格：{style}"
    )

    # ── 对话示例（few-shot，仅在用户填写时注入）──────────────
    if examples:
        prompt_parts.append("\n【对话示例】")
        for ex in examples:
            prompt_parts.append(
                f"{address}：{ex.get('user', '')}\n"
                f"{name}：{ex.get('char', '')}"
            )

    # ── 情绪标签规则 ──────────────────────────────────────────
    prompt_parts.append(
        "\n【情感表达】根据当前回复的情感，在回复句末加入且仅加入一个情绪标签，"
        "从以下选项中选择最贴切的一个：\n"
        "[happy]开心高兴 / [sad]难过伤心 / [angry]生气不满 / "
        "[shy]害羞脸红 / [surprised]惊讶吃惊 / [sigh]叹气无奈 / [neutral]平静默认\n"
        "严格只使用以上7个标签，不要自创其他标签。\n"
        "例如：「哼，谁要你说这种话。[angry]」"
    )

    # ── 截屏意图识别指令（Phase 3 视觉感知）─────────────────
    prompt_parts.append(
        "\n【屏幕观察】当你判断用户希望你观察屏幕画面时，"
        "在回复的最开头输出 [NEED_SCREENSHOT] 标签（仅此一个标签，无需其他解释）。"
    )

    # ── 硬性约束（始终在最后，防止被覆盖）───────────────────
    prompt_parts.append(
        "\n【重要限制】这是一段语音对话场景。"
        "请用极其简短、口语化的句子回复，严禁超过50个字（情绪标签不计入字数）。"
        "只输出角色说的话，不要输出任何说明、括号内的动作描述或思考过程。"
    )

    return "\n".join(prompt_parts)


def trim_history(
    history: list[dict],
    window_index: int = DEFAULT_WINDOW_INDEX,
) -> list[dict]:
    """
    对带时间戳的扩展 history 执行「时间窗口 + 轮数」交集裁剪。
    """
    idx = max(0, min(window_index, len(WINDOW_PRESETS) - 1))
    _, time_window_seconds, max_rounds = WINDOW_PRESETS[idx]
    max_items = max_rounds * 2

    now = time.time()
    cutoff = now - time_window_seconds

    time_filtered = [msg for msg in history if msg.get("timestamp", 0) >= cutoff]
    trimmed = time_filtered[-max_items:] if len(time_filtered) > max_items else time_filtered

    return trimmed


def build_messages(
    system_prompt: str,
    history: list[dict],
    user_message: str,
    window_index: int = DEFAULT_WINDOW_INDEX,
    character_id: str = "",
    character_name: str = "",
    relevant_summaries: Optional[list[str]] = None,
) -> list[dict]:
    """
    组装完整的 messages 列表传给 LLM API。
    """
    trimmed = trim_history(history, window_index)

    clean_history = [
        {"role": msg["role"], "content": msg["content"]}
        for msg in trimmed
    ]

    memory_layer = _build_memory_layer(
        character_id=character_id,
        character_name=character_name,
        relevant_summaries=relevant_summaries or [],
    )

    time_note = _build_time_note()

    full_system = system_prompt + "\n\n" + time_note
    if memory_layer:
        full_system += "\n\n" + memory_layer

    messages = [{"role": "system", "content": full_system}]
    messages.extend(clean_history)
    messages.append({"role": "user", "content": user_message})
    return messages


def build_screenshot_messages(
    system_prompt: str,
    history: list[dict],
    user_message: str,
    screenshot_info: dict,
    window_index: int = DEFAULT_WINDOW_INDEX,
    character_id: str = "",
    character_name: str = "",
    relevant_summaries: Optional[list[str]] = None,
) -> list[dict]:
    """
    用户主动请求观察屏幕时，将截图分析结果注入对话上下文后重新组装 messages。
    """
    trimmed = trim_history(history, window_index)
    clean_history = [
        {"role": msg["role"], "content": msg["content"]}
        for msg in trimmed
    ]

    memory_layer = _build_memory_layer(
        character_id=character_id,
        character_name=character_name,
        relevant_summaries=relevant_summaries or [],
    )

    time_note = _build_time_note()

    full_system = system_prompt + "\n\n" + time_note
    if memory_layer:
        full_system += "\n\n" + memory_layer

    scene_type  = screenshot_info.get("scene_type", "unknown")
    desc        = screenshot_info.get("scene_description", "无法识别画面内容")
    game_name   = screenshot_info.get("game_name")
    game_genre  = screenshot_info.get("game_genre")
    confidence  = screenshot_info.get("confidence", "low")

    screen_ctx_parts = [f"【屏幕分析结果】\n场景：{scene_type}，{desc}"]
    if game_name:
        line = f"游戏：{game_name}"
        if game_genre:
            line += f"（{game_genre}）"
        screen_ctx_parts.append(line)
    screen_ctx_parts.append(f"置信度：{confidence}")
    screen_context = "\n".join(screen_ctx_parts)

    combined_user_msg = f"{user_message}\n\n{screen_context}"

    messages = [{"role": "system", "content": full_system}]
    messages.extend(clean_history)
    messages.append({"role": "user", "content": combined_user_msg})
    return messages


def _build_memory_layer(
    character_id: str,
    character_name: str,
    relevant_summaries: list[str],
) -> str:
    """
    构建 Layer 2 记忆注入文本。
    """
    parts = []
    name = character_name or "你"

    try:
        from memory.db_notebook import get_all_entries
        from memory.models import NotebookSource

        entries = get_all_entries(character_id=character_id)
        if entries:
            lines = []
            for e in entries:
                if e.source == NotebookSource.MANUAL:
                    lines.append(f"· {e.content}（来自：我的备忘录）")
                else:
                    lines.append(f"· {e.content}")
            parts.append(f"【{name}的核心记忆】\n" + "\n".join(lines))
    except Exception:
        pass

    if relevant_summaries:
        lines = [f"· {s}" for s in relevant_summaries]
        parts.append(f"【{name}的回忆片段】\n" + "\n".join(lines))

    return "\n\n".join(parts)


def _build_time_note() -> str:
    """构建当前时间字符串（提取为公共函数，避免重复）"""
    _weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    _now = datetime.now()
    _time_str = _now.strftime("%Y-%m-%d %H:%M") + f"（{_weekdays[_now.weekday()]}）"
    return f"【当前时间】{_time_str}"


# ══════════════════════════════════════════════════════════════════
# 以下是改进的视觉发言函数
# ══════════════════════════════════════════════════════════════════


def build_vision_speech_messages(
    system_prompt: str,
    trigger: dict,
    recent_speeches: list[str] = None,
    history: list[dict] = None,
    window_index: int = DEFAULT_WINDOW_INDEX,
    character_id: str = "",
    character_name: str = "",
    relevant_summaries: Optional[list[str]] = None,
) -> list[dict]:
    """
    为视觉感知主动发言组装 LLM messages（改进版，替换原同名函数）。

    相比原版的改进：
      1. 注入最近对话历史 → AI 知道上下文，不会断裂
      2. 传入 recent_speeches → 防重复
      3. 视觉上下文独立注入 → 不被角色定义淹没
      4. 触发消息随机化 → 打破固定回复模式
      5. 融入 activity_context 和 player_state

    新增参数（都有默认值，向后兼容原有调用）：
      recent_speeches:    最近 3-5 条桌宠主动发言的内容
      history:            当前会话的对话历史
      window_index:       历史裁剪档位
      character_id/name:  用于记忆注入
      relevant_summaries: 向量记忆检索结果

    trigger 格式（来自 VisionSystem._check_speech）：
      {
        "reason":         "interest_threshold" | "silence_fallback" | "idle_nudge",
        "context_prompt": str,
        "scene_info":     {
          "scene_type": str,
          "scene_description": str,
          "game_name": str | None,
          "game_genre": str | None,
          "confidence": str,
          "scene_instruction": str,
          "activity_context": str,       # 改进：用户活动状态
          "player_state": str,           # 改进：playing|spectating|in_menu|...
        },
        "session_id":    str,
        "character_id":  str,
      }
    """
    scene_info   = trigger.get("scene_info", {})
    ctx_prompt   = trigger.get("context_prompt", "")
    reason       = trigger.get("reason", "interest_threshold")
    scene_type   = scene_info.get("scene_type", "unknown")
    game_name    = scene_info.get("game_name")
    game_genre   = scene_info.get("game_genre")
    confidence   = scene_info.get("confidence", "low")
    instruction  = scene_info.get("scene_instruction", "")
    desc         = scene_info.get("scene_description", "")
    activity_ctx = scene_info.get("activity_context", "")
    player_state = scene_info.get("player_state", "unknown")

    recent_speeches = recent_speeches or []
    history = history or []

    # ================================================================
    # 第一层 system：角色定义 + 时间 + 记忆
    # （和普通对话用的 system prompt 一样，保持人格一致性）
    # ================================================================

    memory_layer = _build_memory_layer(
        character_id=character_id,
        character_name=character_name,
        relevant_summaries=relevant_summaries or [],
    )

    time_note = _build_time_note()

    full_system = system_prompt + "\n\n" + time_note
    if memory_layer:
        full_system += "\n\n" + memory_layer

    # ================================================================
    # 第二层：视觉上下文（独立构建，后面决定怎么注入）
    #
    # 为什么不直接塞进 full_system？
    # 因为 LLM 对超长 system prompt 中间段落的注意力最弱，
    # 视觉信息放中间容易被忽略。独立注入可以确保 LLM 在
    # 生成回复前最后读到的就是画面信息。
    # ================================================================

    vision_parts = []

    # ── 画面观测摘要（事件缓冲池输出）─────────────────────────
    if ctx_prompt:
        vision_parts.append(ctx_prompt)

    # ── 场景信息 ─────────────────────────────────────────────
    vision_parts.append("【当前场景】")
    if game_name:
        line = f"正在玩：{game_name}"
        if game_genre:
            line += f"（{game_genre}）"
        vision_parts.append(line)
    if desc:
        vision_parts.append(f"画面：{desc}")
    if activity_ctx:
        vision_parts.append(f"用户状态：{activity_ctx}")
    if player_state and player_state != "unknown":
        _player_state_labels = {
            "playing":    "用户正在操作自己的角色",
            "spectating": "用户正在观看他人（死亡回放/队友视角/观战）",
            "in_menu":    "用户在菜单/商店/设置界面",
            "cutscene":   "正在播放过场动画/剧情",
            "waiting":    "用户在等待（加载/匹配/复活）",
        }
        label = _player_state_labels.get(player_state, "")
        if label:
            vision_parts.append(f"操作状态：{label}")

    # ── 认知置信度约束 ───────────────────────────────────────
    if confidence == "high" and game_name:
        vision_parts.append("（你了解这个游戏，可以评论策略和机制）")
    elif confidence == "medium" and game_genre:
        vision_parts.append("（只评论画面里能看到的内容，可以基于游戏类型做通用评论）")
    else:
        vision_parts.append("（只做基础陪伴式评论，不假设具体游戏机制）")

    # ── 场景行为指令 ─────────────────────────────────────────
    if instruction:
        vision_parts.append(f"\n{instruction}")

    # ── 防重复指令 ───────────────────────────────────────────
    if recent_speeches:
        recent_text = " / ".join(f"「{s[:30]}」" for s in recent_speeches[-3:])
        vision_parts.append(
            f"\n【防重复】你最近说过这些话：{recent_text}\n"
            f"这次必须说完全不同的内容，用不同的句式和切入点。"
            f"如果画面确实没什么新变化值得说，"
            f"你可以选择只回复一个语气词（如「嗯。」「哦。」）"
            f"或者干脆不说话（回复「……」）。"
        )

    # ── 发言风格指令 ─────────────────────────────────────────
    if scene_type == "game":
        # 根据 player_state 调整评论方向
        if player_state == "spectating":
            vision_parts.append(
                "\n【发言风格】画面里不是用户在操作。"
                "不要说'你打得好'之类的话——不是他在打。"
                "可以评论画面中正在发生的事，或者关心一下用户的状况。"
            )
        elif player_state == "in_menu":
            vision_parts.append(
                "\n【发言风格】用户在看菜单/商店界面。"
                "可以对装备或选择发表看法，也可以不说话。"
            )
        elif player_state == "waiting":
            vision_parts.append(
                "\n【发言风格】用户在等待（加载/匹配/复活）。"
                "可以闲聊几句，不用评论画面。"
            )
        elif player_state == "cutscene":
            vision_parts.append(
                "\n【发言风格】正在播放过场动画/剧情。"
                "可以对剧情做反应，但不要说太多打断观看。"
            )
        else:
            # playing 或 unknown
            vision_parts.append(
                "\n【发言风格】你是坐在旁边一起看的朋友。"
                "像看直播弹幕那样反应——"
                "有时一个字的感叹，有时吐槽一句，有时分析两句战况。"
                "绝对不要说'你在玩xx呢''加油''好厉害'这种空话。"
                "必须针对画面里具体发生的事情说话。"
            )
    elif scene_type == "idle" or reason == "idle_nudge":
        vision_parts.append(
            "\n【发言风格】你在自言自语或表达等待。"
            "不需要每次都问用户在不在——有时只是叹口气，"
            "有时自顾自嘟囔几句。"
        )

    vision_context = "\n".join(vision_parts)

    # ================================================================
    # 组装最终 messages
    # ================================================================

    messages = [{"role": "system", "content": full_system}]

    # ── 改进 1：注入最近对话历史 ─────────────────────────────
    # 让 AI 知道上下文，不会每次主动发言都"失忆"
    # 只取最近 4 轮（8 条），保持连贯性即可
    if history:
        trimmed = trim_history(history, window_index)
        recent_history = trimmed[-8:]
        clean = [{"role": m["role"], "content": m["content"]} for m in recent_history]
        messages.extend(clean)

    # ── 改进 2：视觉上下文作为独立 system 消息注入 ────────────
    # 放在历史之后、触发消息之前，确保 AI 最后读到的是画面信息
    #
    # 注意：不是所有 API 都支持多条 system 消息。
    # 如果你的 LLM API 不支持，把下面这行改为：
    #   messages[0]["content"] += "\n\n" + vision_context
    # 即追加到第一条 system 消息末尾。
    messages.append({"role": "system", "content": vision_context})

    # ── 改进 3：触发消息随机化 ───────────────────────────────
    # 原来固定用"（请根据上述屏幕内容…）"，AI 每次都以相同模式回复
    # 现在从短语池中随机选一个，打破固定模式
    if scene_type == "game":
        trigger_phrase = random.choice(_TRIGGER_GAME_PHRASES)
    elif scene_type == "idle" or reason == "idle_nudge":
        trigger_phrase = random.choice(_TRIGGER_IDLE_PHRASES)
    else:
        trigger_phrase = random.choice(_TRIGGER_GENERAL_PHRASES)

    messages.append({"role": "user", "content": trigger_phrase})

    return messages