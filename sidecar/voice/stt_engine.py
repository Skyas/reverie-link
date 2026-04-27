"""
stt_engine.py — SenseVoice STT 封装

职责：加载 sherpa-onnx SenseVoice 模型，接收 PCM bytes → 返回 { text, emotion, language }。

关键设计：
  - 模型路径：models/sense-voice-small-int8/
  - API：sherpa_onnx.OfflineRecognizer.from_sense_voice()
  - recognize() 同步方法，上层通过 asyncio.to_thread() 调用
"""

import logging
import os

logger = logging.getLogger(__name__)

# 模型路径（相对于 sidecar/ 目录）
MODEL_DIR = os.path.join(os.path.dirname(__file__), "..", "models", "sense-voice-small-int8")


class STTEngine:
    """
    语音识别引擎封装。
    当前基于 sherpa-onnx SenseVoice-Small int8。
    若模型不可用则进入降级模式（始终返回空文本）。
    """

    def __init__(self):
        self._recognizer = None
        self._ready = False
        self._init_error: str | None = None
        self._try_init()

    def _try_init(self):
        """尝试初始化识别器；失败时记录日志但不阻断程序启动。"""
        try:
            import sherpa_onnx
        except ImportError as e:
            self._init_error = f"sherpa_onnx 未安装: {e}"
            logger.warning("[STT] %s", self._init_error)
            return

        model_path = os.path.join(MODEL_DIR, "model.int8.onnx")
        tokens_path = os.path.join(MODEL_DIR, "tokens.txt")

        if not os.path.isfile(model_path):
            self._init_error = f"模型文件不存在: {model_path}"
            logger.warning("[STT] %s", self._init_error)
            return
        if not os.path.isfile(tokens_path):
            self._init_error = f"词表文件不存在: {tokens_path}"
            logger.warning("[STT] %s", self._init_error)
            return

        try:
            self._recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
                model=model_path,
                tokens=tokens_path,
                num_threads=2,
                debug=False,
                language="auto",
                use_itn=True,
            )
            self._ready = True
            logger.info("[STT] SenseVoice 模型加载成功 | path=%s", MODEL_DIR)
        except Exception as e:
            self._init_error = f"模型初始化失败: {e}"
            logger.warning("[STT] %s", self._init_error)

    @property
    def ready(self) -> bool:
        return self._ready

    def recognize(self, pcm_bytes: bytes) -> dict:
        """
        同步识别接口。
        返回：{ text, emotion, language }
        emotion / language 字段在模型不支持时可能为 None。
        """
        if not self._ready or self._recognizer is None:
            return {"text": "", "emotion": None, "language": None}

        try:
            import sherpa_onnx
            # pcm_bytes 为 int16 little-endian mono 16kHz
            samples = self._int16_bytes_to_float32(pcm_bytes)
            stream = self._recognizer.create_stream()
            stream.accept_waveform(16000, samples)
            self._recognizer.decode_stream(stream)
            result = stream.result

            # SenseVoice 结果字段名需实测确认；以下按常见实现处理
            text = result.text.strip() if hasattr(result, "text") else ""
            # emotion / language 可能挂在 result 的属性或文本标签中
            emotion = self._extract_emotion(result)
            language = self._extract_language(result)

            return {"text": text, "emotion": emotion, "language": language}
        except Exception as e:
            logger.warning("[STT] 识别异常: %s", e)
            return {"text": "", "emotion": None, "language": None}

    @staticmethod
    def _int16_bytes_to_float32(pcm_bytes: bytes) -> list[float]:
        """将 int16 little-endian bytes 转为 float32 list（-1.0 ~ 1.0）。"""
        import array
        arr = array.array("h", pcm_bytes)
        return [s / 32768.0 for s in arr]

    @staticmethod
    def _extract_emotion(result) -> str | None:
        """尝试从识别结果中提取情绪标签。"""
        # 部分 sherpa-onnx 版本将 emotion 作为 result 属性
        if hasattr(result, "emotion") and result.emotion:
            return result.emotion.strip().lower() or None
        # 备选：从文本中解析 <|emotion|> 标签
        text = result.text if hasattr(result, "text") else ""
        import re
        m = re.search(r'<\|(angry|happy|neutral|sad)\|>', text)
        if m:
            return m.group(1)
        return None

    @staticmethod
    def _extract_language(result) -> str | None:
        """尝试从识别结果中提取语种代码。"""
        if hasattr(result, "language") and result.language:
            return result.language.strip().lower() or None
        text = result.text if hasattr(result, "text") else ""
        import re
        m = re.search(r'<\|(zh|en|ja|ko|yue)\|>', text)
        if m:
            return m.group(1)
        return None
