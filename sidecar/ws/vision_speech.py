"""
Reverie Link · 视觉感知主动发言处理器

【本次重构要点】
  1. 移除 event 机制（session_events 参数、event 提取/抹除正则）
     —— event 簿被验证会引发自我强化复读循环
  2. 移除 _recent_vision_speeches —— 不再回喂模型最近原话
  3. history append 时打 _source="vision_proactive" 标记
     —— 让 build_vision_speech_messages 能识别并过滤
  4. 新增退化重复检测 —— 若模型输出复读，直接静默丢弃
  5. max_tokens 从 200 降到 150 —— 50字硬约束 150 tokens 完全够用
"""

import asyncio
import json
import logging
import re
import time

from fastapi.websockets import WebSocket

from utils.emotion import _extract_emotion
from utils.dedup import is_degenerate_repetition
from memory import (
    MessageType,
    TimelineMessage,
    save_message,
)
from memory.vector_store import retrieve_relevant_summaries
from prompt_builder import build_vision_speech_messages

logger = logging.getLogger(__name__)

_last_proactive_time: float = 0.0


async def _drain_vision_speech(
    websocket: WebSocket,
    llm_client,
    llm_model: str,
    system_prompt: str,
    session_id: str,
    session_character_id: str,
    history,
    session_messages: list,
    speech_queue: asyncio.Queue,
    window_index: int = 1,
    character_name: str = "",
    character: dict = None,
    temperature: float = 0.8,
    top_p: float = 0.9,
    frequency_penalty: float = 0.5,
) -> None:
    global _last_proactive_time

    now = time.time()

    # ── 防连发：30 秒强制冷却 ─────────────────────────────────
    if now - _last_proactive_time < 30.0:
        # 清空队列里堆积的触发，避免冷却结束后扎堆触发
        while not speech_queue.empty():
            try:
                speech_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        return

    # ── 取出一个触发，丢弃其余 ─────────────────────────────────
    try:
        trigger = speech_queue.get_nowait()
    except asyncio.QueueEmpty:
        return

    while not speech_queue.empty():
        try:
            speech_queue.get_nowait()
        except asyncio.QueueEmpty:
            break

    # 即便后续大模型报错，也立刻锁死接下来的 30 秒
    _last_proactive_time = time.time()

    # 跨 session 触发直接丢弃
    if trigger.get("session_id") and trigger["session_id"] != session_id:
        logger.debug("[VisionSpeech] 跨 session 触发，丢弃")
        return

    # ── 向量检索召回相关摘要 ───────────────────────────────────
    relevant_summaries = []
    if session_character_id:
        scene_info = trigger.get("scene_info", {})
        query_parts = []
        scene_desc = scene_info.get("scene_description", "")
        if scene_desc:
            query_parts.append(scene_desc)
        game_name = scene_info.get("game_name")
        if game_name:
            query_parts.append(game_name)
        if not query_parts and history:
            for msg in reversed(list(history)):
                if msg.get("role") == "user" and msg.get("content"):
                    query_parts.append(msg["content"])
                    break
        if query_parts:
            query = " ".join(query_parts)
            try:
                relevant_summaries = retrieve_relevant_summaries(
                    query=query,
                    character_id=session_character_id,
                    top_k=3,
                )
            except Exception as e:
                logger.warning("[VisionSpeech] 向量检索失败: %s", e)

    if character and "address" not in trigger:
        trigger["address"] = character.get("address", "用户")

    # ── 构造 messages 并调用 LLM ───────────────────────────────
    try:
        messages = build_vision_speech_messages(
            system_prompt,
            trigger,
            history=list(history),
            window_index=window_index,
            character_id=session_character_id,
            character_name=character_name,
            relevant_summaries=relevant_summaries,
        )

        # max_completion_tokens 优先（OpenAI 新接口），失败则 fallback 到 max_tokens
        try:
            response = await llm_client.chat.completions.create(
                model=llm_model,
                messages=messages,
                max_completion_tokens=150,
                temperature=temperature,
                top_p=top_p,
                frequency_penalty=frequency_penalty,
            )
        except Exception:
            response = await llm_client.chat.completions.create(
                model=llm_model,
                messages=messages,
                max_tokens=150,
                temperature=temperature,
                top_p=top_p,
                frequency_penalty=frequency_penalty,
            )
        reply = response.choices[0].message.content.strip()
    except Exception as e:
        logger.error("[VisionSpeech] 主动发言 LLM 调用失败: %s", e)
        return

    emotion = _extract_emotion(reply)

    # ── 抹除标签 ───────────────────────────────────────────────
    clean_reply = re.sub(
        r'\[(happy|sad|angry|shy|surprised|neutral|sigh)\]',
        '',
        reply,
        flags=re.IGNORECASE,
    )
    clean_reply = re.sub(r'\[[a-zA-Z_]+\]', '', clean_reply).strip()

    # 模型主动选择沉默
    if not clean_reply or clean_reply in ("……", "...", "。"):
        logger.info("[VisionSpeech] 模型选择沉默，跳过发送")
        return

    # ── 退化重复检测：直接静默丢弃 ─────────────────────────────
    if is_degenerate_repetition(clean_reply):
        logger.warning(
            "[VisionSpeech] 检测到退化重复输出，静默丢弃 | 内容=%r",
            clean_reply[:60],
        )
        return

    # ── 写入数据库 + history（带 _source 标记）─────────────────
    scene_info = trigger.get("scene_info", {})
    game_event_msg = TimelineMessage.create(
        msg_type=MessageType.GAME_EVENT,
        content=clean_reply,
        session_id=session_id,
        character_id=session_character_id,
        metadata={
            "emotion":    emotion,
            "scene_type": scene_info.get("scene_type", "unknown"),
            "game_name":  scene_info.get("game_name"),
            "confidence": scene_info.get("confidence", "low"),
            "source":     "vision_proactive",
            "reason":     trigger.get("reason", ""),
        },
    )
    save_message(game_event_msg)
    session_messages.append(game_event_msg)

    # 关键：写入 history 时打 _source 标记
    # 普通对话路径读 history 时不会过滤这条（保证记忆联通），
    # 视觉主动发言路径下次读 history 时会跳过这条（避免自我强化）。
    history.append({
        "role": "assistant",
        "content": clean_reply,
        "timestamp": time.time(),
        "_source": "vision_proactive",
    })

    logger.info("[VisionSpeech] 主动发言已发送 | 长度=%d 情绪=%s", len(clean_reply), emotion)

    await websocket.send_text(json.dumps(
        {"type": "vision_proactive_speech", "message": reply},
        ensure_ascii=False,
    ))