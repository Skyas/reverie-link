"""
Reverie Link · 视觉感知主动发言处理器
"""

import asyncio
import json
import logging
import re
import time  # 新增：用于静默期控制和记忆同步

from fastapi.websockets import WebSocket

from utils.emotion import _extract_emotion
from memory import (
    MessageType,
    TimelineMessage,
    save_message,
)
from memory.vector_store import retrieve_relevant_summaries
from prompt_builder import build_vision_speech_messages

logger = logging.getLogger(__name__)

# 最近发言记录
_recent_vision_speeches: list = []

# 【新增】全局静默期锁，记录最后一次主动发言的时间
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
    # 【修复重复】：接收你在前端调的采样参数
    temperature: float = 0.8,
    top_p: float = 0.9,
    frequency_penalty: float = 0.5,
) -> None:
    global _recent_vision_speeches
    global _last_proactive_time

    now = time.time()

    # 【修复抢话 ①】：距离上次主动搭话不足 15 秒，直接放弃
    if now - _last_proactive_time < 15.0:
        # 清空堆积的队列，防止 15 秒后像憋坏了一样连发
        while not speech_queue.empty():
            speech_queue.get_nowait()
        return

    try:
        trigger = speech_queue.get_nowait()
    except asyncio.QueueEmpty:
        return

    # 【修复抢话 ②】：只要取出一个发言任务，就把队列里剩下的清空，保证绝对只发一条
    while not speech_queue.empty():
        speech_queue.get_nowait()

    if trigger.get("session_id") and trigger["session_id"] != session_id:
        return

    # ── 向量检索 ──────────
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
                if relevant_summaries:
                    logger.info(f"[Vision] 主动发言向量检索召回 {len(relevant_summaries)} 条摘要")
            except Exception as e:
                logger.warning(f"[Vision] 主动发言向量检索失败: {e}")

    # ── 补充 address ──────────────
    if character and "address" not in trigger:
        trigger["address"] = character.get("address", "用户")

    try:
        messages = build_vision_speech_messages(
            system_prompt,
            trigger,
            recent_speeches=_recent_vision_speeches,
            history=list(history),
            window_index=window_index,
            character_id=session_character_id,
            character_name=character_name,
            relevant_summaries=relevant_summaries,
        )
        
        # 【修复重复】：在这里真正应用上 Frequency Penalty
        try:
            response = await llm_client.chat.completions.create(
                model=llm_model, messages=messages,
                max_completion_tokens=200, 
                temperature=temperature,
                top_p=top_p,
                frequency_penalty=frequency_penalty
            )
        except Exception:
            response = await llm_client.chat.completions.create(
                model=llm_model, messages=messages,
                max_tokens=200, 
                temperature=temperature,
                top_p=top_p,
                frequency_penalty=frequency_penalty
            )
        reply = response.choices[0].message.content.strip()
        logger.info(f"[Vision] LLM回复: {reply[:50]}")
    except Exception as e:
        logger.error(f"[Vision] 主动发言 LLM 调用失败: {e}")
        return

    emotion = _extract_emotion(reply)
    reply = re.sub(r'[<＜]event[>＞].*?[<＜]/event[>＞]', '', reply, flags=re.DOTALL | re.IGNORECASE).strip()
    clean_reply = re.sub(r'\[(happy|sad|angry|shy|surprised|neutral|sigh)\]', '', reply, flags=re.IGNORECASE)
    clean_reply = re.sub(r'\[[a-zA-Z_]+\]', '', clean_reply)
    clean_reply = clean_reply.strip()

    # 允许"不说话"（回复 …… 或空）
    if not clean_reply or clean_reply in ("……", "...", "。"):
        return

    # 记录最近发言，防重复
    _recent_vision_speeches.append(clean_reply)
    if len(_recent_vision_speeches) > 5:
        _recent_vision_speeches.pop(0)

    # 写入时间线
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

    # 【修复记忆断层】：让主动发言真正写入主记忆本，摆脱“前言不搭后语”
    history.append({
        "role": "assistant",
        "content": clean_reply,
        "timestamp": time.time()
    })

    # 【刷新静默期】：重置时间，接下来 15 秒内闭嘴
    _last_proactive_time = time.time()

    await websocket.send_text(json.dumps({
        "type":    "vision_proactive_speech",
        "message": reply,
    }, ensure_ascii=False))