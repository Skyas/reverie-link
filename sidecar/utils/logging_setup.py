"""
Reverie Link · 日志系统统一配置

在 main.py lifespan 最早位置调用 setup_logging()，所有子模块在 import 时
拿到的 logger 自动继承根配置，无需感知配置细节。

日志文件路径：
    data/logs/
    ├── sidecar_2026-04-14.log         ← INFO 及以上，按天滚动，保留 14 天
    └── sidecar_2026-04-14.debug.log   ← DEBUG 及以上，按天滚动，保留 3 天

格式：2026-04-14 14:30:22.156 | INFO  | ws.vision_speech | [VisionSpeech] 主动发言已发送 | 长度=18 情绪=shy
"""

import logging
import os
import sys
from logging.handlers import TimedRotatingFileHandler

# ── 日志目录（相对于 sidecar 根目录）────────────────────────────────────────
_SIDECAR_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LOG_DIR = os.path.join(_SIDECAR_ROOT, "data", "logs")

# ── 全局格式器 ──────────────────────────────────────────────────────────────
_LOG_FORMAT = (
    "%(asctime)s | %(levelname)-5s | %(module)s | %(message)s"
)
_DEBUG_FORMAT = (
    "%(asctime)s | %(levelname)-5s | %(name)s | %(message)s"
)
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def _ensure_log_dir() -> None:
    """首次运行时自动创建日志目录（幂等）"""
    os.makedirs(_LOG_DIR, exist_ok=True)


def setup_logging() -> None:
    """
    统一配置 logging：
      - 控制台 handler（INFO 级别，开发期友好）
      - 文件 handler（INFO 级别，按天滚动，保留 14 天）
      - 调试文件 handler（DEBUG 级别，按天滚动，保留 3 天）
      - 格式：时间 | 级别 | 模块 | 消息
    """
    _ensure_log_dir()

    # ── 根 logger 配置 ────────────────────────────────────────────────
    root_logger = logging.getLogger()
    # 避免重复注册（IPython / notebook 环境多次调用时保护）
    if root_logger.handlers:
        return
    root_logger.setLevel(logging.DEBUG)  # 所有级别都接收，由 handler 过滤

    # ── 控制台 handler（INFO，只在非 test 环境输出）────────────────
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT))
    root_logger.addHandler(console)

    # ── 主日志文件 handler（INFO，按天滚动，保留 14 天）────────────
    info_handler = TimedRotatingFileHandler(
        os.path.join(_LOG_DIR, "sidecar.log"),
        when="midnight",
        interval=1,
        backupCount=14,
        encoding="utf-8",
    )
    info_handler.setLevel(logging.INFO)
    info_handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT))
    root_logger.addHandler(info_handler)

    # ── 调试日志文件 handler（DEBUG，按天滚动，保留 3 天）─────────
    debug_handler = TimedRotatingFileHandler(
        os.path.join(_LOG_DIR, "sidecar.debug.log"),
        when="midnight",
        interval=1,
        backupCount=3,
        encoding="utf-8",
    )
    debug_handler.setLevel(logging.DEBUG)
    debug_handler.setFormatter(logging.Formatter(_DEBUG_FORMAT, datefmt=_DATE_FORMAT))
    root_logger.addHandler(debug_handler)

    # 首次启动打一条启动标记，方便确认日志系统已加载
    root_logger.info("[Logging] 日志系统已初始化 | log_dir=%s", _LOG_DIR)
