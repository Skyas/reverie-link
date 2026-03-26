"""
视觉感知 · 事件缓冲池（改进版，直接替换原 event_buffer.py）

改进点：
  1. 新增 add_score() 方法：只累加兴趣分，不创建事件。
     用于 pixel_skip / static_frame 等无 VLM 分析的帧，
     避免产生大量空描述事件污染聊天 AI 的上下文。
"""
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


def _gen_event_id() -> str:
    now = datetime.now(timezone.utc)
    rand = format(random.randint(0, 0xFFFF), "04x")
    return f"evt_{now.strftime('%Y%m%d_%H%M%S')}_{rand}"


@dataclass
class VisionEvent:
    id: str
    timestamp: float           # time.time()
    interest_score: int        # 1~15
    scene_type: str            # game|video|work|browsing|idle|unknown
    scene_description: str
    game_name: Optional[str]
    confidence: str            # high|medium|low
    consumed: bool = False
    source: str = "vlm"        # vlm_background|vlm_user_triggered|pixel_skip

    def to_context_line(self) -> str:
        """转为注入 Prompt 的单行摘要"""
        dt = datetime.fromtimestamp(self.timestamp)
        ts = dt.strftime("%H:%M:%S")
        desc = self.scene_description or "无描述"
        return f"[{ts}] {desc}（兴趣分 +{self.interest_score}）"


class EventBuffer:
    """
    事件缓冲池。
    - 累积兴趣分
    - 保留最近 N 条已消费事件作为连续帧上下文
    """

    # 已消费事件保留数量（用于下次 VLM 分析的前文）
    _CONTEXT_KEEP = 3

    def __init__(self):
        self._events: list[VisionEvent] = []
        self._accumulated_score: int = 0

    @property
    def accumulated_score(self) -> int:
        return self._accumulated_score

    # ── 改进：只加分不加事件 ─────────────────────────────────────

    def add_score(self, score: int):
        """
        只累加兴趣分，不创建事件。

        用于 pixel_skip / static_frame 等无 VLM 分析的帧。
        这些帧没有 scene_description，如果也 push 进事件列表，
        会产生大量 "[14:02:30] 无描述（兴趣分 +1）" 的垃圾条目，
        污染 build_context_prompt() 输出给聊天 AI 的上下文。

        只加分可以正常推进发言触发（兴趣分累积），
        同时保持上下文干净（只包含有实际描述的 VLM 事件）。
        """
        self._accumulated_score += score

    # ── 以下与原版完全一致 ───────────────────────────────────────

    def push(
    self,
    interest_score: int,
    scene_type: str,
    scene_description: str,
    game_name: Optional[str],
    confidence: str,
    source: str = "vlm_background",
    ) -> Optional[VisionEvent]:       # ← 返回类型从 VisionEvent 改为 Optional
        """
        添加一条新事件，并累积兴趣分。
        改进：如果描述和上一条高度相似，只加分不加事件，防止重复上下文污染 LLM。
        """
        if scene_type == "work":
            scene_description = "用户正在工作"

        # ── 去重：和最近一条有描述的事件比较 ─────────────────────
        if scene_description and self._events:
            last_with_desc = None
            for e in reversed(self._events):
                if e.scene_description:
                    last_with_desc = e
                    break
            if last_with_desc and self._is_similar(scene_description, last_with_desc.scene_description):
                # 描述太像，只加分不加事件
                self._accumulated_score += interest_score
                return None

        evt = VisionEvent(
            id=_gen_event_id(),
            timestamp=time.time(),
            interest_score=interest_score,
            scene_type=scene_type,
            scene_description=scene_description,
            game_name=game_name,
            confidence=confidence,
            consumed=False,
           source=source,
        )
        self._events.append(evt)
        self._accumulated_score += interest_score
        return evt

    @staticmethod
    def _is_similar(a: str, b: str) -> bool:
        """
        简单的字符串相似度判断。
        不用复杂的算法——VLM 重复时描述几乎一模一样，
        只要检查共同字符比例就够了。
        """
        if not a or not b:
            return False
        # 短文本直接比较
        if a == b:
            return True
        # 用字符集合的 Jaccard 相似度
        # 把描述拆成2-gram（连续两个字）比较
        def bigrams(s):
            return set(s[i:i+2] for i in range(len(s) - 1))
        bg_a = bigrams(a)
        bg_b = bigrams(b)
        if not bg_a or not bg_b:
            return a == b
        intersection = len(bg_a & bg_b)
        union = len(bg_a | bg_b)
        similarity = intersection / union
        return similarity > 0.7    # 70% 以上相似就认为是重复

    def get_unconsumed(self) -> list[VisionEvent]:
        """获取所有未消费事件"""
        return [e for e in self._events if not e.consumed]

    def get_recent_context(self) -> list[str]:
        """获取最近已消费事件的描述，用于 VLM 连续帧前文"""
        consumed = [e for e in self._events if e.consumed]
        recent = consumed[-self._CONTEXT_KEEP:]
        return [e.scene_description for e in recent if e.scene_description]

    def consume_all(self) -> list[VisionEvent]:
        """标记所有未消费事件为已消费，返回这批事件（用于写入时间线）"""
        batch = self.get_unconsumed()
        for e in batch:
            e.consumed = True
        return batch

    def reset_score(self):
        """兴趣分计数器清零（发言后调用）"""
        self._accumulated_score = 0

    def build_context_prompt(self) -> str:
        """
        将未消费事件摘要打包为 Prompt 上下文字符串。
        格式参考设计文档 § 9。
        """
        unconsumed = self.get_unconsumed()
        if not unconsumed:
            return ""
        lines = [e.to_context_line() for e in unconsumed]
        return "【当前屏幕观测摘要】\n" + "\n".join(lines)

    def prune_old(self, max_keep: int = 30):
        """清理过旧的事件（只保留最近 max_keep 条）"""
        if len(self._events) > max_keep:
            self._events = self._events[-max_keep:]