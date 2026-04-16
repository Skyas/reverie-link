"""
Reverie Link · TTSManager — TTS 路由层

变更记录：
  [FIX-⑤] configure() 接收 proxy 字段，传递给各在线引擎
  [FEAT-①] configure() 接收 model 字段，透传给各引擎构造函数
"""

import logging
from typing import AsyncGenerator, Optional

from .base import TTSEngineBase, VoiceInfo

logger = logging.getLogger(__name__)


class TTSManager:
    """TTS 路由层单例。"""

    def __init__(self) -> None:
        self._engine: Optional[TTSEngineBase] = None
        self._config: dict = {}
        self._mode: str = "disabled"      
        self._provider: str = ""           
        self._voice_id: str = ""
        self._model: str = ""
        self._error: str = ""              

    def configure(self, config: dict) -> None:
        self._config   = config
        self._mode     = config.get("mode", "disabled")
        self._provider = config.get("provider", "")
        self._voice_id = config.get("voice_id", "")
        self._model    = config.get("model", "")
        self._engine   = None
        self._error    = ""

        if self._mode == "disabled":
            logger.info("[TTSManager] 已进入无语音模式（用户主动禁用）")
            return

        if self._mode == "online":
            self._build_online_engine(config)
        elif self._mode == "offline":
            logger.info("[TTSManager] 离线引擎尚未实现，进入无语音模式")
            self._mode = "disabled"
        else:
            logger.warning(f"[TTSManager] 未知 mode='{self._mode}'，进入无语音模式")
            self._mode = "disabled"

    def _build_online_engine(self, config: dict) -> None:
        api_key  = config.get("api_key", "").strip()
        base_url = config.get("base_url", "").strip()
        provider = config.get("provider", "").strip()
        model    = config.get("model", "").strip()
        # [FIX-⑤] 代理地址：前端仅在开关开启且有地址时才传非空值
        proxy    = config.get("proxy", "").strip()

        if not api_key:
            self._mode  = "disabled"
            self._error = "在线引擎缺少 API Key"
            logger.warning(f"[TTSManager] {self._error}，进入无语音模式")
            return

        if proxy:
            logger.info(f"[TTSManager] 使用 HTTP 代理: {proxy}")
        else:
            logger.debug("[TTSManager] 未配置代理，直连模式")

        try:
            if provider == "minimax":
                from .online.minimax import MiniMaxEngine
                # [FEAT-①] model 为空时交由引擎使用自己的默认值
                kwargs = dict(
                    api_key=api_key,
                    group_id=config.get("group_id", "").strip(),
                    base_url=base_url or "",
                    proxy=proxy or None,
                )
                if model:
                    kwargs["model"] = model
                self._engine = MiniMaxEngine(**kwargs)
            elif provider == "elevenlabs":
                from .online.elevenlabs import ElevenLabsEngine
                kwargs = dict(
                    api_key=api_key,
                    base_url=base_url or "",
                    proxy=proxy or None,
                )
                if model:
                    kwargs["model"] = model
                self._engine = ElevenLabsEngine(**kwargs)
            elif provider == "aliyun_cosyvoice":
                from .online.aliyun import AliyunCosyVoiceEngine
                kwargs = dict(
                    api_key=api_key,
                    base_url=base_url or "",
                    proxy=proxy or None,
                )
                if model:
                    kwargs["model"] = model
                self._engine = AliyunCosyVoiceEngine(**kwargs)
            else:
                self._mode  = "disabled"
                self._error = f"未知在线供应商: {provider}"
                return

            logger.info(
                f"[TTSManager] 在线引擎已构建 | provider={provider} "
                f"model={model or '(默认)'} voice_id={self._voice_id} "
                f"has_key=True proxy={'Yes' if proxy else 'No'}"
            )
        except Exception as e:
            self._mode  = "disabled"
            self._error = str(e)
            logger.error(f"[TTSManager] 构建引擎失败: {e}，进入无语音模式")

    async def synthesize(
        self,
        text: str,
        emotion: str = "neutral",
        voice_id: str = "",
    ) -> AsyncGenerator[bytes, None]:
        """
        流式合成语音。产生音频块，无语音模式下静默返回空迭代。
        """
        if self._mode == "disabled" or self._engine is None:
            return

        effective_voice = voice_id or self._voice_id
        if not effective_voice:
            logger.debug("[TTSManager] 未配置 voice_id，跳过合成")
            return

        text = text.strip()
        if not text:
            return

        try:
            async for chunk in self._engine.synthesize(text, effective_voice, emotion):
                yield chunk
        except Exception as e:
            logger.error(f"[TTSManager] 合成失败 | provider={self._provider} error={repr(e)}", exc_info=True)
            import traceback
            print("================ TTS 报错拉响警报 ================")
            print(f"当前 Provider: {self._provider}")
            print(f"当前 Model:    {self._model}")
            print(f"错误摘要: {repr(e)}")
            print("完整堆栈:")
            traceback.print_exc()
            print("==================================================")
            return

    async def list_voices(self) -> list[VoiceInfo]:
        if self._engine is None:
            return []
        try:
            return await self._engine.list_voices()
        except Exception as e:
            logger.error(f"[TTSManager] 获取音色列表失败: {e}")
            return []

    async def test_connection(self) -> dict:
        if self._engine is None:
            return {"success": False, "message": "未配置任何 TTS 引擎"}
        try:
            ok = await self._engine.test_connection()
            return {"success": ok, "message": "连接成功" if ok else "连接失败"}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def get_status(self) -> dict:
        ready = self._mode != "disabled" and self._engine is not None
        return {
            "mode":       self._mode,
            "provider":   self._provider,
            "voice_id":   self._voice_id,
            "model":      self._model,
            "ready":      ready,
            "error":      self._error,
            "label":      self._status_label(),
        }

    def _status_label(self) -> str:
        if self._mode == "disabled":
            return "语音未启用"
        if self._error:
            return f"配置错误：{self._error}"
        provider_names = {
            "minimax":          "MiniMax Speech",
            "elevenlabs":       "ElevenLabs",
            "aliyun_cosyvoice": "阿里云 CosyVoice",
        }
        name = provider_names.get(self._provider, self._provider)
        if self._model:
            return f"● 就绪  {name} · {self._model}"
        return f"● 就绪  {name}"

    @property
    def is_enabled(self) -> bool:
        return self._mode != "disabled" and self._engine is not None

    @property
    def active_voice_id(self) -> str:
        return self._voice_id