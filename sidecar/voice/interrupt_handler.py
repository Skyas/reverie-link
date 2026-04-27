"""
interrupt_handler.py — 打断 + 任务取消 + 状态清理

职责：管理打断信号，取消正在进行的 LLM 生成任务，清理前后端状态。
"""

import asyncio
import json

from fastapi.websockets import WebSocket


class InterruptHandler:
    def __init__(self):
        self._current_task: asyncio.Task | None = None

    def register_task(self, task: asyncio.Task):
        """chat flow 开始时注册当前 LLM 任务"""
        self._current_task = task

    async def handle_interrupt(self, websocket: WebSocket):
        """
        用户打断时调用：
        1. 取消 LLM 生成任务
        2. 发送打断确认给前端（清理 Live2D 口型等）
        3. 清理本地任务引用
        """
        if self._current_task and not self._current_task.done():
            self._current_task.cancel()
            try:
                await self._current_task
            except asyncio.CancelledError:
                pass

        # 发送打断确认，前端据此清理口型动画等状态
        await websocket.send_text(json.dumps({
            "type": "interrupted",
            "clear_lip_sync": True,
        }, ensure_ascii=False))

        self._current_task = None

    def clear(self):
        self._current_task = None
