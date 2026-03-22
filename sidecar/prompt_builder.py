"""
Prompt 组装模块
负责将角色模板字段拼装为 LLM 可用的 System Prompt
"""

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


def build_system_prompt(character: dict) -> str:
    """
    Layer 1：将角色模板字段组装为 System Prompt。
    Layer 2（记忆注入）在 Phase 3 接入，此处预留位置。
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
        "[shy]害羞脸红 / [surprised]惊讶吃惊 / [neutral]平静默认\n"
        "例如：「哼，谁要你说这种话。[angry]」"
    )

    # ── 硬性约束（始终在最后，防止被覆盖）───────────────────
    prompt_parts.append(
        "\n【重要限制】这是一段语音对话场景。"
        "请用极其简短、口语化的句子回复，严禁超过50个字（情绪标签不计入字数）。"
        "只输出角色说的话，不要输出任何说明、括号内的动作描述或思考过程。"
    )

    return "\n".join(prompt_parts)


def build_messages(
    system_prompt: str,
    history: list[dict],
    user_message: str
) -> list[dict]:
    """
    组装完整的 messages 列表传给 LLM API。
    history 格式：[{"role": "user"|"assistant", "content": "..."}]
    """
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_message})
    return messages