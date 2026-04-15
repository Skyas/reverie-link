"""
Reverie Link · MiniMax Speech 2.8 在线 TTS 适配器 (流式版)
"""

import json
import logging
from typing import AsyncGenerator

import httpx

from ..base import TTSEngineBase, VoiceInfo

logger = logging.getLogger(__name__)

_MINIMAX_EMOTIONS: dict[str, str] = {
    "neutral":   "neutral", "happy":     "happy",
    "sad":       "sad",     "angry":     "angry",
    "fearful":   "fear",    "surprised": "surprise",
    "disgusted": "disgusted", "excited": "excited",
    "gentle":    "gentle",  "playful":   "happy",
    "shy":       "gentle",  "proud":     "happy",
    "worried":   "fear",    "confused":  "neutral",
    "cold":      "neutral", "serious":   "neutral",
    "whisper":   "gentle",  "shout":     "excited",
    "cry":       "sad",     "laugh":     "happy",
    "sigh":      "sad",
}

_BUILTIN_VOICES: list[VoiceInfo] = [
    VoiceInfo(id="female-shaonv",      name="少女音",      engine="minimax", tags=["中文", "女声", "清甜"]),
    VoiceInfo(id="female-yujie",       name="御姐音",      engine="minimax", tags=["中文", "女声", "成熟"]),
    VoiceInfo(id="female-tianmei",     name="甜美音",      engine="minimax", tags=["中文", "女声", "甜美"]),
    VoiceInfo(id="female-qingxin",     name="清新音",      engine="minimax", tags=["中文", "女声", "清新"]),
    VoiceInfo(id="male-qn-jingying",   name="精英男声",    engine="minimax", tags=["中文", "男声", "成熟"]),
    VoiceInfo(id="male-qn-badao",      name="霸道男声",    engine="minimax", tags=["中文", "男声", "霸气"]),
    VoiceInfo(id="male-qn-qingse",     name="青涩男声",    engine="minimax", tags=["中文", "男声", "青涩"]),
]


class MiniMaxEngine(TTSEngineBase):
    
    DEFAULT_BASE_URL = "https://api.minimaxi.com"

    def __init__(
        self,
        api_key: str,
        group_id: str = "",
        base_url: str = "",
        model: str = "speech-2.8-turbo",  # 升级至支持极低延迟与流式的 2.8 架构
    ) -> None:
        self._api_key  = api_key
        self._group_id = group_id
        self._base_url = (base_url or self.DEFAULT_BASE_URL).rstrip("/")
        self._model    = model

    async def synthesize(
        self,
        text: str,
        voice_id: str,
        emotion: str = "neutral",
    ) -> AsyncGenerator[bytes, None]:
        
        mm_emotion = _MINIMAX_EMOTIONS.get(emotion, "neutral")

        payload: dict = {
            "model": self._model,
            "text": text,
            "stream": True,  # 开启流式 SSE 输出
            "stream_options": {
                "exclude_aggregated_audio": True  # 防止结尾包包含全量数据导致瞬时带宽爆炸
            },
            "voice_setting": {
                "voice_id": voice_id,
                "speed":    1.0,
                "vol":      1.0,
                "pitch":    0,
                "emotion":  mm_emotion,
            },
            "audio_setting": {
                "audio_sample_rate": 32000,
                "bitrate":          128000,
                "format":           "mp3",
                "channel":          1,
            },
        }

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type":  "application/json",
        }
        if self._group_id:
            headers["GroupId"] = self._group_id

        url = f"{self._base_url}/v1/t2a_v2"

        logger.debug(
            f"[MiniMax] 发起流式合成 | model={self._model} "
            f"voice={voice_id} emotion={emotion}→{mm_emotion}"
        )

        async with httpx.AsyncClient(timeout=30.0, trust_env=False) as client:
            async with client.stream("POST", url, headers=headers, json=payload) as resp:
                if resp.status_code != 200:
                    await resp.aread()
                    body_preview = resp.text[:200]
                    logger.error(f"[MiniMax] API 错误 status={resp.status_code} body={body_preview}")
                    raise RuntimeError(f"MiniMax TTS 错误 {resp.status_code}: {body_preview}")

                # 解析 SSE 数据流
                async for line in resp.aiter_lines():
                    line = line.strip()
                    if not line or not line.startswith("data:"):
                        continue
                        
                    data_str = line[5:].strip()
                    if data_str == "[DONE]":
                        break
                        
                    try:
                        data_json = json.loads(data_str)
                        
                        base_resp = data_json.get("base_resp", {})
                        if base_resp.get("status_code", 0) != 0:
                            msg = base_resp.get("status_msg", "Unknown error")
                            raise RuntimeError(f"MiniMax 业务错误: {msg}")

                        # 获取音频并解 Hex 转换成原始 mp3 bytes 返回
                        audio_hex = data_json.get("data", {}).get("audio", "")
                        if audio_hex:
                            yield bytes.fromhex(audio_hex)
                            
                        # 状态 2 为流结束
                        status = data_json.get("data", {}).get("status", 0)
                        if status == 2:
                            break
                    except json.JSONDecodeError:
                        continue

    async def list_voices(self) -> list[VoiceInfo]:
        return list(_BUILTIN_VOICES)

    async def is_ready(self) -> bool:
        return True

    async def test_connection(self) -> bool:
        try:
            # 修改连接测试：拉取首块数据即成功断开
            async for chunk in self.synthesize("测试", "female-shaonv", "neutral"):
                if chunk:
                    logger.info("[MiniMax] 连通性测试通过")
                    return True
            return False
        except Exception as e:
            logger.warning(f"[MiniMax] 连通性测试失败: {e}")
            return False