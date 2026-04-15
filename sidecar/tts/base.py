"""
Reverie Link · TTS 抽象基类与公共数据结构

所有引擎（在线/离线）均实现 TTSEngineBase，上层对引擎类型完全无感知。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncGenerator

# ── 21 个标准情感标签 ─────────────────────────────────────────────────────
EMOTION_TAGS: list[str] = [
    "neutral", "happy", "sad", "angry", "fearful", "surprised", "disgusted", 
    "excited", "gentle", "playful", "shy", "proud", "worried", "confused", 
    "cold", "serious", "whisper", "shout", "cry", "laugh", "sigh"
]

EMOTION_SET: set[str] = set(EMOTION_TAGS)

EMOTION_FALLBACK: dict[str, str] = {
    "playful":   "happy",
    "shy":       "gentle",
    "proud":     "happy",
    "worried":   "fearful",
    "confused":  "neutral",
    "cold":      "neutral",
    "serious":   "neutral",
    "whisper":   "gentle",
    "shout":     "excited",
    "cry":       "sad",
    "laugh":     "happy",
    "sigh":      "sad",
}

@dataclass
class VoiceInfo:
    id: str
    name: str
    engine: str               
    preview_url: str = ""
    tags: list[str] = field(default_factory=list)


class TTSEngineBase(ABC):
    """所有 TTS 引擎的抽象基类。"""

    @abstractmethod
    async def synthesize(
        self,
        text: str,
        voice_id: str,
        emotion: str = "neutral",
    ) -> AsyncGenerator[bytes, None]:
        """
        流式合成语音。
        :return: 异步产出音频二进制块 (WAV / MP3)
        """
        ...

    @abstractmethod
    async def list_voices(self) -> list[VoiceInfo]:
        ...

    @abstractmethod
    async def is_ready(self) -> bool:
        ...

    @abstractmethod
    async def test_connection(self) -> bool:
        ...

    def resolve_emotion(self, emotion: str, supported: set[str]) -> str:
        if emotion in supported:
            return emotion
        fallback = EMOTION_FALLBACK.get(emotion, "neutral")
        if fallback in supported:
            return fallback
        return "neutral"