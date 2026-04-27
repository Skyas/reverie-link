"""
intent_filter.py — 意图判断 + 人设接入

职责：仅对 IDLE 状态下的语音输入做意图判断。窗口内直接通过。
"""


class IntentFilter:
    def __init__(self, llm_client, llm_model: str, character: dict | None = None):
        self._llm = llm_client
        self._model = llm_model
        self._character = character or {}

    def update_character(self, character: dict):
        self._character = character

    async def should_respond(self, text: str, context) -> bool:
        """
        判断是否应该对这段语音文本做出回应。
        窗口内（含预窗口）直接通过；窗口外交由 LLM 结合人设判断。
        """
        from .conversation_context import ConversationContext
        if context.is_in_window():
            context.extend_window()
            return True

        # 窗口外：LLM 结合人设判断
        prompt = self._build_prompt(text)
        try:
            response = await self._llm.chat.completions.create(
                model=self._model,
                messages=[{"role": "system", "content": prompt}],
                max_tokens=10,
                temperature=0.1,
            )
            content = response.choices[0].message.content.strip()
            return "[NOT_FOR_ME]" not in content
        except Exception:
            # 兜底：LLM 调用失败时保守处理（静默丢弃）
            return False

    def _build_prompt(self, text: str) -> str:
        c = self._character
        name = c.get("name", "桌宠")
        identity = c.get("identity", "")
        personality = c.get("personality", "")
        address = c.get("address", "你")
        style = c.get("style", "")

        return (
            f"你现在扮演「{name}」，{identity}。\n"
            f"性格：{personality}\n"
            f"称呼用户为：{address}\n"
            f"说话风格：{style}\n\n"
            f"请判断用户是否在对你说：\n"
            f"- 如果用户在自言自语、打电话、约朋友、工作开会、对第三方说话，"
            f"只输出 [NOT_FOR_ME]\n"
            f"- 如果用户在跟你分享、请求、感叹、回应、闲聊，只输出 [OK]\n\n"
            f"用户说的话：\" {text} \"\n"
            f"只输出 [NOT_FOR_ME] 或 [OK]。"
        )
