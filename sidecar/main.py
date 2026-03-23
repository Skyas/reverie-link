"""
Reverie Link · Python 后端
FastAPI + WebSocket 主入口
"""

import json
import os
import logging
from collections import deque
from pathlib import Path

import asyncio
import tempfile
import uuid

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.websockets import WebSocket, WebSocketDisconnect
from openai import AsyncOpenAI

from prompt_builder import DEFAULT_CHARACTER, build_messages, build_system_prompt

# ── 屏蔽烦人的刷屏日志，只显示警告和错误 ─────────────────────────
logging.getLogger("fairseq").setLevel(logging.WARNING)
logging.getLogger("rvc_python").setLevel(logging.WARNING)

# ── 环境变量加载 ───────────────────────────────────────────────
load_dotenv()

LLM_BASE_URL    = os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
LLM_API_KEY     = os.getenv("LLM_API_KEY", "")
LLM_MODEL       = os.getenv("LLM_MODEL", "deepseek-chat")
HISTORY_ROUNDS  = int(os.getenv("HISTORY_ROUNDS", "10"))
HISTORY_MAX_LEN = HISTORY_ROUNDS * 2

# ── 目录配置 ───────────────────────────────────────────────────
LIVE2D_DIR = Path(__file__).parent.parent / "public" / "live2d"
RVC_DIR = Path(__file__).parent.parent / "public" / "rvc"
TMP_DIR = Path(__file__).parent / "tmp_audio"
TMP_DIR.mkdir(exist_ok=True)

# ── FastAPI 实例 ───────────────────────────────────────────────
app = FastAPI(title="Reverie Link Backend", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

llm_client = AsyncOpenAI(
    api_key=LLM_API_KEY,
    base_url=LLM_BASE_URL,
)

current_character = DEFAULT_CHARACTER
system_prompt     = build_system_prompt(current_character)


def _has_cuda() -> bool:
    """检测是否有可用的 CUDA GPU"""
    try:
        import torch
        return torch.cuda.is_available()
    except ImportError:
        return False


# ── 全局模型缓存区（彻底解决每次说话都要加载 1.5秒 的问题） ──

# 1. MeloTTS 缓存
melo_model = None
def get_melo_model():
    global melo_model
    if melo_model is None:
        from melo.api import TTS
        device = "cuda:0" if _has_cuda() else "cpu"
        print(f"[*] 正在加载 MeloTTS 模型 (Device: {device})...")
        melo_model = TTS(language='ZH', device=device)
        print("[*] MeloTTS 模型加载完成！")
    return melo_model

# 2. RVC 模型缓存
rvc_instance = None
current_rvc_pth = None
def get_rvc_model(pth_path, index_path):
    global rvc_instance, current_rvc_pth
    # 如果没加载过，或者用户切换了音色，才重新加载
    if rvc_instance is None or current_rvc_pth != str(pth_path):
        import torch
        
        # 核心修复补丁：兼容 PyTorch 2.6+
        original_load = torch.load
        def patched_load(*args, **kwargs):
            kwargs.setdefault('weights_only', False)
            return original_load(*args, **kwargs)
        torch.load = patched_load

        from rvc_python.infer import RVCInference
        device = "cuda:0" if _has_cuda() else "cpu"
        print(f"[*] 正在加载 RVC 模型到 {device}: {Path(pth_path).name} ...")
        
        rvc_instance = RVCInference(device=device)
        rvc_instance.load_model(
            str(pth_path),
            version="v2",
            index_path=str(index_path) if index_path and Path(index_path).exists() else "",
        )
        current_rvc_pth = str(pth_path)
        print("[*] RVC 模型加载完成！")
        
    return rvc_instance


# ── Live2D 模型扫描接口 ────────────────────────────────────────
@app.get("/api/live2d/models")
async def list_live2d_models():
    if not LIVE2D_DIR.exists():
        return {"models": [], "error": f"目录不存在：{LIVE2D_DIR}"}

    models = []
    for folder in sorted(LIVE2D_DIR.iterdir()):
        if not folder.is_dir(): continue

        model_files = sorted(folder.glob("*.model3.json"))
        if not model_files: continue

        model_file = model_files[0]

        try:
            _auto_fix_motions(folder, model_file)
        except Exception as e:
            print(f"[AutoFix] {folder.name} 修复失败（跳过）: {e}")

        display_name = folder.name.replace("_", " ").replace("-", " ")
        models.append({
            "folder":       folder.name,
            "display_name": display_name,
            "path":         f"live2d/{folder.name}/{model_file.name}",
        })

    return {"models": models}

def _auto_fix_motions(folder: Path, model_file: Path) -> None:
    import json as _json
    with open(model_file, "r", encoding="utf-8") as f:
        data = _json.load(f)

    file_refs = data.get("FileReferences", {})
    if file_refs.get("Motions"): return

    motion_dir = None
    for candidate in ["animations", "motion"]:
        p = folder / candidate
        if p.is_dir():
            motion_dir = p
            break

    if motion_dir is None: return

    motion_files = sorted(motion_dir.glob("*.motion3.json"))
    if not motion_files: return

    idle_candidates = [f for f in motion_files if "idle" in f.name.lower()]
    idle_file = idle_candidates[0] if idle_candidates else motion_files[0]
    rel_dir = motion_dir.name

    idle_entry = {"File": f"{rel_dir}/{idle_file.name}", "FadeInTime": 0.5, "FadeOutTime": 0.5}
    other_entries = [{"File": f"{rel_dir}/{f.name}", "FadeInTime": 0.3, "FadeOutTime": 0.3} for f in motion_files if f != idle_file]

    file_refs["Motions"] = {"Idle": [idle_entry]}
    if other_entries:
        file_refs["Motions"][""] = other_entries

    data["FileReferences"] = file_refs
    with open(model_file, "w", encoding="utf-8") as f:
        _json.dump(data, f, ensure_ascii=False, indent="	")


# ── ElevenLabs TTS 接口 (保持原样) ──────────────────────────────
@app.post("/api/tts")
async def tts(body: dict):
    # ... (原有逻辑未修改，保持原样以支持在线方案) ...
    text     = body.get("text", "").strip()
    api_key  = body.get("api_key", "").strip()
    voice_id = body.get("voice_id", "").strip()

    if not text or not api_key or not voice_id:
        return Response(content=json.dumps({"error": "缺少 text / api_key / voice_id"}), status_code=400)

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    headers = {"xi-api-key": api_key, "Content-Type": "application/json", "Accept": "audio/mpeg"}
    payload = {
        "text": text,
        "model_id": "eleven_flash_v2_5",
        "voice_settings": {"stability": 0.45, "similarity_boost": 0.80, "style": 0.35, "use_speaker_boost": True},
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
        if resp.status_code != 200:
            return Response(content=json.dumps({"error": f"ElevenLabs 错误: {resp.status_code}"}), status_code=resp.status_code)
        return Response(content=resp.content, media_type="audio/mpeg")
    except Exception as e:
        return Response(content=json.dumps({"error": str(e)[:100]}), status_code=500)


# ── RVC 音色扫描接口 ───────────────────────────────────────────
@app.get("/api/rvc/voices")
async def list_rvc_voices():
    if not RVC_DIR.exists(): return {"voices": []}
    index_stems = {f.stem: f for f in RVC_DIR.glob("*.index")}
    voices = []
    for pth_file in sorted(RVC_DIR.glob("*.pth")):
        name = pth_file.stem
        matched_index_file = index_stems.get(name)
        voices.append({
            "name":          name,
            "pth":           f"rvc/{pth_file.name}",
            "index":         f"rvc/{matched_index_file.name}" if matched_index_file else "",
            "index_missing": matched_index_file is None,
        })
    return {"voices": voices}


# ── 本地 RVC TTS 接口 (核心重构区) ──────────────────────────────
@app.post("/api/tts/local")
async def tts_local(body: dict):
    """
    本地语音合成：MeloTTS 生成原声 → RVC v2 变声 → 返回 WAV。
    """
    text       = body.get("text", "").strip()
    pth        = body.get("pth", "").strip()
    index      = body.get("index", "").strip()

    if not text or not pth:
        return Response(
            content=json.dumps({"error": "缺少 text 或 pth"}, ensure_ascii=False),
            status_code=400, media_type="application/json",
        )

    project_root = Path(__file__).parent.parent
    pth_path   = project_root / "public" / pth
    index_path = (project_root / "public" / index) if index else None

    if not pth_path.exists():
        return Response(
            content=json.dumps({"error": f"模型文件不存在: {pth}"}, ensure_ascii=False),
            status_code=404, media_type="application/json",
        )

    uid          = uuid.uuid4().hex[:8]
    raw_path     = TMP_DIR / f"raw_{uid}.wav"
    output_path  = TMP_DIR / f"out_{uid}.wav"

    try:
        # ── Step 1: 调用 MeloTTS 缓存离线生成高质量原声 ──
        def generate_base_tts():
            model = get_melo_model()
            speaker_ids = model.hps.data.spk2id
            model.tts_to_file(text, speaker_ids['ZH'], str(raw_path), speed=1.0)

        await asyncio.to_thread(generate_base_tts)

        # ── Step 2: 调用 RVC 缓存进行极速变声 ──
        def run_rvc():
            rvc = get_rvc_model(pth_path, index_path)
            
            # --- RVC 核心调音参数 ---
            rvc.f0method      = "rmvpe"  
            rvc.index_rate    = 0.75     
            rvc.protect       = 0.33     
            
            # ⬇️【关键设置：变调】⬇️
            # MeloTTS是成熟女声，如果你换成了萝莉/少女模型(Hibiki)，这里填 4 到 8。
            # 填 0 会变成类似大妈音（电音严重）。
            rvc.f0up_key      = 6       
            
            rvc.filter_radius = 3       
            rvc.rms_mix_rate  = 0.25    
            
            rvc.infer_file(str(raw_path), str(output_path))

        await asyncio.to_thread(run_rvc)

        if not output_path.exists():
            raise RuntimeError("RVC 输出文件未生成")

        audio_bytes = output_path.read_bytes()
        return Response(content=audio_bytes, media_type="audio/wav")

    except Exception as e:
        print(f"[TTS Local] 错误: {e}")
        return Response(
            content=json.dumps({"error": str(e)[:150]}, ensure_ascii=False),
            status_code=500, media_type="application/json",
        )
    finally:
        for f in [raw_path, output_path]:
            try:
                if f.exists(): f.unlink()
            except Exception:
                pass


# ── WebSocket 端点 ─────────────────────────────────────────────
@app.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    await websocket.accept()
    history: deque[dict] = deque(maxlen=HISTORY_MAX_LEN)

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue

            msg_type = data.get("type")
            user_msg = data.get("message", "").strip()

            if msg_type == "configure":
                llm_cfg  = data.get("llm", {})
                char_cfg = data.get("character", {})
                global llm_client, LLM_MODEL, current_character, system_prompt
                if llm_cfg.get("api_key") and llm_cfg.get("base_url"):
                    llm_client = AsyncOpenAI(api_key=llm_cfg["api_key"], base_url=llm_cfg["base_url"])
                    LLM_MODEL = llm_cfg.get("model", LLM_MODEL)
                if char_cfg:
                    current_character = {**DEFAULT_CHARACTER, **char_cfg}
                    system_prompt = build_system_prompt(current_character)
                await websocket.send_text(json.dumps({"type": "configure_ack", "message": "配置已更新"}, ensure_ascii=False))
                continue

            if msg_type != "chat" or not user_msg:
                continue

            messages = build_messages(system_prompt, list(history), user_msg)

            try:
                response = await llm_client.chat.completions.create(
                    model=LLM_MODEL,
                    messages=messages,
                    max_tokens=150,
                    temperature=0.85,
                )
                reply = response.choices[0].message.content.strip()
            except Exception as e:
                await websocket.send_text(json.dumps({"type": "error", "message": f"错误: {str(e)[:50]}"}, ensure_ascii=False))
                continue

            history.append({"role": "user",      "content": user_msg})
            history.append({"role": "assistant",  "content": reply})

            await websocket.send_text(json.dumps({"type": "chat_response", "message": reply}, ensure_ascii=False))

    except WebSocketDisconnect:
        pass


@app.get("/health")
async def health():
    return {"status": "ok", "model": LLM_MODEL}