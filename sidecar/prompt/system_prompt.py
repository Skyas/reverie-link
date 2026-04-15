"""
prompt/system_prompt.py — System Prompt 组装

包含：
  build_system_prompt()   — Layer 1 角色定义组装（不含硬性约束，约束在拼接末尾统一追加）
  _build_memory_layer()   — Layer 2 记忆注入（笔记本 + 向量摘要）
  _build_time_note()      — 当前时间字符串
  _HARD_CONSTRAINT        — 硬性约束文本（供 _build_full_system 追加到最末尾）

【2026-04-09 修改】
  1. 在 build_system_prompt 末尾新增「事件计数」简洁提示
     —— 教模型区分"实际发生过的事件"和"对话里出现过的词"
  2. 补 print 临时日志，便于排查 prompt 组装过程
     —— 前缀 [SystemPrompt]，与 vision/ 下既有风格保持一致
     —— 待统一整改 logging 后改为 logger.xxx
"""

import sys
import os
from datetime import datetime

# 允许从本模块访问 memory 子包（memory/ 与 prompt/ 同在 sidecar/ 下）
_SIDECAR_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SIDECAR_DIR not in sys.path:
    sys.path.insert(0, _SIDECAR_DIR)


# ── 硬性约束（独立常量，由 _build_full_system 追加到最末尾）─────────────────
#
# 设计原则：
#   1. 放在 system prompt 末尾 — Gemini 等模型对 prompt 末尾的注意力最强
#   2. 只保留"必须做"和"绝对不能做"两类硬约束 — 软性表达建议（"要有变化"）
#      对 LLM 几乎无效，反而占 token，已移除
#   3. event 机制已移除（详见 CHANGELOG）— 模型自产文本注入会引发自我强化
#      复读循环，记忆功能由 history + 笔记本 + 向量库三层架构承担
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

    # ── 情感表达规则（21 个标准情感标签）───────────────────────────
    # 与 TTS 引擎的情感参数一一对应，不允许模型自由发明
    parts.append(
        "\n【情感表达】每句回复末尾加一个情绪标签，从以下21个中选一个，严格只用这些，不要自创：\n"
        "基础情绪：[neutral] [happy] [sad] [angry] [fearful] [surprised] [disgusted] [excited] [gentle]\n"
        "角色风格：[playful] [shy] [proud] [worried] [confused] [cold] [serious]\n"
        "说话方式：[whisper] [shout] [cry] [laugh] [sigh]\n"
        "规则：每句只用一个标签，放在句末，不要在句中插入多个标签。"
    )

    # ── 截屏意图识别（Phase 3 视觉感知）──────────────────────────
    parts.append(
        "\n【屏幕观察】若判断用户想让你看屏幕，回复开头输出 [NEED_SCREENSHOT]。"
    )

    # ── 事件计数提示（2026-04-09 新增）────────────────────────────
    # 简洁版：教模型区分"实际发生的事件"和"对话里出现过的词"
    # 设计意图：用户问"今天 xx 几次了"这类问题时，模型常常把
    #   ① 自己之前主动发言里抱怨的「还没 xx」当成事件痕迹数进去
    #   ② 用户提问里出现的「xx」这个词当成事件数进去
    # 用一句话约束最常见的两种误判，效果不完美也无所谓 —— 计数本身不是核心需求
    parts.append(
        "\n【关于次数】如果用户问你「今天/刚才 xx 过几次」这类问题，"
        "只数真正发生过的动作，不要把对话里出现「xx」这个词的次数也算进去。"
        "不确定就说「好几次了」或「大概两三次」，不要瞎报具体数字。"
    )

    full_prompt = "\n".join(parts)

    # ── 临时 print 日志（待 logging 整改时改为 logger.debug）────────
    print(
        f"[SystemPrompt] build_system_prompt 完成 | name={name} "
        f"length={len(full_prompt)} examples={len(examples)}",
        flush=True,
    )

    return full_prompt


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

    notebook_count = 0
    notebook_error = None

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
            notebook_count = len(entries)
    except Exception as e:
        notebook_error = str(e)

    # ── 回忆片段（向量检索召回）────────────────────────────────────
    if relevant_summaries:
        lines = [f"· {s}" for s in relevant_summaries]
        parts.append(f"【{name}的回忆片段】\n" + "\n".join(lines))

    # ── 临时 print 日志 ─────────────────────────────────────────────
    print(
        f"[SystemPrompt] _build_memory_layer | character_id={character_id} "
        f"notebook_entries={notebook_count} vector_summaries={len(relevant_summaries or [])} "
        f"notebook_error={notebook_error}",
        flush=True,
    )

    return "\n\n".join(parts)


def _build_time_note() -> str:
    """构建当前时间字符串（注入 system prompt，帮助模型感知时间语境）"""
    _weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    _now = datetime.now()
    _time_str = _now.strftime("%Y-%m-%d %H:%M") + f"（{_weekdays[_now.weekday()]}）"
    return f"【当前时间】{_time_str}"