"""
voice/ — 语音输入处理子包

职责：
  - STT 语音识别（SenseVoice-Small）
  - 文本消歧层
  - 对话窗口管理（含 3s 预窗口）
  - 意图判断
  - 打断处理
  - 对外统一入口 VoiceProcessor

用法：
  from voice import VoiceProcessor
"""

from .processor import VoiceProcessor

__all__ = ["VoiceProcessor"]
