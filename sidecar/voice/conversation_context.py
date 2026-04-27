"""
conversation_context.py — 对话窗口管理（含 3s 预窗口）

状态：IDLE / PRE_WINDOW / CONVERSATION_WINDOW
"""

import time


class ConversationContext:
    """
    管理桌宠与用户的对话状态。
    - PRE_WINDOW: 3 秒预窗口（视觉/主动发言 LLM 生成完成后开启）
    - CONVERSATION_WINDOW: 正式对话窗口（桌宠发言/用户文字消息后开启）
    - IDLE: 静默待机
    """

    def __init__(self, default_window_sec: float = 15.0):
        self._default_duration = max(5.0, min(60.0, default_window_sec))
        self._pre_window_expiry: float = 0.0
        self._window_expiry: float = 0.0
        self._state = "IDLE"

    # ── 预窗口 ──
    def open_pre_window(self, duration_sec: float = 3.0):
        """视觉/主动发言 LLM 生成完成后调用"""
        self._pre_window_expiry = time.time() + duration_sec
        self._state = "PRE_WINDOW"

    def is_in_pre_window(self) -> bool:
        if self._state == "PRE_WINDOW":
            if time.time() > self._pre_window_expiry:
                self._state = "IDLE"
                return False
            return True
        return False

    # ── 正式窗口 ──
    def open_window(self):
        """桌宠发言/用户文字消息后调用"""
        self._state = "CONVERSATION_WINDOW"
        self._window_expiry = time.time() + self._default_duration
        # 预窗口被正式窗口覆盖
        self._pre_window_expiry = 0.0

    def extend_window(self):
        """用户在窗口内回复，延续窗口"""
        if self._state in ("PRE_WINDOW", "CONVERSATION_WINDOW"):
            self._state = "CONVERSATION_WINDOW"
            self._window_expiry = time.time() + self._default_duration

    def close_window(self):
        self._state = "IDLE"
        self._window_expiry = 0.0
        self._pre_window_expiry = 0.0

    def is_in_window(self) -> bool:
        """检查是否在任何有效窗口内（预窗口或正式窗口）"""
        # 先检查预窗口
        if self.is_in_pre_window():
            return True
        # 再检查正式窗口
        if self._state == "CONVERSATION_WINDOW":
            if time.time() > self._window_expiry:
                self._state = "IDLE"
                return False
            return True
        return False

    def on_user_interaction(self):
        """
        抽象接口：任意用户交互触发对话窗口。
        当前触发点：桌宠发言后、用户文字消息后。
        """
        self.open_window()

    def update_window_duration(self, seconds: float):
        """用户设置更新窗口时长"""
        self._default_duration = max(5.0, min(60.0, seconds))
