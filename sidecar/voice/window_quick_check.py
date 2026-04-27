"""
window_quick_check.py — 窗口内轻量规则（仅日志，不阻断）

职责：窗口内语音的轻量规则筛检。仅用于日志记录和后续统计分析，不阻断语音进入 chat flow。
"""

import re
import logging

logger = logging.getLogger(__name__)


class WindowQuickCheck:
    """
    窗口内语音的轻量规则筛检。
    仅用于日志记录和后续统计分析，不阻断语音进入 chat flow。
    """

    # 可能指向与他人通话的模式
    PHONE_PATTERNS = [
        r'(喂|哪位|你是谁|找.+?吗|今晚.+?吃饭|几点.+?见|在哪.+?等)',
        r'(我.+?过来|你.+?过来|等我|马上到|路上)',
    ]

    @classmethod
    def check(cls, text: str) -> str | None:
        """
        检测窗口内语音是否包含可能的"与他人对话"信号。
        返回：提示字符串 或 None（无异常）。
        """
        for pattern in cls.PHONE_PATTERNS:
            if re.search(pattern, text):
                return "possible_external_conversation"
        return None

    @classmethod
    def log_if_suspicious(cls, text: str, source: str = "voice"):
        """仅在检测到可疑模式时记录日志"""
        flag = cls.check(text)
        if flag:
            logger.info(
                f"[WindowQuickCheck] 窗口内语音标记为可疑 | "
                f"flag={flag} text={text[:40]!r} source={source}"
            )
