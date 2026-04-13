"""
prompt/messages.py — LLM messages 列表组装

包含：
  trim_history()                        — 滑动窗口裁剪
  build_messages()                      — 普通对话
  build_screenshot_messages()           — 用户主动截屏（VLM 中转后注入文字描述）
  build_multimodal_screenshot_messages() — 多模态直传（图片嵌入消息体）
  build_vision_speech_messages()        — 视觉感知主动发言

【2026-04-13 修改】
  ★ 重新引入 history 过滤（与避免重复区配套）
    上一版尝试"history 完整保留 + 系统末尾避免重复区"双管齐下，
    实测发现：避免重复区作为 system 内的负向约束，敌不过 history 里
    同名 assistant turn 给自回归模型的延续诱导（最近的 assistant
    消息是模型最强的延续信号）。日志中 #4#5 同一句长度 13 的台词
    背靠背出现 → 第三轮再次复读，就是这条诱导链路的铁证。

    新方案 = 避免重复区（信息保留）+ history 过滤（诱导消除）：
      · 避免重复区在 system 末尾告诉模型"你刚说过 A B C"
      · history 里不再以 assistant role 形式呈现这些话
      · 两者必须配套，缺一不可

    _source 标记继续写入 —— 既供避免重复区扫描，未来从 DB 重建
    history 时也作为还原依据。

【2026-04-09 修改】
  ★ 补 print 临时日志，前缀 [PromptBuild]
    —— 待统一整改 logging 后改为 logger.xxx
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

# 「避免重复区」扫描窗口（秒）
# 10 分钟覆盖密集复读场景，又不会让 prompt 膨胀到不可控
_AVOID_REPEAT_WINDOW_SECONDS = 600


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
    messages, full_system = _prepare_base(
        system_prompt, history, window_index,
        character_id, character_name, relevant_summaries,
    )
    messages.append({"role": "user", "content": user_message})

    print(
        f"[PromptBuild] build_messages | history_in={len(history)} "
        f"messages_out={len(messages)} system_len={len(full_system)} "
        f"user_len={len(user_message)} window_idx={window_index}",
        flush=True,
    )

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

    print(
        f"[PromptBuild] build_screenshot_messages | history_in={len(history)} "
        f"messages_out={len(messages)} scene={scene_type} game={game_name} confidence={confidence}",
        flush=True,
    )

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

    print(
        f"[PromptBuild] build_multimodal_screenshot_messages | history_in={len(history)} "
        f"messages_out={len(messages)} img_b64_len={len(img_b64)} window_title={window_title!r}",
        flush=True,
    )

    return messages


# ── 视觉感知主动发言 ──────────────────────────────────────────────────────

def _collect_recent_vision_speeches(
    history: list[dict],
    window_seconds: int = _AVOID_REPEAT_WINDOW_SECONDS,
) -> list[str]:
    """
    从 history 中收集最近 window_seconds 秒内、_source=="vision_proactive" 的 assistant turn。

    返回每条 assistant turn 的 content（去重，保持时间顺序）。
    用于「避免重复区」注入 —— 不作为示范，而是作为负向约束告诉模型"别重复这些"。
    """
    if not history:
        return []

    cutoff = time.time() - window_seconds
    seen = set()
    result = []

    for msg in history:
        if msg.get("role") != "assistant":
            continue
        if msg.get("_source") != "vision_proactive":
            continue
        if msg.get("timestamp", 0) < cutoff:
            continue
        content = (msg.get("content") or "").strip()
        if not content:
            continue
        if content in seen:
            continue
        seen.add(content)
        result.append(content)

    return result


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

    【2026-04-13 修复】history 过滤 + 避免重复区 双管齐下
      · history 中 _source=="vision_proactive" 的 assistant turn 被过滤
        —— 不再以 assistant role 形式诱导模型延续/复读
      · 同时在 system 末尾保留「避免重复区」
        —— 用负向约束告知模型"你最近说过 A B C，严禁重复"
        —— 信息保留 + 诱导消除，两者缺一不可
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

    # ── 【核心：避免重复区】──────────────────────────────────────────
    # 从 history 里反向扫描最近 10 分钟的 vision_proactive turn，
    # 把 content 列出来，明确告诉模型"严禁重复"。
    # 注意措辞：列表条目前面用 "-"，不带任何"示范""例子"色彩的字眼，
    # 而是明确包裹在"严禁重复"的负向约束里。
    recent_speeches = _collect_recent_vision_speeches(history)
    if recent_speeches:
        repeat_lines = ["", "【你最近主动说过的话 — 严禁重复以下任一话题或类似表达】"]
        for s in recent_speeches:
            repeat_lines.append(f"- {s}")
        repeat_lines.append("（如果你想说的话与上面任何一条相似，直接输出「……」表示沉默）")
        vision_parts.append("\n".join(repeat_lines))

    # ── 通用表达提示（独立于避免重复区，永远存在）────────────────
    vision_parts.append(
        "\n【表达提示】这是你的主动发言。如果当前画面没有真正值得说的新内容，"
        "可以直接只输出「……」三个字。不要为了说话而说话。"
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

    # ── 【核心修改 2026-04-13】重新引入 vision_proactive 过滤 ─────────
    # 上一版"history 完整传入"导致 history 里同一句台词作为 assistant
    # role 出现 → 强烈诱导模型复读（避免重复区敌不过 assistant 历史的
    # 延续信号）。
    # 现在的做法：
    #   · 保留 _source 标记的 assistant turn 用于避免重复区扫描（已在上面完成）
    #   · 但在传给 LLM 的 messages 里，从 history 中剔除这些 turn
    # 这样模型既能从 system 末尾知道"我刚说过什么"（信息保留），
    # 又不会被 assistant 历史诱导继续吐同样的话（诱导消除）。
    if history:
        filtered = [m for m in history if m.get("_source") != "vision_proactive"]
        trimmed = trim_history(filtered, window_index) if filtered else []
        clean = [{"role": m["role"], "content": m["content"]} for m in trimmed]
        messages.extend(clean)
        filtered_out = len(history) - len(filtered)
    else:
        trimmed = []
        filtered_out = 0

    messages.append({
        "role": "user",
        "content": "（桌宠内心活动：想主动说点什么）",
    })

    # ── 临时 print 日志：完整记录这次组装的全貌 ─────────────────────
    print(
        f"[PromptBuild] build_vision_speech_messages | "
        f"history_in={len(history)} history_filtered_out={filtered_out} "
        f"history_trimmed={len(trimmed)} "
        f"messages_out={len(messages)} system_len={len(full_system)} "
        f"avoid_repeat_count={len(recent_speeches)} "
        f"scene={scene_type} game={game_name} confidence={confidence} reason={reason}",
        flush=True,
    )
    if recent_speeches:
        print(
            f"[PromptBuild] 避免重复区注入内容: {recent_speeches}",
            flush=True,
        )

    return messages