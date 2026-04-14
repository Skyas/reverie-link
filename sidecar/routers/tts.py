"""
Reverie Link · TTS 路由

包含三个语音合成相关接口：
  - POST /api/tts         ElevenLabs 云端 TTS
  - GET  /api/rvc/voices  本地 RVC 音色扫描
  - POST /api/tts/local   本地 Edge-TTS + RVC 变声
"""

import asyncio
import json
import uuid
from pathlib import Path
import logging
logger = logging.getLogger(__name__)


import httpx
from fastapi import APIRouter
from fastapi.responses import Response

# ── 路径常量（本文件位于 sidecar/routers/tts.py）─────────────────
RVC_DIR = Path(__file__).parent.parent.parent / "public" / "rvc"
TMP_DIR = Path(__file__).parent.parent / "tmp_audio"
TMP_DIR.mkdir(exist_ok=True)

router = APIRouter()


# ── ElevenLabs TTS ─────────────────────────────────────────────

@router.post("/api/tts")
async def tts(body: dict):
    """
    调用 ElevenLabs TTS API，返回 MP3 音频流。
    请求体：{ text, api_key, voice_id }
    """
    text     = body.get("text", "").strip()
    api_key  = body.get("api_key", "").strip()
    voice_id = body.get("voice_id", "").strip()

    if not text or not api_key or not voice_id:
        return Response(
            content=json.dumps({"error": "缺少 text / api_key / voice_id"}, ensure_ascii=False),
            status_code=400, media_type="application/json",
        )

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    headers = {
        "xi-api-key":   api_key,
        "Content-Type": "application/json",
        "Accept":       "audio/mpeg",
    }
    payload = {
        "text": text,
        "model_id": "eleven_flash_v2_5",
        "voice_settings": {
            "stability":         0.45,
            "similarity_boost":  0.80,
            "style":             0.35,
            "use_speaker_boost": True,
        },
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
        if resp.status_code != 200:
            return Response(
                content=json.dumps({"error": f"ElevenLabs 错误: {resp.status_code}"}, ensure_ascii=False),
                status_code=502, media_type="application/json",
            )
        return Response(content=resp.content, media_type="audio/mpeg")
    except httpx.TimeoutException:
        return Response(
            content=json.dumps({"error": "ElevenLabs 请求超时"}, ensure_ascii=False),
            status_code=504, media_type="application/json",
        )
    except Exception as e:
        return Response(
            content=json.dumps({"error": str(e)}, ensure_ascii=False),
            status_code=500, media_type="application/json",
        )


# ── RVC 音色扫描 ────────────────────────────────────────────────

@router.get("/api/rvc/voices")
async def list_rvc_voices():
    """
    扫描 public/rvc/ 目录，返回所有可用音色。
    .pth 和 .index 文件必须同名（扩展名不同）。
    """
    if not RVC_DIR.exists():
        return {"voices": []}

    voices = []
    for pth_file in sorted(RVC_DIR.glob("*.pth")):
        name         = pth_file.stem
        index_file   = RVC_DIR / f"{name}.index"
        voices.append({
            "name":          name,
            "pth":           f"rvc/{pth_file.name}",
            "index":         f"rvc/{index_file.name}" if index_file.exists() else "",
            "index_missing": not index_file.exists(),
        })

    return {"voices": voices}


# ── 本地 RVC TTS ────────────────────────────────────────────────

@router.post("/api/tts/local")
async def tts_local(body: dict):
    """
    本地语音合成：Edge-TTS 生成原声 → RVC v2 变声 → 返回 WAV。
    请求体：{ text, pth, index, edge_voice }
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

    project_root = Path(__file__).parent.parent.parent
    pth_path     = project_root / "public" / pth
    index_path   = (project_root / "public" / index) if index else None

    if not pth_path.exists():
        return Response(
            content=json.dumps({"error": f"模型文件不存在: {pth}"}, ensure_ascii=False),
            status_code=404, media_type="application/json",
        )

    tmp_mp3 = TMP_DIR / f"edge_{uuid.uuid4().hex}.mp3"
    tmp_wav = TMP_DIR / f"rvc_{uuid.uuid4().hex}.wav"

    try:
        import edge_tts
        communicate = edge_tts.Communicate(text, edge_voice)
        await communicate.save(str(tmp_mp3))

        rvc_script = Path(__file__).parent.parent / "rvc_infer.py"
        cmd = ["python", str(rvc_script), "--pth", str(pth_path), "--input", str(tmp_mp3), "--output", str(tmp_wav)]
        if index_path and index_path.exists():
            cmd += ["--index", str(index_path)]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
        if proc.returncode != 0:
            logger.error("[RVC] 推理失败: %s", stderr.decode(errors="replace")[:300])
            return Response(
                content=json.dumps({"error": "RVC 推理失败"}, ensure_ascii=False),
                status_code=500, media_type="application/json",
            )

        return Response(content=tmp_wav.read_bytes(), media_type="audio/wav")

    except asyncio.TimeoutError:
        return Response(
            content=json.dumps({"error": "RVC 推理超时（超过60秒）"}, ensure_ascii=False),
            status_code=504, media_type="application/json",
        )
    except ImportError:
        return Response(
            content=json.dumps({"error": "edge-tts 未安装，请执行 pip install edge-tts"}, ensure_ascii=False),
            status_code=501, media_type="application/json",
        )
    except Exception as e:
        return Response(
            content=json.dumps({"error": str(e)}, ensure_ascii=False),
            status_code=500, media_type="application/json",
        )
    finally:
        for f in [tmp_mp3, tmp_wav]:
            try:
                if f.exists():
                    f.unlink()
            except Exception:
                pass