"""
Reverie Link · 情绪提取工具

从 AI 回复文本中提取情绪标签。
零外部依赖（仅使用 Python 标准库 re），可被任何模块 import。
"""

import re

# 已知情绪标签集合（与前端 EMOTION_TAGS 保持同步）
_KNOWN_EMOTIONS = {"happy", "sad", "angry", "shy", "surprised", "neutral", "sigh"}


def _extract_emotion(text: str) -> str:
    """
    提取 AI 回复中的情绪标签。
    优先匹配已知标签；若 LLM 造了未知标签，兜底正则也能识别，
    但不存入已知情绪，记为空字符串（前端统一剥离即可）。
    """
    match = re.search(r'\[(happy|sad|angry|shy|surprised|neutral|sigh)\]', text, re.IGNORECASE)
    if match:
        return match.group(1).lower()
    return ""