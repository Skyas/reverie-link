"""
视觉感知 · 主系统编排器（改进版，直接替换原 vision_system.py）
"""
import asyncio
import time
from typing import Optional

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
from vision.activity_monitor import ActivityMonitor, ActivityState
from vision.capture_strategy import CaptureStrategy

DEFAULT_CAPTURE_INTERVAL = 10


class VisionSystem:

    def __init__(self, speech_queue: asyncio.Queue):
        self._speech_queue = speech_queue
        self._enabled = False
        self._task: Optional[asyncio.Task] = None

        # 子模块
        self.vlm_client       = VLMClient()
        self.game_detector    = GameDetector()
        self.event_buffer     = EventBuffer()
        self.scene_manager    = SceneManager()
        self.speech_engine    = SpeechEngine()
        self.activity_monitor = ActivityMonitor()
        self.capture_strategy = CaptureStrategy()    # ← 之前漏了这行

        # 上一帧截图
        self._prev_screenshot: Optional[bytes] = None

        # 会话信息
        self._session_id:    str = ""
        self._character_id:  str = ""
        self._address:       str = "你"

        # 闲置行为
        self._last_idle_nudge_time: float = 0.0
        self._idle_nudge_interval: float = 300.0

    # ── 配置接口 ─────────────────────────────────────────────────

    def configure(self, cfg: dict):
        was_enabled = self._enabled
        self._enabled = bool(cfg.get("enabled", False))

        self.vlm_client.configure_vlm(
            base_url=cfg.get("vlm_base_url", ""),
            api_key=cfg.get("vlm_api_key", ""),
            model=cfg.get("vlm_model", "glm-4.6v-flash"),
        )
        self.speech_engine.set_talk_level(int(cfg.get("talk_level", 1)))
        self.speech_engine.set_cooldown(float(cfg.get("cooldown_seconds", 20)))
        self.game_detector.set_manual_game_mode(bool(cfg.get("manual_game_mode", False)))

        # VLM 预算（可选配置）
        if "vlm_budget_per_minute" in cfg:
            self.capture_strategy.vlm_budget_per_minute = int(cfg["vlm_budget_per_minute"])

        if self.game_detector.is_manual_game_mode():
            self.scene_manager.on_manual_reset()

        if not was_enabled and self._enabled:
            self._prev_screenshot = None
            self.event_buffer.reset_score()
            self.capture_strategy.reset()
            self.activity_monitor.start()
            print("[Vision] 视觉感知已启用（含活动监控）")
        elif was_enabled and not self._enabled:
            self.activity_monitor.stop()
            print("[Vision] 视觉感知已关闭")

    def set_session_info(self, session_id: str, character_id: str, address: str = "你"):
        self._session_id   = session_id
        self._character_id = character_id
        self._address      = address

    def set_main_llm(self, client, model: str):
        self.vlm_client.set_main_client(client, model)

    def on_user_message(self):
        self.speech_engine.on_user_message()
        self.speech_engine.set_user_interacting(True)
        
        # ---------------------------------------------------------
        # 【修改：温和的驱动力释放（动态减分）】
        # ---------------------------------------------------------
        # 1. 获取当前的话痨档位（兜底为 2 适中档）
        talk_level = getattr(self.speech_engine, '_talk_level', 2)
        
        # 2. 根据档位决定扣减的兴趣分：话痨扣得少，话少扣得多
        reduce_map = {
            3: 5,   # 话痨档：只减 5 分
            2: 8,   # 适中档：减 8 分
            1: 10   # 话少档：减 10 分
        }
        reduce_score = reduce_map.get(talk_level, 8)
        
        # 3. 执行减分，并确保最低跌到 0 分
        old_score = self.event_buffer.accumulated_score
        new_score = max(0, old_score - reduce_score)
        self.event_buffer.accumulated_score = new_score
        
        # 4. 但不管减多少分，刚刚碰巧堆积在“嘴边”的废话必须无情删掉，防抢话
        while not self._speech_queue.empty():
            try:
                self._speech_queue.get_nowait()
            except Exception:
                break
                
        print(f"[Vision] 🛑 用户主动互动，待发队列已清空。兴趣分冷却：{old_score} -> {new_score} (档位:{talk_level}, -{reduce_score})")

    def on_user_message_done(self):
        self.speech_engine.set_user_interacting(False)

    # ── 任务生命周期 ─────────────────────────────────────────────

    def start(self):
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._run_loop(), name="vision_loop")
        print("[Vision] 后台任务已启动")

    def stop(self):
        if self._task and not self._task.done():
            self._task.cancel()
            self._task = None
        self.activity_monitor.stop()
        print("[Vision] 后台任务已停止")

    # ── 主循环 ───────────────────────────────────────────────────

    async def _run_loop(self):
        while True:
            try:
                is_game = self.scene_manager.current_scene_type == "game"
                interval = self.activity_monitor.get_adaptive_interval(is_game)

                await asyncio.sleep(interval)

                if self._enabled:
                    await self._check_idle_behavior()
                    await self._process_frame()

            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[Vision] 主循环异常: {e}")
                await asyncio.sleep(DEFAULT_CAPTURE_INTERVAL)

    # ── 闲置行为 ─────────────────────────────────────────────────

    async def _check_idle_behavior(self):
        summary = self.activity_monitor.get_summary()
        now = time.time()

        if summary.state == ActivityState.TYPING:
            return

        if summary.state == ActivityState.IDLE:
            since_last_nudge = now - self._last_idle_nudge_time
            if since_last_nudge >= self._idle_nudge_interval:
                self._last_idle_nudge_time = now

                idle_trigger = {
                    "reason":          "idle_nudge",
                    "context_prompt":  summary.to_prompt_context(),
                    "scene_info": {
                        "scene_type":        "idle",
                        "scene_description": "",
                        "game_name":         None,
                        "game_genre":        None,
                        "confidence":        "high",
                        "player_state":      "unknown",
                        "scene_instruction": (
                            f"{self._address}已经很久没有操作了。"
                            f"你可以表达一下关心，"
                            f"比如问问是不是去忙别的了、要不要休息一下，"
                            f"或者自言自语表达等待的情绪。"
                            f"语气要自然随意，不要每次都一样。"
                        ),
                        "activity_context":  summary.to_prompt_context(),
                    },
                    "session_id":      self._session_id,
                    "character_id":    self._character_id,
                    "consumed_events": [],
                }
                await self._speech_queue.put(idle_trigger)
                self.scene_manager.on_speech_triggered()
                print(f"[Vision] 💤 闲置触发（{summary.idle_seconds:.0f}秒无操作）")

    # ── 帧处理 ───────────────────────────────────────────────────

    async def _process_frame(self):

        # ─ 1. 截屏 ──────────────────────────────────────────────
        screenshot = await asyncio.to_thread(capture_screen)
        if screenshot is None:
            return

        # ─ 2. 空白检测 ──────────────────────────────────────────
        if await asyncio.to_thread(is_blank_screen, screenshot):
            print("[Vision] 截屏为空白，跳过本帧")
            return

        # ─ 3. 像素差异 ─────────────────────────────────────────
        pixel_diff = 100.0  # 首帧默认 100
        if self._prev_screenshot is not None:
            pixel_diff = await asyncio.to_thread(
                compute_pixel_diff, self._prev_screenshot, screenshot
            )
        self._prev_screenshot = screenshot

        # ─ 4. CaptureStrategy 决定是否调 VLM ────────────────────
        should_call, reason = self.capture_strategy.should_call_vlm(
            pixel_diff=pixel_diff,
            is_first_frame=(pixel_diff >= 100.0),  # 首帧 pixel_diff 被设为 100
            has_current_scene=(self.scene_manager.current_result is not None),
        )

        if not should_call:
            if reason in ("static_frame", "boring_streak"):
                self.event_buffer.add_score(1)
            # budget_exceeded 不加分
            threshold = self.speech_engine._get_threshold()
            print(
                f"[Vision] ⏭ 跳过VLM（原因={reason}，像素差={pixel_diff:.1f}%）"
                f" 累计={self.event_buffer.accumulated_score}/{threshold}"
            )
            await self._check_speech()
            return

        # ─ 5. 前台进程信息 ──────────────────────────────────────
        process_info = await asyncio.to_thread(get_foreground_process_info)
        window_title = process_info.get("window_title", "")

        # ─ 6. 完整 vs 增量 ─────────────────────────────────────
        needs_full = self.scene_manager.needs_full_analysis(window_title, pixel_diff)
        prompt_type = "background" if needs_full else "incremental"

        # ─ 7. 压缩截图 ─────────────────────────────────────────
        compressed = await asyncio.to_thread(compress_for_vlm, screenshot)

        # ─ 8. 调用 VLM ─────────────────────────────────────────
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
            print(f"[Vision] ❌ VLM 失败（像素差={pixel_diff:.1f}%），跳过")
            return

        # ─ 8.5 通知 CaptureStrategy ─────────────────────────────
        self.capture_strategy.on_vlm_result(vlm_result.interest_score)

        # ─ 8.6 场景质变检测 ─────────────────────────────────────
        if vlm_result.scene_changed:
            print("[Vision] 🔄 检测到场景内切换，下一帧将完整重识别")
            self.scene_manager.on_manual_reset()

        # ─ 9. 游戏检测（保守策略：VLM 优先）────────────────
        detect = self.game_detector.detect(
            process_info=process_info,
            vlm_scene_type=vlm_result.scene_type,
            vlm_game_name=vlm_result.game_name,
        )
        if detect["is_game"]:
            if vlm_result.scene_type == "game":
                # VLM 和 game_detector 一致 → 补全游戏名
                if detect["game_name"] and not vlm_result.game_name:
                    vlm_result.game_name = detect["game_name"]
            elif vlm_result.confidence == "low":
                # VLM 不确定 → 允许 game_detector 覆盖
                vlm_result.scene_type = "game"
                if detect["game_name"] and not vlm_result.game_name:
                    vlm_result.game_name = detect["game_name"]
                print(f"[Vision] 🎮 game_detector 覆盖VLM（来源={detect['source']}，VLM置信=low）")
            else:
                # VLM 明确说不是游戏（medium/high）→ 信任 VLM
                print(f"[Vision] ℹ️ game_detector={detect['source']}认为是游戏，但VLM置信={vlm_result.confidence}判定为{vlm_result.scene_type}，以VLM为准")

        # 场景不是 game 时，清除残留的游戏字段
        if vlm_result.scene_type != "game":
            vlm_result.game_name = None
            vlm_result.game_genre = None

        # ─ 10. 更新场景管理器 ──────────────────────────────────
        self.scene_manager.update(vlm_result, window_title)

        # ─ 11. 写入事件缓冲池 ──────────────────────────────────
        self.event_buffer.push(
            interest_score=vlm_result.interest_score,
            scene_type=vlm_result.scene_type,
            scene_description=vlm_result.scene_description,
            game_name=vlm_result.game_name,
            confidence=vlm_result.confidence,
            source="vlm_background",
        )

        threshold = self.speech_engine._get_threshold()
        game_str = f"《{vlm_result.game_name}》" if vlm_result.game_name else ""
        activity = self.activity_monitor.get_summary()
        stats = self.capture_strategy.get_stats()
        print(
            f"[Vision] 🔍 VLM分析（像素差={pixel_diff:.1f}%，{prompt_type}）"
            f" 场景={vlm_result.scene_type}{game_str}"
            f" 置信={vlm_result.confidence}"
            f" 兴趣={vlm_result.interest_score}"
            f" 累计={self.event_buffer.accumulated_score}/{threshold}"
            f" 活动={activity.state.value}"
            f" VLM次数={stats['total_vlm_calls']}"
            f"\n         描述: {vlm_result.scene_description}"
        )

        # ─ 12. 发言决策 ────────────────────────────────────────
        await self._check_speech()

    # ── 发言决策 ─────────────────────────────────────────────────

    async def _check_speech(self):
        activity = self.activity_monitor.get_summary()

        if activity.state == ActivityState.TYPING and activity.state_duration > 10:
            return

        scene_info = self._build_enhanced_scene_info(activity)

        trigger = self.speech_engine.should_speak(
            accumulated_score=self.event_buffer.accumulated_score,
            silence_fallback=self.scene_manager.check_silence_fallback(),
            context_prompt=self.event_buffer.build_context_prompt(),
            scene_info=scene_info,
        )

        if trigger is not None:
            print(
                f"[Vision] 💬 触发发言！原因={trigger.reason}"
                f" 场景={scene_info.get('scene_type')}"
                f" 活动={activity.state.value}"
            )
            consumed_events = self.event_buffer.consume_all()
            self.event_buffer.reset_score()
            self.speech_engine.on_speech_sent()
            self.scene_manager.on_speech_triggered()

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

    def _build_enhanced_scene_info(self, activity) -> dict:
        result = self.scene_manager.current_result
        address = self._address

        if result is None:
            return {
                "scene_type": "unknown",
                "scene_description": "",
                "game_name": None,
                "game_genre": None,
                "confidence": "low",
                "player_state": "unknown",
                "scene_instruction": (
                    f"你不确定{address}在做什么。"
                    f"可以好奇地自言自语，或者表达等待的心情。"
                ),
                "activity_context": activity.to_prompt_context(),
            }

        scene_type = result.scene_type
        confidence = result.confidence
        desc = result.scene_description or ""
        player_state = getattr(result, 'player_state', 'unknown')

        # ── 低置信度 ─────────────────────────────────────────
        if confidence == "low":
            instruction = (
                f"你不太确定{address}在做什么。"
            )
            if desc:
                instruction += f"画面大致是：{desc}。"
            instruction += f"不要断言{address}的行为，可以好奇地问一句或自言自语。"

        # ── 游戏场景 ─────────────────────────────────────────
        elif scene_type == "game":
            game_ctx = result.game_name or "某个游戏"
            genre_ctx = f"（{result.game_genre}）" if result.game_genre else ""

            # 根据 player_state 调整
            if player_state == "spectating":
                state_hint = (
                    f"{address}的角色可能已死亡或在观战。"
                    f"画面里不是{address}在操作。"
                )
            elif player_state == "in_menu":
                state_hint = f"{address}在看菜单/商店界面。"
            elif player_state == "cutscene":
                state_hint = "正在播放过场动画/剧情。"
            elif player_state == "waiting":
                state_hint = f"{address}在等待（加载/匹配/复活）。"
            else:
                # playing 或 unknown
                activity_hint = ""
                if activity.state == ActivityState.INTENSE:
                    activity_hint = f"{address}操作非常频繁，看起来正处于紧张时刻。"
                elif activity.state == ActivityState.PASSIVE:
                    activity_hint = f"{address}似乎在等待或观看。"
                state_hint = activity_hint

            instruction = (
                f"{address}正在玩{game_ctx}{genre_ctx}。"
                f"当前画面：{desc}。"
                f"{state_hint}"
                f"请根据【当前屏幕观测摘要】中的具体画面内容做出反应。"
                f"重要：不要说泛泛的鼓励（如'加油''好厉害'），"
                f"要针对你实际看到的东西评论。"
                f"回复风格要随机变化——有时一个语气词，有时一句吐槽，"
                f"有时一段分析，有时只是发出惊叹。绝不要重复相同的句式。"
            )

        # ── 视频 ─────────────────────────────────────────────
        elif scene_type == "video":
            instruction = (
                f"{address}正在看视频。画面内容：{desc}。"
                f"可以对画面内容做轻松自然的反应，不用每次都评论。"
            )

        # ── 工作 ─────────────────────────────────────────────
        elif scene_type == "work":
            typing_hint = ""
            if activity.state == ActivityState.TYPING:
                typing_hint = f"{address}正在专注打字，不要打扰。"
            instruction = (
                f"{address}正在工作。{typing_hint}"
                f"不要评论工作内容。只在合适的时候做关怀式提醒，"
                f"比如久坐提醒、喝水提醒。但不要太频繁。"
            )

        # ── 浏览 ─────────────────────────────────────────────
        elif scene_type == "browsing":
            instruction = (
                f"{address}正在浏览网页。{desc}。"
                f"可以轻松地聊几句，但不要对每个网页都评论。"
            )

        # ── 其他 ─────────────────────────────────────────────
        else:
            instruction = (
                f"{address}似乎不在屏幕前。"
                f"{activity.to_prompt_context()}"
                f"你可以自言自语或表达等待的情绪。"
            )

        return {
            "scene_type":        scene_type,
            "scene_description": desc,
            "game_name":         result.game_name,
            "game_genre":        result.game_genre,
            "confidence":        confidence,
            "player_state":      player_state,
            "scene_instruction": instruction,
            "activity_context":  activity.to_prompt_context(),
        }

    # ── 用户主动截屏 ─────────────────────────────────────────────

    @property
    def is_main_multimodal(self) -> bool:
        """主模型是否支持多模态（用于决定截屏走直传还是走VLM中转）"""
        return self.vlm_client._main_is_multimodal()

    async def capture_screenshot_only(self) -> Optional[dict]:
        """
        仅截屏+压缩，不调 VLM。
        用于多模态主模型场景：图片直接嵌入 LLM 消息，跳过 VLM 中间步骤。
        返回 {"img_b64": str, "window_title": str} 或 {"error": str} 或 None。
        """
        import base64

        screenshot = await asyncio.to_thread(capture_screen)
        if screenshot is None:
            return None

        if await asyncio.to_thread(is_blank_screen, screenshot):
            return {"error": "截屏失败（可能被反作弊系统拦截）"}

        process_info = await asyncio.to_thread(get_foreground_process_info)
        window_title = process_info.get("window_title", "")
        compressed   = await asyncio.to_thread(compress_for_vlm, screenshot)
        img_b64      = base64.b64encode(compressed).decode()

        return {
            "img_b64":      img_b64,
            "window_title": window_title,
        }

    async def capture_for_user(self) -> Optional[dict]:
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

        self.scene_manager.update(vlm_result, window_title)
        self.event_buffer.push(
            interest_score=vlm_result.interest_score,
            scene_type=vlm_result.scene_type,
            scene_description=vlm_result.scene_description,
            game_name=vlm_result.game_name,
            confidence=vlm_result.confidence,
            source="vlm_user_triggered",
        )

        return {
            "app_name":          vlm_result.app_name,
            "scene_type":        vlm_result.scene_type,
            "game_name":         vlm_result.game_name,
            "game_genre":        vlm_result.game_genre,
            "confidence":        vlm_result.confidence,
            "interest_score":    vlm_result.interest_score,
            "scene_description": vlm_result.scene_description,
        }