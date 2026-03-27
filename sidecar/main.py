"""
Reverie Link · Python 后端
FastAPI + WebSocket 主入口
"""

import json
import os
from collections import deque
from pathlib import Path

import asyncio
import tempfile
import uuid

import httpx
import pyttsx3
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.websockets import WebSocket, WebSocketDisconnect
from openai import AsyncOpenAI

from prompt_builder import DEFAULT_CHARACTER, build_messages, build_system_prompt

# ── 环境变量加载 ───────────────────────────────────────────────
load_dotenv()

LLM_BASE_URL    = os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
LLM_API_KEY     = os.getenv("LLM_API_KEY", "")
LLM_MODEL       = os.getenv("LLM_MODEL", "deepseek-chat")
HISTORY_ROUNDS  = int(os.getenv("HISTORY_ROUNDS", "10"))
HISTORY_MAX_LEN = HISTORY_ROUNDS * 2

# ── Live2D 模型目录 ────────────────────────────────────────────
LIVE2D_DIR = Path(__file__).parent.parent / "public" / "live2d"

# ── RVC 音色目录 ────────────────────────────────────────────────
# 用户将 .pth 和 .index 文件放入 public/rvc/ 即可自动识别
RVC_DIR = Path(__file__).parent.parent / "public" / "rvc"

# ── 临时音频目录（Edge-TTS 原声 + RVC 输出）──────────────────────
TMP_DIR = Path(__file__).parent / "tmp_audio"
TMP_DIR.mkdir(exist_ok=True)

# ── FastAPI 实例 ───────────────────────────────────────────────
app = FastAPI(title="Reverie Link Backend", version="0.2.0")

# 允许前端（Vite devserver）跨域请求 HTTP 接口
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── LLM 客户端（全局复用）──────────────────────────────────────
llm_client = AsyncOpenAI(
    api_key=LLM_API_KEY,
    base_url=LLM_BASE_URL,
)

# ── 当前使用的角色配置 ─────────────────────────────────────────
current_character = DEFAULT_CHARACTER
system_prompt     = build_system_prompt(current_character)


# ── Live2D 模型扫描接口 ────────────────────────────────────────
@app.get("/api/live2d/models")
async def list_live2d_models():
    """
    扫描 public/live2d/ 目录，返回所有可用模型列表。
    每个子文件夹只要包含 *.model3.json 就被识别为一个模型。

    自动修复：若 model3.json 缺少 Motions 字段但存在 animations/ 或 motion/ 文件夹，
    自动将 idle 动画注入 model3.json（原地写入，用户无感）。
    """
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

        # ── 自动修复：补全缺失的 Motions 字段 ────────────────────
        try:
            _auto_fix_motions(folder, model_file)
        except Exception as e:
            print(f"[AutoFix] {folder.name} 修复失败（跳过）: {e}")

        try:
            _optimize_idle_fade(folder, model_file)
        except Exception as e:
            print(f"[AutoFix] {folder.name} idle 优化失败（跳过）: {e}")

        display_name = folder.name.replace("_", " ").replace("-", " ")
        models.append({
            "folder":       folder.name,
            "display_name": display_name,
            "path":         f"live2d/{folder.name}/{model_file.name}",
        })

    return {"models": models}


def _auto_fix_motions(folder: Path, model_file: Path) -> None:
    """
    检查 model3.json 是否缺少 Motions 字段。
    若缺少，且存在 animations/ 或 motion/ 子目录，则自动将其中的
    motion3.json 文件注册进去，idle 动画优先（文件名含 idle 或排序第一个）。
    已有 Motions 字段的模型跳过，不做修改。
    """
    import json as _json

    with open(model_file, "r", encoding="utf-8") as f:
        data = _json.load(f)

    file_refs = data.get("FileReferences", {})

    # 已有 Motions 且不为空 → 不处理
    if file_refs.get("Motions"):
        return

    # 查找动作文件夹：优先 animations/，其次 motion/
    motion_dir = None
    for candidate in ["animations", "motion"]:
        p = folder / candidate
        if p.is_dir():
            motion_dir = p
            break

    if motion_dir is None:
        return  # 没有动作文件夹，无需处理

    motion_files = sorted(motion_dir.glob("*.motion3.json"))
    if not motion_files:
        return

    # 找 idle 动画：文件名含 idle（不区分大小写），否则取排序第一个
    idle_candidates = [f for f in motion_files if "idle" in f.name.lower()]
    idle_file = idle_candidates[0] if idle_candidates else motion_files[0]

    # 构造相对于模型文件夹的路径（用正斜杠）
    rel_dir = motion_dir.name  # "animations" 或 "motion"

    idle_entry = {
        "File": f"{rel_dir}/{idle_file.name}",
        "FadeInTime": 0.5,
        "FadeOutTime": 0.5,
    }

    other_entries = [
        {
            "File": f"{rel_dir}/{f.name}",
            "FadeInTime": 0.3,
            "FadeOutTime": 0.3,
        }
        for f in motion_files if f != idle_file
    ]

    file_refs["Motions"] = {"Idle": [idle_entry]}
    if other_entries:
        file_refs["Motions"][""] = other_entries

    data["FileReferences"] = file_refs

    # 写回文件，保留原有缩进风格
    with open(model_file, "w", encoding="utf-8") as f:
        _json.dump(data, f, ensure_ascii=False, indent="	")

    print(f"[AutoFix] {folder.name}: 自动注入 Motions（idle={idle_file.name}，共 {len(motion_files)} 个动作）")


def _optimize_idle_fade(folder: Path, model_file: Path) -> None:
    """
    检测 idle 动作是否为「帧切换型」（线稿逐帧抖动等），自动优化 model3.json。

    判定规则：idle 动作数 > 1 且所有 idle motion 的 Duration 均 < 2 秒。
    此类动作依赖 stepped 插值做 0/1 跳变来切换绘画帧，
    pixi-live2d-display 的 crossfade 会将跳变值线性混合，
    导致多帧叠加显示（视觉上表现为闪烁）。

    修复策略：只保留第一个 idle，FadeInTime/FadeOutTime 设为 0。
    单个 Loop=true 的短动作自身就包含完整的帧切换周期，
    无需多动作轮换，消除 crossfade 即消除闪烁。

    对以下情况完全不做任何修改：
    - 只有 0~1 个 idle 的模型（无 crossfade 问题）
    - 存在任一 Duration >= 2s 的 idle（正常模型）
    - motion 文件缺失或解析失败（不冒险修改）
    """
    import json as _json

    with open(model_file, "r", encoding="utf-8") as f:
        data = _json.load(f)

    file_refs = data.get("FileReferences", {})
    motions = file_refs.get("Motions", {})
    idle_list = motions.get("Idle", [])

    if len(idle_list) <= 1:
        return  # 只有 0~1 个 idle，无 crossfade 问题

    # ── 逐个读取 idle motion 文件，检查 Duration ──────────────
    DURATION_THRESHOLD = 2.0  # 秒：低于此值判定为帧切换型

    for motion_entry in idle_list:
        motion_rel = motion_entry.get("File", "")
        if not motion_rel:
            return  # 配置异常，不冒险修改
        motion_path = folder / motion_rel
        if not motion_path.exists():
            return  # 文件缺失，跳过
        try:
            with open(motion_path, "r", encoding="utf-8") as f:
                motion_data = _json.load(f)
            duration = motion_data.get("Meta", {}).get("Duration", 999)
            if duration >= DURATION_THRESHOLD:
                return  # 存在长 idle，属于正常模型，不修改
        except Exception:
            return  # 解析失败，不冒险修改

    # ── 全部 idle 均为短周期 → 帧切换型，执行优化 ────────────
    first_idle = idle_list[0].copy()
    first_idle["FadeInTime"] = 0
    first_idle["FadeOutTime"] = 0
    motions["Idle"] = [first_idle]
    file_refs["Motions"] = motions
    data["FileReferences"] = file_refs

    with open(model_file, "w", encoding="utf-8") as f:
        _json.dump(data, f, ensure_ascii=False, indent="\t")

    print(f"[AutoFix] {folder.name}: 检测到帧切换型 idle（全部 Duration < {DURATION_THRESHOLD}s），"
          f"已精简为 1 个动作并禁用 crossfade")


# ── ElevenLabs TTS 接口 ───────────────────────────────────────
@app.post("/api/tts")
async def tts(body: dict):
    """
    调用 ElevenLabs TTS API，返回 MP3 音频流。
    请求体：{ text, api_key, voice_id }
    API Key 和 Voice ID 由前端从用户配置中读取并传入，后端不存储。
    """
    text     = body.get("text", "").strip()
    api_key  = body.get("api_key", "").strip()
    voice_id = body.get("voice_id", "").strip()

    if not text or not api_key or not voice_id:
        return Response(
            content=json.dumps({"error": "缺少 text / api_key / voice_id"}, ensure_ascii=False),
            status_code=400,
            media_type="application/json",
        )

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    headers = {
        "xi-api-key":   api_key,
        "Content-Type": "application/json",
        "Accept":       "audio/mpeg",
    }
    payload = {
        "text": text,
        "model_id": "eleven_flash_v2_5",   # 最低延迟模型，适合对话场景
        "voice_settings": {
            "stability":        0.45,   # 适度稳定，保留情感起伏
            "similarity_boost": 0.80,   # 高相似度，贴近原始音色
            "style":            0.35,   # 适度风格，避免过于夸张
            "use_speaker_boost": True,
        },
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, headers=headers, json=payload)

        if resp.status_code != 200:
            err = resp.text[:200]
            print(f"[TTS] ElevenLabs 返回错误 {resp.status_code}: {err}")
            return Response(
                content=json.dumps({"error": f"ElevenLabs 错误: {resp.status_code}"}, ensure_ascii=False),
                status_code=resp.status_code,
                media_type="application/json",
            )

        return Response(content=resp.content, media_type="audio/mpeg")

    except httpx.TimeoutException:
        return Response(
            content=json.dumps({"error": "TTS 请求超时，请检查网络"}, ensure_ascii=False),
            status_code=504,
            media_type="application/json",
        )
    except Exception as e:
        print(f"[TTS] 异常: {e}")
        return Response(
            content=json.dumps({"error": str(e)[:100]}, ensure_ascii=False),
            status_code=500,
            media_type="application/json",
        )


# ── RVC 音色扫描接口 ───────────────────────────────────────────
@app.get("/api/rvc/voices")
async def list_rvc_voices():
    """
    扫描 public/rvc/ 目录，返回所有可用音色。

    命名规则（强制）：.pth 和 .index 文件必须同名（扩展名不同），例如：
        Hibiki.pth  +  Hibiki.index  → 正常匹配
        Amy.pth     +  Amy.index     → 正常匹配
        Mike.pth    （无同名 .index） → index_missing = True，界面提示用户

    返回格式：
    [{ "name": "Hibiki", "pth": "rvc/Hibiki.pth", "index": "rvc/Hibiki.index",
       "index_missing": false }]
    """
    if not RVC_DIR.exists():
        return {"voices": []}

    # 收集所有 .index 文件的 stem 集合（用于快速查找）
    index_stems = {f.stem: f for f in RVC_DIR.glob("*.index")}

    voices = []
    for pth_file in sorted(RVC_DIR.glob("*.pth")):
        name = pth_file.stem

        # 精确同名匹配（大小写敏感，要求用户按规范命名）
        matched_index_file = index_stems.get(name)
        index_path  = f"rvc/{matched_index_file.name}" if matched_index_file else ""
        index_missing = matched_index_file is None

        voices.append({
            "name":          name,
            "pth":           f"rvc/{pth_file.name}",
            "index":         index_path,
            "index_missing": index_missing,
        })

    return {"voices": voices}


# ── 本地 RVC TTS 接口 ──────────────────────────────────────────
@app.post("/api/tts/local")
async def tts_local(body: dict):
    """
    本地语音合成：Edge-TTS 生成原声 → RVC v2 变声 → 返回 WAV。
    请求体：{ text, pth, index, edge_voice }
    - pth：相对于项目根的路径，如 "rvc/Hibiki.pth"
    - index：同上，可为空字符串
    - edge_voice：Edge-TTS 语音名，默认 zh-CN-XiaoxiaoNeural
    """
    text       = body.get("text", "").strip()
    pth        = body.get("pth", "").strip()
    index      = body.get("index", "").strip()
    edge_voice = body.get("edge_voice", "zh-CN-XiaoxiaoNeural").strip()

    if not text or not pth:
        return Response(
            content=json.dumps({"error": "缺少 text 或 pth"}, ensure_ascii=False),
            status_code=400, media_type="application/json",
        )

    project_root = Path(__file__).parent.parent
    # 前端传入路径如 "rvc/Hibiki.pth"，实际文件在 public/rvc/ 下
    pth_path   = project_root / "public" / pth
    index_path = (project_root / "public" / index) if index else None

    if not pth_path.exists():
        return Response(
            content=json.dumps({"error": f"模型文件不存在: {pth}"}, ensure_ascii=False),
            status_code=404, media_type="application/json",
        )

    uid          = uuid.uuid4().hex[:8]
    raw_path     = TMP_DIR / f"raw_{uid}.wav"   # pyttsx3 输出 WAV
    output_path  = TMP_DIR / f"out_{uid}.wav"

    try:
        # ── Step 1: pyttsx3 离线生成原声（Windows SAPI，无需网络）──
        def generate_base_tts():
            engine = pyttsx3.init()
            # 尝试根据 edge_voice 选择中文语音
            voices = engine.getProperty("voices")
            zh_voices = [v for v in voices if "zh" in v.id.lower()
                        or "chinese" in v.name.lower()
                        or "huihui" in v.name.lower()
                        or "yaoyao" in v.name.lower()]
            if zh_voices:
                engine.setProperty("voice", zh_voices[0].id)
            engine.setProperty("rate", 200)   # 语速，稍快适合对话
            engine.setProperty("volume", 1.0)
            # pyttsx3 在 Windows 上直接保存为 wav
            raw_wav = str(raw_path).replace(".mp3", ".wav")
            engine.save_to_file(text, raw_wav)
            engine.runAndWait()
            return raw_wav

        raw_wav_path = await asyncio.to_thread(generate_base_tts)
        raw_path = Path(raw_wav_path)  # 更新 raw_path 为实际生成的 wav 文件

        # ── Step 2: RVC 变声 ─────────────────────────────────────
        # rvc-python 的推理在同步代码里执行，用 asyncio.to_thread 避免阻塞事件循环
        def run_rvc():
            import torch
            
            # --- 核心修复补丁：兼容 PyTorch 2.6+ ---
            original_load = torch.load
            def patched_load(*args, **kwargs):
                kwargs.setdefault('weights_only', False)
                return original_load(*args, **kwargs)
            torch.load = patched_load
            # --------------------------------------

            from rvc_python.infer import RVCInference
            device = "cuda:0" if _has_cuda() else "cpu"
            rvc = RVCInference(device=device)
            rvc.load_model(
                str(pth_path),
                version="v2",
                index_path=str(index_path) if index_path and index_path.exists() else "",
            )
            # 推理参数通过属性赋值（rvc-python 的接口方式）
            rvc.f0method      = "rmvpe"  # pitch 提取算法，rmvpe 效果最佳
            rvc.index_rate    = 0.75     # index 文件影响度（0~1）
            rvc.protect       = 0.33     # 清辅音保护（0~0.5）
            rvc.f0up_key      = 0        # 音调偏移，0 = 不偏移
            rvc.filter_radius = 3        # 中值滤波半径
            rvc.rms_mix_rate  = 0.25     # 音量包络混合比
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
        # 清理临时文件
        for f in [raw_path, output_path]:
            try:
                if f.exists(): f.unlink()
            except Exception:
                pass


def _has_cuda() -> bool:
    """检测是否有可用的 CUDA GPU"""
    try:
        import torch
        return torch.cuda.is_available()
    except ImportError:
        return False


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
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "message": "消息格式错误，请发送 JSON。"
                }, ensure_ascii=False))
                continue

            msg_type = data.get("type")
            user_msg = data.get("message", "").strip()

            if msg_type == "configure":
                llm_cfg  = data.get("llm", {})
                char_cfg = data.get("character", {})

                global llm_client, LLM_MODEL, current_character, system_prompt

                if llm_cfg.get("api_key") and llm_cfg.get("base_url"):
                    llm_client = AsyncOpenAI(
                        api_key=llm_cfg["api_key"],
                        base_url=llm_cfg["base_url"],
                    )
                    LLM_MODEL = llm_cfg.get("model", LLM_MODEL)

                if char_cfg:
                    current_character = {**DEFAULT_CHARACTER, **char_cfg}
                    system_prompt = build_system_prompt(current_character)

                await websocket.send_text(json.dumps(
                    {"type": "configure_ack", "message": "配置已更新"},
                    ensure_ascii=False
                ))
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
                    {"type": "error", "message": friendly},
                    ensure_ascii=False
                ))
                continue

            history.append({"role": "user",      "content": user_msg})
            history.append({"role": "assistant",  "content": reply})

            await websocket.send_text(json.dumps({
                "type": "chat_response",
                "message": reply
            }, ensure_ascii=False))

    except WebSocketDisconnect:
        pass


# ── 健康检查 ───────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "ok", "model": LLM_MODEL}