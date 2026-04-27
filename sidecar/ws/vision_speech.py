"""
Reverie Link · 视觉感知主动发言处理器

【2026-04-09 修改】
  ★ 配合 messages.py 的核心修复：history 不再被过滤
    —— _source=="vision_proactive" 标记仍然写入（供 messages.py 的避免重复区扫描使用）
    —— 但 build_vision_speech_messages 内部不再据此过滤 history
  ★ 补完整的 print 临时日志链路，便于排查
    —— 触发取出 / 冷却命中 / 跨 session 丢弃 / 向量检索
    —— LLM 调用前后耗时 / LLM 原始输出全文（不是清洗后版本）
    —— 沉默/复读丢弃决策 / 写入数据库与 history
    —— 前缀 [VisionSpeech]，待统一整改 logging 后改为 logger.xxx

【既有要点（保留）】
  1. 移除 event 机制（session_events 参数、event 提取/抹除正则）
     —— event 簿被验证会引发自我强化复读循环
  2. history append 时打 _source="vision_proactive" 标记
     —— 让 build_vision_speech_messages 能识别并组装到「避免重复区」
  3. 退化重复检测 —— 若模型输出复读，直接静默丢弃
  4. max_tokens 150 —— 50字硬约束 150 tokens 完全够用
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


def _summarize_messages_for_log(messages: list) -> str:
    """把 messages 列表压缩成一行可读摘要，用于日志"""
    parts = []
    for i, m in enumerate(messages):
        role = m.get("role", "?")
        content = m.get("content", "")
        if isinstance(content, str):
            length = len(content)
        elif isinstance(content, list):
            # 多模态消息体
            length = sum(
                len(part.get("text", "")) if isinstance(part, dict) else 0
                for part in content
            )
        else:
            length = 0
        parts.append(f"#{i}({role},{length})")
    return " ".join(parts)


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
    voice_processor=None,
) -> None:
    global _last_proactive_time

    now = time.time()

    # ── 防连发：30 秒强制冷却 ─────────────────────────────────
    cooldown_remaining = 30.0 - (now - _last_proactive_time)
    if cooldown_remaining > 0:
        # 清空队列里堆积的触发，避免冷却结束后扎堆触发
        drained = 0
        while not speech_queue.empty():
            try:
                speech_queue.get_nowait()
                drained += 1
            except asyncio.QueueEmpty:
                break
        if drained > 0:
            print(
                f"[VisionSpeech] 冷却中(剩余{cooldown_remaining:.1f}s)，"
                f"丢弃队列中堆积的 {drained} 个触发",
                flush=True,
            )
        return

    # ── 取出一个触发，丢弃其余 ─────────────────────────────────
    try:
        trigger = speech_queue.get_nowait()
    except asyncio.QueueEmpty:
        return

    extras_dropped = 0
    while not speech_queue.empty():
        try:
            speech_queue.get_nowait()
            extras_dropped += 1
        except asyncio.QueueEmpty:
            break

    # 即便后续大模型报错，也立刻锁死接下来的 30 秒
    _last_proactive_time = time.time()

    trigger_reason = trigger.get("reason", "")
    trigger_scene = trigger.get("scene_info", {}).get("scene_type", "unknown")
    trigger_game  = trigger.get("scene_info", {}).get("game_name")
    trigger_desc  = trigger.get("scene_info", {}).get("scene_description", "")
    print(
        f"[VisionSpeech] ▶ 触发取出 | reason={trigger_reason} scene={trigger_scene} "
        f"game={trigger_game} extras_dropped={extras_dropped} "
        f"history_len={len(history)} window_idx={window_index}",
        flush=True,
    )
    if trigger_desc:
        print(f"[VisionSpeech]   场景描述: {trigger_desc[:120]}", flush=True)

    # 跨 session 触发直接丢弃
    if trigger.get("session_id") and trigger["session_id"] != session_id:
        print(
            f"[VisionSpeech] ✗ 跨 session 丢弃 | "
            f"trigger_session={trigger.get('session_id')} current_session={session_id}",
            flush=True,
        )
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
                t_vec = time.time()
                relevant_summaries = retrieve_relevant_summaries(
                    query=query,
                    character_id=session_character_id,
                    top_k=3,
                )
                print(
                    f"[VisionSpeech] 🔍 向量检索完成 | query={query[:60]!r} "
                    f"hits={len(relevant_summaries)} 耗时={time.time()-t_vec:.2f}s",
                    flush=True,
                )
                if relevant_summaries:
                    for i, s in enumerate(relevant_summaries):
                        print(f"[VisionSpeech]   命中#{i}: {s[:80]}", flush=True)
            except Exception as e:
                print(f"[VisionSpeech] ⚠ 向量检索失败: {e}", flush=True)

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

        print(
            f"[VisionSpeech] 📝 messages 组装完成 | count={len(messages)} | "
            f"{_summarize_messages_for_log(messages)}",
            flush=True,
        )

        t_llm = time.time()
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
        except Exception as fallback_e:
            print(
                f"[VisionSpeech] max_completion_tokens 不被支持，"
                f"fallback 到 max_tokens | err={fallback_e}",
                flush=True,
            )
            response = await llm_client.chat.completions.create(
                model=llm_model,
                messages=messages,
                max_tokens=150,
                temperature=temperature,
                top_p=top_p,
                frequency_penalty=frequency_penalty,
            )
        llm_elapsed = time.time() - t_llm
        reply = response.choices[0].message.content.strip()

        # 关键：记录 LLM 原始完整输出（不是清洗后给前端的版本）
        # 这是事后排查"为什么模型这次输出了奇怪的东西"的唯一手段
        print(
            f"[VisionSpeech] 🤖 LLM 调用完成 | model={llm_model} 耗时={llm_elapsed:.2f}s "
            f"原始长度={len(reply)}",
            flush=True,
        )
        print(f"[VisionSpeech]   LLM 原始输出: {reply!r}", flush=True)
    except Exception as e:
        print(f"[VisionSpeech] ✗ 主动发言 LLM 调用失败: {e}", flush=True)
        return

    # 【2026-04-27 语音输入系统】LLM 生成完成后开启 3 秒预窗口，覆盖生成延迟期间用户的语音
    if voice_processor:
        voice_processor.open_pre_window()

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
        print(
            f"[VisionSpeech] 🤐 模型选择沉默，跳过发送 | clean={clean_reply!r}",
            flush=True,
        )
        return

    # ── 退化重复检测：直接静默丢弃 ─────────────────────────────
    if is_degenerate_repetition(clean_reply):
        print(
            f"[VisionSpeech] 🚫 退化重复输出，静默丢弃 | 内容={clean_reply[:60]!r}",
            flush=True,
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
    # 普通对话路径完整保留这条消息，记忆联通；
    # 视觉主动发言路径下次组装时会从 history 中识别这条 _source，
    # 拼装到「避免重复区」，明确告诉模型"严禁重复"。
    history.append({
        "role": "assistant",
        "content": clean_reply,
        "timestamp": time.time(),
        "_source": "vision_proactive",
    })

    print(
        f"[VisionSpeech] ✅ 主动发言已发送 | clean_len={len(clean_reply)} "
        f"emotion={emotion} history_len_after={len(history)}",
        flush=True,
    )
    print(f"[VisionSpeech]   清洗后内容: {clean_reply!r}", flush=True)

    await websocket.send_text(json.dumps(
        {"type": "vision_proactive_speech", "message": reply},
        ensure_ascii=False,
    ))

    # 【2026-04-27 语音输入系统】发送完成后开启正式 15 秒对话窗口（自动覆盖预窗口）
    if voice_processor:
        voice_processor.on_pet_response_sent()