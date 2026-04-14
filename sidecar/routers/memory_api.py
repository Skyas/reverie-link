"""
Reverie Link · 记忆相关 HTTP API

包含以下接口：
  聊天记录：GET /api/chat/sessions | /api/chat/messages | /api/chat/search
  笔记本：  GET|POST /api/notebook/entries | PUT|DELETE /api/notebook/entries/{id} | GET /api/notebook/stats
  角色数据：GET /api/character/{id}/export | DELETE /api/character/{id}/data
"""

import json
from datetime import datetime
import logging
logger = logging.getLogger(__name__)


from fastapi import APIRouter, Query
from fastapi.responses import Response

from memory import (
    MessageType,
    NotebookSource,
    NotebookEntry,
    get_messages_page,
    get_sessions,
    search_messages,
    delete_messages_by_character,
    export_messages_by_character,
    get_entries_page,
    add_entry as nb_add_entry,
    update_entry as nb_update_entry,
    delete_entry as nb_delete_entry,
    count_entries as nb_count_entries,
    delete_entries_by_character,
    export_entries_by_character,
    delete_summaries_by_character,
    export_summaries_by_character,
)

router = APIRouter()


# ══════════════════════════════════════════════════════════════════
# 聊天记录 API
# ══════════════════════════════════════════════════════════════════

@router.get("/api/chat/sessions")
async def api_chat_sessions(character_id: str = Query(None)):
    return {"sessions": get_sessions(character_id=character_id)}


@router.get("/api/chat/messages")
async def api_chat_messages(
    page: int = Query(1, ge=1),
    page_size: int = Query(30, ge=1, le=100),
    session_id: str = Query(None),
    keyword: str = Query(None),
    character_id: str = Query(None),
):
    result = get_messages_page(
        page=page, page_size=page_size,
        session_id=session_id, keyword=keyword,
        character_id=character_id,
    )
    result["items"] = [m.to_dict() for m in result["items"]]
    return result


@router.get("/api/chat/search")
async def api_chat_search(
    keyword: str = Query(..., min_length=1),
    limit: int = Query(50, ge=1, le=200),
    character_id: str = Query(None),
):
    results = search_messages(keyword, limit=limit, character_id=character_id)
    return {"items": [m.to_dict() for m in results]}


# ══════════════════════════════════════════════════════════════════
# 笔记本 API
# ══════════════════════════════════════════════════════════════════

@router.get("/api/notebook/entries")
async def api_notebook_entries(
    source: str = Query(..., pattern="^(manual|auto)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=50),
    keyword: str = Query(None),
    search_by: str = Query("content", pattern="^(content|tag)$"),
    character_id: str = Query(None),
):
    nb_source = NotebookSource(source)
    result = get_entries_page(
        source=nb_source, page=page, page_size=page_size,
        keyword=keyword, search_by=search_by, character_id=character_id,
    )
    result["items"] = [e.to_dict() for e in result["items"]]
    return result


@router.post("/api/notebook/entries")
async def api_notebook_add(body: dict):
    content      = body.get("content", "").strip()
    tags         = body.get("tags", [])
    character_id = body.get("character_id", "").strip()

    if not content:
        return Response(
            content=json.dumps({"error": "内容不能为空"}, ensure_ascii=False),
            status_code=400, media_type="application/json",
        )

    entry = NotebookEntry.create(
        source=NotebookSource.MANUAL,
        content=content, tags=tags, character_id=character_id,
    )
    nb_add_entry(entry)
    return {"ok": True, "entry": entry.to_dict()}


@router.put("/api/notebook/entries/{entry_id}")
async def api_notebook_update(entry_id: str, body: dict):
    content = body.get("content", "").strip()
    tags    = body.get("tags", [])

    if not content:
        return Response(
            content=json.dumps({"error": "内容不能为空"}, ensure_ascii=False),
            status_code=400, media_type="application/json",
        )

    ok = nb_update_entry(entry_id, content, tags)
    if not ok:
        return Response(
            content=json.dumps({"error": "条目不存在或非手动区条目"}, ensure_ascii=False),
            status_code=404, media_type="application/json",
        )
    return {"ok": True}


@router.delete("/api/notebook/entries/{entry_id}")
async def api_notebook_delete(entry_id: str):
    ok = nb_delete_entry(entry_id)
    if not ok:
        return Response(
            content=json.dumps({"error": "条目不存在"}, ensure_ascii=False),
            status_code=404, media_type="application/json",
        )
    return {"ok": True}


@router.get("/api/notebook/stats")
async def api_notebook_stats(character_id: str = Query(None)):
    return {
        "total":  nb_count_entries(character_id=character_id),
        "manual": nb_count_entries(NotebookSource.MANUAL, character_id=character_id),
        "auto":   nb_count_entries(NotebookSource.AUTO,   character_id=character_id),
    }


# ══════════════════════════════════════════════════════════════════
# 角色数据管理 API（删除 / 导出）
# ══════════════════════════════════════════════════════════════════

@router.get("/api/character/{character_id}/export")
async def api_character_export(character_id: str):
    """
    导出指定角色卡的全部数据（聊天记录 + 笔记本 + 长期摘要）为 JSON 文件。
    """
    chat_data     = export_messages_by_character(character_id)
    notebook_data = export_entries_by_character(character_id)
    summary_data  = export_summaries_by_character(character_id)

    export_payload = {
        "export_time":        datetime.utcnow().isoformat() + "Z",
        "character_id":       character_id,
        "chat_history":       chat_data,
        "notebook":           notebook_data,
        "long_term_summaries": summary_data,
    }
    filename = f"reverie_export_{character_id[:16]}.json"
    return Response(
        content=json.dumps(export_payload, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("/api/character/{character_id}/data")
async def api_character_delete_data(character_id: str):
    """
    删除指定角色卡的全部数据（聊天记录 + 笔记本 + 长期摘要）。
    不可恢复，由前端确认弹框后调用。
    """
    if not character_id.strip():
        return Response(
            content=json.dumps({"error": "character_id 不能为空"}, ensure_ascii=False),
            status_code=400, media_type="application/json",
        )

    deleted_msgs      = delete_messages_by_character(character_id)
    deleted_entries   = delete_entries_by_character(character_id)
    deleted_summaries = delete_summaries_by_character(character_id)

    logger.info("[Memory] 角色 %s 数据已删除：%s 条消息，%s 条笔记本条目，%s 条摘要",
                character_id, deleted_msgs, deleted_entries, deleted_summaries)

    return {
        "ok":                        True,
        "deleted_messages":          deleted_msgs,
        "deleted_notebook_entries":  deleted_entries,
        "deleted_summaries":         deleted_summaries,
    }