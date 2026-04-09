"""
Reverie Link · 记忆系统 — 核心档案自动提取模块

从对话记录中自动提取关于用户的信息,以角色口吻写入「{角色名}的日记本」。

触发时机:
  1. 每累积 EXTRACT_EVERY_N_ROUNDS 轮新对话触发一次(后台异步)
  2. 会话结束(WebSocket 断开)时对未提取内容做收尾提取(同步 await)

参考文档:PHASE3_MEMORY_DESIGN.md § 5

【2026-04-09 修复】
  ▸ on_session_end 阈值从 < 3 降为 < 1 —— 碎片化短会话也能触发收尾
  ▸ Prompt 大改 + 新增 _is_about_self 机械 post-check —— 拦截桌宠自述
  ▸ 关键路径临时 print 日志(logger.xxx 未配置 basicConfig 看不到)
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Optional

from openai import AsyncOpenAI

from .models import (
    MessageType,
    NotebookEntry,
    NotebookSource,
    TimelineMessage,
)
from .db_notebook import (
    add_entries_batch,
    get_all_entries,
    get_all_entries_for_prompt,
)

logger = logging.getLogger(__name__)  # 保留,整改后切回 logger.xxx

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

    return f"""你是「{name}」,{identity}。
性格:{personality}
说话风格:{style}
你称呼用户为:{address}

你正在写日记本,记录你对{address}的了解。
以下是你和{address}最近的对话。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【⚠️ 核心规则 —— 必须严格遵守】
日记本只记录关于【{address}】的事情,绝不记录关于【你自己】的事情。

你自己(「{name}」)的性格、身份、外貌、口头禅、小动作、喜好、
种族设定、背景故事,这些是你的人物设定,不是你从对话中观察到
的{address}。它们【绝对不能】出现在日记本里。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【❌ 绝对禁止写的内容】
- 任何以"我"开头的条目
- "我叫XX" / "我是XX" / "我性格XX" / "我住在XX" / "我喜欢XX"
- 你自己的性格特点、口头禅、说话习惯、身体小动作
- 你自己的身份设定(名字、种族、职业、外貌、背景)
- 你自己在对话里表达的情绪或做的动作

【✅ 应该写的内容 —— 只记关于 {address} 这个人的信息】
- 基本信息:{address}的姓名、年龄、性别、职业、所在地
- 爱好兴趣:{address}喜欢玩的【具体游戏名】、运动、音乐、影视、美食、动漫
- 生活习惯:{address}的作息、日常行为、反复出现的举动
- 人际关系:{address}的家人、朋友、同事、宠物
- 相处模式:{address}和你之间反复出现的互动习惯
  例如「{address}习惯睡前和我聊天」「{address}打游戏时喜欢和我分享战况」
- 重要事件:{address}提到的值得长期记住的经历、计划、纪念日

【写作要求】
1. 用你的性格和口吻来写,但事实必须准确,绝不编造
2. 每条一句话
3. **每一条的主语必须是 {address} 或其代称**,绝不能以"我"开头
4. 每条分配 1~3 个标签,优先从预设标签中选:{PRESET_TAGS_STR}
5. 没有值得记录的新信息就返回空数组 []
6. 宁可少记,也不要记关于你自己的内容

【已有的记忆(不要重复)】
{existing_entries}

【对话记录】
{recent_conversations}

以 JSON 数组格式输出,每个元素包含 content 和 tags 两个字段。
不要输出任何其他内容,不要使用 markdown 代码块。
示例:[{{"content": "{address}喜欢打羽毛球。", "tags": ["运动", "羽毛球"]}}]"""


def _build_dedup_prompt(new_content: str, existing_content: str) -> str:
    return f"""以下两条信息是否描述同一件事?只回答"是"或"否"。

信息A:{new_content}
信息B:{existing_content}"""


# ── 格式化对话记录 ─────────────────────────────────────────────────

def _format_conversations(messages: list[TimelineMessage]) -> str:
    lines = []
    for msg in messages:
        ts = msg.timestamp[:19].replace("T", " ")
        if msg.type in (MessageType.USER_TEXT, MessageType.USER_VOICE):
            lines.append(f"[{ts}] 用户:{msg.content}")
        elif msg.type == MessageType.AI_REPLY:
            lines.append(f"[{ts}] {msg.content}")
    return "\n".join(lines) if lines else "(无对话记录)"


# ── 机械 post-check:拦截以"我"开头的桌宠自述条目 ─────────────────

def _is_about_self(content: str) -> bool:
    """
    拦截以"我"开头的桌宠自述条目。
    Prompt 之外的最后一道硬防线,防 LLM 不听话。
    只做保守的硬规则,不做语义判断,避免误杀。
    """
    if not content:
        return True
    stripped = content.lstrip(" \t「\"'『【·-—*·").strip()
    if not stripped:
        return True
    return stripped.startswith("我")


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
        return resp.choices[0].message.content.strip().startswith("是")
    except Exception as e:
        print(f"[Extractor] ⚠ 去重精判失败(保守返回 False): {e}", flush=True)
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
        candidates  = [e for e in existing_entries if _tags_overlap(e.tags, new_tags)]

        is_dup = False
        for candidate in candidates:
            if await _is_duplicate_by_llm(llm_client, model, new_content, candidate.content):
                print(f"[Extractor]   去重丢弃: {new_content!r} ≈ {candidate.content!r}", flush=True)
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
    """从最近对话中提取新信息并写入笔记本自动区。Returns: 写入的新条目数量"""

    dialog_messages = [
        m for m in recent_messages
        if m.type in (MessageType.USER_TEXT, MessageType.USER_VOICE, MessageType.AI_REPLY)
    ]
    print(
        f"[Extractor] ▶ extract_and_save | session={session_id} "
        f"recent={len(recent_messages)} dialog={len(dialog_messages)} character={character_id!r}",
        flush=True,
    )

    if len(dialog_messages) < 2:
        print(f"[Extractor] ✗ 对话消息不足 2 条,跳过", flush=True)
        return 0

    conversation_text = _format_conversations(dialog_messages)
    existing_entries  = get_all_entries(character_id=character_id)
    existing_text     = get_all_entries_for_prompt(character_id=character_id)

    prompt = _build_extract_prompt(character, conversation_text, existing_text)

    # ── 调用 LLM 提取 ─────────────────────────────────────────
    t_llm = time.time()
    try:
        resp = await llm_client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=800,
            temperature=0.3,
        )
        raw_output = resp.choices[0].message.content.strip()
    except Exception as e:
        print(f"[Extractor] ✗ LLM 提取失败 耗时={time.time()-t_llm:.2f}s: {e}", flush=True)
        return 0

    # 关键:记录 LLM 原始完整输出(不清洗,按项目约定)
    print(
        f"[Extractor] 🤖 LLM 提取完成 耗时={time.time()-t_llm:.2f}s "
        f"已有记忆={len(existing_entries)}条 prompt长度={len(prompt)}",
        flush=True,
    )
    print(f"[Extractor]   LLM 原始输出: {raw_output!r}", flush=True)

    if not raw_output:
        return 0

    # ── 解析 JSON ─────────────────────────────────────────────
    try:
        clean = raw_output.strip()
        if clean.startswith("```"):
            clean = "\n".join(clean.split("\n")[1:])
        if clean.endswith("```"):
            clean = "\n".join(clean.split("\n")[:-1])
        extracted = json.loads(clean.strip())
        if not isinstance(extracted, list):
            print(f"[Extractor] ✗ LLM 输出不是数组,跳过", flush=True)
            return 0
        if not extracted:
            print(f"[Extractor] ○ LLM 返回空数组,无新信息", flush=True)
            return 0
    except json.JSONDecodeError as e:
        print(f"[Extractor] ✗ JSON 解析失败: {e}", flush=True)
        return 0

    # ── Post-check:拦截桌宠自述条目 ──────────────────────────
    post_checked = []
    for item in extracted:
        content = item.get("content", "").strip()
        if _is_about_self(content):
            print(f"[Extractor]   🚫 post-check 丢弃(桌宠自述): {content!r}", flush=True)
            continue
        post_checked.append(item)

    if not post_checked:
        print(f"[Extractor] ✗ post-check 后为空(候选 {len(extracted)} 条全是自述)", flush=True)
        return 0

    # ── 双层去重 ──────────────────────────────────────────────
    deduped = await _deduplicate(llm_client, model, post_checked, existing_entries)
    if not deduped:
        print(f"[Extractor] ○ 去重后为 0(候选 {len(post_checked)} 条全部重复)", flush=True)
        return 0

    # ── 构造并写入笔记本 ──────────────────────────────────────
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
        print(f"[Extractor] ✅ 写入 {len(entries)} 条新记忆 | session={session_id}", flush=True)
        for e in entries:
            print(f"[Extractor]   ✓ {e.content!r} tags={e.tags}", flush=True)

    return len(entries)


# ── 会话级提取管理器 ───────────────────────────────────────────────

class SessionExtractor:
    """
    管理单个 WebSocket 会话的提取状态。
    每次 WS 连接创建一个实例,_round_count 从 0 开始计数。
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

        print(
            f"[Extractor] 🆕 SessionExtractor 创建 | session={session_id} "
            f"character={character_id!r} 阈值={EXTRACT_EVERY_N_ROUNDS}轮",
            flush=True,
        )

    def on_round_complete(self, messages_so_far: list[TimelineMessage]) -> None:
        """每完成一轮对话后调用,达到阈值时异步触发后台提取。"""
        self._round_count += 1
        gap = self._round_count - self._extracted_up_to

        print(
            f"[Extractor] 📈 轮数+1 round={self._round_count} "
            f"gap={gap}/{EXTRACT_EVERY_N_ROUNDS} session={self.session_id}",
            flush=True,
        )

        if gap >= EXTRACT_EVERY_N_ROUNDS:
            print(f"[Extractor] 🔔 达到阈值,触发后台提取", flush=True)
            self._trigger_background_extraction(messages_so_far)

    async def on_session_end(self, messages_so_far: list[TimelineMessage]) -> None:
        """
        会话结束时调用(async,调用方需 await)。
        【修复】阈值从 < 3 降为 < 1 —— 只要有至少 1 轮未提取就做收尾。
        """
        # 等待之前的后台任务完成
        if self._pending_task and not self._pending_task.done():
            try:
                await asyncio.wait_for(self._pending_task, timeout=15.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                print(f"[Extractor] ⚠ 等待上一个后台提取超时,继续收尾", flush=True)

        unextracted_rounds = self._round_count - self._extracted_up_to
        print(
            f"[Extractor] 🏁 会话结束 round={self._round_count} "
            f"extracted_up_to={self._extracted_up_to} unextracted={unextracted_rounds} "
            f"session={self.session_id}",
            flush=True,
        )

        if unextracted_rounds < 1:
            print(f"[Extractor] ○ 无未提取对话,跳过收尾", flush=True)
            return

        self._extracted_up_to = self._round_count
        recent_count = max(unextracted_rounds * 2, 4)
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
            print(f"[Extractor] 🏁 收尾提取完成,新增 {count} 条", flush=True)
        except Exception as e:
            print(f"[Extractor] ✗ 收尾提取异常: {e}", flush=True)

    def _trigger_background_extraction(self, messages: list[TimelineMessage]) -> None:
        """后台触发提取(10 轮定时,不阻塞对话)"""
        self._extracted_up_to = self._round_count

        recent_count = EXTRACT_EVERY_N_ROUNDS * 2
        recent = messages[-recent_count:] if len(messages) > recent_count else messages[:]

        session_id   = self.session_id
        llm_client   = self.llm_client
        model        = self.model
        character    = self.character
        character_id = self.character_id

        async def _run():
            try:
                count = await extract_and_save(
                    llm_client=llm_client, model=model, character=character,
                    character_id=character_id, session_id=session_id, recent_messages=recent,
                )
                print(f"[Extractor] 📦 后台提取完成,新增 {count} 条 (session={session_id})", flush=True)
            except Exception as e:
                print(f"[Extractor] ✗ 后台提取异常 (session={session_id}): {e}", flush=True)

        if self._pending_task and not self._pending_task.done():
            print(f"[Extractor]   上一个后台提取还在运行,跳过本次", flush=True)
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