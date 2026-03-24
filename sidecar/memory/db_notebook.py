"""
Reverie Link · 记忆系统 — 笔记本数据库（世界书）

管理核心档案的持久化：手动区（我的备忘录）+ 自动区（角色的日记本）。
数据文件：data/notebook.db

参考文档：PHASE3_MEMORY_DESIGN.md § 5
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Optional

from .models import NotebookEntry, NotebookSource


# ── 数据库文件路径 ─────────────────────────────────────────────────

def _get_db_path() -> Path:
    """获取笔记本数据库文件路径，确保 data/ 目录存在"""
    project_root = Path(__file__).parent.parent.parent
    data_dir = project_root / "data"
    data_dir.mkdir(exist_ok=True)
    return data_dir / "notebook.db"


# ── 数据库初始化 ──────────────────────────────────────────────────

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS notebook_entries (
    id         TEXT PRIMARY KEY,
    source     TEXT NOT NULL,
    content    TEXT NOT NULL,
    tags       TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

_CREATE_INDEXES_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_nb_source     ON notebook_entries(source);",
    "CREATE INDEX IF NOT EXISTS idx_nb_created_at  ON notebook_entries(created_at);",
]


def _get_connection() -> sqlite3.Connection:
    """获取数据库连接"""
    db_path = _get_db_path()
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def init_notebook_db() -> None:
    """初始化笔记本数据库（幂等操作）"""
    conn = _get_connection()
    try:
        conn.execute(_CREATE_TABLE_SQL)
        for idx_sql in _CREATE_INDEXES_SQL:
            conn.execute(idx_sql)
        conn.commit()
        print("[Memory] 笔记本数据库初始化完成")
    finally:
        conn.close()


# ── 全局连接 ──────────────────────────────────────────────────────

_conn: Optional[sqlite3.Connection] = None


def get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = _get_connection()
    return _conn


def close_conn() -> None:
    global _conn
    if _conn is not None:
        _conn.close()
        _conn = None


# ── 行转对象 ──────────────────────────────────────────────────────

def _row_to_entry(row: sqlite3.Row) -> NotebookEntry:
    return NotebookEntry(
        id=row["id"],
        source=NotebookSource(row["source"]),
        content=row["content"],
        tags=json.loads(row["tags"]) if row["tags"] else [],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


# ── 写入操作 ──────────────────────────────────────────────────────

def add_entry(entry: NotebookEntry) -> None:
    """添加一条笔记本条目"""
    conn = get_conn()
    conn.execute(
        """
        INSERT OR IGNORE INTO notebook_entries
            (id, source, content, tags, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            entry.id,
            entry.source.value,
            entry.content,
            json.dumps(entry.tags, ensure_ascii=False),
            entry.created_at,
            entry.updated_at,
        ),
    )
    conn.commit()


def add_entries_batch(entries: list[NotebookEntry]) -> None:
    """批量添加条目（自动提取时使用）"""
    conn = get_conn()
    conn.executemany(
        """
        INSERT OR IGNORE INTO notebook_entries
            (id, source, content, tags, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (
                e.id, e.source.value, e.content,
                json.dumps(e.tags, ensure_ascii=False),
                e.created_at, e.updated_at,
            )
            for e in entries
        ],
    )
    conn.commit()


def update_entry(entry_id: str, content: str, tags: list[str]) -> bool:
    """
    更新一条条目的内容和标签（仅允许手动区条目）。
    返回是否成功更新。
    """
    from .models import now_iso
    conn = get_conn()
    cursor = conn.execute(
        """
        UPDATE notebook_entries
        SET content = ?, tags = ?, updated_at = ?
        WHERE id = ? AND source = ?
        """,
        (
            content,
            json.dumps(tags, ensure_ascii=False),
            now_iso(),
            entry_id,
            NotebookSource.MANUAL.value,
        ),
    )
    conn.commit()
    return cursor.rowcount > 0


def delete_entry(entry_id: str) -> bool:
    """
    删除一条条目。
    手动区和自动区均可删除（自动区删除表示"这条记错了"）。
    返回是否成功删除。
    """
    conn = get_conn()
    cursor = conn.execute(
        "DELETE FROM notebook_entries WHERE id = ?",
        (entry_id,),
    )
    conn.commit()
    return cursor.rowcount > 0


# ── 查询操作 ──────────────────────────────────────────────────────

def get_entries_page(
    source: NotebookSource,
    page: int = 1,
    page_size: int = 10,
    keyword: Optional[str] = None,
    search_by: str = "content",    # "content" | "tag"
) -> dict:
    """
    分页查询笔记本条目。

    Args:
        source: 按来源筛选（manual / auto）
        page: 页码（从 1 开始）
        page_size: 每页条数
        keyword: 搜索关键词（可选）
        search_by: 搜索维度，"content" 按内容 / "tag" 按标签

    Returns:
        {
            "items": [NotebookEntry, ...],
            "total": 总条数,
            "page": 当前页码,
            "page_size": 每页条数,
            "total_pages": 总页数,
        }
    """
    conn = get_conn()

    conditions = ["source = ?"]
    params: list = [source.value]

    if keyword:
        if search_by == "tag":
            # 标签存储为 JSON 数组，用 LIKE 模糊匹配
            conditions.append("tags LIKE ?")
            params.append(f'%"{keyword}"%')
        else:
            conditions.append("content LIKE ?")
            params.append(f"%{keyword}%")

    where_clause = " AND ".join(conditions)

    # 总数
    total = conn.execute(
        f"SELECT COUNT(*) as cnt FROM notebook_entries WHERE {where_clause}",
        params,
    ).fetchone()["cnt"]

    # 分页
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = max(1, min(page, total_pages))
    offset = (page - 1) * page_size

    # 数据（按创建时间倒序）
    rows = conn.execute(
        f"""
        SELECT * FROM notebook_entries
        WHERE {where_clause}
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
        """,
        params + [page_size, offset],
    ).fetchall()

    return {
        "items": [_row_to_entry(r) for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }


def get_all_entries(source: Optional[NotebookSource] = None) -> list[NotebookEntry]:
    """
    获取所有条目（可选按来源筛选）。
    主要用于：
    - 注入 System Prompt Layer 2（核心记忆）
    - 自动提取时的去重比对
    """
    conn = get_conn()
    if source is not None:
        rows = conn.execute(
            "SELECT * FROM notebook_entries WHERE source = ? ORDER BY created_at ASC",
            (source.value,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM notebook_entries ORDER BY created_at ASC",
        ).fetchall()

    return [_row_to_entry(r) for r in rows]


def get_all_entries_for_prompt() -> str:
    """
    获取所有条目，格式化为可注入 Prompt 的文本。
    用于自动提取时喂给 LLM 做去重参考。
    """
    entries = get_all_entries()
    if not entries:
        return "（暂无记忆）"

    lines = []
    for e in entries:
        tag_str = ", ".join(e.tags) if e.tags else ""
        src = "备忘录" if e.source == NotebookSource.MANUAL else "日记"
        lines.append(f"- [{src}][{tag_str}] {e.content}")

    return "\n".join(lines)


def count_entries(source: Optional[NotebookSource] = None) -> int:
    """统计条目数量"""
    conn = get_conn()
    if source is not None:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM notebook_entries WHERE source = ?",
            (source.value,),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM notebook_entries",
        ).fetchone()
    return row["cnt"]
