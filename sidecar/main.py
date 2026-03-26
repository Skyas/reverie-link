"""
Reverie Link · Python 后端
FastAPI + WebSocket 主入口
"""

import json
import os
import re
import time
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path

import asyncio
import tempfile
import uuid
from typing import Optional

import httpx
import pyttsx3
from dotenv import load_dotenv
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.websockets import WebSocket, WebSocketDisconnect
from openai import AsyncOpenAI

from prompt_builder import (
    DEFAULT_CHARACTER,
    DEFAULT_WINDOW_INDEX,
    WINDOW_PRESETS,
    build_messages,
    build_system_prompt,
    build_vision_speech_messages,
    build_screenshot_messages,
)

from memory import (
    init_memory_system,
    shutdown_memory_system,
    MessageType,
    TimelineMessage,
    NotebookSource,
    NotebookEntry,
    generate_session_id,
    save_message,
    get_messages_page,
    get_sessions,
    search_messages,
    delete_messages_by_character,
    export_messages_by_character,
    get_entries_page,
    get_all_entries,
    add_entry as nb_add_entry,
    update_entry as nb_update_entry,
    delete_entry as nb_delete_entry,
    count_entries as nb_count_entries,
    delete_entries_by_character,
    export_entries_by_character,
    SessionExtractor,
    SummaryQueue,
    retrieve_relevant_summaries,
    delete_summaries_by_character,
    export_summaries_by_character,
)

# ── 视觉感知模块 ──────────────────────────────────────────────
import sys as _sys
import os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from vision.vision_system import VisionSystem

# ── 环境变量加载 ───────────────────────────────────────────────
load_dotenv()

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
LLM_API_KEY  = os.getenv("LLM_API_KEY", "")
LLM_MODEL    = os.getenv("LLM_MODEL", "deepseek-chat")

# Phase 3: 滑动窗口上限保护（deque maxlen）
_MAX_HISTORY_ITEMS = WINDOW_PRESETS[-1][2] * 2 # 极限档 35 轮 × 2 = 70 条

# ── 路径常量 ───────────────────────────────────────────────────
LIVE2D_DIR = Path(__file__).parent.parent / "public" / "live2d"
RVC_DIR    = Path(__file__).parent.parent / "public" / "rvc"
TMP_DIR    = Path(__file__).parent / "tmp_audio"
TMP_DIR.mkdir(exist_ok=True)


# ── 视觉感知全局状态 ──────────────────────────────────────────
vision_speech_queue: asyncio.Queue = asyncio.Queue()
vision_system: Optional[VisionSystem] = None


# ── FastAPI 生命周期 ───────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    global vision_system
    init_memory_system()
    vision_system = VisionSystem(speech_queue=vision_speech_queue)
    vision_system.start()
    yield
    if vision_system:
        vision_system.stop()
    shutdown_memory_system()


app = FastAPI(title="Reverie Link Backend", version="0.3.2", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ── 全局状态 ───────────────────────────────────────────────────
llm_client           = AsyncOpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)
current_character    = DEFAULT_CHARACTER
system_prompt        = build_system_prompt(current_character)
current_window_index: int = DEFAULT_WINDOW_INDEX
current_character_id: str = ""   # 当前激活角色卡的 preset.id，角色隔离键

# 关键词快筛：匹配用户请求观察屏幕的意图
_SCREENSHOT_KEYWORDS = re.compile(
    r"(看看屏幕|屏幕上|画面|你看到了什么|帮我看看|看一眼|看一下|"
    r"屏幕怎么了|你看到什么|现在在干什么|帮我看|屏幕里)",
    re.IGNORECASE,
)


# ── Live2D 模型扫描接口 ────────────────────────────────────────
@app.get("/api/live2d/models")
async def list_live2d_models():
    if not LIVE2D_DIR.exists():
        return {"models": [], "error": f"目录不存在：{LIVE2D_DIR}"}
    models = []
    for folder in sorted(LIVE2D_DIR.iterdir()):
        if not folder.is_dir():
            continue
        model_files = sorted(folder.glob("*.model3.json"))
        if not model_files:
            continue
        model_file = model_files[0]
        try:
            _auto_fix_motions(folder, model_file)
        except Exception as e:
            print(f"[AutoFix] {folder.name} 修复失败（跳过）: {e}")
        display_name = folder.name.replace("_", " ").replace("-", " ")
        models.append({"folder": folder.name, "display_name": display_name, "path": f"live2d/{folder.name}/{model_file.name}"})
    return {"models": models}


def _auto_fix_motions(folder: Path, model_file: Path) -> None:
    import json as _json
    with open(model_file, "r", encoding="utf-8") as f:
        data = _json.load(f)
    file_refs = data.get("FileReferences", {})
    if file_refs.get("Motions"):
        return
    motion_dir = None
    for candidate in ["animations", "motion"]:
        p = folder / candidate
        if p.is_dir():
            motion_dir = p
            break
    if motion_dir is None:
        return
    motion_files = sorted(motion_dir.glob("*.motion3.json"))
    if not motion_files:
        return
    idle_candidates = [f for f in motion_files if "idle" in f.name.lower()]
    idle_file = idle_candidates[0] if idle_candidates else motion_files[0]
    rel_dir = motion_dir.name
    file_refs["Motions"] = {"Idle": [{"File": f"{rel_dir}/{idle_file.name}", "FadeInTime": 0.5, "FadeOutTime": 0.5}]}
    file_refs["Motions"][""] = [{"File": f"{rel_dir}/{f.name}", "FadeInTime": 0.3, "FadeOutTime": 0.3} for f in motion_files if f != idle_file]
    data["FileReferences"] = file_refs
    with open(model_file, "w", encoding="utf-8") as f:
        _json.dump(data, f, ensure_ascii=False, indent="\t")
    print(f"[AutoFix] {folder.name}: 自动注入 Motions（idle={idle_file.name}，共 {len(motion_files)} 个动作）")


# ── ElevenLabs TTS 接口 ───────────────────────────────────────
@app.post("/api/tts")
async def tts(body: dict):
    text     = body.get("text", "").strip()
    api_key  = body.get("api_key", "").strip()
    voice_id = body.get("voice_id", "").strip()
    if not text or not api_key or not voice_id:
        return Response(content=json.dumps({"error": "缺少 text / api_key / voice_id"}, ensure_ascii=False), status_code=400, media_type="application/json")
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    headers = {"xi-api-key": api_key, "Content-Type": "application/json", "Accept": "audio/mpeg"}
    payload = {"text": text, "model_id": "eleven_flash_v2_5", "voice_settings": {"stability": 0.45, "similarity_boost": 0.80, "style": 0.35, "use_speaker_boost": True}}
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
        if resp.status_code != 200:
            return Response(content=json.dumps({"error": f"ElevenLabs 错误: {resp.status_code}"}, ensure_ascii=False), status_code=502, media_type="application/json")
        return Response(content=resp.content, media_type="audio/mpeg")
    except httpx.TimeoutException:
        return Response(content=json.dumps({"error": "ElevenLabs 请求超时"}, ensure_ascii=False), status_code=504, media_type="application/json")
    except Exception as e:
        return Response(content=json.dumps({"error": str(e)}, ensure_ascii=False), status_code=500, media_type="application/json")


# ── RVC 音色扫描接口 ───────────────────────────────────────────
@app.get("/api/rvc/voices")
async def list_rvc_voices():
    if not RVC_DIR.exists():
        return {"voices": []}
    voices = []
    for pth_file in sorted(RVC_DIR.glob("*.pth")):
        name = pth_file.stem
        index_file = RVC_DIR / f"{name}.index"
        voices.append({"name": name, "pth": f"rvc/{pth_file.name}", "index": f"rvc/{index_file.name}" if index_file.exists() else "", "index_missing": not index_file.exists()})
    return {"voices": voices}


# ── 本地 RVC TTS 接口 ──────────────────────────────────────────
@app.post("/api/tts/local")
async def tts_local(body: dict):
    text       = body.get("text", "").strip()
    pth        = body.get("pth", "").strip()
    index      = body.get("index", "").strip()
    edge_voice = body.get("edge_voice", "zh-CN-XiaoxiaoNeural").strip()
    if not text or not pth:
        return Response(content=json.dumps({"error": "缺少 text 或 pth"}, ensure_ascii=False), status_code=400, media_type="application/json")
    pth_path   = Path(__file__).parent.parent / "public" / pth
    index_path = Path(__file__).parent.parent / "public" / index if index else None
    if not pth_path.exists():
        return Response(content=json.dumps({"error": f"模型文件不存在: {pth}"}, ensure_ascii=False), status_code=404, media_type="application/json")
    tmp_mp3 = TMP_DIR / f"edge_{uuid.uuid4().hex}.mp3"
    tmp_wav = TMP_DIR / f"rvc_{uuid.uuid4().hex}.wav"
    try:
        import edge_tts
        communicate = edge_tts.Communicate(text, edge_voice)
        await communicate.save(str(tmp_mp3))
        rvc_script = Path(__file__).parent / "rvc_infer.py"
        cmd = ["python", str(rvc_script), "--pth", str(pth_path), "--input", str(tmp_mp3), "--output", str(tmp_wav)]
        if index_path and index_path.exists():
            cmd += ["--index", str(index_path)]
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
        if proc.returncode != 0:
            print(f"[RVC] 推理失败: {stderr.decode(errors='replace')[:300]}")
            return Response(content=json.dumps({"error": "RVC 推理失败"}, ensure_ascii=False), status_code=500, media_type="application/json")
        return Response(content=tmp_wav.read_bytes(), media_type="audio/wav")
    except asyncio.TimeoutError:
        return Response(content=json.dumps({"error": "RVC 推理超时（超过60秒）"}, ensure_ascii=False), status_code=504, media_type="application/json")
    except ImportError:
        return Response(content=json.dumps({"error": "edge-tts 未安装，请执行 pip install edge-tts"}, ensure_ascii=False), status_code=501, media_type="application/json")
    except Exception as e:
        return Response(content=json.dumps({"error": str(e)}, ensure_ascii=False), status_code=500, media_type="application/json")
    finally:
        for f in [tmp_mp3, tmp_wav]:
            try:
                if f.exists():
                    f.unlink()
            except Exception:
                pass


# ── 工具函数 ──────────────────────────────────────────────────
# 已知情绪标签集合（与前端 EMOTION_TAGS 保持同步）
_KNOWN_EMOTIONS = {"happy", "sad", "angry", "shy", "surprised", "neutral", "sigh"}
 
def _extract_emotion(text: str) -> str:
    """
    提取 AI 回复中的情绪标签。
    优先匹配已知标签；若 LLM 造了未知标签，兜底正则也能识别
    但不存入已知情绪，记为空字符串（前端统一剥离即可）。
    """
    # 精确匹配已知标签
    match = re.search(r'\[(happy|sad|angry|shy|surprised|neutral|sigh)\]', text, re.IGNORECASE)
    if match:
        return match.group(1).lower()
    return ""


# ── 视觉主动发言辅助函数 ──────────────────────────────
 
# 全局的最近发言记录（防重复用）
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
    # ── 以下是新增参数 ──
    window_index: int = 1,
    character_name: str = "",
):
    """
    检查并处理视觉感知主动发言队列中的待发事件。
    每次最多处理 1 条，避免连续刷屏。
    """
    global _recent_vision_speeches
 
    try:
        trigger = vision_speech_queue.get_nowait()
    except asyncio.QueueEmpty:
        return
 
    if trigger.get("session_id") and trigger["session_id"] != session_id:
        return
 
    try:
        # 改进：传入 recent_speeches 和 history
        messages = build_vision_speech_messages(
            system_prompt,
            trigger,
            recent_speeches=_recent_vision_speeches,
            history=list(history),
            window_index=window_index,
            character_id=session_character_id,
            character_name=character_name,
        )
        response = await llm_client.chat.completions.create(
            model=llm_model, messages=messages, max_tokens=100, temperature=0.9,
        )
        reply = response.choices[0].message.content.strip()
    except Exception as e:
        print(f"[Vision] 主动发言 LLM 调用失败: {e}")
        return
 
    emotion     = _extract_emotion(reply)
    clean_reply = re.sub(r'\[(happy|sad|angry|shy|surprised|neutral|sigh)\]', '', reply, flags=re.IGNORECASE)
    clean_reply = re.sub(r'\[[a-zA-Z_]+\]', '', clean_reply)
    clean_reply = clean_reply.strip()
 
    # 改进：允许"不说话"（回复 …… 或空）
    if not clean_reply or clean_reply in ("……", "...", "。"):
        return
 
    # 改进：记录最近发言，防重复
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
            "emotion":     emotion,
            "scene_type":  scene_info.get("scene_type", "unknown"),
            "game_name":   scene_info.get("game_name"),
            "confidence":  scene_info.get("confidence", "low"),
            "source":      "vision_proactive",
            "reason":      trigger.get("reason", ""),
        },
    )
    save_message(game_event_msg)
    session_messages.append(game_event_msg)
 
    await websocket.send_text(json.dumps({
        "type":    "vision_proactive_speech",
        "message": reply,
    }, ensure_ascii=False))


# ── WebSocket 端点 ─────────────────────────────────────────────
@app.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    await websocket.accept()
    
    global llm_client, LLM_MODEL, current_character, system_prompt
    global current_window_index, current_character_id
 
    session_id           = generate_session_id()
    history: deque[dict] = deque(maxlen=_MAX_HISTORY_ITEMS)
    session_window_index: int = current_window_index
    session_character_id: str = current_character_id
    
    # 步骤⑤：每个会话持有一个提取管理器
    extractor = SessionExtractor(
        session_id=session_id,
        character_id=session_character_id,
        llm_client=llm_client,
        model=LLM_MODEL,
        character=current_character,
    )
 
    # 本会话的完整消息列表（供提取器使用，独立于滑动窗口 history）
    session_messages: list = []
    
    # 步骤⑥：每个会话持有一个摘要队列
    summary_queue = SummaryQueue(
        character_id=session_character_id,
        session_id=session_id,
        llm_client=llm_client,
        model=LLM_MODEL,
        character=current_character,
    )

    try:
        while True:
            # 同时监听用户消息和视觉主动发言队列（1 秒轮询间隔）
            raw = None
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=1.0)
            except asyncio.TimeoutError:
                # 无用户消息 → 检查视觉主动发言队列
                await _drain_vision_speech(
                    websocket=websocket,
                    llm_client=llm_client,
                    llm_model=LLM_MODEL,
                    system_prompt=system_prompt,
                    session_id=session_id,
                    session_character_id=session_character_id,
                    history=history,
                    session_messages=session_messages,
                    window_index=session_window_index,
                    character_name=current_character.get("name", ""),
                )
                continue

            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_text(json.dumps({"type": "error", "message": "消息格式错误，请发送 JSON。"}, ensure_ascii=False))
                continue

            msg_type = data.get("type")
            user_msg = data.get("message", "").strip()

            if msg_type == "configure":
                llm_cfg  = data.get("llm", {})
                char_cfg = data.get("character", {})

                if llm_cfg.get("api_key") and llm_cfg.get("base_url"):
                    llm_client = AsyncOpenAI(api_key=llm_cfg["api_key"], base_url=llm_cfg["base_url"])
                    LLM_MODEL  = llm_cfg.get("model", LLM_MODEL)

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
                    current_character_id  = new_cid
                    session_character_id  = new_cid

                # Phase 3: 视觉感知配置
                if "vision" in data and vision_system:
                    vision_system.configure(data["vision"])
                    vision_system.set_main_llm(llm_client, LLM_MODEL)
                    vision_system.set_session_info(
                        session_id=session_id,
                        character_id=session_character_id,
                        address=current_character.get("address", "你"),
                    )

                # 步骤⑤：角色/模型切换时同步更新提取器配置
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

                await websocket.send_text(json.dumps({"type": "configure_ack", "message": "配置已更新"}, ensure_ascii=False))
                continue

            if msg_type != "chat" or not user_msg:
                continue

            # Phase 3: 通知视觉系统用户开始交互（打断冷却）
            if vision_system:
                vision_system.on_user_message()

            user_timeline_msg = TimelineMessage.create(
                msg_type=MessageType.USER_TEXT,
                content=user_msg,
                session_id=session_id,
                character_id=session_character_id,
            )
            save_message(user_timeline_msg)

            # Phase 3: 关键词快筛 — 用户是否请求观察屏幕
            user_wants_screenshot = bool(_SCREENSHOT_KEYWORDS.search(user_msg))
            screenshot_info: Optional[dict] = None

            if user_wants_screenshot and vision_system:
                screenshot_info = await vision_system.capture_for_user()

            # 步骤⑥：检索相关摘要，注入 Layer 2
            relevant = retrieve_relevant_summaries(
                query=user_msg,
                character_id=session_character_id,
            )

            if screenshot_info and not screenshot_info.get("error"):
                # 直接用截图结果组装 messages
                messages = build_screenshot_messages(
                    system_prompt,
                    list(history),
                    user_msg,
                    screenshot_info=screenshot_info,
                    window_index=session_window_index,
                    character_id=session_character_id,
                    character_name=current_character.get("name", ""),
                    relevant_summaries=relevant,
                )
            else:
                messages = build_messages(
                    system_prompt,
                    list(history),
                    user_msg,
                    window_index=session_window_index,
                    character_id=session_character_id,
                    character_name=current_character.get("name", ""),
                    relevant_summaries=relevant,
                )
            
            # 步骤⑥：计算本轮被滑动窗口移出的消息，推入摘要队列
            # 原理：trim_history 后的有效条数 < history 总条数，差值即为被移出部分
            from prompt_builder import trim_history as _trim
            kept_count   = len(_trim(list(history), session_window_index))
            total_count  = len(history)
            evicted_count = total_count - kept_count
            if evicted_count > 0:
                # 取 history 最旧的 evicted_count 条（已被移出的部分）
                # 这些对应 session_messages 中最早的消息
                evicted_msgs = session_messages[:evicted_count]
                if evicted_msgs:
                    summary_queue.push(evicted_msgs)
                    # 从 session_messages 中移除已入队的消息，避免重复摘要
                    del session_messages[:evicted_count]

            try:
                response = await llm_client.chat.completions.create(model=LLM_MODEL, messages=messages, max_tokens=150, temperature=0.85)
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
                await websocket.send_text(json.dumps({"type": "error", "message": friendly}, ensure_ascii=False))
                continue

            # Phase 3: 检测 [NEED_SCREENSHOT] 标签（LLM 意图兜底检测）
            if reply.startswith("[NEED_SCREENSHOT]") and vision_system and not screenshot_info:
                screenshot_info = await vision_system.capture_for_user()
                if screenshot_info and not screenshot_info.get("error"):
                    # 用截图结果重新生成回复
                    messages_with_screen = build_screenshot_messages(
                        system_prompt,
                        list(history),
                        user_msg,
                        screenshot_info=screenshot_info,
                        window_index=session_window_index,
                        character_id=session_character_id,
                        character_name=current_character.get("name", ""),
                        relevant_summaries=relevant,
                    )
                    try:
                        response2 = await llm_client.chat.completions.create(
                            model=LLM_MODEL, messages=messages_with_screen,
                            max_tokens=150, temperature=0.85,
                        )
                        reply = response2.choices[0].message.content.strip()
                    except Exception:
                        pass  # 保留原 reply

            emotion     = _extract_emotion(reply)
            # 先剥离已知标签，再用兜底正则清除任何残留的 [xxx] 格式未知标签
            clean_reply = re.sub(r'\[(happy|sad|angry|shy|surprised|neutral|sigh)\]', '', reply, flags=re.IGNORECASE)
            clean_reply = re.sub(r'\[NEED_SCREENSHOT\]', '', clean_reply, flags=re.IGNORECASE)
            clean_reply = re.sub(r'\[[a-zA-Z_]+\]', '', clean_reply)  # 兜底：清除未知标签
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
            history.append({"role": "user",     "content": user_msg, "timestamp": now_ts})
            history.append({"role": "assistant", "content": reply,    "timestamp": now_ts})
 
            # 步骤⑤：记录完整消息供提取器使用，并判断是否触发提取
            session_messages.append(user_timeline_msg)
            session_messages.append(ai_timeline_msg)
            extractor.on_round_complete(session_messages)
 
            await websocket.send_text(json.dumps({"type": "chat_response", "message": reply}, ensure_ascii=False))

            # Phase 3: 用户消息处理完成，恢复视觉感知的主动发言权
            if vision_system:
                vision_system.on_user_message_done()

    except WebSocketDisconnect:
        print(f"[WS] 会话 {session_id} 断开（角色：{session_character_id}）")
        # 步骤⑤：会话结束时对未提取内容做收尾提取
        extractor.on_session_end(session_messages)
        # 步骤⑥：会话结束时强制 flush 摘要队列
        summary_queue.flush_now()


# ── 健康检查 ───────────────────────────────────────────────────
@app.get("/health")
async def health():
    name, _, max_rounds = WINDOW_PRESETS[current_window_index]
    return {"status": "ok", "model": LLM_MODEL, "character_id": current_character_id, "memory_window": current_window_index, "memory_window_name": name, "memory_max_rounds": max_rounds}

@app.get("/api/memory/window")
async def api_memory_window():
    return {
        "current_index": current_window_index,
        "current_name": WINDOW_PRESETS[current_window_index][0],
        "presets": [{"index": i, "name": name, "time_minutes": secs // 60, "max_rounds": rounds} for i, (name, secs, rounds) in enumerate(WINDOW_PRESETS)],
    }


# ══════════════════════════════════════════════════════════════════
# Phase 3: 聊天记录 API
# ══════════════════════════════════════════════════════════════════

@app.get("/api/chat/sessions")
async def api_chat_sessions(character_id: str = Query(None)):
    return {"sessions": get_sessions(character_id=character_id)}


@app.get("/api/chat/messages")
async def api_chat_messages(
    page: int = Query(1, ge=1),
    page_size: int = Query(30, ge=1, le=100),
    session_id: str = Query(None),
    keyword: str = Query(None),
    character_id: str = Query(None),
):
    result = get_messages_page(page=page, page_size=page_size, session_id=session_id, keyword=keyword, character_id=character_id)
    result["items"] = [m.to_dict() for m in result["items"]]
    return result


@app.get("/api/chat/search")
async def api_chat_search(
    keyword: str = Query(..., min_length=1),
    limit: int = Query(50, ge=1, le=200),
    character_id: str = Query(None),
):
    results = search_messages(keyword, limit=limit, character_id=character_id)
    return {"items": [m.to_dict() for m in results]}


# ══════════════════════════════════════════════════════════════════
# Phase 3: 笔记本（世界书）API
# ══════════════════════════════════════════════════════════════════

@app.get("/api/notebook/entries")
async def api_notebook_entries(
    source: str = Query(..., pattern="^(manual|auto)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=50),
    keyword: str = Query(None),
    search_by: str = Query("content", pattern="^(content|tag)$"),
    character_id: str = Query(None),
):
    nb_source = NotebookSource(source)
    result = get_entries_page(source=nb_source, page=page, page_size=page_size, keyword=keyword, search_by=search_by, character_id=character_id)
    result["items"] = [e.to_dict() for e in result["items"]]
    return result


@app.post("/api/notebook/entries")
async def api_notebook_add(body: dict):
    content      = body.get("content", "").strip()
    tags         = body.get("tags", [])
    character_id = body.get("character_id", "").strip()
    if not content:
        return Response(content=json.dumps({"error": "内容不能为空"}, ensure_ascii=False), status_code=400, media_type="application/json")
    entry = NotebookEntry.create(source=NotebookSource.MANUAL, content=content, tags=tags, character_id=character_id)
    nb_add_entry(entry)
    return {"ok": True, "entry": entry.to_dict()}


@app.put("/api/notebook/entries/{entry_id}")
async def api_notebook_update(entry_id: str, body: dict):
    content = body.get("content", "").strip()
    tags    = body.get("tags", [])
    if not content:
        return Response(content=json.dumps({"error": "内容不能为空"}, ensure_ascii=False), status_code=400, media_type="application/json")
    ok = nb_update_entry(entry_id, content, tags)
    if not ok:
        return Response(content=json.dumps({"error": "条目不存在或非手动区条目"}, ensure_ascii=False), status_code=404, media_type="application/json")
    return {"ok": True}


@app.delete("/api/notebook/entries/{entry_id}")
async def api_notebook_delete(entry_id: str):
    ok = nb_delete_entry(entry_id)
    if not ok:
        return Response(content=json.dumps({"error": "条目不存在"}, ensure_ascii=False), status_code=404, media_type="application/json")
    return {"ok": True}


@app.get("/api/notebook/stats")
async def api_notebook_stats(character_id: str = Query(None)):
    return {
        "total":  nb_count_entries(character_id=character_id),
        "manual": nb_count_entries(NotebookSource.MANUAL, character_id=character_id),
        "auto":   nb_count_entries(NotebookSource.AUTO,   character_id=character_id),
    }


# ══════════════════════════════════════════════════════════════════
# Phase 3: 角色数据管理 API（删除 / 导出）
# ══════════════════════════════════════════════════════════════════

@app.get("/api/character/{character_id}/export")
async def api_character_export(character_id: str):
    """
    导出指定角色卡的全部数据（聊天记录 + 笔记本）为 JSON 文件。
    由前端在删除确认弹框中"导出后删除"按钮触发。
    """
    from datetime import datetime
    chat_data     = export_messages_by_character(character_id)
    notebook_data = export_entries_by_character(character_id)
    summary_data  = export_summaries_by_character(character_id)
    export_payload = {
        "export_time": datetime.utcnow().isoformat() + "Z",
        "character_id": character_id,
        "chat_history": chat_data,
        "notebook": notebook_data,
        "long_term_summaries": summary_data,
    }
    filename = f"reverie_export_{character_id[:16]}.json"
    return Response(
        content=json.dumps(export_payload, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.delete("/api/character/{character_id}/data")
async def api_character_delete_data(character_id: str):
    """
    删除指定角色卡的全部数据（聊天记录 + 笔记本）。
    不可恢复，由前端确认弹框后调用。
    """
    if not character_id.strip():
        return Response(content=json.dumps({"error": "character_id 不能为空"}, ensure_ascii=False), status_code=400, media_type="application/json")
    deleted_msgs     = delete_messages_by_character(character_id)
    deleted_entries  = delete_entries_by_character(character_id)
    deleted_summaries = delete_summaries_by_character(character_id)
    print(f"[Memory] 角色 {character_id} 数据已删除：{deleted_msgs} 条消息，{deleted_entries} 条笔记本条目，{deleted_summaries} 条摘要")
    return {
        "ok": True,
        "deleted_messages": deleted_msgs,
        "deleted_notebook_entries": deleted_entries,
        "deleted_summaries": deleted_summaries,
    }