"""
Reverie Link · 记忆系统 — 核心档案自动提取模块

从对话记录中自动提取用户信息，以角色口吻写入「{角色名}的日记本」（自动区）。

触发时机：
  1. 每累积 EXTRACT_EVERY_N_ROUNDS 轮新对话触发一次
  2. 会话结束（WebSocket 断开）时对未提取内容做收尾提取

提取流程：
  1. 读取最近一批对话记录
  2. 读取已有笔记本条目（用于去重）
  3. 调用 LLM（角色口吻）提取新信息
  4. 双层去重：标签粗筛 + LLM 精判
  5. 写入自动区

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
# 每累积多少轮对话触发一次提取（1轮 = 1条用户消息 + 1条AI回复）
EXTRACT_EVERY_N_ROUNDS: int = 10

# ── 预设标签（LLM 优先从此列表选择，不够用时可自建）────────────────
PRESET_TAGS: list[str] = [
    # 基本信息
    "姓名", "年龄", "性别", "职业", "所在地",
    # 兴趣爱好
    "游戏", "运动", "音乐", "动漫", "影视", "阅读", "美食", "旅行",
    # 性格特征
    "性格", "习惯", "偏好", "讨厌的事",
    # 社交关系
    "家人", "朋友", "同事", "宠物",
    # 游戏相关
    "常玩游戏", "游戏ID", "游戏习惯", "段位/水平",
    # 重要经历
    "纪念日", "成就", "近期事件",
]

PRESET_TAGS_STR = "、".join(PRESET_TAGS)


# ── 提取 Prompt ────────────────────────────────────────────────────

def _build_extract_prompt(
    character: dict,
    recent_conversations: str,
    existing_entries: str,
) -> str:
    """
    构造自动提取用的 Prompt。
    使用角色口吻，让日记本内容更具角色特色。
    """
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
把你从对话中了解到的关于{address}的新信息写成简短的日记条目。

要求：
1. 用你的性格和口吻来写，但事实必须准确，不编造
2. 每条一句话
3. 为每条分配1~3个标签，优先从以下预设标签中选择：{PRESET_TAGS_STR}
   不够用时可自建标签
4. 没有新信息就返回空数组 []
5. 只提取关于{address}的信息，不提取关于你自己的

已有的记忆（不要重复这些内容）：
{existing_entries}

对话记录：
{recent_conversations}

以JSON数组格式输出，每个元素包含 content 和 tags 两个字段。
不要输出任何其他内容，不要使用 markdown 代码块。
示例格式：[{{"content": "哥哥喜欢打羽毛球。", "tags": ["运动", "羽毛球"]}}]"""


def _build_dedup_prompt(new_content: str, existing_content: str) -> str:
    """构造语义去重精判 Prompt"""
    return f"""以下两条信息是否描述同一件事？只回答"是"或"否"。

信息A：{new_content}
信息B：{existing_content}"""


# ── 格式化对话记录 ─────────────────────────────────────────────────

def _format_conversations(messages: list[TimelineMessage]) -> str:
    """将消息列表格式化为对话文本，供 Prompt 使用"""
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
    """判断两组标签是否有交集（粗筛）"""
    return bool(set(tags_a) & set(tags_b))


async def _is_duplicate_by_llm(
    llm_client: AsyncOpenAI,
    model: str,
    new_content: str,
    existing_content: str,
) -> bool:
    """
    调用 LLM 精判两条信息是否描述同一件事。
    失败时保守返回 False（宁可重复也不误杀）。
    """
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
    """
    双层去重：
    1. 标签粗筛：找出与新条目有标签交集的已有条目
    2. LLM 精判：对粗筛命中的条目判断是否描述同一件事
    返回去重后的新条目列表。
    """
    result = []
    for new in new_entries:
        new_tags    = new.get("tags", [])
        new_content = new.get("content", "")
        is_dup = False

        # 粗筛：找标签有交集的已有条目
        candidates = [e for e in existing_entries if _tags_overlap(e.tags, new_tags)]

        # 精判：逐一用 LLM 判断
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
    核心提取函数：从最近对话中提取新信息并写入笔记本自动区。

    Args:
        llm_client:      AsyncOpenAI 客户端（复用 main.py 的配置）
        model:           使用的模型名称
        character:       当前角色配置 dict
        character_id:    当前角色卡 ID（用于数据隔离）
        session_id:      当前会话 ID（仅用于日志）
        recent_messages: 待分析的消息列表

    Returns:
        写入的新条目数量
    """
    if not recent_messages:
        return 0

    # 过滤：只保留用户消息和 AI 回复，排除游戏事件等
    dialog_messages = [
        m for m in recent_messages
        if m.type in (MessageType.USER_TEXT, MessageType.USER_VOICE, MessageType.AI_REPLY)
    ]
    if len(dialog_messages) < 2:
        return 0

    # 格式化对话文本
    conversation_text = _format_conversations(dialog_messages)

    # 读取已有条目（用于去重和喂给 LLM 避免重复提取）
    existing_entries  = get_all_entries(character_id=character_id)
    existing_text     = get_all_entries_for_prompt(character_id=character_id)

    # 构造提取 Prompt 并调用 LLM
    prompt = _build_extract_prompt(character, conversation_text, existing_text)
    try:
        resp = await llm_client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=800,
            temperature=0.3,
        )
        raw_output = resp.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"[Extractor] LLM 提取失败（session={session_id}）: {e}")
        return 0

    # 解析 JSON 输出
    try:
        # 清理可能的 markdown 代码块包裹
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

    # 双层去重
    deduped = await _deduplicate(llm_client, model, extracted, existing_entries)
    if not deduped:
        logger.info(f"[Extractor] 提取到 {len(extracted)} 条，去重后为 0，不写入（session={session_id}）")
        return 0

    # 构造 NotebookEntry 对象并批量写入
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
        logger.info(f"[Extractor] 写入 {len(entries)} 条新记忆（session={session_id}，角色={character_id}）")

    return len(entries)


# ── 会话级提取管理器 ───────────────────────────────────────────────

class SessionExtractor:
    """
    管理单个 WebSocket 会话的提取状态。
    每个 websocket_chat 协程持有一个实例。

    职责：
    - 追踪本会话的对话轮数
    - 每 EXTRACT_EVERY_N_ROUNDS 轮触发一次后台提取
    - 会话结束时对剩余未提取内容做收尾提取
    - 所有提取均异步后台执行，不阻塞对话
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

        self._round_count        = 0   # 本会话累计对话轮数
        self._extracted_up_to    = 0   # 已提取到第几轮
        self._pending_task: Optional[asyncio.Task] = None

    def on_round_complete(self, messages_so_far: list[TimelineMessage]) -> None:
        """
        每完成一轮对话后调用（用户消息 + AI 回复各一条算一轮）。
        达到阈值时异步触发提取。
        """
        self._round_count += 1

        if self._round_count - self._extracted_up_to >= EXTRACT_EVERY_N_ROUNDS:
            self._trigger_extraction(messages_so_far)

    def on_session_end(self, messages_so_far: list[TimelineMessage]) -> None:
        """
        会话结束时调用，对尚未提取的对话做收尾提取。
        """
        unextracted_rounds = self._round_count - self._extracted_up_to
        if unextracted_rounds > 0:
            logger.info(f"[Extractor] 会话结束，收尾提取（{unextracted_rounds} 轮未提取，session={self.session_id}）")
            self._trigger_extraction(messages_so_far)

    def _trigger_extraction(self, messages: list[TimelineMessage]) -> None:
        """异步后台触发提取，不阻塞调用方"""
        # 记录本次提取截止轮数，防止重复提取
        self._extracted_up_to = self._round_count

        # 取自上次提取之后的消息（避免重复喂入旧内容）
        # 每轮 2 条消息，截取最近 EXTRACT_EVERY_N_ROUNDS 轮
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
                    logger.info(f"[Extractor] 后台提取完成，新增 {count} 条（session={self.session_id}）")
            except Exception as e:
                logger.error(f"[Extractor] 后台提取异常（session={self.session_id}）: {e}")

        # 取消上一个还没跑完的任务（避免堆积），再启动新任务
        if self._pending_task and not self._pending_task.done():
            self._pending_task.cancel()
        self._pending_task = asyncio.create_task(_run())

    def update_config(
        self,
        llm_client: Optional[AsyncOpenAI] = None,
        model: Optional[str] = None,
        character: Optional[dict] = None,
        character_id: Optional[str] = None,
    ) -> None:
        """
        角色或模型切换时更新配置。
        由 configure 消息处理逻辑调用。
        """
        if llm_client is not None:
            self.llm_client = llm_client
        if model is not None:
            self.model = model
        if character is not None:
            self.character = character
        if character_id is not None:
            self.character_id = character_id