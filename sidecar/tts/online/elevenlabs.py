"""
Reverie Link · ElevenLabs 在线 TTS 适配器 (流式版)

变更记录：
  [FIX-⑤] 统一 proxy 参数：构造函数接收 proxy，synthesize 和 test_connection 使用同一代理
           移除旧的 urllib.request.getproxies() 手动读取逻辑
"""

import logging
from typing import AsyncGenerator, Optional

import httpx

from ..base import TTSEngineBase, VoiceInfo

logger = logging.getLogger(__name__)

_EMOTION_SETTINGS: dict[str, dict] = {
    "neutral":   {"stability": 0.50, "style": 0.20},
    "happy":     {"stability": 0.35, "style": 0.55},
    "sad":       {"stability": 0.60, "style": 0.10},
    "angry":     {"stability": 0.25, "style": 0.80},
    "fearful":   {"stability": 0.30, "style": 0.60},
    "surprised": {"stability": 0.25, "style": 0.70},
    "disgusted": {"stability": 0.30, "style": 0.65},
    "excited":   {"stability": 0.20, "style": 0.90},
    "gentle":    {"stability": 0.65, "style": 0.15},
    "playful":   {"stability": 0.30, "style": 0.60},
    "shy":       {"stability": 0.60, "style": 0.15},
    "proud":     {"stability": 0.40, "style": 0.55},
    "worried":   {"stability": 0.35, "style": 0.50},
    "confused":  {"stability": 0.45, "style": 0.30},
    "cold":      {"stability": 0.70, "style": 0.10},
    "serious":   {"stability": 0.65, "style": 0.20},
    "whisper":   {"stability": 0.70, "style": 0.05},
    "shout":     {"stability": 0.20, "style": 0.95},
    "cry":       {"stability": 0.55, "style": 0.30},
    "laugh":     {"stability": 0.30, "style": 0.65},
    "sigh":      {"stability": 0.60, "style": 0.10},
}

_DEFAULT_SETTINGS = _EMOTION_SETTINGS["neutral"]


class ElevenLabsEngine(TTSEngineBase):

    DEFAULT_BASE_URL = "https://api.elevenlabs.io"

    def __init__(
        self,
        api_key: str,
        base_url: str = "",
        model: str = "eleven_flash_v2_5",
        proxy: Optional[str] = None,
    ) -> None:
        self._api_key  = api_key
        self._base_url = (base_url or self.DEFAULT_BASE_URL).rstrip("/")
        self._model    = model
        self._proxy    = proxy  # [FIX-⑤] 统一代理入口

        if self._proxy:
            logger.info(f"[ElevenLabs] 已配置代理: {self._proxy}")

    def _make_client(self, timeout: float = 30.0) -> httpx.AsyncClient:
        """创建统一的 httpx 客户端，确保 synthesize / test / list_voices 都走相同代理。"""
        return httpx.AsyncClient(
            timeout=timeout,
            proxy=self._proxy,
        )

    async def synthesize(
        self,
        text: str,
        voice_id: str,
        emotion: str = "neutral",
    ) -> AsyncGenerator[bytes, None]:
        
        settings = _EMOTION_SETTINGS.get(emotion, _DEFAULT_SETTINGS)
        payload = {
            "text":     text,
            "model_id": self._model,
            "voice_settings": {
                "stability":         settings["stability"],
                "similarity_boost":  0.80,
                "style":             settings["style"],
                "use_speaker_boost": True,
            },
        }

        url = f"{self._base_url}/v1/text-to-speech/{voice_id}/stream"
        headers = {
            "xi-api-key":   self._api_key,
            "Content-Type": "application/json",
            "Accept":       "audio/mpeg",
        }

        logger.debug(
            f"[ElevenLabs] 发起流式合成 | model={self._model} "
            f"voice={voice_id} emotion={emotion} "
            f"stability={settings['stability']} style={settings['style']} "
            f"proxy={'Yes' if self._proxy else 'No'}"
        )

        async with self._make_client(timeout=30.0) as client:
            async with client.stream("POST", url, headers=headers, json=payload) as resp:
                if resp.status_code != 200:
                    await resp.aread()
                    body_preview = resp.text[:200]
                    logger.error(f"[ElevenLabs] API 错误 status={resp.status_code} body={body_preview}")
                    raise RuntimeError(f"ElevenLabs TTS 错误 {resp.status_code}: {body_preview}")

                async for chunk in resp.aiter_bytes():
                    if chunk:
                        yield chunk

    async def list_voices(self) -> list[VoiceInfo]:
        url = f"{self._base_url}/v1/voices"
        headers = {"xi-api-key": self._api_key}
        try:
            async with self._make_client(timeout=15.0) as client:
                resp = await client.get(url, headers=headers)
            if resp.status_code != 200:
                logger.warning(f"[ElevenLabs] 获取音色列表失败 status={resp.status_code}")
                return []

            data = resp.json()
            voices = []
            for v in data.get("voices", []):
                voices.append(VoiceInfo(
                    id=v.get("voice_id", ""),
                    name=v.get("name", ""),
                    engine="elevenlabs",
                    tags=v.get("labels", {}).get("use_case", "").split(","),
                ))
            logger.info(f"[ElevenLabs] 音色列表获取成功 | count={len(voices)}")
            return voices
        except Exception as e:
            logger.error(f"[ElevenLabs] 获取音色列表异常: {e}")
            return []

    async def is_ready(self) -> bool:
        return True

    async def test_connection(self) -> bool:
        """
        连通性测试：请求 /v1/models 验证 API Key 有效性。
        [FIX-⑤] 使用统一 _make_client()，不再手动读系统代理。
        """
        url = f"{self._base_url}/v1/models"
        headers = {"xi-api-key": self._api_key}

        logger.info(
            f"[ElevenLabs] 连通性测试 | base_url={self._base_url} "
            f"proxy={self._proxy or '直连'} key_len={len(self._api_key)}"
        )

        try:
            async with self._make_client(timeout=10.0) as client:
                resp = await client.get(url, headers=headers)
            
            if resp.status_code == 200:
                logger.info(f"[ElevenLabs] 连通性测试通过 (代理: {self._proxy or '直连'})")
                return True
            elif resp.status_code == 401:
                raise ValueError("API Key 无效或已被 ElevenLabs 拒绝 (HTTP 401)")
            else:
                raise ValueError(f"HTTP 请求失败，状态码: {resp.status_code}")

        except httpx.ConnectError:
            raise ValueError(
                "网络连接被拒绝。如果你在国内，请在「高级选项」中配置 HTTP 代理后重试。"
            )
        except httpx.TimeoutException:
            raise ValueError("网络连接超时，请检查网络或代理节点是否畅通")
        except ValueError:
            raise
        except Exception as e:
            logger.warning(f"[ElevenLabs] 连通性测试异常: {e}")
            raise ValueError(f"未知异常: {repr(e)}")