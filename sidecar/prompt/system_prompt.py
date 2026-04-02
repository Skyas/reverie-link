"""
prompt/system_prompt.py — System Prompt 组装

包含：
  build_system_prompt()   — Layer 1 角色定义组装
  _build_memory_layer()   — Layer 2 记忆注入（笔记本 + 向量摘要）
  _build_time_note()      — 当前时间字符串
"""

import sys
import os
from datetime import datetime

# 允许从本模块访问 memory 子包（memory/ 与 prompt/ 同在 sidecar/ 下）
_SIDECAR_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SIDECAR_DIR not in sys.path:
    sys.path.insert(0, _SIDECAR_DIR)


def build_system_prompt(character: dict) -> str:
    """
    Layer 1：将角色模板字段组装为 System Prompt。
    Layer 2（记忆注入）在 build_messages / build_vision_speech_messages 中拼接，
    此处仅返回纯角色定义部分，便于测试与复用。
    """
    name        = character.get("name", "Assistant")
    identity    = character.get("identity", "")
    personality = character.get("personality", "")
    address     = character.get("address", "你")
    style       = character.get("style", "")
    examples    = character.get("examples", [])

    prompt_parts = []

    # ── 角色核心定义 ──────────────────────────────────────────────
    prompt_parts.append(
        f"你现在扮演「{name}」，{identity}。\n"
        f"性格：{personality}\n"
        f"称呼用户为：{address}\n"
        f"说话风格：{style}"
    )

    # ── 对话示例（few-shot，仅在用户填写时注入）──────────────────
    if examples:
        prompt_parts.append("\n【对话示例】")
        for ex in examples:
            prompt_parts.append(
                f"{address}：{ex.get('user', '')}\n"
                f"{name}：{ex.get('char', '')}"
            )

    # ── 情感表达规则 ──────────────────────────────────────────────
    prompt_parts.append(
        "\n【情感表达】根据当前回复的情感，在回复句末加入且仅加入一个情绪标签，"
        "从以下选项中选择最贴切的一个：\n"
        "[happy]开心高兴 / [sad]难过伤心 / [angry]生气不满 / "
        "[shy]害羞脸红 / [surprised]惊讶吃惊 / [sigh]叹气无奈 / [neutral]平静默认\n"
        "严格只使用以上7个标签，不要自创其他标签。\n"
        "例如：「哼，谁要你说这种话。[angry]」"
    )

    # ── 截屏意图识别指令（Phase 3 视觉感知）──────────────────────
    prompt_parts.append(
        "\n【屏幕观察】当你判断用户希望你观察屏幕画面时，"
        "在回复的最开头输出 [NEED_SCREENSHOT] 标签（仅此一个标签，无需其他解释）。"
    )

    # ── 硬性约束（始终在最后，防止被覆盖）──────────────────────
    prompt_parts.append(
        "\n【重要限制】这是一段语音对话场景。"
        "请用极其简短、口语化的句子回复，严禁超过50个字（情绪标签不计入字数）。"
        "只输出角色说的话，不要输出任何说明、括号内的动作描述或思考过程。"
    )

    return "\n".join(prompt_parts)


def _build_memory_layer(
    character_id: str,
    character_name: str,
    relevant_summaries: list[str],
) -> str:
    """
    构建 Layer 2 记忆注入文本。
    读取笔记本条目（手动区 + 自动区）以及向量检索召回的摘要片段。
    任意一项为空时，对应区块不注入（不产生空标题）。
    """
    parts = []
    name = character_name or "你"

    # ── 核心记忆（笔记本）──────────────────────────────────────────
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

    # ── 回忆片段（向量检索召回）────────────────────────────────────
    if relevant_summaries:
        lines = [f"· {s}" for s in relevant_summaries]
        parts.append(f"【{name}的回忆片段】\n" + "\n".join(lines))

    return "\n\n".join(parts)


def _build_time_note() -> str:
    """构建当前时间字符串（注入 system prompt，帮助模型感知时间语境）"""
    _weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    _now = datetime.now()
    _time_str = _now.strftime("%Y-%m-%d %H:%M") + f"（{_weekdays[_now.weekday()]}）"
    return f"【当前时间】{_time_str}"