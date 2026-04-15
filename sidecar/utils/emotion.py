"""
Reverie Link · 情绪提取工具

从 AI 回复文本中提取情绪标签（21 个标准标签）。
零外部依赖（仅使用 Python 标准库 re），可被任何模块 import。

与 tts/base.py 中的 EMOTION_TAGS 保持同步。
"""

import re

# 21 个标准情感标签（与 tts/base.py EMOTION_TAGS 严格一致）
_KNOWN_EMOTIONS: set[str] = {
    # 基础情绪
    "neutral", "happy", "sad", "angry", "fearful",
    "surprised", "disgusted", "excited", "gentle",
    # 角色风格
    "playful", "shy", "proud", "worried", "confused", "cold", "serious",
    # 说话方式
    "whisper", "shout", "cry", "laugh", "sigh",
}

# 正则：匹配所有已知标签（大小写不敏感）
_EMOTION_PATTERN = re.compile(
    r'\[('
    + "|".join(sorted(_KNOWN_EMOTIONS, key=len, reverse=True))  # 长标签优先匹配
    + r')\]',
    re.IGNORECASE,
)


def _extract_emotion(text: str) -> str:
    """
    提取 AI 回复中的情绪标签，返回小写标签字符串。
    匹配第一个出现的已知标签；若无匹配则返回空字符串。

    前端/后端均可调用，行为与旧版兼容（旧版 7 个标签的子集全部保留）。
    """
    match = _EMOTION_PATTERN.search(text)
    if match:
        return match.group(1).lower()
    return ""


def extract_all_emotions(text: str) -> list[str]:
    """
    提取文本中所有情绪标签（按出现顺序），用于调试。
    正常情况下每句只有一个标签，此函数仅供分析用。
    """
    return [m.group(1).lower() for m in _EMOTION_PATTERN.finditer(text)]


def strip_emotion_tags(text: str) -> str:
    """
    从文本中删除所有情绪标签，返回清洁文本（供 TTS 合成使用）。
    同时兼容未知标签（如 LLM 自造标签），统一使用宽松正则去除。
    """
    # 先去除已知标签
    cleaned = _EMOTION_PATTERN.sub("", text)
    # 再去除 LLM 可能自造的未知标签（形如 [anything]）
    cleaned = re.sub(r'\[\w+\]', "", cleaned)
    return cleaned.strip()
