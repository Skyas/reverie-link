"""
视觉感知 · 捕获策略

决定每一帧是否需要调用 VLM。
像素差只用来跳过"纯静态"帧（加载画面、暂停、锁屏），
不再用来判断"画面有没有值得说的变化"。
"""
import time


class CaptureStrategy:

    STATIC_THRESHOLD = 0.5       # 像素差 < 0.5% = 纯静态，跳过 VLM
    BORING_STREAK_LIMIT = 3      # VLM 连续 N 次返回 interest_score <= 2 → 临时跳一帧

    def __init__(self):
        self._boring_streak = 0
        self._total_vlm_calls = 0
        self._vlm_calls_this_minute = 0
        self._minute_start = 0.0
        self._last_vlm_time = 0.0
        self.vlm_budget_per_minute = 0   # 0 = 不限制

    def should_call_vlm(
        self,
        pixel_diff: float,
        is_first_frame: bool,
        has_current_scene: bool,
    ) -> tuple:
        """
        返回 (should_call: bool, reason: str)
        """
        # 首帧必须分析
        if is_first_frame or not has_current_scene:
            return True, "first_frame"

        # 纯静态画面跳过
        if pixel_diff < self.STATIC_THRESHOLD:
            return False, "static_frame"

        # 连续低兴趣帧跳过，但每 3 帧重置一次防止错过突变
        if self._boring_streak >= self.BORING_STREAK_LIMIT:
            self._boring_streak = 0
            return False, "boring_streak"

        # 预算检查
        if self.vlm_budget_per_minute > 0:
            now = time.time()
            if now - self._minute_start > 60:
                self._minute_start = now
                self._vlm_calls_this_minute = 0
            if self._vlm_calls_this_minute >= self.vlm_budget_per_minute:
                return False, "budget_exceeded"

        return True, "normal"

    def on_vlm_result(self, interest_score: int):
        """VLM 返回后调用"""
        self._total_vlm_calls += 1
        self._vlm_calls_this_minute += 1
        self._last_vlm_time = time.time()
        if interest_score <= 3:
            self._boring_streak += 1
        else:
            self._boring_streak = 0

    def reset(self):
        self._boring_streak = 0
        self._total_vlm_calls = 0
        self._vlm_calls_this_minute = 0

    def get_stats(self) -> dict:
        return {
            "total_vlm_calls": self._total_vlm_calls,
            "boring_streak": self._boring_streak,
            "calls_this_minute": self._vlm_calls_this_minute,
        }