"""
Reverie Link · 记忆系统 — 聊天记录数据库

负责所有原始消息的持久化存储与查询。
数据文件：data/chat_history.db

参考文档：PHASE3_MEMORY_DESIGN.md § 3
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Optional

from .models import TimelineMessage, MessageType


# ── 数据库文件路径 ─────────────────────────────────────────────────

def _get_db_path() -> Path:
    """获取聊天记录数据库文件路径，确保 data/ 目录存在"""
    # sidecar/memory/db_chat.py → sidecar/ → 项目根目录
    project_root = Path(__file__).parent.parent.parent
    data_dir = project_root / "data"
    data_dir.mkdir(exist_ok=True)
    return data_dir / "chat_history.db"


# ── 数据库初始化 ──────────────────────────────────────────────────

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS messages (
    id          TEXT PRIMARY KEY,
    timestamp   TEXT NOT NULL,
    type        TEXT NOT NULL,
    content     TEXT NOT NULL,
    reply_to    TEXT,
    metadata    TEXT,
    session_id  TEXT NOT NULL
);
"""

_CREATE_INDEXES_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_msg_timestamp ON messages(timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_msg_session   ON messages(session_id);",
    "CREATE INDEX IF NOT EXISTS idx_msg_type      ON messages(type);",
]


def _get_connection() -> sqlite3.Connection:
    """获取数据库连接（启用 WAL 模式提升并发性能）"""
    db_path = _get_db_path()
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def init_chat_db() -> None:
    """初始化聊天记录数据库（创建表和索引，幂等操作）"""
    conn = _get_connection()
    try:
        conn.execute(_CREATE_TABLE_SQL)
        for idx_sql in _CREATE_INDEXES_SQL:
            conn.execute(idx_sql)
        conn.commit()
        print("[Memory] 聊天记录数据库初始化完成")
    finally:
        conn.close()


# ── 全局连接（模块级复用，避免反复打开关闭）──────────────────────

_conn: Optional[sqlite3.Connection] = None


def get_conn() -> sqlite3.Connection:
    """获取模块级复用的数据库连接"""
    global _conn
    if _conn is None:
        _conn = _get_connection()
    return _conn


def close_conn() -> None:
    """关闭模块级连接（程序退出时调用）"""
    global _conn
    if _conn is not None:
        _conn.close()
        _conn = None


# ── 写入操作 ──────────────────────────────────────────────────────

def save_message(msg: TimelineMessage) -> None:
    """
    将一条消息持久化到聊天记录数据库。
    在每次收发消息时调用。
    """
    conn = get_conn()
    conn.execute(
        """
        INSERT OR IGNORE INTO messages
            (id, timestamp, type, content, reply_to, metadata, session_id)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            msg.id,
            msg.timestamp,
            msg.type.value,
            msg.content,
            msg.reply_to,
            json.dumps(msg.metadata, ensure_ascii=False) if msg.metadata else "{}",
            msg.session_id,
        ),
    )
    conn.commit()


def save_messages_batch(messages: list[TimelineMessage]) -> None:
    """批量写入消息（用于会话结束时一次性持久化缓冲区内容）"""
    conn = get_conn()
    conn.executemany(
        """
        INSERT OR IGNORE INTO messages
            (id, timestamp, type, content, reply_to, metadata, session_id)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                m.id, m.timestamp, m.type.value, m.content, m.reply_to,
                json.dumps(m.metadata, ensure_ascii=False) if m.metadata else "{}",
                m.session_id,
            )
            for m in messages
        ],
    )
    conn.commit()


# ── 查询操作 ──────────────────────────────────────────────────────

def _row_to_message(row: sqlite3.Row) -> TimelineMessage:
    """将数据库行转为 TimelineMessage 对象"""
    return TimelineMessage(
        id=row["id"],
        timestamp=row["timestamp"],
        type=MessageType(row["type"]),
        content=row["content"],
        reply_to=row["reply_to"],
        metadata=json.loads(row["metadata"]) if row["metadata"] else {},
        session_id=row["session_id"],
    )


def get_messages_page(
    page: int = 1,
    page_size: int = 30,
    session_id: Optional[str] = None,
    keyword: Optional[str] = None,
    types: Optional[list[str]] = None,
) -> dict:
    """
    分页查询聊天记录。

    Args:
        page: 页码（从 1 开始）
        page_size: 每页条数
        session_id: 按会话筛选（可选）
        keyword: 按内容关键词搜索（可选）
        types: 按消息类型筛选（可选），如 ["user_text", "ai_reply"]

    Returns:
        {
            "items": [TimelineMessage, ...],
            "total": 总条数,
            "page": 当前页码,
            "page_size": 每页条数,
            "total_pages": 总页数,
        }
    """
    conn = get_conn()

    # ── 构建 WHERE 子句 ──
    conditions = []
    params: list = []

    # 默认只查询用户可见的消息类型
    if types is None:
        types = [
            MessageType.USER_TEXT.value,
            MessageType.USER_VOICE.value,
            MessageType.AI_REPLY.value,
        ]
    placeholders = ",".join("?" for _ in types)
    conditions.append(f"type IN ({placeholders})")
    params.extend(types)

    if session_id:
        conditions.append("session_id = ?")
        params.append(session_id)

    if keyword:
        conditions.append("content LIKE ?")
        params.append(f"%{keyword}%")

    where_clause = " AND ".join(conditions) if conditions else "1=1"

    # ── 查询总数 ──
    count_sql = f"SELECT COUNT(*) as cnt FROM messages WHERE {where_clause}"
    total = conn.execute(count_sql, params).fetchone()["cnt"]

    # ── 计算分页 ──
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = max(1, min(page, total_pages))
    offset = (page - 1) * page_size

    # ── 查询数据（按时间倒序，最新在前）──
    data_sql = f"""
        SELECT * FROM messages
        WHERE {where_clause}
        ORDER BY timestamp DESC
        LIMIT ? OFFSET ?
    """
    rows = conn.execute(data_sql, params + [page_size, offset]).fetchall()

    return {
        "items": [_row_to_message(r) for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }


def get_sessions() -> list[dict]:
    """
    获取所有会话列表，按时间倒序排列。
    返回每个会话的 id、起止时间、消息数量。
    """
    conn = get_conn()
    rows = conn.execute("""
        SELECT
            session_id,
            MIN(timestamp) as first_msg,
            MAX(timestamp) as last_msg,
            COUNT(*) as msg_count
        FROM messages
        GROUP BY session_id
        ORDER BY first_msg DESC
    """).fetchall()

    return [
        {
            "session_id": r["session_id"],
            "first_msg": r["first_msg"],
            "last_msg": r["last_msg"],
            "msg_count": r["msg_count"],
        }
        for r in rows
    ]


def get_recent_messages(
    session_id: str,
    limit: int = 50,
) -> list[TimelineMessage]:
    """
    获取指定会话中最近的 N 条消息（按时间正序）。
    主要供滑动窗口和自动提取使用。
    """
    conn = get_conn()
    rows = conn.execute(
        """
        SELECT * FROM messages
        WHERE session_id = ?
        ORDER BY timestamp DESC
        LIMIT ?
        """,
        (session_id, limit),
    ).fetchall()

    # 查询是倒序的，翻转为正序返回
    return [_row_to_message(r) for r in reversed(rows)]


def search_messages(
    keyword: str,
    limit: int = 50,
) -> list[TimelineMessage]:
    """
    全局关键词搜索（跨会话）。
    仅搜索用户可见的消息类型。
    """
    conn = get_conn()
    rows = conn.execute(
        """
        SELECT * FROM messages
        WHERE content LIKE ?
          AND type IN (?, ?, ?)
        ORDER BY timestamp DESC
        LIMIT ?
        """,
        (
            f"%{keyword}%",
            MessageType.USER_TEXT.value,
            MessageType.USER_VOICE.value,
            MessageType.AI_REPLY.value,
            limit,
        ),
    ).fetchall()

    return [_row_to_message(r) for r in rows]
