"""
Reverie Link · Python 后端
FastAPI + WebSocket 主入口
"""

import json
import os
from collections import deque

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from openai import AsyncOpenAI

from prompt_builder import DEFAULT_CHARACTER, build_messages, build_system_prompt

# ── 环境变量加载 ───────────────────────────────────────────────
load_dotenv()

LLM_BASE_URL    = os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
LLM_API_KEY     = os.getenv("LLM_API_KEY", "")
LLM_MODEL       = os.getenv("LLM_MODEL", "deepseek-chat")
HISTORY_ROUNDS  = int(os.getenv("HISTORY_ROUNDS", "10"))
# 每轮 = 1问1答 = 2条消息
HISTORY_MAX_LEN = HISTORY_ROUNDS * 2

# ── FastAPI 实例 ───────────────────────────────────────────────
app = FastAPI(title="Reverie Link Backend", version="0.1.0")

# ── LLM 客户端（全局复用）──────────────────────────────────────
llm_client = AsyncOpenAI(
    api_key=LLM_API_KEY,
    base_url=LLM_BASE_URL,
)

# ── 当前使用的角色配置（Phase 1 暂用默认，Phase 4 接配置面板）──
current_character = DEFAULT_CHARACTER
system_prompt     = build_system_prompt(current_character)


# ── WebSocket 端点 ─────────────────────────────────────────────
@app.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    await websocket.accept()

    # 每个连接独立维护对话历史（双端队列，自动限长）
    history: deque[dict] = deque(maxlen=HISTORY_MAX_LEN)

    try:
        while True:
            raw = await websocket.receive_text()

            # ── 解析前端消息 ───────────────────────────────────
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

            if msg_type != "chat" or not user_msg:
                continue

            # ── 组装 messages 并调用 LLM ──────────────────────
            messages = build_messages(system_prompt, list(history), user_msg)

            try:
                response = await llm_client.chat.completions.create(
                    model=LLM_MODEL,
                    messages=messages,
                    max_tokens=150,      # 硬截断，防止超长
                    temperature=0.85,    # 适当随机性，避免机械感
                )
                reply = response.choices[0].message.content.strip()

            except Exception as e:
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "message": f"LLM 调用失败：{str(e)}"
                }, ensure_ascii=False))
                continue

            # ── 更新对话历史 ───────────────────────────────────
            history.append({"role": "user",      "content": user_msg})
            history.append({"role": "assistant", "content": reply})

            # ── 返回给前端 ─────────────────────────────────────
            await websocket.send_text(json.dumps({
                "type": "chat_response",
                "message": reply
            }, ensure_ascii=False))

    except WebSocketDisconnect:
        pass  # 客户端正常断开，不报错


# ── 健康检查端点（开发期用于确认后端是否存活）──────────────────
@app.get("/health")
async def health():
    return {"status": "ok", "model": LLM_MODEL}