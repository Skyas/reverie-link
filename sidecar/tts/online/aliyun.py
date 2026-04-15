"""
Reverie Link · 阿里云 CosyVoice API 在线 TTS 适配器 (流式 WebSocket 版)

API 文档：https://help.aliyun.com/zh/model-studio/cosyvoice-api
模型：cosyvoice-v3-flash（支持流式、支持高自然度情感控制）
依赖：pip install websockets
"""

import json
import uuid
import logging
from typing import AsyncGenerator

import websockets

from ..base import TTSEngineBase, VoiceInfo

logger = logging.getLogger(__name__)

# 情感标签 → 自然语言指令映射（通过 instruction 字段下发）
_EMOTION_PROMPTS: dict[str, str] = {
    "neutral":   "",                      
    "happy":     "用开心愉快的语气说，",
    "sad":       "用悲伤低沉的语气说，",
    "angry":     "用生气强硬的语气说，",
    "fearful":   "用害怕紧张的语气说，",
    "surprised": "用惊讶的语气说，",
    "disgusted": "用厌恶的语气说，",
    "excited":   "用兴奋激动的语气说，",
    "gentle":    "用温柔体贴的语气说，",
    "playful":   "用俏皮调侃的语气说，",
    "shy":       "用害羞拘谨的语气说，",
    "proud":     "用自豪得意的语气说，",
    "worried":   "用担忧焦虑的语气说，",
    "confused":  "用困惑不解的语气说，",
    "cold":      "用冷淡疏离的语气说，",
    "serious":   "用严肃正经的语气说，",
    "whisper":   "用轻声低语的方式说，",
    "shout":     "用大声高亢的方式说，",
    "cry":       "用哽咽哭泣的语气说，",
    "laugh":     "用笑着说话的方式说，",
    "sigh":      "用叹气疲惫的语气说，",
}

# 内置预设音色（部分）
_BUILTIN_VOICES: list[VoiceInfo] = [
    VoiceInfo(id="longxiaochun",   name="龙小淳",   engine="aliyun_cosyvoice", tags=["中文", "女声", "温柔"]),
    VoiceInfo(id="longxiaochun_v2",name="龙小淳V2", engine="aliyun_cosyvoice", tags=["中文", "女声", "温柔"]),
    VoiceInfo(id="longwan",        name="龙婉",     engine="aliyun_cosyvoice", tags=["中文", "女声", "成熟"]),
    VoiceInfo(id="longwan_v2",     name="龙婉V2",   engine="aliyun_cosyvoice", tags=["中文", "女声", "成熟"]),
    VoiceInfo(id="loongstella",    name="Stella",   engine="aliyun_cosyvoice", tags=["中英文", "女声"]),
    VoiceInfo(id="longshu",        name="龙书",     engine="aliyun_cosyvoice", tags=["中文", "男声"]),
    VoiceInfo(id="longjing",       name="龙静",     engine="aliyun_cosyvoice", tags=["中文", "女声", "新闻"]),
    VoiceInfo(id="longhua",        name="龙华",     engine="aliyun_cosyvoice", tags=["中文", "男声", "新闻"]),
]

# 阿里云大模型（百炼） WebSocket 接口地址
_DASHSCOPE_WS_URL = "wss://dashscope.aliyuncs.com/api-ws/v1/inference"


class AliyunCosyVoiceEngine(TTSEngineBase):
    """
    阿里云 CosyVoice API 适配器 (WebSocket 流式返回版)。
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "",
        model: str = "cosyvoice-v3-flash",  # 默认使用支持情感控制的 V3 Flash 模型
    ) -> None:
        self._api_key  = api_key
        self._ws_url   = (base_url or _DASHSCOPE_WS_URL).rstrip("/")
        self._model    = model

    # ── 合成 (流式生成器) ───────────────────────────────────────────────
    async def synthesize(
        self,
        text: str,
        voice_id: str,
        emotion: str = "neutral",
    ) -> AsyncGenerator[bytes, None]:
        """
        调用 DashScope CosyVoice WebSocket API，流式返回音频二进制片段。
        """
        task_id = uuid.uuid4().hex
        emotion_instruction = _EMOTION_PROMPTS.get(emotion, "")

        # 构造符合阿里云流式协议的 Payload
        payload = {
            "header": {
                "action": "run-task",
                "task_id": task_id,
                "streaming": "in"
            },
            "payload": {
                "model": self._model,
                "task_group": "audio",
                "task": "tts",
                "function": "SpeechSynthesizer",
                "input": {
                    "text": text,  # 仅传入正文
                },
                "parameters": {
                    "voice": voice_id,
                    "format": "wav",  # 流式播放时，如果播放器不支持 WAV 流，可考虑换成 "pcm"
                    "sample_rate": 22050,
                    "volume": 100,
                }
            }
        }

        # 注入情感指令
        if emotion_instruction:
            payload["payload"]["parameters"]["instruction"] = emotion_instruction

        logger.debug(
            f"[AliyunCosyVoice] 发起流式合成 | task_id={task_id[:8]} "
            f"model={self._model} voice={voice_id} emotion={emotion}"
        )

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "X-DashScope-DataInspection": "disable",
        }

        try:
            # 建立 WebSocket 连接
            async with websockets.connect(
                self._ws_url,
                extra_headers=headers,
                ping_interval=20,  # 保持连接活跃
                ping_timeout=20
            ) as ws:
                # 1. 发送合成请求
                await ws.send(json.dumps(payload))

                # 2. 循环接收服务器返回的帧
                async for msg in ws:
                    if isinstance(msg, bytes):
                        # 服务器返回的是二进制数据（音频帧），直接 yield 抛给上层
                        yield msg
                        
                    elif isinstance(msg, str):
                        # 服务器返回的是文本数据（状态控制帧）
                        data = json.loads(msg)
                        header = data.get("header", {})
                        action = header.get("action")

                        if action == "task-started":
                            logger.debug("[AliyunCosyVoice] 服务器开始处理任务 (TTFB)")
                        elif action == "task-finished":
                            logger.debug("[AliyunCosyVoice] 音频流接收完毕")
                            break  # 正常结束流
                        elif action == "task-failed":
                            error_msg = header.get("error_message", str(data))
                            logger.error(f"[AliyunCosyVoice] 合成失败: {error_msg}")
                            raise RuntimeError(f"流式合成失败: {error_msg}")

        except websockets.exceptions.WebSocketException as e:
            logger.error(f"[AliyunCosyVoice] WebSocket 连接异常: {e}")
            raise RuntimeError(f"WebSocket 异常: {str(e)}")

    # ── 音色列表 ──────────────────────────────────────────────────────
    async def list_voices(self) -> list[VoiceInfo]:
        """返回内置预设音色列表"""
        return list(_BUILTIN_VOICES)

    # ── 就绪状态 ──────────────────────────────────────────────────────
    async def is_ready(self) -> bool:
        return True

    # ── 连通性测试 ─────────────────────────────────────────────────────
    async def test_connection(self) -> bool:
        try:
            # 对于流式接口，我们可以简单拉取第一块数据就断开，以验证连通性
            async for chunk in self.synthesize("测试", "longxiaochun", "neutral"):
                if chunk:
                    return True
            return False
        except Exception as e:
            logger.warning(f"[AliyunCosyVoice] 连通性测试失败: {e}")
            return False