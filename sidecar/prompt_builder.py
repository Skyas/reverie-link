"""
Prompt 组装模块
负责将角色模板字段拼装为 LLM 可用的 System Prompt，
并对带时间戳的对话历史执行「时间窗口 + 轮数」交集裁剪。
"""

import time
import sys
import os
# 允许从 prompt_builder 访问 memory 模块（两者同在 sidecar/ 下）
_SIDECAR_DIR = os.path.dirname(os.path.abspath(__file__))
if _SIDECAR_DIR not in sys.path:
    sys.path.insert(0, _SIDECAR_DIR)
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

    # ── Layer 2 预留位置（Phase 3 记忆模块在此注入）──────────
    # memory_context = get_memory_context()
    # if memory_context:
    #     prompt_parts.append(f"\n【关于{address}你记得的事】\n{memory_context}")

    # ── 情绪标签规则 ──────────────────────────────────────────
    # 情绪标签由前端剥离，不会出现在气泡文字中，也不会被 TTS 朗读
    prompt_parts.append(
        "\n【情感表达】根据当前回复的情感，在回复句末加入且仅加入一个情绪标签，"
        "从以下选项中选择最贴切的一个：\n"
        "[happy]开心高兴 / [sad]难过伤心 / [angry]生气不满 / "
        "[shy]害羞脸红 / [surprised]惊讶吃惊 / [sigh]叹气无奈 / [neutral]平静默认\n"
        "严格只使用以上7个标签，不要自创其他标签。\n"
        "例如：「哼，谁要你说这种话。[angry]」"
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

    history 中每条记录格式（方案 A）：
        {
            "role": "user" | "assistant",
            "content": "...",
            "timestamp": float   # time.time() 的 Unix 时间戳
        }

    裁剪规则：
    1. 先按时间窗口过滤：只保留 now - time_window_seconds 之内的记录
    2. 再按最大轮数截断：从末尾取最多 max_rounds × 2 条
    3. 两者取交集（同时满足才保留）

    返回裁剪后的记录列表（仍含 timestamp 字段，由调用方决定是否剥离）。
    """
    idx = max(0, min(window_index, len(WINDOW_PRESETS) - 1))
    _, time_window_seconds, max_rounds = WINDOW_PRESETS[idx]
    max_items = max_rounds * 2  # 每轮 = user + assistant 各 1 条

    now = time.time()
    cutoff = now - time_window_seconds

    # 步骤 1：时间窗口过滤
    time_filtered = [msg for msg in history if msg.get("timestamp", 0) >= cutoff]

    # 步骤 2：从末尾取最多 max_items 条（轮数限制）
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
 
    history 格式（扩展格式，含 timestamp）：
        [{"role": "user"|"assistant", "content": "...", "timestamp": float}, ...]
 
    流程：
    1. 对 history 执行时间+轮数交集裁剪
    2. 组装 Layer 2 记忆注入（核心记忆 + 回忆片段）
    3. 合并 system_prompt + Layer 2 + history + user_message
    """
    # 裁剪
    trimmed = trim_history(history, window_index)
 
    # 剥离 timestamp，只保留 role 和 content
    clean_history = [
        {"role": msg["role"], "content": msg["content"]}
        for msg in trimmed
    ]
 
    # ── Layer 2：记忆注入 ────────────────────────────────────────
    memory_layer = _build_memory_layer(
        character_id=character_id,
        character_name=character_name,
        relevant_summaries=relevant_summaries or [],
    )
 
    # ── 当前本地时间注入 ─────────────────────────────────────
    from datetime import datetime
    _weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    _now = datetime.now()
    _time_str = _now.strftime("%Y-%m-%d %H:%M") + f"（{_weekdays[_now.weekday()]}）"
    time_note = f"【当前时间】{_time_str}"

    # 合并 system prompt + 当前时间 + Layer 2
    full_system = system_prompt + "\n\n" + time_note
    if memory_layer:
        full_system += "\n\n" + memory_layer
 
    messages = [{"role": "system", "content": full_system}]
    messages.extend(clean_history)
    messages.append({"role": "user", "content": user_message})
    return messages
 
 
def _build_memory_layer(
    character_id: str,
    character_name: str,
    relevant_summaries: list[str],
) -> str:
    """
    构建 Layer 2 记忆注入文本。
    格式参考 PHASE3_MEMORY_DESIGN.md § 7。
 
    包含两个子区域：
    - 核心记忆（笔记本内容，每次必带）
    - 回忆片段（向量检索结果，按需召回，可能为空）
    """
    parts = []
    name = character_name or "你"
 
    # ── 核心记忆：从笔记本读取所有条目 ──────────────────────────
    try:
        from memory.db_notebook import get_all_entries
        from memory.models import NotebookSource
 
        entries = get_all_entries(character_id=character_id)
        if entries:
            lines = []
            for e in entries:
                # 手动区原样注入，自动区加来源标注
                if e.source == NotebookSource.MANUAL:
                    lines.append(f"· {e.content}（来自：我的备忘录）")
                else:
                    lines.append(f"· {e.content}")
            parts.append(f"【{name}的核心记忆】\n" + "\n".join(lines))
    except Exception:
        pass  # 数据库未初始化或无数据时静默跳过
 
    # ── 回忆片段：向量检索结果 ────────────────────────────────────
    if relevant_summaries:
        lines = [f"· {s}" for s in relevant_summaries]
        parts.append(f"【{name}的回忆片段】\n" + "\n".join(lines))
 
    return "\n\n".join(parts)