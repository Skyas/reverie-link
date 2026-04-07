"""
Reverie Link · Python 后端
FastAPI + WebSocket 主入口

职责（仅保留以下内容，其余职责已拆分到对应模块）：
  - FastAPI 应用初始化 + lifespan 生命周期
  - 全局状态持有（llm_client、current_character 等）
  - WebSocket 聊天端点（/ws/chat）
  - 健康检查接口（/health、/api/memory/window）
  - Router 注册（live2d / tts / memory_api）
"""

import json
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
from ws.vision_speech import _drain_vision_speech
from routers.live2d import router as live2d_router
from routers.tts import router as tts_router
from routers.memory_api import router as memory_router

# ── 环境变量 ───────────────────────────────────────────────────
load_dotenv()

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
LLM_API_KEY  = os.getenv("LLM_API_KEY", "")
LLM_MODEL    = os.getenv("LLM_MODEL", "deepseek-chat")

LLM_TEMPERATURE = 0.8
LLM_TOP_P = 0.9
LLM_FREQ_PENALTY = 0.5

# 滑动窗口上限保护（deque maxlen）
_MAX_HISTORY_ITEMS = WINDOW_PRESETS[-1][2] * 2  # 极限档 35 轮 × 2 = 70 条

# 关键词快筛：匹配用户请求观察屏幕的意图
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
    vision_system = VisionSystem(speech_queue=vision_speech_queue)
    # vision_system.start()
    yield
    if vision_system:
        vision_system.stop()
    shutdown_memory_system()


app = FastAPI(title="Reverie Link Backend", version="0.3.2", lifespan=lifespan)
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

    # 【1. 全局变量统一在最顶端声明】
    global llm_client, LLM_MODEL, current_character, system_prompt
    global current_window_index, current_character_id
    global LLM_TEMPERATURE, LLM_TOP_P, LLM_FREQ_PENALTY
    global vision_system, vision_speech_queue

    # 【2. 极简唤醒】只要前端连进来，直接启动视觉系统
    if not vision_system:
        vision_system = VisionSystem(speech_queue=vision_speech_queue)
    vision_system.start()
    print("[后端状态] 前端已连接，视觉与键鼠监控服务：已唤醒 ✅")

    session_id           = generate_session_id()
    history: deque[dict] = deque(maxlen=_MAX_HISTORY_ITEMS)
    session_window_index: int = current_window_index
    session_character_id: str = current_character_id

    extractor = SessionExtractor(
        session_id=session_id,
        character_id=session_character_id,
        llm_client=llm_client,
        model=LLM_MODEL,
        character=current_character,
    )
    session_messages: list = []

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
                    # 透传采样参数给主动发言
                    temperature=LLM_TEMPERATURE,
                    top_p=LLM_TOP_P,
                    frequency_penalty=LLM_FREQ_PENALTY
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

            # ── configure ──────────────────────────────────────
            if msg_type == "configure":
                llm_cfg  = data.get("llm", {})
                char_cfg = data.get("character", {})

                if llm_cfg.get("api_key") and llm_cfg.get("base_url"):
                    llm_client = AsyncOpenAI(api_key=llm_cfg["api_key"], base_url=llm_cfg["base_url"])
                    LLM_MODEL  = llm_cfg.get("model", LLM_MODEL)
                    # 更新采样参数
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

                extractor.update_config(
                    llm_client=llm_client,
                    model=LLM_MODEL,
                    character=current_character,
                    character_id=session_character_id,
                )
                summary_queue.update_config(
                    llm_client=llm_client,
                    model=LLM_MODEL,
                    character=current_character,
                    character_id=session_character_id,
                )

                await websocket.send_text(json.dumps(
                    {"type": "configure_ack", "message": "配置已更新"},
                    ensure_ascii=False,
                ))
                continue

            if msg_type != "chat" or not user_msg:
                continue

            # ── chat ───────────────────────────────────────────
            if vision_system:
                vision_system.on_user_message()

            user_timeline_msg = TimelineMessage.create(
                msg_type=MessageType.USER_TEXT,
                content=user_msg,
                session_id=session_id,
                character_id=session_character_id,
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

            relevant = retrieve_relevant_summaries(
                query=user_msg,
                character_id=session_character_id,
            )

            if multimodal_screenshot and not multimodal_screenshot.get("error"):
                messages = build_multimodal_screenshot_messages(
                    system_prompt, list(history), user_msg,
                    img_b64=multimodal_screenshot["img_b64"],
                    window_title=multimodal_screenshot.get("window_title", ""),
                    window_index=session_window_index,
                    character_id=session_character_id,
                    character_name=current_character.get("name", ""),
                    relevant_summaries=relevant,
                )
            elif screenshot_info and not screenshot_info.get("error"):
                messages = build_screenshot_messages(
                    system_prompt, list(history), user_msg,
                    screenshot_info=screenshot_info,
                    window_index=session_window_index,
                    character_id=session_character_id,
                    character_name=current_character.get("name", ""),
                    relevant_summaries=relevant,
                )
            else:
                messages = build_messages(
                    system_prompt, list(history), user_msg,
                    window_index=session_window_index,
                    character_id=session_character_id,
                    character_name=current_character.get("name", ""),
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
                    model=LLM_MODEL, messages=messages,
                    max_tokens=300,
                    temperature=LLM_TEMPERATURE,
                    top_p=LLM_TOP_P,
                    frequency_penalty=LLM_FREQ_PENALTY
                )
                reply = response.choices[0].message.content.strip()
            except Exception as e:
                err_str = str(e)
                if "api_key" in err_str.lower() or "401" in err_str or "authentication" in err_str.lower():
                    friendly = "API Key 未配置或无效，请在设置中填写正确的 Key。"
                elif "404" in err_str or "model" in err_str.lower():
                    friendly = f"模型「{LLM_MODEL}」不存在，请在设置中确认模型名称。"
                elif "429" in err_str or "rate" in err_str.lower():
                    friendly = "请求太频繁啦，稍等一下再试试～"
                elif "connect" in err_str.lower() or "network" in err_str.lower() or "timeout" in err_str.lower():
                    friendly = "网络连接失败，请检查 API 地址是否正确。"
                elif "base_url" in err_str.lower() or not LLM_API_KEY:
                    friendly = "还没有配置 API Key，请先打开设置完成配置。"
                else:
                    friendly = f"出了点问题：{err_str[:80]}"
                await websocket.send_text(json.dumps(
                    {"type": "error", "message": friendly}, ensure_ascii=False,
                ))
                continue

            if reply.startswith("[NEED_SCREENSHOT]") and vision_system and not screenshot_info and not multimodal_screenshot:
                if vision_system.is_main_multimodal:
                    fallback_shot = await vision_system.capture_screenshot_only()
                    if fallback_shot and not fallback_shot.get("error"):
                        msgs2 = build_multimodal_screenshot_messages(
                            system_prompt, list(history), user_msg,
                            img_b64=fallback_shot["img_b64"],
                            window_title=fallback_shot.get("window_title", ""),
                            window_index=session_window_index,
                            character_id=session_character_id,
                            character_name=current_character.get("name", ""),
                            relevant_summaries=relevant,
                        )
                        try:
                            r2    = await llm_client.chat.completions.create(
                                model=LLM_MODEL, messages=msgs2, max_tokens=300,
                                temperature=LLM_TEMPERATURE, top_p=LLM_TOP_P, frequency_penalty=LLM_FREQ_PENALTY
                            )
                            reply = r2.choices[0].message.content.strip()
                        except Exception:
                            pass
                else:
                    screenshot_info = await vision_system.capture_for_user()
                    if screenshot_info and not screenshot_info.get("error"):
                        msgs2 = build_screenshot_messages(
                            system_prompt, list(history), user_msg,
                            screenshot_info=screenshot_info,
                            window_index=session_window_index,
                            character_id=session_character_id,
                            character_name=current_character.get("name", ""),
                            relevant_summaries=relevant,
                        )
                        try:
                            r2    = await llm_client.chat.completions.create(
                                model=LLM_MODEL, messages=msgs2, max_tokens=300,
                                temperature=LLM_TEMPERATURE, top_p=LLM_TOP_P, frequency_penalty=LLM_FREQ_PENALTY
                            )
                            reply = r2.choices[0].message.content.strip()
                        except Exception:
                            pass

            emotion     = _extract_emotion(reply)
            reply = re.sub(r'[<＜]event[>＞].*?[<＜]/event[>＞]', '', reply, flags=re.DOTALL | re.IGNORECASE).strip()
            clean_reply = re.sub(r'\[(happy|sad|angry|shy|surprised|neutral|sigh)\]', '', reply, flags=re.IGNORECASE)
            clean_reply = re.sub(r'\[NEED_SCREENSHOT\]', '', clean_reply, flags=re.IGNORECASE)
            clean_reply = re.sub(r'\[[a-zA-Z_]+\]', '', clean_reply)
            clean_reply = clean_reply.strip()

            ai_timeline_msg = TimelineMessage.create(
                msg_type=MessageType.AI_REPLY,
                content=clean_reply,
                session_id=session_id,
                character_id=session_character_id,
                reply_to=user_timeline_msg.id,
                metadata={"emotion": emotion} if emotion else {},
            )
            save_message(ai_timeline_msg)

            now_ts = time.time()
            history.append({"role": "user",      "content": user_msg,    "timestamp": now_ts})
            history.append({"role": "assistant",  "content": clean_reply, "timestamp": now_ts})

            session_messages.append(user_timeline_msg)
            session_messages.append(ai_timeline_msg)
            extractor.on_round_complete(session_messages)

            await websocket.send_text(json.dumps(
                {"type": "chat_response", "message": reply},
                ensure_ascii=False,
            ))

            if vision_system:
                vision_system.on_user_message_done()

    except WebSocketDisconnect:
        print(f"[WS] 会话 {session_id} 断开（角色：{session_character_id}）")
        await extractor.on_session_end(session_messages)
        summary_queue.flush_now()
        
        # 【3. 极简休眠】前端断开，彻底销毁实例
        if vision_system:
            vision_system.stop()
            vision_system = None
            print("[后端状态] 前端已断开，视觉与键鼠监控服务：已休眠 💤")