"""
Reverie Link · 记忆系统 — 长期摘要记忆（向量数据库）

职责：
  当滑动窗口中的旧记录被移出时，由 LLM 压缩成 1~2 句「日记摘要」存入向量库。
  用户提及过去时，通过语义检索召回相关摘要注入 System Prompt Layer 2。

存储路径：data/vector_db/（ChromaDB 自动管理内部结构）

参考文档：PHASE3_MEMORY_DESIGN.md § 6
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Optional

from openai import AsyncOpenAI

from .models import (
    MessageType,
    TimelineMessage,
    generate_summary_id,
    now_iso,
)

logger = logging.getLogger(__name__)

# ── ChromaDB 路径 ─────────────────────────────────────────────────

def _get_vector_db_path() -> str:
    project_root = Path(__file__).parent.parent.parent
    data_dir = project_root / "data" / "vector_db"
    data_dir.mkdir(parents=True, exist_ok=True)
    return str(data_dir)


# ── ChromaDB 客户端（模块级单例）─────────────────────────────────

_chroma_client = None
_collection    = None

def _get_collection(character_id: str):
    """
    获取（或创建）指定角色的 ChromaDB collection。
    每个角色卡对应一个独立 collection，名称为 sanitized 的 character_id。
    collection 名称只能包含字母数字和连字符，且长度 3~63。
    """
    global _chroma_client

    if _chroma_client is None:
        try:
            import chromadb
            _chroma_client = chromadb.PersistentClient(path=_get_vector_db_path())
            logger.info("[VectorStore] ChromaDB 客户端初始化完成")
        except ImportError:
            logger.error("[VectorStore] chromadb 未安装，请执行 pip install chromadb")
            return None
        except Exception as e:
            logger.error(f"[VectorStore] ChromaDB 初始化失败: {e}")
            return None

    # collection 名称处理：只保留字母数字和连字符，确保合法
    safe_id = "".join(c if c.isalnum() or c == "-" else "-" for c in character_id)
    # 长度约束：3~63
    safe_id = safe_id[:63] if len(safe_id) >= 3 else f"char-{safe_id}-mem"
    if len(safe_id) < 3:
        safe_id = "default-memory"

    collection_name = f"memory-{safe_id}"[:63]

    try:
        return _chroma_client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )
    except Exception as e:
        logger.error(f"[VectorStore] 获取 collection 失败: {e}")
        return None


def close_vector_db() -> None:
    """释放 ChromaDB 客户端（程序退出时调用）"""
    global _chroma_client, _collection
    _chroma_client = None
    _collection    = None


# ── 摘要生成 Prompt ────────────────────────────────────────────────

def _build_summary_prompt(
    character: dict,
    expired_records: str,
) -> str:
    name        = character.get("name", "助手")
    identity    = character.get("identity", "")
    personality = character.get("personality", "")
    style       = character.get("style", "")
    address     = character.get("address", "你")

    return f"""你是「{name}」，{identity}。
性格：{personality}
说话风格：{style}
你称呼用户为：{address}

以下是一段已经过去的对话和事件记录。
请用你的语气，将其压缩成1~2句简短的日记回忆。
要保留关键事实（谁做了什么、结果如何、情绪如何），但不需要细节。
直接输出日记内容，不要任何前缀或说明。

记录：
{expired_records}"""


def _format_expired_records(messages: list[TimelineMessage]) -> str:
    """将过期消息格式化为摘要用文本"""
    lines = []
    for msg in messages:
        ts = msg.timestamp[:19].replace("T", " ")
        if msg.type in (MessageType.USER_TEXT, MessageType.USER_VOICE):
            lines.append(f"[{ts}] 用户：{msg.content}")
        elif msg.type == MessageType.AI_REPLY:
            lines.append(f"[{ts}] {msg.content}")
        elif msg.type == MessageType.GAME_EVENT:
            lines.append(f"[{ts}] [游戏] {msg.content}")
    return "\n".join(lines) if lines else ""


# ── 待摘要队列（批量缓冲）────────────────────────────────────────

class SummaryQueue:
    """
    批量缓冲被移出滑动窗口的消息，避免频繁调用 LLM。
    累积到 MIN_BATCH_SIZE 条以上，或超过 FLUSH_INTERVAL_SECONDS 秒后统一压缩。

    参考文档：PHASE3_MEMORY_DESIGN.md § 6（触发时机）
    """

    MIN_BATCH_SIZE:      int = 5    # 累积条数阈值
    FLUSH_INTERVAL_SECS: int = 120  # 时间间隔阈值（2分钟）

    def __init__(
        self,
        character_id: str,
        session_id: str,
        llm_client: AsyncOpenAI,
        model: str,
        character: dict,
    ):
        self.character_id = character_id
        self.session_id   = session_id
        self.llm_client   = llm_client
        self.model        = model
        self.character    = character

        self._buffer: list[TimelineMessage] = []
        self._last_flush_time: float = 0.0
        self._flush_task: Optional[asyncio.Task] = None

    def push(self, messages: list[TimelineMessage]) -> None:
        """
        将被移出滑动窗口的消息加入缓冲队列。
        如果达到阈值，异步触发一次摘要压缩。
        """
        self._buffer.extend(messages)
        self._maybe_flush()

    def _maybe_flush(self) -> None:
        """判断是否满足触发条件，满足则异步执行 flush"""
        import time
        now = time.time()
        size_ok = len(self._buffer) >= self.MIN_BATCH_SIZE
        time_ok = (now - self._last_flush_time) >= self.FLUSH_INTERVAL_SECS and len(self._buffer) > 0

        if size_ok or time_ok:
            self._trigger_flush()

    def flush_now(self) -> None:
        """强制立即 flush（会话结束时调用）"""
        if self._buffer:
            self._trigger_flush()

    def _trigger_flush(self) -> None:
        """异步后台执行摘要压缩，不阻塞调用方"""
        import time
        if not self._buffer:
            return

        batch = self._buffer[:]
        self._buffer = []
        self._last_flush_time = time.time()

        async def _run():
            try:
                await summarize_and_store(
                    llm_client=self.llm_client,
                    model=self.model,
                    character=self.character,
                    character_id=self.character_id,
                    session_id=self.session_id,
                    messages=batch,
                )
            except Exception as e:
                logger.error(f"[VectorStore] 后台摘要异常（session={self.session_id}）: {e}")

        if self._flush_task and not self._flush_task.done():
            # 上一个任务还在跑，把 batch 放回队列等下次
            self._buffer = batch + self._buffer
            return

        self._flush_task = asyncio.create_task(_run())

    def update_config(
        self,
        llm_client: Optional[AsyncOpenAI] = None,
        model: Optional[str] = None,
        character: Optional[dict] = None,
        character_id: Optional[str] = None,
    ) -> None:
        if llm_client   is not None: self.llm_client   = llm_client
        if model        is not None: self.model        = model
        if character    is not None: self.character    = character
        if character_id is not None: self.character_id = character_id


# ── 摘要生成 + 存储 ───────────────────────────────────────────────

async def summarize_and_store(
    llm_client: AsyncOpenAI,
    model: str,
    character: dict,
    character_id: str,
    session_id: str,
    messages: list[TimelineMessage],
) -> bool:
    """
    将一批过期消息压缩为 1~2 句摘要，存入向量数据库。

    Returns:
        True 表示成功存储，False 表示跳过或失败。
    """
    if not messages:
        return False

    # 只处理对话类消息，过滤系统标记
    dialog = [
        m for m in messages
        if m.type in (
            MessageType.USER_TEXT,
            MessageType.USER_VOICE,
            MessageType.AI_REPLY,
            MessageType.GAME_EVENT,
        )
    ]
    if not dialog:
        return False

    records_text = _format_expired_records(dialog)
    if not records_text.strip():
        return False

    # 调用 LLM 生成摘要
    prompt = _build_summary_prompt(character, records_text)
    try:
        resp = await llm_client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=150,
            temperature=0.4,
        )
        summary_text = resp.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"[VectorStore] 摘要生成失败（session={session_id}）: {e}")
        return False

    if not summary_text:
        return False

    # 存入 ChromaDB
    collection = _get_collection(character_id)
    if collection is None:
        return False

    summary_id      = generate_summary_id()
    source_msg_ids  = ",".join(m.id for m in dialog[:20])  # 最多记录20条来源ID

    try:
        collection.add(
            ids=[summary_id],
            documents=[summary_text],
            metadatas=[{
                "created_at":     now_iso(),
                "session_id":     session_id,
                "character_id":   character_id,
                "source_msg_ids": source_msg_ids,
                "type":           "conversation",
            }],
        )
        logger.info(f"[VectorStore] 摘要已存储（id={summary_id}，session={session_id}）: {summary_text[:50]}…")
        return True
    except Exception as e:
        logger.error(f"[VectorStore] ChromaDB 写入失败: {e}")
        return False


# ── 语义检索 ──────────────────────────────────────────────────────

def retrieve_relevant_summaries(
    query: str,
    character_id: str,
    top_k: int = 3,
    min_similarity: float = 0.3,
) -> list[str]:
    """
    用用户消息作为 query，从向量库检索最相关的摘要。

    Args:
        query:          用户当前消息（作为检索查询）
        character_id:   角色卡 ID（只在该角色的 collection 内检索）
        top_k:          返回最相关的条数（默认3）
        min_similarity: 最低相似度阈值，低于此值的结果丢弃（cosine距离，越小越相似）

    Returns:
        摘要文本列表（已按相似度排序，最相关在前）
    """
    if not query.strip():
        return []

    collection = _get_collection(character_id)
    if collection is None:
        return []

    try:
        # 先检查 collection 是否有数据
        if collection.count() == 0:
            return []

        results = collection.query(
            query_texts=[query],
            n_results=min(top_k, collection.count()),
        )

        if not results or not results.get("documents"):
            return []

        docs      = results["documents"][0]      # List[str]
        distances = results.get("distances", [[]])[0]  # cosine 距离，越小越相似

        # 过滤低相似度结果
        filtered = [
            doc for doc, dist in zip(docs, distances)
            if dist <= (1.0 - min_similarity)   # cosine距离转相似度
        ]

        return filtered

    except Exception as e:
        logger.warning(f"[VectorStore] 检索失败（character={character_id}）: {e}")
        return []


# ── 角色数据管理 ───────────────────────────────────────────────────

def delete_summaries_by_character(character_id: str) -> int:
    """
    删除指定角色卡的所有向量摘要。
    由删除角色卡流程调用。
    返回删除的条数。
    """
    collection = _get_collection(character_id)
    if collection is None:
        return 0

    try:
        count = collection.count()
        if count == 0:
            return 0

        # 删除该 collection 内所有文档
        all_ids = collection.get()["ids"]
        if all_ids:
            collection.delete(ids=all_ids)
        logger.info(f"[VectorStore] 已删除角色 {character_id} 的 {count} 条摘要")
        return count
    except Exception as e:
        logger.error(f"[VectorStore] 删除摘要失败: {e}")
        return 0


def export_summaries_by_character(character_id: str) -> list[dict]:
    """
    导出指定角色卡的所有向量摘要。
    供删除前导出使用。
    """
    collection = _get_collection(character_id)
    if collection is None:
        return []

    try:
        if collection.count() == 0:
            return []

        results = collection.get(include=["documents", "metadatas"])
        output  = []
        for i, doc_id in enumerate(results["ids"]):
            output.append({
                "id":       doc_id,
                "summary":  results["documents"][i],
                "metadata": results["metadatas"][i],
            })
        return output
    except Exception as e:
        logger.error(f"[VectorStore] 导出摘要失败: {e}")
        return []