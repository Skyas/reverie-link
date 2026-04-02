"""
prompt_builder.py — 纯 re-export 入口（约 20 行）

所有实现已迁移至 sidecar/prompt/ 子包：
  prompt/constants.py     — 常量与短语池
  prompt/system_prompt.py — 角色定义 + 记忆层 + 时间注入
  prompt/messages.py      — 所有 messages 列表组装函数

此文件保持不变，外部所有 `from prompt_builder import ...` 语句无需修改。
"""

# ── 常量 ──────────────────────────────────────────────────────────────────
from prompt.constants import (
    DEFAULT_CHARACTER,
    WINDOW_PRESETS,
    DEFAULT_WINDOW_INDEX,
)

# ── System Prompt 组装 ────────────────────────────────────────────────────
from prompt.system_prompt import build_system_prompt

# ── Messages 列表组装 ─────────────────────────────────────────────────────
from prompt.messages import (
    trim_history,
    build_messages,
    build_screenshot_messages,
    build_multimodal_screenshot_messages,
    build_vision_speech_messages,
)

__all__ = [
    "DEFAULT_CHARACTER",
    "WINDOW_PRESETS",
    "DEFAULT_WINDOW_INDEX",
    "build_system_prompt",
    "trim_history",
    "build_messages",
    "build_screenshot_messages",
    "build_multimodal_screenshot_messages",
    "build_vision_speech_messages",
]