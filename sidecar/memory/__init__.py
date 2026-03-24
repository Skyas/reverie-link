"""
Reverie Link · 记忆系统

三阶记忆架构的核心模块包：
  第一阶：短期滑动窗口 — timeline.py（步骤③实现）
  第二阶：核心档案（笔记本）— db_notebook.py + extractor.py（步骤⑤实现）
  第三阶：长期摘要记忆 — vector_store.py（步骤⑥实现）

本文件导出所有公共 API，供 main.py 和 prompt_builder.py 使用。
"""

# ── 数据模型 ──────────────────────────────────────────────────────
from .models import (
    MessageType,
    NotebookSource,
    TimelineMessage,
    NotebookEntry,
    WindowPreset,
    WINDOW_PRESETS,
    DEFAULT_WINDOW_INDEX,
    generate_msg_id,
    generate_session_id,
    generate_entry_id,
    generate_summary_id,
    now_iso,
)

# ── 聊天记录数据库 ────────────────────────────────────────────────
from .db_chat import (
    init_chat_db,
    save_message,
    save_messages_batch,
    get_messages_page,
    get_sessions,
    get_recent_messages,
    search_messages,
    close_conn as close_chat_db,
)

# ── 笔记本数据库 ──────────────────────────────────────────────────
from .db_notebook import (
    init_notebook_db,
    add_entry,
    add_entries_batch,
    update_entry,
    delete_entry,
    get_entries_page,
    get_all_entries,
    get_all_entries_for_prompt,
    count_entries,
    close_conn as close_notebook_db,
)


# ── 统一初始化 ────────────────────────────────────────────────────

def init_memory_system() -> None:
    """
    初始化整个记忆系统。
    在 FastAPI 启动时调用一次即可（幂等）。
    """
    init_chat_db()
    init_notebook_db()
    print("[Memory] 记忆系统初始化完成")


def shutdown_memory_system() -> None:
    """
    关闭记忆系统，释放数据库连接。
    在程序退出时调用。
    """
    close_chat_db()
    close_notebook_db()
    print("[Memory] 记忆系统已关闭")
