"""
Reverie Link · 视觉感知主动发言处理器

从视觉感知队列中取出待发事件，调用 LLM 生成发言内容并通过 WebSocket 推送给前端。
所有外部依赖（llm_client、websocket 等）均通过函数参数传入，不引用 main.py 全局变量。
"""

import asyncio
import json
import re

from fastapi.websockets import WebSocket

from utils.emotion import _extract_emotion
from memory import (
    MessageType,
    TimelineMessage,
    save_message,
)
from prompt_builder import build_vision_speech_messages


# 最近发言记录（模块级，防止主动发言重复）
_recent_vision_speeches: list = []


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
) -> None:
    """
    检查并处理视觉感知主动发言队列中的待发事件。
    每次最多处理 1 条，避免连续刷屏。
    """
    global _recent_vision_speeches

    try:
        trigger = speech_queue.get_nowait()
    except asyncio.QueueEmpty:
        return

    if trigger.get("session_id") and trigger["session_id"] != session_id:
        return

    try:
        messages = build_vision_speech_messages(
            system_prompt,
            trigger,
            recent_speeches=_recent_vision_speeches,
            history=list(history),
            window_index=window_index,
            character_id=session_character_id,
            character_name=character_name,
        )
        try:
            response = await llm_client.chat.completions.create(
                model=llm_model, messages=messages,
                max_completion_tokens=200, temperature=0.9,
            )
        except Exception:
            response = await llm_client.chat.completions.create(
                model=llm_model, messages=messages,
                max_tokens=200, temperature=0.9,
            )
        reply = response.choices[0].message.content.strip()
        print(f"[Vision] LLM回复（finish_reason={response.choices[0].finish_reason}）: {reply[:50]}")
    except Exception as e:
        print(f"[Vision] 主动发言 LLM 调用失败: {e}")
        return

    emotion = _extract_emotion(reply)
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

    await websocket.send_text(json.dumps({
        "type":    "vision_proactive_speech",
        "message": reply,
    }, ensure_ascii=False))