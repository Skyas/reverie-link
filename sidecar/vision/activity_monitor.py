"""
视觉感知 · 本地活动监控器

零成本、实时的用户行为感知层。
不依赖 VLM，通过键鼠活动推断用户状态，驱动：
  - 自适应截屏间隔（游戏激烈时缩短，闲置时拉长）
  - 基础行为触发（打字忙碌时安静，长时间不动时"戳"用户）
  - 为 VLM 分析提供辅助上下文（"用户最近30秒疯狂点击"）

依赖：pynput（pip install pynput）
"""
import time
import threading
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Callable


# ── 用户活动状态 ─────────────────────────────────────────────────

class ActivityState(Enum):
    IDLE       = "idle"        # 无操作 > 2分钟
    PASSIVE    = "passive"     # 偶尔动一下（看视频、阅读）
    TYPING     = "typing"      # 持续键盘输入（工作/聊天）
    CLICKING   = "clicking"    # 稳定鼠标操作（浏览/办公）
    INTENSE    = "intense"     # 高频键鼠混合（游戏激烈操作）


# ── 活动快照（每秒采样一次）────────────────────────────────────

@dataclass
class ActivitySnapshot:
    timestamp: float = 0.0
    keys_per_sec: float = 0.0
    clicks_per_sec: float = 0.0
    mouse_distance: float = 0.0     # 像素距离
    scroll_count: int = 0


# ── 活动状态摘要（供外部使用）──────────────────────────────────

@dataclass
class ActivitySummary:
    state: ActivityState = ActivityState.IDLE
    state_duration: float = 0.0           # 当前状态持续秒数
    avg_keys_per_sec: float = 0.0         # 近30秒平均
    avg_clicks_per_sec: float = 0.0
    avg_mouse_speed: float = 0.0
    peak_actions_per_sec: float = 0.0     # 近30秒峰值（键+点击）
    idle_seconds: float = 0.0             # 距上次任意输入的秒数
    description: str = ""                 # 自然语言描述，可注入 prompt

    def to_prompt_context(self) -> str:
        """生成可注入聊天 AI prompt 的活动描述"""
        if self.state == ActivityState.IDLE:
            mins = int(self.idle_seconds // 60)
            if mins > 0:
                return f"用户已经{mins}分钟没有任何操作了。"
            return f"用户已经{int(self.idle_seconds)}秒没有操作了。"
        elif self.state == ActivityState.TYPING:
            return f"用户正在快速打字（{self.avg_keys_per_sec:.0f}键/秒），看起来很忙。"
        elif self.state == ActivityState.INTENSE:
            return f"用户操作非常频繁（{self.peak_actions_per_sec:.0f}次/秒峰值），可能正在激烈游戏中。"
        elif self.state == ActivityState.CLICKING:
            return f"用户在稳定地点击和移动鼠标。"
        else:  # PASSIVE
            return f"用户偶尔有操作，可能在看视频或阅读。"


# ── 自适应截屏间隔建议 ──────────────────────────────────────────

# 根据活动状态动态调整截屏间隔
ADAPTIVE_INTERVALS = {
    ActivityState.IDLE:     30,    # 闲置时 30 秒一帧，省资源
    ActivityState.PASSIVE:  15,    # 被动观看 15 秒
    ActivityState.TYPING:   20,    # 打字工作 20 秒（工作场景不需要频繁看）
    ActivityState.CLICKING: 10,    # 普通点击 10 秒
    ActivityState.INTENSE:   4,    # 激烈操作 4 秒（游戏关键时刻）
}

# 游戏模式下的覆盖间隔（当 scene_type == "game" 时使用）
GAME_ADAPTIVE_INTERVALS = {
    ActivityState.IDLE:     15,    # 游戏里闲置（可能暂停/加载）
    ActivityState.PASSIVE:  10,    # 游戏里被动（等待/过场）
    ActivityState.TYPING:   10,    # 游戏里打字（聊天）
    ActivityState.CLICKING:  6,    # 游戏里稳定操作（策略类/探索）
    ActivityState.INTENSE:   3,    # 游戏里激烈操作（团战/boss）
}


class ActivityMonitor:
    """
    本地键鼠活动监控器。

    启动后在后台线程中监听键盘和鼠标事件，
    每秒生成一个 ActivitySnapshot，维护滑动窗口，
    对外提供 ActivitySummary。
    """

    # 滑动窗口大小（秒）
    _WINDOW_SIZE = 30

    # 状态判定阈值
    _IDLE_THRESHOLD = 120.0        # 无操作 > 120秒 = IDLE
    _PASSIVE_THRESHOLD = 15.0      # 无操作 > 15秒 = PASSIVE
    _TYPING_KPS = 2.0              # 键盘 > 2键/秒 且 点击少 = TYPING
    _INTENSE_APS = 4.0             # 键+点击 > 4次/秒 = INTENSE
    _CLICKING_CPS = 0.5            # 点击 > 0.5次/秒 = CLICKING

    def __init__(self):
        self._snapshots: deque[ActivitySnapshot] = deque(maxlen=self._WINDOW_SIZE)
        self._lock = threading.Lock()

        # 实时计数器（在监听回调中累加，每秒采样后清零）
        self._key_count = 0
        self._click_count = 0
        self._scroll_count = 0
        self._mouse_distance = 0.0
        self._last_mouse_pos: Optional[tuple] = None
        self._last_any_input_time: float = time.time()

        # 状态追踪
        self._current_state = ActivityState.IDLE
        self._state_start_time: float = time.time()

        # 后台线程
        self._running = False
        self._sampler_thread: Optional[threading.Thread] = None
        self._listeners = []

    # ── 生命周期 ────────────────────────────────────────────────

    def start(self):
        """启动监听（非阻塞）"""
        if self._running:
            return
        self._running = True

        # 启动 pynput 监听器
        try:
            from pynput import keyboard, mouse

            kb_listener = keyboard.Listener(on_press=self._on_key)
            ms_listener = mouse.Listener(
                on_move=self._on_mouse_move,
                on_click=self._on_click,
                on_scroll=self._on_scroll,
            )
            kb_listener.daemon = True
            ms_listener.daemon = True
            kb_listener.start()
            ms_listener.start()
            self._listeners = [kb_listener, ms_listener]
        except ImportError:
            print("[ActivityMonitor] pynput 未安装，键鼠监听不可用。"
                  "请 pip install pynput")
            self._running = False
            return

        # 启动每秒采样线程
        self._sampler_thread = threading.Thread(
            target=self._sampler_loop, daemon=True
        )
        self._sampler_thread.start()
        print("[ActivityMonitor] 已启动")

    def stop(self):
        """停止监听"""
        self._running = False
        for listener in self._listeners:
            listener.stop()
        self._listeners = []
        print("[ActivityMonitor] 已停止")

    # ── pynput 回调（在监听线程中执行）──────────────────────────

    def _on_key(self, key):
        self._key_count += 1
        self._last_any_input_time = time.time()

    def _on_click(self, x, y, button, pressed):
        if pressed:
            self._click_count += 1
            self._last_any_input_time = time.time()

    def _on_scroll(self, x, y, dx, dy):
        self._scroll_count += 1
        self._last_any_input_time = time.time()

    def _on_mouse_move(self, x, y):
        self._last_any_input_time = time.time()
        if self._last_mouse_pos is not None:
            dx = x - self._last_mouse_pos[0]
            dy = y - self._last_mouse_pos[1]
            self._mouse_distance += (dx**2 + dy**2) ** 0.5
        self._last_mouse_pos = (x, y)

    # ── 每秒采样 ────────────────────────────────────────────────

    def _sampler_loop(self):
        """每秒采样一次，将计数器转为快照"""
        while self._running:
            time.sleep(1.0)
            snap = ActivitySnapshot(
                timestamp=time.time(),
                keys_per_sec=self._key_count,
                clicks_per_sec=self._click_count,
                mouse_distance=self._mouse_distance,
                scroll_count=self._scroll_count,
            )
            # 清零计数器
            self._key_count = 0
            self._click_count = 0
            self._scroll_count = 0
            self._mouse_distance = 0.0

            with self._lock:
                self._snapshots.append(snap)

    # ── 对外接口 ────────────────────────────────────────────────

    def get_summary(self) -> ActivitySummary:
        """获取当前活动状态摘要"""
        with self._lock:
            snaps = list(self._snapshots)

        now = time.time()
        idle_secs = now - self._last_any_input_time

        if not snaps:
            state = ActivityState.IDLE
            return ActivitySummary(
                state=state,
                state_duration=now - self._state_start_time,
                idle_seconds=idle_secs,
            )

        # 计算窗口内平均值
        n = len(snaps)
        avg_kps = sum(s.keys_per_sec for s in snaps) / n
        avg_cps = sum(s.clicks_per_sec for s in snaps) / n
        avg_mouse = sum(s.mouse_distance for s in snaps) / n
        peak_aps = max(s.keys_per_sec + s.clicks_per_sec for s in snaps)

        # 判定状态
        state = self._classify_state(idle_secs, avg_kps, avg_cps, peak_aps)

        # 状态变化时更新计时
        if state != self._current_state:
            self._current_state = state
            self._state_start_time = now

        summary = ActivitySummary(
            state=state,
            state_duration=now - self._state_start_time,
            avg_keys_per_sec=avg_kps,
            avg_clicks_per_sec=avg_cps,
            avg_mouse_speed=avg_mouse,
            peak_actions_per_sec=peak_aps,
            idle_seconds=idle_secs,
        )
        summary.description = summary.to_prompt_context()
        return summary

    def get_adaptive_interval(self, is_game: bool = False) -> float:
        """根据当前活动状态返回建议的截屏间隔（秒）"""
        summary = self.get_summary()
        table = GAME_ADAPTIVE_INTERVALS if is_game else ADAPTIVE_INTERVALS
        return table.get(summary.state, 10)

    def _classify_state(
        self,
        idle_secs: float,
        avg_kps: float,
        avg_cps: float,
        peak_aps: float,
    ) -> ActivityState:
        """根据指标判定用户活动状态"""
        # 优先判 IDLE
        if idle_secs > self._IDLE_THRESHOLD:
            return ActivityState.IDLE

        # 长时间无操作但未达 IDLE
        if idle_secs > self._PASSIVE_THRESHOLD:
            return ActivityState.PASSIVE

        # 高频混合操作 → INTENSE
        if peak_aps >= self._INTENSE_APS:
            return ActivityState.INTENSE

        # 持续打字 → TYPING
        if avg_kps >= self._TYPING_KPS and avg_cps < self._CLICKING_CPS:
            return ActivityState.TYPING

        # 稳定点击 → CLICKING
        if avg_cps >= self._CLICKING_CPS:
            return ActivityState.CLICKING

        # 有零星操作 → PASSIVE
        return ActivityState.PASSIVE