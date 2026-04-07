"""
prompt/messages.py — LLM messages 列表组装

包含：
  trim_history()                        — 滑动窗口裁剪
  build_messages()                      — 普通对话
  build_screenshot_messages()           — 用户主动截屏（VLM 中转后注入文字描述）
  build_multimodal_screenshot_messages() — 多模态直传（图片嵌入消息体）
  build_vision_speech_messages()        — 视觉感知主动发言

【本次重构要点】
  1. 移除 session_events 参数 — event 机制已废弃，记忆由 history+笔记本+向量库承担
  2. build_vision_speech_messages 新增：
     a. 过滤 history 中 _source=="vision_proactive" 的 assistant turn
        （切断视觉主动发言的自我强化循环）
     b. 防复读提示改为纯否定形式，不再回喂模型最近原话
"""

import logging
import re
import time
from typing import Optional

from .constants import WINDOW_PRESETS, DEFAULT_WINDOW_INDEX
from .system_prompt import (
    _build_memory_layer,
    _build_time_note,
    _HARD_CONSTRAINT,
)

logger = logging.getLogger(__name__)


# ── 视觉主动发言：模块级常量 ──────────────────────────────────────────────

# 操作状态标签（player_state → 事实描述，不包含行为指导）
_PLAYER_STATE_LABELS = {
    "playing":    "用户正在操作角色",
    "spectating": "画面中操作的不是用户（死亡回放/观战/队友视角）",
    "in_menu":    "用户在菜单/商店/设置界面",
    "cutscene":   "正在播放过场动画/剧情",
    "waiting":    "用户在等待（加载/匹配/复活等）",
}

# 场景方向引导（scene_type → 主动发言时 LLM 的方向提示）
# 注意：只引导"可以从什么方向说话"，不限制语气和用词，语气由角色定义决定
_SCENE_DIRECTIONS = {
    "game": (
        "你正在旁边看{address}玩游戏。可以从以下方向中选一个自然地说：\n"
        "- 对画面里具体发生的事做反应\n"
        "- 找个日常话题聊（吃什么、最近怎么样、接下来的安排）\n"
        "- 聊聊你记忆中知道的事\n"
        "- 表达你当前的心情\n"
        "选最自然的一个方向就好，不需要都覆盖。"
    ),
    "video": (
        "你注意到{address}在看视频。可以对画面内容做轻松反应，"
        "也可以找个话题聊聊，或者表达你的心情。"
    ),
    "work": (
        "你注意到{address}在工作。不要评论工作内容，"
        "可以关心一下（提醒休息、喝水），或者找个轻松话题聊几句。"
    ),
    "browsing": (
        "你注意到{address}在浏览网页。可以轻松地聊几句，"
        "找个话题，或者表达你的心情。"
    ),
    "idle": (
        "{address}好像不在屏幕前。你可以自言自语，表达等待的情绪，"
        "找个话题自己嘟囔几句，或者回忆点什么。"
    ),
}


# ── 滑动窗口裁剪 ──────────────────────────────────────────────────────────

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


# ── 内部辅助：组装完整 system 层 ──────────────────────────────────────────

def _build_full_system(
    system_prompt: str,
    character_id: str = "",
    character_name: str = "",
    relevant_summaries: Optional[list[str]] = None,
    *,
    append_hard_constraint: bool = True,
    extra_suffix: str = "",
) -> str:
    """
    将 Layer1 角色定义、记忆、时间注记拼接为完整 system 字符串。
    硬性约束始终追加到最末尾（Gemini recency bias 友好）。
    """
    memory_layer = _build_memory_layer(
        character_id=character_id,
        character_name=character_name,
        relevant_summaries=relevant_summaries or [],
    )
    time_note = _build_time_note()

    full = system_prompt
    if memory_layer:
        full += "\n\n" + memory_layer
    full += "\n\n" + time_note

    if extra_suffix:
        full += "\n\n" + extra_suffix
    if append_hard_constraint:
        full += "\n\n" + _HARD_CONSTRAINT
    return full


def _prepare_base(
    system_prompt: str,
    history: list[dict],
    window_index: int,
    character_id: str,
    character_name: str,
    relevant_summaries: Optional[list[str]],
    **full_system_kwargs,
) -> tuple[list[dict], str]:
    """
    公共流程：裁剪历史 + 构建完整 system + 返回 (messages_with_system_and_history, full_system_text)。
    """
    trimmed = trim_history(history, window_index)
    clean_history = [
        {"role": msg["role"], "content": msg["content"]}
        for msg in trimmed
    ]

    full_system = _build_full_system(
        system_prompt, character_id, character_name, relevant_summaries,
        **full_system_kwargs,
    )

    messages = [{"role": "system", "content": full_system}]
    messages.extend(clean_history)
    return messages, full_system


# ── 普通对话 ──────────────────────────────────────────────────────────────

def build_messages(
    system_prompt: str,
    history: list[dict],
    user_message: str,
    window_index: int = DEFAULT_WINDOW_INDEX,
    character_id: str = "",
    character_name: str = "",
    relevant_summaries: Optional[list[str]] = None,
) -> list[dict]:
    messages, _ = _prepare_base(
        system_prompt, history, window_index,
        character_id, character_name, relevant_summaries,
    )
    messages.append({"role": "user", "content": user_message})
    return messages


# ── 用户主动截屏（VLM 分析结果注入文字）─────────────────────────────────

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
    messages, _ = _prepare_base(
        system_prompt, history, window_index,
        character_id, character_name, relevant_summaries,
    )

    scene_type  = screenshot_info.get("scene_type", "unknown")
    desc        = screenshot_info.get("scene_description", "无法识别画面内容")
    game_name   = screenshot_info.get("game_name")
    game_genre  = screenshot_info.get("game_genre")
    confidence  = screenshot_info.get("confidence", "low")

    screen_parts = [f"【屏幕分析结果】场景：{scene_type}，{desc}"]
    if game_name:
        line = f"游戏：{game_name}"
        if game_genre:
            line += f"（{game_genre}）"
        screen_parts.append(line)
    screen_parts.append(f"置信度：{confidence}")

    combined_user_msg = f"{user_message}\n\n" + "\n".join(screen_parts)

    messages.append({"role": "user", "content": combined_user_msg})
    return messages


# ── 多模态截屏（图片直接嵌入消息体）────────────────────────────────────

def build_multimodal_screenshot_messages(
    system_prompt: str,
    history: list[dict],
    user_message: str,
    img_b64: str,
    window_title: str = "",
    window_index: int = DEFAULT_WINDOW_INDEX,
    character_id: str = "",
    character_name: str = "",
    relevant_summaries: Optional[list[str]] = None,
) -> list[dict]:
    messages, _ = _prepare_base(
        system_prompt, history, window_index,
        character_id, character_name, relevant_summaries,
    )

    observe_hint = f"（当前窗口：{window_title}）" if window_title else ""
    text_content = f"{user_message}\n\n请观察这张屏幕截图{observe_hint}，结合画面内容回复。"
    img_url = f"data:image/jpeg;base64,{img_b64}"

    messages.append({
        "role": "user",
        "content": [
            {"type": "text",      "text": text_content},
            {"type": "image_url", "image_url": {"url": img_url}},
        ],
    })
    return messages


# ── 视觉感知主动发言 ──────────────────────────────────────────────────────

def build_vision_speech_messages(
    system_prompt: str,
    trigger: dict,
    history: list[dict] = None,
    window_index: int = DEFAULT_WINDOW_INDEX,
    character_id: str = "",
    character_name: str = "",
    relevant_summaries: Optional[list[str]] = None,
) -> list[dict]:
    """
    构造视觉主动发言的 messages。

    【关键防复读机制】
      1. 不再接收/回喂 recent_speeches —— 给模型看自己说过的原话会成为
         强 few-shot 暗示，触发模型继续模仿那个模式（详见 DECISIONS.md）
      2. 过滤 history 中 _source=="vision_proactive" 的 assistant turn ——
         视觉主动发言彼此之间不相互引用，避免自我强化循环
      3. 普通对话路径仍然能在 history 里看到 vision 主动发言（不过滤），
         保证记忆联通
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
    address      = trigger.get("address", "用户")

    history = history or []

    vision_parts = []
    if ctx_prompt:
        vision_parts.append(ctx_prompt)

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
        label = _PLAYER_STATE_LABELS.get(player_state, "")
        if label:
            vision_parts.append(f"操作状态：{label}")

    if confidence == "high" and game_name:
        vision_parts.append("（你了解这个游戏，可以评论策略和机制）")
    elif confidence == "medium" and game_genre:
        vision_parts.append("（只评论画面能看到的内容，可基于游戏类型做通用评论）")
    else:
        vision_parts.append("（只做陪伴式评论，不假设具体游戏机制）")

    if instruction:
        vision_parts.append(instruction)

    direction_template = _SCENE_DIRECTIONS.get(
        scene_type,
        _SCENE_DIRECTIONS.get("idle" if reason == "idle_nudge" else "browsing"),
    )
    if direction_template:
        vision_parts.append(f"\n{direction_template.format(address=address)}")

    # 【防复读：纯否定提示，不回喂原话】
    # 之前的实现是把 recent_speeches 的具体内容拼进 prompt，这会成为
    # 强 few-shot 暗示，反而引发模型模仿。改为不暴露任何原话。
    vision_parts.append(
        "\n【表达提示】这是你的主动发言。如果当前画面没有真正值得说的新内容，"
        "或者你刚刚已经说过类似的话了，可以直接只输出「……」三个字。"
        "不要为了说话而说话，不要重复刚说过的话题。"
    )

    vision_context = "\n".join(vision_parts)

    clean_system_prompt = re.sub(
        r'\n【屏幕观察】[^\n]*\[NEED_SCREENSHOT\][^\n]*',
        '',
        system_prompt,
    )

    personality_reminder = (
        "【重要提醒】你是有性格的角色，始终保持开头定义的性格和说话风格。"
        "用自己的语气说话。禁超50字。只输出角色的话。"
    )

    full_system = _build_full_system(
        clean_system_prompt,
        character_id,
        character_name,
        relevant_summaries,
        append_hard_constraint=False,
        extra_suffix=vision_context + "\n\n" + personality_reminder,
    )

    messages = [{"role": "system", "content": full_system}]

    # 【防自我强化：过滤掉 history 中其他 vision_proactive 的 assistant turn】
    # 普通对话路径不做这个过滤，那里的 build_messages 仍然能读到完整 history
    if history:
        trimmed = trim_history(history, window_index)
        clean = []
        filtered_count = 0
        for m in trimmed:
            # 跳过其他视觉主动发言（带 _source 标记的 assistant 消息）
            if m.get("role") == "assistant" and m.get("_source") == "vision_proactive":
                filtered_count += 1
                continue
            clean.append({"role": m["role"], "content": m["content"]})
        if filtered_count > 0:
            logger.debug(
                "[VisionSpeech] history 已过滤 %d 条历史 vision 主动发言（防自我强化）",
                filtered_count,
            )
        messages.extend(clean)

    messages.append({
        "role": "user",
        "content": "（桌宠内心活动：想主动说点什么）",
    })

    return messages