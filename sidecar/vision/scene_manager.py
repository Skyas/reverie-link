"""
视觉感知 · 场景管理器

负责：
  - 连续帧记忆（避免每帧做完整场景识别）
  - 场景切换检测（窗口标题变化 / 剧变画面）
  - 静默兜底计时（游戏 3 分钟 / 其他 15 分钟）
  - 场景自适应行为参数输出
"""
import time
from typing import Optional

from vision.vlm_client import VLMResult


# ── 场景静默兜底时间（秒）──────────────────────────────────────

SILENCE_FALLBACK_SECS = {
    "game":     3 * 60,    # 3 分钟
    "video":   15 * 60,    # 15 分钟
    "work":    15 * 60,
    "browsing":15 * 60,
    "idle":    15 * 60,
    "unknown": 15 * 60,
}


class SceneManager:
    """
    场景状态维护与切换检测。

    连续帧策略：
      - 首帧：完整识别（full_analysis=True）
      - 后续帧：若场景未切换，只做增量分析（interest_score + scene_description）
      - 触发重新完整识别的条件：
          1. 窗口标题变化
          2. 像素差异 > 50%（画面风格剧变）
          3. 手动切换场景标记
    """

    def __init__(self):
        self._current_result: Optional[VLMResult] = None
        self._last_window_title: str = ""
        self._last_full_analysis_time: float = 0.0
        self._last_speech_time: float = 0.0
        self._session_start_time: float = time.time()

    # ── 场景切换检测 ────────────────────────────────────────────

    def needs_full_analysis(self, window_title: str, pixel_diff: float) -> bool:
        """
        判断本次是否需要做完整场景识别（vs 增量分析）。
        """
        # 首帧
        if self._current_result is None:
            return True

        # 窗口标题变化
        if window_title != self._last_window_title:
            return True

        # 像素差异极大（> 50%，画面风格剧变）
        if pixel_diff > 50.0:
            return True

        return False

    def update(self, result: VLMResult, window_title: str):
        """更新当前场景状态"""
        self._current_result = result
        self._last_window_title = window_title
        self._last_full_analysis_time = time.time()

    def on_manual_reset(self):
        """手动切换场景标记时强制触发完整重识别"""
        self._current_result = None
        self._last_window_title = ""

    # ── 当前场景属性 ────────────────────────────────────────────

    @property
    def current_scene_type(self) -> str:
        if self._current_result:
            return self._current_result.scene_type
        return "unknown"

    @property
    def current_result(self) -> Optional[VLMResult]:
        return self._current_result

    # ── 静默兜底检测 ────────────────────────────────────────────

    def check_silence_fallback(self) -> bool:
        """
        检查是否超过静默兜底时间（未发过言的情况下）。
        返回 True 表示应该触发兜底发言。
        """
        scene = self.current_scene_type
        threshold = SILENCE_FALLBACK_SECS.get(scene, 15 * 60)

        since_speech = time.time() - self._last_speech_time
        since_start  = time.time() - self._session_start_time

        # 会话开始后，用 since_start 和 since_speech 中的较小值（防止刚启动就触发）
        elapsed = min(since_speech, since_start) if self._last_speech_time == 0 else since_speech
        return elapsed >= threshold

    def on_speech_triggered(self):
        """记录最后发言时间（用于静默兜底计时重置）"""
        self._last_speech_time = time.time()

    # ── 场景自适应参数 ──────────────────────────────────────────

    # def get_scene_prompt_info(self, address: str = "你") -> dict:
    #     """
    #     返回场景相关的 Prompt 注入信息。
    #     """
    #     result = self._current_result
    #     if result is None:
    #         return {
    #             "scene_type": "unknown",
    #             "scene_description": "",
    #             "game_name": None,
    #             "game_genre": None,
    #             "confidence": "low",
    #             "scene_instruction": f"{address}好像不在屏幕前，你可以自言自语或表达等待的情绪。",
    #         }

    #     # scene_type = result.scene_type
    #     # instructions = {
    #     #     "game":     f"你正在观看{address}玩游戏，可以评论游戏画面、提供策略建议或表达情绪反应。",
    #     #     "video":    f"你注意到{address}正在看视频，可以偶尔对画面内容做轻松的反应。",
    #     #     "work":     f"你注意到{address}正在工作，不要评论工作内容，只做关怀式提醒，比如提醒休息、喝水。",
    #     #     "browsing": f"你注意到{address}正在浏览网页，可以轻松地聊几句。",
    #     #     "idle":     f"{address}好像不在屏幕前，你可以自言自语或表达等待的情绪。",
    #     #     "unknown":  f"{address}好像不在屏幕前，你可以自言自语或表达等待的情绪。",
    #     # }

    #     return {
    #         "scene_type":        scene_type,
    #         "scene_description": result.scene_description,
    #         "game_name":         result.game_name,
    #         "game_genre":        result.game_genre,
    #         "confidence":        result.confidence,
    #         "scene_instruction": instructions.get(scene_type, instructions["unknown"]),
    #     }
