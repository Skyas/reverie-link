"""
视觉感知 · 发言决策引擎

负责：
  - 兴趣分阈值判断（3 档：话少/适中/话多）
  - 冷却机制管理
  - 静默兜底触发
  - 并发冲突处理（用户正在交互时不独立触发）
  - 生成发言触发事件（内容由外部 LLM 调用生成）
"""
import time
from dataclasses import dataclass
from enum import IntEnum
from typing import Optional


# ── 话痨程度档位 ─────────────────────────────────────────────────

class TalkLevel(IntEnum):
    QUIET  = 0   # 话少，阈值 30
    NORMAL = 1   # 适中，阈值 20（默认）
    TALKATIVE = 2  # 话多，阈值 12

INTEREST_THRESHOLDS = {
    TalkLevel.QUIET:     30,
    TalkLevel.NORMAL:    20,
    TalkLevel.TALKATIVE: 12,
}


# ── 发言触发事件 ─────────────────────────────────────────────────

@dataclass
class SpeechTrigger:
    reason: str   # "interest_threshold" | "silence_fallback"
    context_prompt: str   # 缓冲池摘要，注入到 LLM Prompt
    scene_info: dict      # SceneManager.get_scene_prompt_info() 的输出


class SpeechEngine:
    """发言决策引擎"""

    def __init__(self):
        self._talk_level: TalkLevel = TalkLevel.NORMAL
        self._cooldown_seconds: float = 20.0
        self._last_speech_time: float = 0.0
        self._user_interacting: bool = False   # 用户正在与桌宠交互

    # ── 配置更新 ────────────────────────────────────────────────

    def set_talk_level(self, level: int):
        self._talk_level = TalkLevel(max(0, min(2, level)))

    def set_cooldown(self, seconds: float):
        self._cooldown_seconds = max(5.0, float(seconds))

    def _get_threshold(self) -> int:
        """返回当前话痨档位对应的兴趣分阈值（供日志使用）"""
        return INTEREST_THRESHOLDS[self._talk_level]

    # ── 用户交互状态 ────────────────────────────────────────────

    def set_user_interacting(self, interacting: bool):
        """用户开始或结束主动交互时调用"""
        self._user_interacting = interacting

    # ── 冷却状态 ────────────────────────────────────────────────

    def _in_cooldown(self) -> bool:
        return (time.time() - self._last_speech_time) < self._cooldown_seconds

    def on_speech_sent(self):
        """桌宠主动发言完成后调用，重置冷却计时"""
        self._last_speech_time = time.time()

    # ── 用户打断冷却 ────────────────────────────────────────────

    def on_user_message(self):
        """用户主动发消息时调用，立即结束冷却"""
        self._last_speech_time = 0.0

    # ── 主判断逻辑 ──────────────────────────────────────────────

    def should_speak(
        self,
        accumulated_score: int,
        silence_fallback: bool,
        context_prompt: str,
        scene_info: dict,
    ) -> Optional[SpeechTrigger]:
        """
        判断当前是否应该触发主动发言。

        规则：
          1. 用户正在交互 → 不触发（视觉事件并入对话上下文，而非独立触发）
          2. 冷却中 → 不触发（但兴趣分保留）
          3. 兴趣分 ≥ 阈值 → 触发
          4. 静默兜底时间到 → 触发

        返回 SpeechTrigger 或 None。
        """
        # 用户正在交互时不独立触发
        if self._user_interacting:
            return None

        # 冷却中
        if self._in_cooldown():
            return None

        threshold = INTEREST_THRESHOLDS[self._talk_level]

        # 兴趣分阈值判断
        if accumulated_score >= threshold:
            return SpeechTrigger(
                reason="interest_threshold",
                context_prompt=context_prompt,
                scene_info=scene_info,
            )

        # 静默兜底
        if silence_fallback:
            return SpeechTrigger(
                reason="silence_fallback",
                context_prompt=context_prompt,
                scene_info=scene_info,
            )

        return None
