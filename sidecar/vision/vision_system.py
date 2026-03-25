"""
视觉感知 · 主系统编排器

将所有子模块串联起来，作为后台 asyncio 任务运行。
每 10 秒截屏一次，完成预筛 → VLM 分析 → 事件缓冲 → 发言决策的完整流程。
"""
import asyncio
import time
from typing import Optional, TYPE_CHECKING

from vision.screen_capture import (
    capture_screen,
    get_foreground_process_info,
    compute_pixel_diff,
    compress_for_vlm,
    is_blank_screen,
)
from vision.vlm_client import VLMClient, VLMResult
from vision.game_detector import GameDetector
from vision.event_buffer import EventBuffer
from vision.scene_manager import SceneManager
from vision.speech_engine import SpeechEngine, SpeechTrigger

# 截屏间隔（秒）
CAPTURE_INTERVAL = 10

# 像素预筛阈值
PIXEL_DIFF_SKIP_THRESHOLD = 5.0   # < 5%  → 跳过 VLM，兴趣分 +1
# ≥ 5% → 调用 VLM


class VisionSystem:
    """
    视觉感知系统主类。
    在 FastAPI lifespan 中作为后台 asyncio 任务运行。
    通过 speech_queue 向 WebSocket 层推送主动发言触发事件。
    """

    def __init__(self, speech_queue: asyncio.Queue):
        self._speech_queue = speech_queue
        self._enabled = False
        self._task: Optional[asyncio.Task] = None

        # 子模块
        self.vlm_client   = VLMClient()
        self.game_detector = GameDetector()
        self.event_buffer = EventBuffer()
        self.scene_manager = SceneManager()
        self.speech_engine = SpeechEngine()

        # 上一帧截图（用于像素差异计算）
        self._prev_screenshot: Optional[bytes] = None

        # 当前会话信息（由 main.py 注入）
        self._session_id:    str = ""
        self._character_id:  str = ""
        self._address:       str = "你"

    # ── 配置接口（由 main.py 调用）─────────────────────────────

    def configure(self, cfg: dict):
        """
        处理来自前端的视觉感知配置。
        cfg 格式：
          {
            "enabled": bool,
            "vlm_base_url": str,
            "vlm_api_key": str,
            "vlm_model": str,
            "talk_level": int,      # 0|1|2
            "cooldown_seconds": int,
            "manual_game_mode": bool,
          }
        """
        was_enabled = self._enabled
        self._enabled = bool(cfg.get("enabled", False))

        self.vlm_client.configure_vlm(
            base_url=cfg.get("vlm_base_url", ""),
            api_key=cfg.get("vlm_api_key", ""),
            model=cfg.get("vlm_model", "glm-4v-flash"),
        )
        self.speech_engine.set_talk_level(int(cfg.get("talk_level", 1)))
        self.speech_engine.set_cooldown(float(cfg.get("cooldown_seconds", 20)))
        self.game_detector.set_manual_game_mode(bool(cfg.get("manual_game_mode", False)))

        if self.game_detector.is_manual_game_mode():
            self.scene_manager.on_manual_reset()

        # 启用状态变化时重置
        if not was_enabled and self._enabled:
            self._prev_screenshot = None
            self.event_buffer.reset_score()
            print("[Vision] 视觉感知已启用")
        elif was_enabled and not self._enabled:
            print("[Vision] 视觉感知已关闭")

    def set_session_info(self, session_id: str, character_id: str, address: str = "你"):
        """更新当前活跃会话信息"""
        self._session_id   = session_id
        self._character_id = character_id
        self._address      = address

    def set_main_llm(self, client, model: str):
        """注入主 LLM 客户端（用于多模态 fallback）"""
        self.vlm_client.set_main_client(client, model)

    def on_user_message(self):
        """用户发消息时调用，打断冷却、标记正在交互"""
        self.speech_engine.on_user_message()
        self.speech_engine.set_user_interacting(True)

    def on_user_message_done(self):
        """AI 回复完成后调用，解除交互标记"""
        self.speech_engine.set_user_interacting(False)

    # ── 任务生命周期 ─────────────────────────────────────────────

    def start(self):
        """启动后台任务（在 asyncio event loop 中调用）"""
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._run_loop(), name="vision_loop")
        print("[Vision] 后台任务已启动")

    def stop(self):
        """停止后台任务"""
        if self._task and not self._task.done():
            self._task.cancel()
            self._task = None
        print("[Vision] 后台任务已停止")

    # ── 主循环 ───────────────────────────────────────────────────

    async def _run_loop(self):
        """每 10 秒执行一次完整的感知-决策流程"""
        while True:
            try:
                await asyncio.sleep(CAPTURE_INTERVAL)
                if self._enabled:
                    await self._process_frame()
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[Vision] 主循环异常: {e}")
                await asyncio.sleep(CAPTURE_INTERVAL)

    async def _process_frame(self):
        """处理一帧：截屏 → 预筛 → VLM → 缓冲 → 发言决策"""

        # ─ 1. 截屏 ─────────────────────────────────────────────
        screenshot = await asyncio.to_thread(capture_screen)
        if screenshot is None:
            return

        # ─ 2. 检测空白截屏（反作弊拦截）──────────────────────
        if await asyncio.to_thread(is_blank_screen, screenshot):
            print("[Vision] 截屏为空白（可能被反作弊拦截），跳过本帧")
            return

        # ─ 3. 像素差异预筛 ─────────────────────────────────────
        pixel_diff = 0.0
        if self._prev_screenshot is not None:
            pixel_diff = await asyncio.to_thread(
                compute_pixel_diff, self._prev_screenshot, screenshot
            )
        else:
            pixel_diff = 100.0  # 首帧强制分析

        self._prev_screenshot = screenshot

        # ─ 4. 差异 < 5% → 跳过 VLM，直接给 +1 兴趣分 ─────────
        if pixel_diff < PIXEL_DIFF_SKIP_THRESHOLD and self.scene_manager.current_result is not None:
            self.event_buffer.push(
                interest_score=1,
                scene_type=self.scene_manager.current_scene_type,
                scene_description="",
                game_name=self.scene_manager.current_result.game_name if self.scene_manager.current_result else None,
                confidence="high",
                source="pixel_skip",
            )
            await self._check_speech()
            return

        # ─ 5. 获取前台进程信息 ──────────────────────────────────
        process_info = await asyncio.to_thread(get_foreground_process_info)
        window_title = process_info.get("window_title", "")

        # ─ 6. 判断是否需要完整场景识别 or 增量分析 ──────────────
        needs_full = self.scene_manager.needs_full_analysis(window_title, pixel_diff)
        prompt_type = "background" if needs_full else "incremental"

        # ─ 7. 压缩截图 ──────────────────────────────────────────
        compressed = await asyncio.to_thread(compress_for_vlm, screenshot)

        # ─ 8. 调用 VLM ──────────────────────────────────────────
        current = self.scene_manager.current_result
        vlm_result = await self.vlm_client.analyze(
            img_bytes=compressed,
            window_title=window_title,
            prompt_type=prompt_type,
            prev_descriptions=self.event_buffer.get_recent_context(),
            base_result=current,
            scene_type=current.scene_type if current else "unknown",
            game_name=current.game_name if current else None,
            game_genre=current.game_genre if current else None,
        )

        if vlm_result is None:
            print("[Vision] VLM 调用失败，跳过本帧")
            return

        # ─ 9. 游戏检测（结合进程信息 + VLM 结果）──────────────
        detect = self.game_detector.detect(
            process_info=process_info,
            vlm_scene_type=vlm_result.scene_type,
            vlm_game_name=vlm_result.game_name,
        )
        # 游戏检测结果可以覆盖 VLM 的 scene_type（进程检测更准）
        if detect["is_game"] and vlm_result.scene_type != "game":
            vlm_result.scene_type = "game"
        if detect["game_name"] and not vlm_result.game_name:
            vlm_result.game_name = detect["game_name"]

        # ─ 10. 更新场景管理器 ────────────────────────────────────
        self.scene_manager.update(vlm_result, window_title)

        # ─ 11. 写入事件缓冲池 ────────────────────────────────────
        self.event_buffer.push(
            interest_score=vlm_result.interest_score,
            scene_type=vlm_result.scene_type,
            scene_description=vlm_result.scene_description,
            game_name=vlm_result.game_name,
            confidence=vlm_result.confidence,
            source="vlm_background",
        )

        # ─ 12. 发言决策 ─────────────────────────────────────────
        await self._check_speech()

    async def _check_speech(self):
        """检查是否应该触发主动发言"""
        scene_info = self.scene_manager.get_scene_prompt_info(self._address)
        trigger = self.speech_engine.should_speak(
            accumulated_score=self.event_buffer.accumulated_score,
            silence_fallback=self.scene_manager.check_silence_fallback(),
            context_prompt=self.event_buffer.build_context_prompt(),
            scene_info=scene_info,
        )

        if trigger is not None:
            # 标记事件已消费，重置兴趣分
            consumed_events = self.event_buffer.consume_all()
            self.event_buffer.reset_score()
            self.speech_engine.on_speech_sent()
            self.scene_manager.on_speech_triggered()

            # 推入发言队列（由 WebSocket 层处理 LLM 生成）
            await self._speech_queue.put({
                "reason":          trigger.reason,
                "context_prompt":  trigger.context_prompt,
                "scene_info":      trigger.scene_info,
                "session_id":      self._session_id,
                "character_id":    self._character_id,
                "consumed_events": [
                    {
                        "id":          e.id,
                        "timestamp":   e.timestamp,
                        "scene_type":  e.scene_type,
                        "description": e.scene_description,
                        "game_name":   e.game_name,
                        "confidence":  e.confidence,
                        "score":       e.interest_score,
                    }
                    for e in consumed_events
                ],
            })

    # ── 用户主动截屏识别 ─────────────────────────────────────────

    async def capture_for_user(self) -> Optional[dict]:
        """
        用户主动请求观察屏幕时调用（细看模式）。
        返回 VLM 分析结果 dict，或 None（截屏/VLM 失败）。
        """
        screenshot = await asyncio.to_thread(capture_screen)
        if screenshot is None:
            return None

        if await asyncio.to_thread(is_blank_screen, screenshot):
            return {"error": "截屏失败（可能被反作弊系统拦截）"}

        process_info = await asyncio.to_thread(get_foreground_process_info)
        window_title = process_info.get("window_title", "")
        compressed   = await asyncio.to_thread(compress_for_vlm, screenshot)

        vlm_result = await self.vlm_client.analyze(
            img_bytes=compressed,
            window_title=window_title,
            prompt_type="user_triggered",
            prev_descriptions=self.event_buffer.get_recent_context(),
        )

        if vlm_result is None:
            return {"error": "视觉模型调用失败"}

        # 更新场景状态
        self.scene_manager.update(vlm_result, window_title)

        # 写入缓冲池（用户触发）
        self.event_buffer.push(
            interest_score=vlm_result.interest_score,
            scene_type=vlm_result.scene_type,
            scene_description=vlm_result.scene_description,
            game_name=vlm_result.game_name,
            confidence=vlm_result.confidence,
            source="vlm_user_triggered",
        )

        return {
            "app_name":         vlm_result.app_name,
            "scene_type":       vlm_result.scene_type,
            "game_name":        vlm_result.game_name,
            "game_genre":       vlm_result.game_genre,
            "confidence":       vlm_result.confidence,
            "interest_score":   vlm_result.interest_score,
            "scene_description": vlm_result.scene_description,
        }
