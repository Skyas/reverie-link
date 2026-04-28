"""
stt_engine.py — SenseVoice STT 封装

职责：加载 sherpa-onnx SenseVoice 模型，接收 PCM bytes → 返回 { text, emotion, language }。

关键设计：
  - 模型路径：models/sense-voice-small-int8/
  - API：sherpa_onnx.OfflineRecognizer.from_sense_voice()
  - recognize() 同步方法，上层通过 asyncio.to_thread() 调用

Mock 模式（开发测试用）：
  若模型不存在且环境变量 VOICE_MOCK_TEXT 已设置，则返回预设文本，
  用于在无模型环境下验证语音输入完整链路。
"""

import logging
import os
import subprocess
import sys

logger = logging.getLogger(__name__)

# 模型路径（相对于 sidecar/ 目录）
MODEL_DIR = os.path.join(os.path.dirname(__file__), "..", "models", "sense-voice-small-int8")


class STTEngine:
    """
    语音识别引擎封装。
    当前基于 sherpa-onnx SenseVoice-Small int8。
    若模型不可用则进入降级模式（始终返回空文本），
    并在首次初始化时尝试自动下载模型。
    """

    def __init__(self):
        self._recognizer = None
        self._ready = False
        self._init_error: str | None = None
        # Mock 模式优先级：环境变量 > 自动 fallback（模型缺失时自动启用）
        env_mock = os.environ.get("VOICE_MOCK_TEXT", "").strip()
        self._mock_text: str | None = env_mock or None
        self._auto_mock = False  # 是否因模型缺失而自动启用 Mock
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

        # 若模型文件缺失，尝试自动下载
        if not os.path.isfile(model_path) or not os.path.isfile(tokens_path):
            logger.info("[STT] 模型文件缺失，尝试自动下载...")
            self._auto_download_model()

        if not os.path.isfile(model_path):
            self._init_error = f"模型文件不存在: {model_path}"
            logger.warning("[STT] %s", self._init_error)
            # 自动启用 Mock 模式，确保语音链路可测试
            if not self._mock_text:
                self._mock_text = "你好桌宠"
                self._auto_mock = True
                logger.warning("[STT] ⚠️ 自动启用 Mock 模式 | 返回预设文本=%r | 如需真实识别，请运行 python sidecar/download_stt_model.py 下载模型", self._mock_text)
            else:
                logger.warning("[STT] ⚠️ Mock 模式已启用 | 预设文本=%r", self._mock_text)
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

    @staticmethod
    def _auto_download_model():
        """调用 download_stt_model.py 自动下载模型。"""
        script_path = os.path.join(os.path.dirname(__file__), "..", "download_stt_model.py")
        script_path = os.path.abspath(script_path)
        if not os.path.isfile(script_path):
            logger.warning("[STT] 自动下载脚本不存在: %s", script_path)
            return
        try:
            # 使用当前 Python 解释器运行下载脚本
            # 不捕获输出，让下载进度直接打印到后端控制台，避免管道缓冲区满导致死锁
            logger.info("[STT] 正在启动自动下载脚本，请稍候（首次下载约 160MB，可能需要几分钟）...")
            result = subprocess.run(
                [sys.executable, script_path],
                timeout=600,  # 最多等待 10 分钟
            )
            if result.returncode == 0:
                logger.info("[STT] 自动下载模型成功")
            else:
                logger.warning("[STT] 自动下载模型失败 | returncode=%d", result.returncode)
        except subprocess.TimeoutExpired:
            logger.warning("[STT] 自动下载模型超时（超过 10 分钟），请检查网络后手动运行: python sidecar/download_stt_model.py")
        except Exception as e:
            logger.warning("[STT] 自动下载模型异常: %s", e)

    @property
    def ready(self) -> bool:
        return self._ready

    def recognize(self, pcm_bytes: bytes) -> dict:
        """
        同步识别接口。
        返回：{ text, emotion, language, mock }
        emotion / language 字段在模型不支持时可能为 None。
        mock 为 True 表示当前使用模拟识别（模型未就绪）。
        """
        # Mock 模式：无真实模型时返回预设文本（用于开发测试链路）
        if not self._ready and self._mock_text:
            logger.info("[STT] Mock 识别 | pcm=%d bytes | 返回预设文本=%r", len(pcm_bytes), self._mock_text)
            return {"text": self._mock_text, "emotion": None, "language": "zh", "mock": True}

        if not self._ready or self._recognizer is None:
            if self._init_error:
                logger.warning("[STT] 引擎未就绪，跳过识别 | 原因: %s", self._init_error)
            return {"text": "", "emotion": None, "language": None, "mock": False}

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
