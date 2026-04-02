"""
prompt/messages.py — LLM messages 列表组装

包含：
  trim_history()                        — 滑动窗口裁剪
  build_messages()                      — 普通对话
  build_screenshot_messages()           — 用户主动截屏（VLM 中转后注入文字描述）
  build_multimodal_screenshot_messages() — 多模态直传（图片嵌入消息体）
  build_vision_speech_messages()        — 视觉感知主动发言
"""

import re
import random
import time
from typing import Optional

from .constants import WINDOW_PRESETS, DEFAULT_WINDOW_INDEX
from .constants import (
    _TRIGGER_GAME_PHRASES,
    _TRIGGER_IDLE_PHRASES,
    _TRIGGER_GENERAL_PHRASES,
)
from .system_prompt import _build_memory_layer, _build_time_note


# ── 滑动窗口裁剪 ──────────────────────────────────────────────────────────
def trim_history(
    history: list[dict],
    window_index: int = DEFAULT_WINDOW_INDEX,
) -> list[dict]:
    """
    对带时间戳的扩展 history 执行「时间窗口 + 轮数」交集裁剪。

    两个条件取交集：
      - 时间窗口：丢弃 N 分钟前的消息
      - 最大轮数：限制 Token 上限
    这样既防止高频聊天爆 Token，又确保旧消息不占用上下文。
    """
    idx = max(0, min(window_index, len(WINDOW_PRESETS) - 1))
    _, time_window_seconds, max_rounds = WINDOW_PRESETS[idx]
    max_items = max_rounds * 2  # 1 轮 = 1 user + 1 assistant

    now = time.time()
    cutoff = now - time_window_seconds

    time_filtered = [msg for msg in history if msg.get("timestamp", 0) >= cutoff]
    trimmed = time_filtered[-max_items:] if len(time_filtered) > max_items else time_filtered

    return trimmed


# ── 内部辅助：组装 system 层（角色定义 + 时间 + 记忆）────────────────────
def _build_full_system(
    system_prompt: str,
    character_id: str = "",
    character_name: str = "",
    relevant_summaries: Optional[list[str]] = None,
) -> str:
    """将 Layer1 角色定义、时间注记、Layer2 记忆拼接为完整 system 字符串。"""
    memory_layer = _build_memory_layer(
        character_id=character_id,
        character_name=character_name,
        relevant_summaries=relevant_summaries or [],
    )
    time_note = _build_time_note()

    full = system_prompt + "\n\n" + time_note
    if memory_layer:
        full += "\n\n" + memory_layer
    return full


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
    """
    组装完整的 messages 列表传给 LLM API（普通文字对话路径）。
    """
    trimmed = trim_history(history, window_index)
    clean_history = [
        {"role": msg["role"], "content": msg["content"]}
        for msg in trimmed
    ]

    full_system = _build_full_system(
        system_prompt, character_id, character_name, relevant_summaries
    )

    messages = [{"role": "system", "content": full_system}]
    messages.extend(clean_history)
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
    """
    用户主动请求观察屏幕时，将截图分析结果（文字描述）注入对话上下文后组装 messages。
    适用于主模型不支持多模态的情况（由 VLM 先分析，再把描述文字传入这里）。
    """
    trimmed = trim_history(history, window_index)
    clean_history = [
        {"role": msg["role"], "content": msg["content"]}
        for msg in trimmed
    ]

    full_system = _build_full_system(
        system_prompt, character_id, character_name, relevant_summaries
    )

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
    """
    多模态截屏消息：图片以 base64 方式直接嵌入 LLM 消息，跳过 VLM 中转。
    仅在主模型支持多模态（如 GPT-4o / Claude 3.5）时使用，省去一次 VLM 调用。
    """
    trimmed = trim_history(history, window_index)
    clean_history = [
        {"role": msg["role"], "content": msg["content"]}
        for msg in trimmed
    ]

    full_system = _build_full_system(
        system_prompt, character_id, character_name, relevant_summaries
    )

    observe_hint = f"（当前窗口：{window_title}）" if window_title else ""
    text_content = f"{user_message}\n\n请观察这张屏幕截图{observe_hint}，结合画面内容回复。"
    img_url = f"data:image/jpeg;base64,{img_b64}"

    messages = [{"role": "system", "content": full_system}]
    messages.extend(clean_history)
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
    recent_speeches: list[str] = None,
    history: list[dict] = None,
    window_index: int = DEFAULT_WINDOW_INDEX,
    character_id: str = "",
    character_name: str = "",
    relevant_summaries: Optional[list[str]] = None,
) -> list[dict]:
    """
    为视觉感知主动发言组装 LLM messages。

    改进点（相比最初版本）：
      1. 注入最近对话历史 → AI 知道上下文，不会每次主动发言都"失忆"
      2. 传入 recent_speeches → 防重复
      3. 视觉上下文作为独立 system 消息注入（放在历史之后，确保 LLM 最后读到画面）
      4. 触发消息随机化 → 打破固定回复模式
      5. 融入 activity_context 和 player_state

    trigger 格式（来自 VisionSystem._check_speech）：
      {
        "reason":         "interest_threshold" | "silence_fallback" | "idle_nudge",
        "context_prompt": str,
        "scene_info":     {
          "scene_type":        str,
          "scene_description": str,
          "game_name":         str | None,
          "game_genre":        str | None,
          "confidence":        str,
          "scene_instruction": str,
          "activity_context":  str,
          "player_state":      str,   # playing|spectating|in_menu|cutscene|waiting|unknown
        },
        "session_id":   str,
        "character_id": str,
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
    history         = history or []

    # ── 第一层 system：角色定义 + 时间 + 记忆 ────────────────────────
    # 和普通对话使用相同的 system prompt，保持人格一致性。
    # 主动发言时移除 [NEED_SCREENSHOT] 相关指令（桌宠自己在看屏幕，该指令无意义）。
    full_system = _build_full_system(
        system_prompt, character_id, character_name, relevant_summaries
    )
    full_system = re.sub(
        r'\n【屏幕观察】.*?\[NEED_SCREENSHOT\].*?。',
        '',
        full_system,
        flags=re.DOTALL,
    )

    # ── 第二层：视觉上下文（独立构建） ───────────────────────────────
    # 为什么不直接塞进 full_system？
    # LLM 对超长 system prompt 中间段落的注意力最弱，
    # 放在历史之后、触发消息之前可确保 LLM 最后读到的是画面信息。
    vision_parts = []

    # 画面观测摘要（事件缓冲池输出）
    if ctx_prompt:
        vision_parts.append(ctx_prompt)

    # 场景信息
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
            "spectating": "用户正在观看他人（死亡回放/队友视角/观战等）",
            "in_menu":    "用户在菜单/商店/设置界面",
            "cutscene":   "正在播放过场动画/剧情",
            "waiting":    "用户在等待（加载/匹配/复活/队友操作/对手操作等）",
        }
        label = _player_state_labels.get(player_state, "")
        if label:
            vision_parts.append(f"操作状态：{label}")

    # 认知置信度约束
    if confidence == "high" and game_name:
        vision_parts.append("（你了解这个游戏，可以评论策略和机制）")
    elif confidence == "medium" and game_genre:
        vision_parts.append("（只评论画面里能看到的内容，可以基于游戏类型做通用评论）")
    else:
        vision_parts.append("（只做基础陪伴式评论，不假设具体游戏机制）")

    # 场景行为指令
    if instruction:
        vision_parts.append(f"\n{instruction}")

    # 防重复指令
    if recent_speeches:
        recent_text = " / ".join(f"「{s[:30]}」" for s in recent_speeches[-3:])
        vision_parts.append(
            f"\n【防重复】你最近说过这些话：{recent_text}\n"
            f"这次必须说完全不同的内容，用不同的句式和切入点。"
            f"如果画面确实没什么新变化值得说，"
            f"你可以选择只回复一个语气词（如「嗯。」「哦。」）"
            f"或者干脆不说话（回复「……」）。"
        )

    # 发言风格指令（按场景分支）
    if scene_type == "game":
        _game_style_map = {
            "spectating": (
                "\n【发言风格】画面里不是用户在操作。"
                "不要说'你打得好'之类的话——不是他在打。"
                "可以评论画面中正在发生的事，或者关心一下用户的状况。"
            ),
            "in_menu": (
                "\n【发言风格】用户在看菜单/商店界面。"
                "可以对装备或选择发表看法，也可以不说话。"
            ),
            "waiting": (
                "\n【发言风格】用户在等待（加载/匹配/复活）。"
                "可以闲聊几句，不用评论画面。"
            ),
            "cutscene": (
                "\n【发言风格】正在播放过场动画/剧情。"
                "可以对剧情做反应，但不要说太多打断观看。"
            ),
        }
        style_text = _game_style_map.get(
            player_state,
            # playing 或 unknown 默认
            "\n【发言风格】你是坐在旁边一起看的朋友。"
            "像看直播弹幕那样反应——"
            "有时一个字的感叹，有时吐槽一句，有时分析两句战况。"
            "绝对不要说'你在玩xx呢''加油''好厉害'这种空话。"
            "必须针对画面里具体发生的事情说话。"
        )
        vision_parts.append(style_text)
    elif scene_type == "idle" or reason == "idle_nudge":
        vision_parts.append(
            "\n【发言风格】你在自言自语或表达等待。"
            "不需要每次都问用户在不在——有时只是叹口气，"
            "有时自顾自嘟囔几句。"
        )

    vision_context = "\n".join(vision_parts)

    # ── 组装最终 messages ────────────────────────────────────────────
    messages = [{"role": "system", "content": full_system}]

    # 注入最近对话历史（让 AI 知道上下文，最多取最近 4 轮 / 8 条）
    if history:
        trimmed = trim_history(history, window_index)
        recent_history = trimmed[-8:]
        clean = [{"role": m["role"], "content": m["content"]} for m in recent_history]
        messages.extend(clean)

    # 视觉上下文作为独立 system 消息（放在历史之后，确保 LLM 最后读到画面信息）
    # 注意：不是所有 API 都支持多条 system 消息。
    # 如果你的 LLM API 不支持，可改为追加到 messages[0]["content"] 末尾。
    messages.append({"role": "system", "content": vision_context})

    # 触发消息随机化（打破固定回复模式）
    if scene_type == "game":
        trigger_phrase = random.choice(_TRIGGER_GAME_PHRASES)
    elif scene_type == "idle" or reason == "idle_nudge":
        trigger_phrase = random.choice(_TRIGGER_IDLE_PHRASES)
    else:
        trigger_phrase = random.choice(_TRIGGER_GENERAL_PHRASES)

    messages.append({"role": "user", "content": trigger_phrase})

    return messages