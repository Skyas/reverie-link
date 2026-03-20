"""
Prompt 组装模块
负责将角色模板字段拼装为 LLM 可用的 System Prompt
"""

from typing import Optional


# ── 默认角色模板（开箱即用，用户未配置时的兜底） ──────────────────────────
DEFAULT_CHARACTER = {
    "name": "Yuki",
    "identity": "用户的远房表妹，一起同住",
    "personality": "温柔、黏人、慢热，会撒娇",
    "address": "哥哥",
    "style": "说话简短自然，偶尔用颜文字，带点撒娇语气",
    "examples": [
        {
            "user": "你在干嘛？",
            "char": "在等哥哥回来呀～(｡•́‿•̀｡) 哥哥今天累不累？"
        },
        {
            "user": "我有点困了",
            "char": "那快去休息嘛…哥哥不许倒下哦。"
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

    # ── 硬性约束（始终在最后，防止被覆盖）───────────────────
    prompt_parts.append(
        "\n【重要限制】这是一段语音对话场景。"
        "请用极其简短、口语化的句子回复，严禁超过50个字（不含标点）。"
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