"""
Reverie Link · 阿里云 CosyVoice API 在线 TTS 适配器 (流式 WebSocket 版)

变更记录：
  [FIX-⑤] 构造函数接收 proxy 参数，WebSocket 连接支持通过 SOCKS/HTTP 代理
"""

import json
import uuid
import logging
from typing import AsyncGenerator, Optional

import websockets

from ..base import TTSEngineBase, VoiceInfo

logger = logging.getLogger(__name__)

# 情感标签 → 自然语言指令映射
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

# 内置预设音色
_BUILTIN_VOICES: list[VoiceInfo] = [
    VoiceInfo(id="longanyang",   name="龙安洋",   engine="aliyun_cosyvoice", tags=["中文", "男声", "阳光"]),
    VoiceInfo(id="longanhuan",   name="龙安欢",   engine="aliyun_cosyvoice", tags=["中文", "女声", "元气"]),
    VoiceInfo(id="longhuhu_v3",  name="龙呼呼",   engine="aliyun_cosyvoice", tags=["中文", "女声", "童声"]),
]

# 阿里云大模型（百炼） WebSocket 接口地址
_DASHSCOPE_WS_URL ='wss://dashscope.aliyuncs.com/api-ws/v1/inference'
_DASHSCOPE_HTTP_URL = 'https://dashscope.aliyuncs.com/api/v1'


class AliyunCosyVoiceEngine(TTSEngineBase):
    """
    阿里云 CosyVoice API 适配器 (WebSocket 流式返回版)。
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "",
        model: str = "cosyvoice-v3-flash",
        proxy: Optional[str] = None,
    ) -> None:
        self._api_key  = api_key
        self._ws_url   = (base_url or _DASHSCOPE_WS_URL).rstrip("/")
        self._model    = model
        self._proxy    = proxy

        if self._proxy:
            logger.info(f"[AliyunCosyVoice] 已配置代理: {self._proxy}")

    async def synthesize(
        self,
        text: str,
        voice_id: str,
        emotion: str = "neutral",
    ) -> AsyncGenerator[bytes, None]:
        task_id = uuid.uuid4().hex
        
        # v3 模型不再支持通过 instruction 参数传入情感，改用 SSML。
        # 为保证基础连通性，这里暂不将文本包装为 SSML，先使用纯文本模式。

        # 1. Start Task 
        run_payload = {
            "header": {
                "action": "run-task",
                "task_id": task_id,
                "streaming": "duplex"
            },
            "payload": {
                "model": self._model,
                "task_group": "audio",
                "task": "tts",
                "function": "SpeechSynthesizer",
                "input": {},
                "parameters": {
                    "text_type": "PlainText",  # [必填修复] 声明文本类型
                    "voice": voice_id,
                    "format": "mp3",           # [建议修正] 与官方对齐，使用前端兼容性最好的 mp3
                    "sample_rate": 22050,
                    "volume": 50,              # 与官方对齐，音量设为 50
                    "rate": 1,                 # [必填修复] 语速
                    "pitch": 1                 # [必填修复] 音调
                }
            }
        }

        # 2. Continue Task (发送文本)
        continue_payload = {
            "header": {
                "action": "continue-task",
                "task_id": task_id,
                "streaming": "duplex"
            },
            "payload": {
                "input": {
                    "text": text
                }
            }
        }

        # 3. Finish Task (结束标识)
        finish_payload = {
            "header": {
                "action": "finish-task",
                "task_id": task_id,
                "streaming": "duplex"
            },
            "payload": {
                "input": {}
            }
        }

        logger.debug(
            f"[AliyunCosyVoice] 发起流式合成 | task_id={task_id[:8]} "
            f"model={self._model} voice={voice_id} "
            f"proxy={'Yes' if self._proxy else 'No'}"
        )

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "X-DashScope-DataInspection": "disable",
        }

        try:
            ws_kwargs: dict = {
                "additional_headers": headers,
                "ping_interval": 20,
                "ping_timeout": 20,
            }
            
            if self._proxy:
                try:
                    ws_kwargs["proxy"] = self._proxy
                except Exception:
                    logger.warning("[AliyunCosyVoice] websockets 版本不支持 proxy 参数，将直连")

            async with websockets.connect(self._ws_url, **ws_kwargs) as ws:
                
                # 1. 发送初始化指令
                await ws.send(json.dumps(run_payload))

                # 2. 监听服务端响应
                async for msg in ws:
                    if isinstance(msg, bytes):
                        # 收到了音频二进制数据
                        yield msg
                        
                    elif isinstance(msg, str):
                        data = json.loads(msg)
                        header = data.get("header", {})
                        event = header.get("event")

                        if event == "task-started":
                            logger.debug("[AliyunCosyVoice] 收到 task-started，开始推送文本...")
                            # 3. 收到就绪信号后，推送文本并结束
                            await ws.send(json.dumps(continue_payload))
                            await ws.send(json.dumps(finish_payload))
                            
                        elif event == "result-generated":
                            pass
                        elif event == "task-finished":
                            logger.debug("[AliyunCosyVoice] 任务完成，正常关闭连接")
                            break
                        elif event == "task-failed":
                            error_msg = header.get("error_message", str(data))
                            logger.error(f"[AliyunCosyVoice] 合成失败: {error_msg}")
                            raise RuntimeError(f"流式合成失败: {error_msg}")

        except websockets.exceptions.WebSocketException as e:
            logger.error(f"[AliyunCosyVoice] WebSocket 连接异常: {e}")
            raise RuntimeError(f"WebSocket 异常: {str(e)}")
        
    async def list_voices(self) -> list[VoiceInfo]:
        return list(_BUILTIN_VOICES)

    async def is_ready(self) -> bool:
        return True

    async def test_connection(self) -> bool:
        try:
            async for chunk in self.synthesize("测试", "longanyang", "neutral"):
                if chunk:
                    return True
            return False
        except Exception as e:
            logger.warning(f"[AliyunCosyVoice] 连通性测试失败: {e}")
            return False