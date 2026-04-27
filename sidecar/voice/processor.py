"""
processor.py — 语音处理对外统一入口 VoiceProcessor

职责：串联所有子模块，处理来自 WebSocket 的语音数据。
"""

from .stt_engine import STTEngine
from .text_sanitizer import TextSanitizer
from .interrupt_handler import InterruptHandler
from .conversation_context import ConversationContext
from .intent_filter import IntentFilter
from .window_quick_check import WindowQuickCheck


class VoiceProcessor:
    def __init__(
        self,
        llm_client,
        llm_model: str,
        character: dict | None = None,
        window_sec: float = 15.0,
    ):
        self.stt = STTEngine()
        self.context = ConversationContext(window_sec)
        self.filter = IntentFilter(llm_client, llm_model, character)
        self.interrupt = InterruptHandler()
        self.sanitizer = TextSanitizer()

    async def process(self, pcm_bytes: bytes) -> dict | None:
        """
        处理一段语音 PCM 数据。
        返回 voice_result dict，或 None（音频无效/被过滤）。
        """
        # 1. STT
        result = await __import__("asyncio").to_thread(self.stt.recognize, pcm_bytes)
        text = result.get("text", "").strip()

        # 2. 文本消歧层
        if self.sanitizer.is_degradation(text):
            return None

        # 3. 对话窗口 / 意图判断
        in_window = self.context.is_in_window()
        should_reply = await self.filter.should_respond(text, self.context)

        # 4. 窗口内轻量规则（仅日志，不阻断）
        if in_window:
            WindowQuickCheck.log_if_suspicious(text)

        reason = (
            "pre_window" if self.context.is_in_pre_window()
            else "conversation_window" if in_window
            else "intent_ok" if should_reply
            else "not_triggered"
        )

        return {
            "type": "voice_result",
            "text": text,
            "emotion": result.get("emotion"),
            "language": result.get("language"),
            "triggered": should_reply,
            "reason": reason,
        }

    async def handle_interrupt(self, websocket):
        """用户打断时调用"""
        await self.interrupt.handle_interrupt(websocket)

    def on_pet_response_sent(self):
        """桌宠发送回复（chat_response 或 vision_proactive_speech）后调用"""
        self.context.open_window()

    def on_user_interaction(self):
        """用户发送文字消息后调用"""
        self.context.on_user_interaction()

    def open_pre_window(self):
        """视觉/主动发言 LLM 生成完成后调用"""
        self.context.open_pre_window()

    def update_character(self, character: dict):
        self.filter.update_character(character)

    def update_window_duration(self, seconds: float):
        self.context.update_window_duration(seconds)

    def register_llm_task(self, task):
        """chat flow 开始时注册 LLM 任务，供打断时取消"""
        self.interrupt.register_task(task)

    def clear_llm_task(self):
        """chat flow 结束时清理"""
        self.interrupt.clear()
