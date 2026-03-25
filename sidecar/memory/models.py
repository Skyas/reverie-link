"""
Reverie Link · 记忆系统 — 数据结构定义

定义统一时间线中所有消息/事件的数据模型。
这是整个记忆系统的基础，所有模块共享同一套结构。

参考文档：PHASE3_MEMORY_DESIGN.md § 2
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


# ── 消息类型枚举 ──────────────────────────────────────────────────

class MessageType(str, Enum):
    """统一时间线中的消息类型"""
    USER_TEXT   = "user_text"       # 用户文字输入
    USER_VOICE  = "user_voice"      # 用户语音输入（STT 转写后的文字）
    AI_REPLY    = "ai_reply"        # AI 回复（剥离情绪标签后的纯文本）
    GAME_EVENT  = "game_event"      # 游戏感知事件（VLM 精简摘要）
    SYSTEM_NOTE = "system_note"     # 系统标记


class NotebookSource(str, Enum):
    """笔记本条目来源"""
    MANUAL = "manual"   # 用户手动添加（我的备忘录）
    AUTO   = "auto"     # AI 自动提取（角色的日记本）


# ── ID 生成器 ─────────────────────────────────────────────────────

def generate_msg_id() -> str:
    """
    生成消息唯一标识。
    格式：msg_{YYYYMMDD}_{HHmmss}_{4位随机hex}
    示例：msg_20250325_143022_a7f3
    """
    now = datetime.now(timezone.utc)
    date_part = now.strftime("%Y%m%d")
    time_part = now.strftime("%H%M%S")
    rand_part = format(random.randint(0, 0xFFFF), "04x")
    return f"msg_{date_part}_{time_part}_{rand_part}"


def generate_session_id() -> str:
    """
    生成会话标识。每次程序启动或 WS 重连时调用。
    格式：session_{YYYYMMDD}_{HHmm}_{4位随机hex}
    示例：session_20250325_1430_b2e1
    """
    now = datetime.now(timezone.utc)
    date_part = now.strftime("%Y%m%d")
    time_part = now.strftime("%H%M")
    rand_part = format(random.randint(0, 0xFFFF), "04x")
    return f"session_{date_part}_{time_part}_{rand_part}"


def generate_entry_id() -> str:
    """
    生成笔记本条目唯一标识。
    格式：entry_{YYYYMMDD}_{HHmmss}_{4位随机hex}
    """
    now = datetime.now(timezone.utc)
    date_part = now.strftime("%Y%m%d")
    time_part = now.strftime("%H%M%S")
    rand_part = format(random.randint(0, 0xFFFF), "04x")
    return f"entry_{date_part}_{time_part}_{rand_part}"


def generate_summary_id() -> str:
    """
    生成向量摘要唯一标识。
    格式：summary_{YYYYMMDD}_{HHmmss}_{4位随机hex}
    """
    now = datetime.now(timezone.utc)
    date_part = now.strftime("%Y%m%d")
    time_part = now.strftime("%H%M%S")
    rand_part = format(random.randint(0, 0xFFFF), "04x")
    return f"summary_{date_part}_{time_part}_{rand_part}"


def now_iso() -> str:
    """返回当前时间的 ISO 8601 字符串（UTC，精确到毫秒）"""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


# ── 消息数据模型 ──────────────────────────────────────────────────

@dataclass
class TimelineMessage:
    """
    统一时间线中的一条消息/事件。
    对应 PHASE3_MEMORY_DESIGN.md § 2 定义的结构。

    所有通道（文字、语音、游戏事件）共享此结构，
    通过 type 字段区分来源。

    character_id 绑定角色卡（preset.id），确保不同角色的记忆完全隔离。
    """
    id: str                                 # 唯一标识
    timestamp: str                          # ISO 8601 UTC
    type: MessageType                       # 消息类型
    content: str                            # 消息正文
    reply_to: Optional[str] = None          # 关联消息 id
    metadata: dict[str, Any] = field(default_factory=dict)
    session_id: str = ""                    # 所属会话
    character_id: str = ""                  # 绑定角色卡 preset.id（Phase 3 角色隔离）

    @classmethod
    def create(
        cls,
        msg_type: MessageType,
        content: str,
        session_id: str,
        character_id: str = "",
        reply_to: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> TimelineMessage:
        """工厂方法：自动填充 id 和 timestamp"""
        return cls(
            id=generate_msg_id(),
            timestamp=now_iso(),
            type=msg_type,
            content=content,
            reply_to=reply_to,
            metadata=metadata or {},
            session_id=session_id,
            character_id=character_id,
        )

    def to_dict(self) -> dict:
        """转为可序列化的 dict"""
        d = asdict(self)
        d["type"] = self.type.value
        return d

    def to_history_entry(self) -> Optional[dict]:
        """
        转为 LLM messages 格式的 history 条目。
        仅 user_text / user_voice / ai_reply 可转换，
        其他类型返回 None。
        """
        if self.type in (MessageType.USER_TEXT, MessageType.USER_VOICE):
            return {"role": "user", "content": self.content}
        elif self.type == MessageType.AI_REPLY:
            return {"role": "assistant", "content": self.content}
        return None

    def to_timeline_display(self) -> str:
        """
        转为注入 Prompt 的时间线格式文本。
        包含时间戳和类型标记，便于 AI 理解上下文时序。
        """
        ts_short = self.timestamp[:19].replace("T", " ")

        if self.type in (MessageType.USER_TEXT, MessageType.USER_VOICE):
            channel = "语音" if self.type == MessageType.USER_VOICE else "文字"
            return f"[{ts_short}] 用户({channel}): {self.content}"
        elif self.type == MessageType.AI_REPLY:
            return f"[{ts_short}] 你回复: {self.content}"
        elif self.type == MessageType.GAME_EVENT:
            return f"[{ts_short}] [游戏画面] {self.content}"
        elif self.type == MessageType.SYSTEM_NOTE:
            return f"[{ts_short}] [系统] {self.content}"
        return f"[{ts_short}] {self.content}"


# ── 笔记本条目数据模型 ────────────────────────────────────────────

@dataclass
class NotebookEntry:
    """
    笔记本中的一条记忆条目。
    对应 PHASE3_MEMORY_DESIGN.md § 5 定义的结构。

    character_id 绑定角色卡，确保不同角色的笔记本完全隔离。
    """
    id: str                         # 唯一标识
    source: NotebookSource          # 来源：manual | auto
    content: str                    # 条目正文
    tags: list[str]                 # 标签列表
    created_at: str                 # ISO 8601
    updated_at: str                 # ISO 8601
    character_id: str = ""          # 绑定角色卡 preset.id（Phase 3 角色隔离）

    @classmethod
    def create(
        cls,
        source: NotebookSource,
        content: str,
        tags: list[str],
        character_id: str = "",
    ) -> NotebookEntry:
        """工厂方法：自动填充 id 和时间"""
        ts = now_iso()
        return cls(
            id=generate_entry_id(),
            source=source,
            content=content,
            tags=tags,
            created_at=ts,
            updated_at=ts,
            character_id=character_id,
        )

    def to_dict(self) -> dict:
        d = asdict(self)
        d["source"] = self.source.value
        return d


# ── 滑动窗口档位配置 ──────────────────────────────────────────────

@dataclass(frozen=True)
class WindowPreset:
    """滑动窗口档位"""
    name: str               # 档位显示名称
    minutes: int            # 时间窗口（分钟）
    max_rounds: int         # 最大对话轮数
    est_tokens: int         # 预估 Token 消耗

# 5 档预设（对应 PHASE3_MEMORY_DESIGN.md § 4）
WINDOW_PRESETS: list[WindowPreset] = [
    WindowPreset(name="极速省流", minutes=3,  max_rounds=5,  est_tokens=2000),
    WindowPreset(name="均衡",     minutes=8,  max_rounds=12, est_tokens=5000),
    WindowPreset(name="沉浸",     minutes=15, max_rounds=20, est_tokens=8000),
    WindowPreset(name="深度",     minutes=20, max_rounds=28, est_tokens=11000),
    WindowPreset(name="极限",     minutes=25, max_rounds=35, est_tokens=14000),
]

# 默认档位索引（均衡）
DEFAULT_WINDOW_INDEX = 1