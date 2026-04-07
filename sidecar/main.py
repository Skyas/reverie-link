"""
Reverie Link · Python 后端
FastAPI + WebSocket 主入口

【本次重构要点】
  1. 移除 session_events 列表与所有传递（event 机制已废弃）
  2. 移除 event 提取与抹除的正则
  3. 普通对话路径加入退化重复检测：
     - 退化输出降级为 "……[neutral]" 发给前端
     - 不写入 history、不写入数据库（避免污染下一轮）
  4. 关键位置加 logger 输出，方便测试定位
"""

import json
import logging
import os
import re
import time
from collections import deque
from contextlib import asynccontextmanager
from typing import Optional

import asyncio
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.websockets import WebSocket, WebSocketDisconnect
from openai import AsyncOpenAI

from prompt_builder import (
    DEFAULT_CHARACTER,
    DEFAULT_WINDOW_INDEX,
    WINDOW_PRESETS,
    build_messages,
    build_system_prompt,
    build_screenshot_messages,
    build_multimodal_screenshot_messages,
    trim_history as _trim,
)
from memory import (
    init_memory_system,
    shutdown_memory_system,
    MessageType,
    TimelineMessage,
    generate_session_id,
    save_message,
    SessionExtractor,
    SummaryQueue,
    retrieve_relevant_summaries,
)
from vision.vision_system import VisionSystem
from utils.emotion import _extract_emotion
from utils.dedup import is_degenerate_repetition
from ws.vision_speech import _drain_vision_speech
from routers.live2d import router as live2d_router
from routers.tts import router as tts_router
from routers.memory_api import router as memory_router

logger = logging.getLogger(__name__)

# ── 环境变量 ───────────────────────────────────────────────────
load_dotenv()

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
LLM_API_KEY  = os.getenv("LLM_API_KEY", "")
LLM_MODEL    = os.getenv("LLM_MODEL", "deepseek-chat")

LLM_TEMPERATURE = 0.8
LLM_TOP_P = 0.9
LLM_FREQ_PENALTY = 0.5

_MAX_HISTORY_ITEMS = WINDOW_PRESETS[-1][2] * 2

_SCREENSHOT_KEYWORDS = re.compile(
    r"(看看屏幕|屏幕上|画面|你看到了什么|帮我看看|看一眼|看一下|"
    r"屏幕怎么了|你看到什么|现在在干什么|帮我看|屏幕里)",
    re.IGNORECASE,
)

# ── 视觉感知全局状态 ──────────────────────────────────────────
vision_speech_queue: asyncio.Queue = asyncio.Queue()
vision_system: Optional[VisionSystem] = None


# ── FastAPI 生命周期 ───────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    global vision_system
    init_memory_system()
    yield
    if vision_system:
        vision_system.stop()
    shutdown_memory_system()


app = FastAPI(title="Reverie Link Backend", version="0.3.3", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ── Router 注册 ────────────────────────────────────────────────
app.include_router(live2d_router)
app.include_router(tts_router)
app.include_router(memory_router)

# ── 全局状态 ───────────────────────────────────────────────────
llm_client           = AsyncOpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)
current_character    = DEFAULT_CHARACTER
system_prompt        = build_system_prompt(current_character)
current_window_index: int = DEFAULT_WINDOW_INDEX
current_character_id: str = ""


# ── 健康检查 ───────────────────────────────────────────────────
@app.get("/health")
async def health():
    name, _, max_rounds = WINDOW_PRESETS[current_window_index]
    return {
        "status":            "ok",
        "model":             LLM_MODEL,
        "character_id":      current_character_id,
        "memory_window":     current_window_index,
        "memory_window_name": name,
        "memory_max_rounds": max_rounds,
    }

@app.get("/api/memory/window")
async def api_memory_window():
    return {
        "current_index": current_window_index,
        "current_name":  WINDOW_PRESETS[current_window_index][0],
        "presets": [
            {"index": i, "name": name, "time_minutes": secs // 60, "max_rounds": rounds}
            for i, (name, secs, rounds) in enumerate(WINDOW_PRESETS)
        ],
    }


# ── WebSocket 端点 ─────────────────────────────────────────────
@app.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    await websocket.accept()

    global llm_client, LLM_MODEL, current_character, system_prompt
    global current_window_index, current_character_id
    global LLM_TEMPERATURE, LLM_TOP_P, LLM_FREQ_PENALTY
    global vision_system, vision_speech_queue

    if not vision_system:
        vision_system = VisionSystem(speech_queue=vision_speech_queue)
    vision_system.start()
    print("[后端状态] 前端已连接，视觉与键鼠监控服务：已唤醒 ✅")

    session_id           = generate_session_id()
    history: deque[dict] = deque(maxlen=_MAX_HISTORY_ITEMS)
    session_window_index: int = current_window_index
    session_character_id: str = current_character_id

    session_messages: list = []

    extractor = SessionExtractor(
        session_id=session_id,
        character_id=session_character_id,
        llm_client=llm_client,
        model=LLM_MODEL,
        character=current_character,
    )

    summary_queue = SummaryQueue(
        character_id=session_character_id,
        session_id=session_id,
        llm_client=llm_client,
        model=LLM_MODEL,
        character=current_character,
    )

    try:
        while True:
            raw = None
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=1.0)
            except asyncio.TimeoutError:
                await _drain_vision_speech(
                    websocket=websocket,
                    llm_client=llm_client,
                    llm_model=LLM_MODEL,
                    system_prompt=system_prompt,
                    session_id=session_id,
                    session_character_id=session_character_id,
                    history=history,
                    session_messages=session_messages,
                    speech_queue=vision_speech_queue,
                    window_index=session_window_index,
                    character_name=current_character.get("name", ""),
                    character=current_character,
                    temperature=LLM_TEMPERATURE,
                    top_p=LLM_TOP_P,
                    frequency_penalty=LLM_FREQ_PENALTY,
                )
                continue

            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_text(json.dumps(
                    {"type": "error", "message": "消息格式错误，请发送 JSON。"},
                    ensure_ascii=False,
                ))
                continue

            msg_type = data.get("type")
            user_msg = data.get("message", "").strip()

            if msg_type == "configure":
                llm_cfg  = data.get("llm", {})
                char_cfg = data.get("character", {})

                if llm_cfg.get("api_key") and llm_cfg.get("base_url"):
                    llm_client = AsyncOpenAI(api_key=llm_cfg["api_key"], base_url=llm_cfg["base_url"])
                    LLM_MODEL  = llm_cfg.get("model", LLM_MODEL)
                    LLM_TEMPERATURE = float(llm_cfg.get("temperature", LLM_TEMPERATURE))
                    LLM_TOP_P = float(llm_cfg.get("top_p", LLM_TOP_P))
                    LLM_FREQ_PENALTY = float(llm_cfg.get("frequency_penalty", LLM_FREQ_PENALTY))

                if char_cfg:
                    current_character = {**DEFAULT_CHARACTER, **char_cfg}
                    system_prompt     = build_system_prompt(current_character)

                if "memory_window" in data:
                    raw_idx = data["memory_window"]
                    if isinstance(raw_idx, int) and 0 <= raw_idx <= 4:
                        current_window_index = raw_idx
                        session_window_index = raw_idx

                if "character_id" in data:
                    new_cid = str(data["character_id"]).strip()
                    current_character_id = new_cid
                    session_character_id = new_cid

                if "vision" in data and vision_system:
                    vision_system.configure(data["vision"])
                    vision_system.set_main_llm(llm_client, LLM_MODEL)
                    vision_system.set_session_info(
                        session_id=session_id,
                        character_id=session_character_id,
                        address=current_character.get("address", "你"),
                    )

                extractor.update_config(llm_client=llm_client, model=LLM_MODEL, character=current_character, character_id=session_character_id)
                summary_queue.update_config(llm_client=llm_client, model=LLM_MODEL, character=current_character, character_id=session_character_id)

                await websocket.send_text(json.dumps({"type": "configure_ack", "message": "配置已更新"}, ensure_ascii=False))
                continue

            if msg_type != "chat" or not user_msg:
                continue

            if vision_system:
                vision_system.on_user_message()

            user_timeline_msg = TimelineMessage.create(
                msg_type=MessageType.USER_TEXT, content=user_msg,
                session_id=session_id, character_id=session_character_id,
            )
            save_message(user_timeline_msg)

            user_wants_screenshot = bool(_SCREENSHOT_KEYWORDS.search(user_msg))
            screenshot_info: Optional[dict] = None
            multimodal_screenshot: Optional[dict] = None

            if user_wants_screenshot and vision_system:
                if vision_system.is_main_multimodal:
                    multimodal_screenshot = await vision_system.capture_screenshot_only()
                else:
                    screenshot_info = await vision_system.capture_for_user()

            relevant = retrieve_relevant_summaries(query=user_msg, character_id=session_character_id)

            if multimodal_screenshot and not multimodal_screenshot.get("error"):
                messages = build_multimodal_screenshot_messages(
                    system_prompt, list(history), user_msg, img_b64=multimodal_screenshot["img_b64"],
                    window_title=multimodal_screenshot.get("window_title", ""), window_index=session_window_index,
                    character_id=session_character_id, character_name=current_character.get("name", ""),
                    relevant_summaries=relevant,
                )
            elif screenshot_info and not screenshot_info.get("error"):
                messages = build_screenshot_messages(
                    system_prompt, list(history), user_msg, screenshot_info=screenshot_info,
                    window_index=session_window_index, character_id=session_character_id,
                    character_name=current_character.get("name", ""), relevant_summaries=relevant,
                )
            else:
                messages = build_messages(
                    system_prompt, list(history), user_msg, window_index=session_window_index,
                    character_id=session_character_id, character_name=current_character.get("name", ""),
                    relevant_summaries=relevant,
                )

            kept_count    = len(_trim(list(history), session_window_index))
            evicted_count = len(history) - kept_count
            if evicted_count > 0:
                evicted_msgs = session_messages[:evicted_count]
                if evicted_msgs:
                    summary_queue.push(evicted_msgs)
                    del session_messages[:evicted_count]

            try:
                response = await llm_client.chat.completions.create(
                    model=LLM_MODEL, messages=messages, max_tokens=300,
                    temperature=LLM_TEMPERATURE, top_p=LLM_TOP_P, frequency_penalty=LLM_FREQ_PENALTY
                )
                reply = response.choices[0].message.content.strip()
            except Exception as e:
                friendly = f"调用失败：{str(e)[:80]}"
                await websocket.send_text(json.dumps({"type": "error", "message": friendly}, ensure_ascii=False))
                continue

            if reply.startswith("[NEED_SCREENSHOT]") and vision_system and not screenshot_info and not multimodal_screenshot:
                if vision_system.is_main_multimodal:
                    fallback_shot = await vision_system.capture_screenshot_only()
                    if fallback_shot and not fallback_shot.get("error"):
                        msgs2 = build_multimodal_screenshot_messages(
                            system_prompt, list(history), user_msg, img_b64=fallback_shot["img_b64"],
                            window_title=fallback_shot.get("window_title", ""), window_index=session_window_index,
                            character_id=session_character_id, character_name=current_character.get("name", ""),
                            relevant_summaries=relevant,
                        )
                        try:
                            r2 = await llm_client.chat.completions.create(model=LLM_MODEL, messages=msgs2, max_tokens=300, temperature=LLM_TEMPERATURE, top_p=LLM_TOP_P, frequency_penalty=LLM_FREQ_PENALTY)
                            reply = r2.choices[0].message.content.strip()
                        except Exception:
                            pass
                else:
                    screenshot_info = await vision_system.capture_for_user()
                    if screenshot_info and not screenshot_info.get("error"):
                        msgs2 = build_screenshot_messages(
                            system_prompt, list(history), user_msg, screenshot_info=screenshot_info,
                            window_index=session_window_index, character_id=session_character_id,
                            character_name=current_character.get("name", ""), relevant_summaries=relevant,
                        )
                        try:
                            r2 = await llm_client.chat.completions.create(model=LLM_MODEL, messages=msgs2, max_tokens=300, temperature=LLM_TEMPERATURE, top_p=LLM_TOP_P, frequency_penalty=LLM_FREQ_PENALTY)
                            reply = r2.choices[0].message.content.strip()
                        except Exception:
                            pass

            emotion = _extract_emotion(reply)

            # 标签清理（不再处理 event 标签）
            clean_reply = re.sub(r'\[(happy|sad|angry|shy|surprised|neutral|sigh)\]', '', reply, flags=re.IGNORECASE)
            clean_reply = re.sub(r'\[NEED_SCREENSHOT\]', '', clean_reply, flags=re.IGNORECASE)
            clean_reply = re.sub(r'\[[a-zA-Z_]+\]', '', clean_reply).strip()

            # ── 退化重复检测：降级为 "……" 发送，不污染下一轮 ─────────
            if is_degenerate_repetition(clean_reply):
                logger.warning(
                    "[Chat] 检测到退化重复输出，降级为省略号 | 原文=%r",
                    clean_reply[:80],
                )
                # 降级输出
                fallback_clean = "……"
                fallback_reply = "……[neutral]"

                # 仍然写入数据库（用户能在聊天记录里看到桌宠"沉默"了一下）
                ai_timeline_msg = TimelineMessage.create(
                    msg_type=MessageType.AI_REPLY,
                    content=fallback_clean,
                    session_id=session_id,
                    character_id=session_character_id,
                    reply_to=user_timeline_msg.id,
                    metadata={"emotion": "neutral", "degenerate_filtered": True},
                )
                save_message(ai_timeline_msg)

                # 关键：写入 history 的是降级后的"……"，而不是原来的复读文本
                # 这样下一轮就不会再被坏内容污染
                now_ts = time.time()
                history.append({"role": "user",      "content": user_msg,       "timestamp": now_ts})
                history.append({"role": "assistant", "content": fallback_clean, "timestamp": now_ts})

                session_messages.append(user_timeline_msg)
                session_messages.append(ai_timeline_msg)
                extractor.on_round_complete(session_messages)

                await websocket.send_text(json.dumps(
                    {"type": "chat_response", "message": fallback_reply},
                    ensure_ascii=False,
                ))

                if vision_system:
                    vision_system.on_user_message_done()
                continue

            # ── 正常路径 ───────────────────────────────────────────
            ai_timeline_msg = TimelineMessage.create(
                msg_type=MessageType.AI_REPLY, content=clean_reply,
                session_id=session_id, character_id=session_character_id,
                reply_to=user_timeline_msg.id, metadata={"emotion": emotion} if emotion else {},
            )
            save_message(ai_timeline_msg)

            now_ts = time.time()
            history.append({"role": "user",      "content": user_msg,    "timestamp": now_ts})
            history.append({"role": "assistant", "content": clean_reply, "timestamp": now_ts})

            session_messages.append(user_timeline_msg)
            session_messages.append(ai_timeline_msg)
            extractor.on_round_complete(session_messages)

            await websocket.send_text(json.dumps({"type": "chat_response", "message": reply}, ensure_ascii=False))

            if vision_system:
                vision_system.on_user_message_done()

    except WebSocketDisconnect:
        print(f"[WS] 会话 {session_id} 断开（角色：{session_character_id}）")
        await extractor.on_session_end(session_messages)
        summary_queue.flush_now()

        if vision_system:
            vision_system.stop()
            vision_system = None
            print("[后端状态] 前端已断开，视觉与键鼠监控服务：已休眠 💤")