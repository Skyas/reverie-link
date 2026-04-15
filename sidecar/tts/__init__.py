"""
Reverie Link · TTS 模块

对话流程调用统一入口 TTSManager，内部按配置路由至：
  - 在线引擎（MiniMax / 阿里云 CosyVoice / ElevenLabs）
  - 离线引擎（Fish Speech / GPT-SoVITS / CosyVoice3，通过 Worker 子进程，Phase 2）

外部只需导入：
    from tts import tts_manager
"""

from .manager import TTSManager

# 全局单例，由 main.py 在 lifespan 中初始化
tts_manager = TTSManager()

__all__ = ["tts_manager", "TTSManager"]
