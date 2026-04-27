"""
text_sanitizer.py — 文本消歧层

过滤 VAD 误触发产生的无意义识别结果。
执行时间 < 1ms，不影响整体延迟。
"""

import re


class TextSanitizer:
    """
    文本消歧层：过滤 VAD 误触发产生的无意义识别结果。
    """

    FILLER_WORDS = {"嗯", "啊", "哦", "呃", "哈", "唔", "哎", "嘛", "呢", "吧"}

    @staticmethod
    def is_degradation(text: str) -> bool:
        """
        判断识别文本是否为无意义的误触发结果。
        返回 True → 静默丢弃，不进入后续流程。
        """
        stripped = text.strip()

        # 1. 过短（1 字以内）
        if len(stripped) <= 1:
            return True

        # 2. 纯语气词
        chars = set(stripped)
        if chars.issubset(TextSanitizer.FILLER_WORDS):
            return True

        # 3. 可读字符占比过低（噪音识别出的乱码）
        readable = re.findall(r'[\u4e00-\u9fff\u3000-\u303fa-zA-Z0-9\s]', stripped)
        if len(stripped) > 0 and len(readable) / len(stripped) < 0.5:
            return True

        return False
