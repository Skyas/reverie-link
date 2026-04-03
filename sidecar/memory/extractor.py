"""
Reverie Link · 记忆系统 — 核心档案自动提取模块

从对话记录中自动提取用户信息，以角色口吻写入「{角色名}的日记本」（自动区）。

触发时机：
  1. 每累积 EXTRACT_EVERY_N_ROUNDS 轮新对话触发一次（后台异步）
  2. 会话结束（WebSocket 断开）时对未提取内容做收尾提取（同步 await，确保执行）

参考文档：PHASE3_MEMORY_DESIGN.md § 5
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from openai import AsyncOpenAI

from .models import (
    MessageType,
    NotebookEntry,
    NotebookSource,
    TimelineMessage,
    now_iso,
)
from .db_notebook import (
    add_entries_batch,
    get_all_entries,
    get_all_entries_for_prompt,
)
from .db_chat import get_recent_messages

logger = logging.getLogger(__name__)

# ── 触发阈值 ──────────────────────────────────────────────────────
EXTRACT_EVERY_N_ROUNDS: int = 10

# ── 预设标签 ──────────────────────────────────────────────────────
PRESET_TAGS: list[str] = [
    "姓名", "年龄", "性别", "职业", "所在地",
    "游戏", "运动", "音乐", "动漫", "影视", "阅读", "美食", "旅行",
    "性格", "习惯", "偏好", "讨厌的事",
    "家人", "朋友", "同事", "宠物",
    "常玩游戏", "游戏ID", "游戏习惯", "段位/水平",
    "纪念日", "成就", "近期事件",
]

PRESET_TAGS_STR = "、".join(PRESET_TAGS)


# ── 提取 Prompt ────────────────────────────────────────────────────

def _build_extract_prompt(
    character: dict,
    recent_conversations: str,
    existing_entries: str,
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

以下是你和{address}最近的对话。请用你自己的语气和风格，
提取关于{address}的**持久性信息**，写成简短的日记条目。

【应该记录的内容】
- 身份信息：姓名、年龄、职业、所在地等
- 持久偏好：喜欢/讨厌的事物、兴趣爱好、口味偏好
- 人际关系：家人、朋友、宠物等
- 习惯特征：作息习惯、行为模式、性格特点
- 经常提起的话题：如果{address}在对话中反复做某件事或提起某个话题，可以记录为习惯或偏好
- 重要经历：值得长期记住的事件（如成就、纪念日）

【不应该记录的内容】
- 单次闲聊中的临时互动（如某次开玩笑、某句随口一说的话）
- 角色扮演中的即兴互动（除非反复出现，说明是用户真正的偏好）
- 已经在"已有记忆"中存在的信息

要求：
1. 用你的性格和口吻来写，但事实必须准确，不编造
2. 每条一句话
3. 为每条分配1~3个标签，优先从以下预设标签中选择：{PRESET_TAGS_STR}
   不够用时可自建标签
4. 没有值得长期记住的新信息就返回空数组 []
5. 只提取关于{address}的信息，不提取关于你自己的
6. 宁可少记也不要记录没有长期价值的内容

已有的记忆（不要重复这些内容）：
{existing_entries}

对话记录：
{recent_conversations}

以JSON数组格式输出，每个元素包含 content 和 tags 两个字段。
不要输出任何其他内容，不要使用 markdown 代码块。
示例格式：[{{"content": "哥哥喜欢打羽毛球。", "tags": ["运动", "羽毛球"]}}]"""


def _build_dedup_prompt(new_content: str, existing_content: str) -> str:
    return f"""以下两条信息是否描述同一件事？只回答"是"或"否"。

信息A：{new_content}
信息B：{existing_content}"""


# ── 格式化对话记录 ─────────────────────────────────────────────────

def _format_conversations(messages: list[TimelineMessage]) -> str:
    lines = []
    for msg in messages:
        ts = msg.timestamp[:19].replace("T", " ")
        if msg.type in (MessageType.USER_TEXT, MessageType.USER_VOICE):
            lines.append(f"[{ts}] 用户：{msg.content}")
        elif msg.type == MessageType.AI_REPLY:
            lines.append(f"[{ts}] {msg.content}")
    return "\n".join(lines) if lines else "（无对话记录）"


# ── 去重逻辑 ──────────────────────────────────────────────────────

def _tags_overlap(tags_a: list[str], tags_b: list[str]) -> bool:
    return bool(set(tags_a) & set(tags_b))


async def _is_duplicate_by_llm(
    llm_client: AsyncOpenAI,
    model: str,
    new_content: str,
    existing_content: str,
) -> bool:
    try:
        resp = await llm_client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": _build_dedup_prompt(new_content, existing_content)}],
            max_tokens=10,
            temperature=0,
        )
        answer = resp.choices[0].message.content.strip()
        return answer.startswith("是")
    except Exception as e:
        logger.warning(f"[Extractor] 去重精判失败（保守返回 False）: {e}")
        return False


async def _deduplicate(
    llm_client: AsyncOpenAI,
    model: str,
    new_entries: list[dict],
    existing_entries: list[NotebookEntry],
) -> list[dict]:
    result = []
    for new in new_entries:
        new_tags    = new.get("tags", [])
        new_content = new.get("content", "")
        is_dup = False

        candidates = [e for e in existing_entries if _tags_overlap(e.tags, new_tags)]

        for candidate in candidates:
            if await _is_duplicate_by_llm(llm_client, model, new_content, candidate.content):
                logger.info(f"[Extractor] 去重命中，丢弃：{new_content!r}")
                is_dup = True
                break

        if not is_dup:
            result.append(new)

    return result


# ── 核心提取函数 ───────────────────────────────────────────────────

async def extract_and_save(
    llm_client: AsyncOpenAI,
    model: str,
    character: dict,
    character_id: str,
    session_id: str,
    recent_messages: list[TimelineMessage],
) -> int:
    """
    从最近对话中提取新信息并写入笔记本自动区。
    Returns: 写入的新条目数量
    """
    if not recent_messages:
        logger.debug(f"[Extractor] 无消息可提取（session={session_id}）")
        return 0

    dialog_messages = [
        m for m in recent_messages
        if m.type in (MessageType.USER_TEXT, MessageType.USER_VOICE, MessageType.AI_REPLY)
    ]
    if len(dialog_messages) < 2:
        logger.debug(f"[Extractor] 对话消息不足2条，跳过（session={session_id}）")
        return 0

    conversation_text = _format_conversations(dialog_messages)
    existing_entries  = get_all_entries(character_id=character_id)
    existing_text     = get_all_entries_for_prompt(character_id=character_id)

    prompt = _build_extract_prompt(character, conversation_text, existing_text)
    logger.info(f"[Extractor] 开始提取（session={session_id}，{len(dialog_messages)} 条对话）")

    try:
        resp = await llm_client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=800,
            temperature=0.3,
        )
        raw_output = resp.choices[0].message.content.strip()
        logger.debug(f"[Extractor] LLM 原始输出：{raw_output[:200]}")
    except Exception as e:
        logger.error(f"[Extractor] LLM 提取失败（session={session_id}）: {e}")
        return 0

    if not raw_output:
        logger.info(f"[Extractor] LLM 返回为空（session={session_id}）")
        return 0

    # 解析 JSON
    try:
        clean = raw_output.strip()
        if clean.startswith("```"):
            clean = "\n".join(clean.split("\n")[1:])
        if clean.endswith("```"):
            clean = "\n".join(clean.split("\n")[:-1])
        clean = clean.strip()

        extracted = json.loads(clean)
        if not isinstance(extracted, list):
            logger.warning(f"[Extractor] LLM 输出不是数组，跳过（session={session_id}）")
            return 0
        if len(extracted) == 0:
            logger.info(f"[Extractor] 本次无新信息（session={session_id}）")
            return 0
    except json.JSONDecodeError as e:
        logger.warning(f"[Extractor] JSON 解析失败（session={session_id}）: {e}\n原始输出：{raw_output[:200]}")
        return 0

    logger.info(f"[Extractor] LLM 提取到 {len(extracted)} 条候选（session={session_id}）")

    # 双层去重
    deduped = await _deduplicate(llm_client, model, extracted, existing_entries)
    if not deduped:
        logger.info(f"[Extractor] 提取到 {len(extracted)} 条，去重后为 0，不写入（session={session_id}）")
        return 0

    entries = [
        NotebookEntry.create(
            source=NotebookSource.AUTO,
            content=item.get("content", "").strip(),
            tags=item.get("tags", []),
            character_id=character_id,
        )
        for item in deduped
        if item.get("content", "").strip()
    ]

    if entries:
        add_entries_batch(entries)
        logger.info(f"[Extractor] ✅ 写入 {len(entries)} 条新记忆（session={session_id}，角色={character_id}）")

    return len(entries)


# ── 会话级提取管理器 ───────────────────────────────────────────────

class SessionExtractor:
    """
    管理单个 WebSocket 会话的提取状态。

    修复：on_session_end 改为 async，由调用方 await 确保收尾提取完成。
    旧版本用 create_task 的"发射后遗忘"模式，导致 WS 断开后 task 来不及执行。
    """

    def __init__(
        self,
        session_id: str,
        character_id: str,
        llm_client: AsyncOpenAI,
        model: str,
        character: dict,
    ):
        self.session_id    = session_id
        self.character_id  = character_id
        self.llm_client    = llm_client
        self.model         = model
        self.character     = character

        self._round_count        = 0
        self._extracted_up_to    = 0
        self._pending_task: Optional[asyncio.Task] = None

    def on_round_complete(self, messages_so_far: list[TimelineMessage]) -> None:
        """
        每完成一轮对话后调用。达到阈值时异步触发后台提取。
        """
        self._round_count += 1
        logger.debug(f"[Extractor] 轮数 +1 → {self._round_count}（阈值 {EXTRACT_EVERY_N_ROUNDS}，已提取到 {self._extracted_up_to}）")

        if self._round_count - self._extracted_up_to >= EXTRACT_EVERY_N_ROUNDS:
            logger.info(f"[Extractor] 达到 {EXTRACT_EVERY_N_ROUNDS} 轮阈值，触发后台提取（session={self.session_id}）")
            self._trigger_background_extraction(messages_so_far)

    async def on_session_end(self, messages_so_far: list[TimelineMessage]) -> None:
        """
        会话结束时调用（async，调用方需 await）。
        对尚未提取的对话做收尾提取，同步等待完成。
        """
        # 先等待之前的后台任务完成（如果有的话）
        if self._pending_task and not self._pending_task.done():
            try:
                await asyncio.wait_for(self._pending_task, timeout=15.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                logger.warning("[Extractor] 等待之前的后台提取超时，继续收尾")

        unextracted_rounds = self._round_count - self._extracted_up_to
        if unextracted_rounds < 3:
            logger.info(
                f"[Extractor] 会话结束，仅 {unextracted_rounds} 轮未提取（不足3轮），跳过收尾（session={self.session_id}）"
            )
            return

        logger.info(f"[Extractor] 会话结束，收尾提取（{unextracted_rounds} 轮未提取，session={self.session_id}）")
        self._extracted_up_to = self._round_count

        recent_count = max(unextracted_rounds * 2, 4)  # 至少取 4 条
        recent = messages_so_far[-recent_count:] if len(messages_so_far) > recent_count else messages_so_far[:]

        try:
            count = await extract_and_save(
                llm_client=self.llm_client,
                model=self.model,
                character=self.character,
                character_id=self.character_id,
                session_id=self.session_id,
                recent_messages=recent,
            )
            if count > 0:
                logger.info(f"[Extractor] ✅ 收尾提取完成，新增 {count} 条（session={self.session_id}）")
            else:
                logger.info(f"[Extractor] 收尾提取完成，无新信息（session={self.session_id}）")
        except Exception as e:
            logger.error(f"[Extractor] 收尾提取异常（session={self.session_id}）: {e}")

    def _trigger_background_extraction(self, messages: list[TimelineMessage]) -> None:
        """异步后台触发提取（用于 10 轮定时触发，不阻塞对话）"""
        self._extracted_up_to = self._round_count

        recent_count = EXTRACT_EVERY_N_ROUNDS * 2
        recent = messages[-recent_count:] if len(messages) > recent_count else messages[:]

        async def _run():
            try:
                count = await extract_and_save(
                    llm_client=self.llm_client,
                    model=self.model,
                    character=self.character,
                    character_id=self.character_id,
                    session_id=self.session_id,
                    recent_messages=recent,
                )
                if count > 0:
                    logger.info(f"[Extractor] ✅ 后台提取完成，新增 {count} 条（session={self.session_id}）")
                else:
                    logger.info(f"[Extractor] 后台提取完成，无新信息（session={self.session_id}）")
            except Exception as e:
                logger.error(f"[Extractor] 后台提取异常（session={self.session_id}）: {e}")

        if self._pending_task and not self._pending_task.done():
            logger.debug("[Extractor] 上一个后台提取还在运行，跳过本次")
            return

        self._pending_task = asyncio.create_task(_run())

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