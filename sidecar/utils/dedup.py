"""
utils/dedup.py — LLM 输出退化重复检测

用途：
  在 LLM 回复发往前端 / 写入 history 之前，检测是否出现"复读机"式退化输出。
  退化模式典型表现：模型在一次 max_tokens 内反复输出相同句子，例如：
    "……主人今天还没摸我头。……主人今天还没摸我头。……主人今天还没摸我头。"

  这种情况源自 LLM 的概率坍缩，frequency_penalty 对中文整句重复几乎无效。
  唯一可靠的兜底是后处理检测 + 截断。

使用方式：
  from utils.dedup import is_degenerate_repetition

  if is_degenerate_repetition(clean_reply):
      # 丢弃 / 降级处理
      ...
"""

import logging
import re

logger = logging.getLogger(__name__)


# 中文 / 英文句子分隔符
_SENTENCE_SPLIT_RE = re.compile(r'[。！？\.\!\?\n]+')


def _split_sentences(text: str) -> list[str]:
    """
    按中英文句子分隔符切句，剥掉首尾空白和省略号干扰。
    省略号本身不算分隔符（避免 "……我" 被误切），但 "……" 单独一段会被过滤掉。
    """
    if not text:
        return []
    raw_parts = _SENTENCE_SPLIT_RE.split(text)
    sentences = []
    for p in raw_parts:
        s = p.strip()
        # 剥掉句首的省略号（"……主人今天还没亲我" → "主人今天还没亲我"）
        s = s.lstrip('…').lstrip('.').strip()
        # 过滤空串和纯省略号
        if s and s not in ('…', '..', '...'):
            sentences.append(s)
    return sentences


def is_degenerate_repetition(text: str, *, min_sentences: int = 2, threshold: float = 0.5) -> bool:
    """
    检测文本是否为退化重复输出。

    判定标准：
      把文本切成句子后，去重句子数 / 总句子数 <= threshold 即判定为退化。
      （即：至少 (1 - threshold) 比例的句子是重复的）

    例：
      "A。A。A。"     → 3 句中只有 1 个唯一 → 1/3 ≈ 0.33 ≤ 0.5 → True
      "A。B。A。A。" → 4 句中有 2 个唯一  → 2/4 = 0.50 ≤ 0.5 → True
      "A。B。A。"     → 3 句中有 2 个唯一  → 2/3 ≈ 0.67 > 0.5 → False
      "A。"           → 只有 1 句          → 不足 min_sentences → False
      "A。B。"        → 2 句全不同         → 2/2 = 1.0 > 0.5 → False

    参数：
      min_sentences: 句子数少于此值时不判定（短回复不算退化）
      threshold:     去重率阈值，低于此值判定为退化

    返回：
      True  — 退化输出（应丢弃 / 降级）
      False — 正常输出
    """
    if not text or not text.strip():
        return False

    sentences = _split_sentences(text)
    if len(sentences) < min_sentences:
        return False

    unique = set(sentences)
    unique_ratio = len(unique) / len(sentences)

    if unique_ratio <= threshold:
        logger.warning(
            "[Dedup] 检测到退化重复输出 | 总句数=%d 唯一句数=%d 唯一率=%.2f | 文本=%r",
            len(sentences), len(unique), unique_ratio, text[:80]
        )
        return True

    return False