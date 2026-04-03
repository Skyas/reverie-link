"""
prompt/system_prompt.py — System Prompt 组装

包含：
  build_system_prompt()   — Layer 1 角色定义组装（不含硬性约束，约束在拼接末尾统一追加）
  _build_memory_layer()   — Layer 2 记忆注入（笔记本 + 向量摘要）
  _build_time_note()      — 当前时间字符串
  _HARD_CONSTRAINT        — 硬性约束文本（供 _build_full_system 追加到最末尾）
"""

import sys
import os
from datetime import datetime

# 允许从本模块访问 memory 子包（memory/ 与 prompt/ 同在 sidecar/ 下）
_SIDECAR_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SIDECAR_DIR not in sys.path:
    sys.path.insert(0, _SIDECAR_DIR)


# ── 硬性约束（独立常量，由 _build_full_system 追加到最末尾）─────────────────
# 放在末尾的理由：Gemini 等模型对长 system prompt 有 recency bias，
# 末尾内容注意力最强，硬性约束放这里最有效。
_HARD_CONSTRAINT = (
    "【重要限制】语音对话场景，用极简短口语回复，禁超50字（情绪标签不计）。"
    "只输出角色的话，禁止说明、动作描述、思考过程。"
)


def build_system_prompt(character: dict) -> str:
    """
    Layer 1：将角色模板字段组装为 System Prompt。
    注意：硬性约束不在此处追加，由 _build_full_system() 统一放到最末尾。
    """
    name        = character.get("name", "Assistant")
    identity    = character.get("identity", "")
    personality = character.get("personality", "")
    address     = character.get("address", "你")
    style       = character.get("style", "")
    examples    = character.get("examples", [])

    parts = []

    # ── 角色核心定义 ──────────────────────────────────────────────
    parts.append(
        f"你现在扮演「{name}」，{identity}。\n"
        f"性格：{personality}\n"
        f"称呼用户为：{address}\n"
        f"说话风格：{style}"
    )

    # ── 对话示例（few-shot，仅在用户填写时注入）──────────────────
    if examples:
        parts.append("\n【对话示例】")
        for ex in examples:
            parts.append(
                f"{address}：{ex.get('user', '')}\n"
                f"{name}：{ex.get('char', '')}"
            )

    # ── 情感表达规则（精简版）─────────────────────────────────────
    parts.append(
        "\n【情感表达】在回复句末加一个情绪标签：\n"
        "[happy] / [sad] / [angry] / [shy] / [surprised] / [sigh] / [neutral]\n"
        "严格只用以上7个，不要自创。"
    )

    # ── 截屏意图识别（Phase 3 视觉感知）──────────────────────────
    parts.append(
        "\n【屏幕观察】若判断用户想让你看屏幕，回复开头输出 [NEED_SCREENSHOT]。"
    )

    return "\n".join(parts)


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