"""
Reverie Link · TTS 路由层（全流式重构版）

接口列表：
  POST /tts/config          更新 TTS 引擎配置（Settings 保存时调用）
  GET  /tts/status          查询当前引擎状态
  GET  /tts/voices          获取当前引擎音色列表
  POST /tts/synthesize      流式合成语音（对话流程调用，返回音频流）
  POST /tts/test            测试当前引擎连通性

旧接口保留兼容：
  POST /api/tts             → 旧 ElevenLabs 路由（向后兼容，确认前端不调用后可删除）
"""

import json
import logging
from pathlib import Path

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import Response, StreamingResponse

from tts import tts_manager

logger = logging.getLogger(__name__)

router = APIRouter()

# ════════════════════════════════════════════════════════════════
#  新接口 — TTSManager 统一路由
# ════════════════════════════════════════════════════════════════

@router.post("/tts/config")
async def tts_config(body: dict):
    """
    更新 TTS 引擎配置。前端 Settings 保存时调用。
    """
    logger.info(
        f"[TTS Route] 收到配置更新 | mode={body.get('mode')} "
        f"provider={body.get('provider')} voice_id={body.get('voice_id')}"
    )
    tts_manager.configure(body)
    return {"status": "ok", **tts_manager.get_status()}


@router.get("/tts/status")
async def tts_status():
    """查询当前 TTS 引擎状态，供前端状态栏展示。"""
    status = tts_manager.get_status()
    logger.debug(f"[TTS Route] 状态查询 | {status}")
    return status


@router.get("/tts/voices")
async def tts_voices():
    """获取当前引擎的可用音色列表。"""
    voices = await tts_manager.list_voices()
    logger.debug(f"[TTS Route] 音色列表 | count={len(voices)}")
    return {
        "voices": [
            {
                "id":          v.id,
                "name":        v.name,
                "engine":      v.engine,
                "preview_url": v.preview_url,
                "tags":        v.tags,
            }
            for v in voices
        ]
    }


@router.post("/tts/synthesize")
async def tts_synthesize(body: dict):
    """
    流式合成语音。对话流程通过此接口触发。
    返回：分块传输的音频流 (Transfer-Encoding: chunked)
    """
    text     = body.get("text", "").strip()
    emotion  = body.get("emotion", "neutral")
    voice_id = body.get("voice_id", "")

    if not text:
        return Response(
            content=json.dumps({"error": "text 不能为空"}, ensure_ascii=False),
            status_code=400, media_type="application/json",
        )

    # 检查是否处于无语音模式，如果是，直接返回 204
    if not tts_manager.is_enabled:
        logger.debug("[TTS Route] 无语音模式或引擎未就绪，返回 204")
        return Response(status_code=204)

    logger.debug(
        f"[TTS Route] 流式合成请求 | emotion={emotion} "
        f"voice_id={voice_id or '(default)'} text_len={len(text)}"
    )

    audio_generator = tts_manager.synthesize(text, emotion=emotion, voice_id=voice_id)

    return StreamingResponse(
        audio_generator,
        media_type="application/octet-stream"
    )


@router.post("/tts/test")
async def tts_test():
    """测试当前引擎连通性。"""
    logger.info("[TTS Route] 连通性测试请求")
    result = await tts_manager.test_connection()
    return result


# ════════════════════════════════════════════════════════════════
#  旧接口兼容层（Deprecated）
# ════════════════════════════════════════════════════════════════

@router.post("/api/tts")
async def tts_legacy(body: dict):
    """[Deprecated] 旧 ElevenLabs TTS 接口。"""
    text     = body.get("text", "").strip()
    api_key  = body.get("api_key", "").strip()
    voice_id = body.get("voice_id", "").strip()

    logger.warning("[TTS Route] 旧接口 /api/tts 被调用（Deprecated）")

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
            "stability": 0.45, "similarity_boost": 0.80,
            "style": 0.35, "use_speaker_boost": True,
        },
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
        if resp.status_code != 200:
            return Response(
                content=json.dumps(
                    {"error": f"ElevenLabs 错误: {resp.status_code}"}, ensure_ascii=False
                ),
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