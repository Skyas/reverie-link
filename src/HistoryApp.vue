<script setup lang="ts">
import { ref, computed, onMounted } from "vue";

// ── 类型定义 ───────────────────────────────────────────────────
interface Message {
    id: string;
    timestamp: string;
    type: string;
    content: string;
    reply_to: string | null;
    metadata: Record<string, unknown>;
    session_id: string;
    character_id: string;
}

interface Session {
    session_id: string;
    first_msg: string;
    last_msg: string;
    msg_count: number;
}

// ── 情绪图标映射 ───────────────────────────────────────────────
const EMOTION_ICON: Record<string, string> = {
    happy:     "😊",
    sad:       "😢",
    angry:     "😠",
    shy:       "😳",
    surprised: "😲",
    sigh:      "😮‍💨",
    neutral:   "😐",
};

// ── 当前角色信息（从 localStorage 读取）───────────────────────
const characterId   = ref(localStorage.getItem("rl-active-preset-id") ?? "");
const characterName = ref("角色");

function loadCharacterName() {
    try {
        const presets = JSON.parse(localStorage.getItem("rl-presets") ?? "[]");
        const found   = presets.find((p: { id: string; name: string }) => p.id === characterId.value);
        if (found) characterName.value = found.name;
    } catch { /* ignore */ }
}

// ── 会话列表 ───────────────────────────────────────────────────
const sessions       = ref<Session[]>([]);
const selectedSession = ref<string | null>(null);

async function fetchSessions() {
    try {
        const params = new URLSearchParams();
        if (characterId.value) params.set("character_id", characterId.value);
        const res  = await fetch(`http://localhost:18000/api/chat/sessions?${params}`);
        const data = await res.json();
        sessions.value = data.sessions ?? [];
        // 默认选中最近一次会话
        if (sessions.value.length > 0 && selectedSession.value === null) {
            selectedSession.value = sessions.value[0].session_id;
            await fetchMessages(1);
        }
    } catch {
        showToast("获取会话列表失败，请确认后端已启动", true);
    }
}

function formatSession(s: Session): string {
    const d = new Date(s.first_msg);
    const pad = (n: number) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

// ── 消息列表 ───────────────────────────────────────────────────
const messages    = ref<Message[]>([]);
const total       = ref(0);
const page        = ref(1);
const totalPages  = ref(1);
const pageSize    = 30;
const loading     = ref(false);
const jumpPage    = ref<number | "">(1);

async function fetchMessages(p: number) {
    if (!selectedSession.value) return;
    loading.value = true;
    try {
        const params = new URLSearchParams({
            session_id: selectedSession.value,
            page:       String(p),
            page_size:  String(pageSize),
        });
        if (characterId.value) params.set("character_id", characterId.value);
        if (keyword.value.trim()) params.set("keyword", keyword.value.trim());
        const res  = await fetch(`http://localhost:18000/api/chat/messages?${params}`);
        const data = await res.json();
        // API 返回倒序，翻转为正序显示（最早的在上面）
        messages.value = (data.items ?? []).reverse();
        total.value      = data.total      ?? 0;
        page.value       = data.page       ?? 1;
        totalPages.value = data.total_pages ?? 1;
        jumpPage.value   = page.value;
    } catch {
        showToast("获取消息失败", true);
    } finally {
        loading.value = false;
    }
}

async function selectSession(sessionId: string) {
    selectedSession.value = sessionId;
    keyword.value = "";
    await fetchMessages(1);
}

// ── 搜索 ───────────────────────────────────────────────────────
const keyword    = ref("");
const searching  = ref(false);

async function doSearch() {
    if (!keyword.value.trim()) {
        await fetchMessages(1);
        return;
    }
    searching.value = true;
    loading.value   = true;
    try {
        const params = new URLSearchParams({
            keyword: keyword.value.trim(),
            limit:   "200",
        });
        if (characterId.value) params.set("character_id", characterId.value);
        const res  = await fetch(`http://localhost:18000/api/chat/search?${params}`);
        const data = await res.json();
        messages.value   = (data.items ?? []).reverse();
        total.value      = messages.value.length;
        page.value       = 1;
        totalPages.value = 1;
        selectedSession.value = null;
    } catch {
        showToast("搜索失败", true);
    } finally {
        loading.value   = false;
        searching.value = false;
    }
}

function clearSearch() {
    keyword.value = "";
    if (sessions.value.length > 0) {
        selectedSession.value = sessions.value[0].session_id;
        fetchMessages(1);
    }
}

// ── 跳页 ───────────────────────────────────────────────────────
async function jumpToPage() {
    const p = Number(jumpPage.value);
    if (p >= 1 && p <= totalPages.value) await fetchMessages(p);
}

// ── Toast ──────────────────────────────────────────────────────
const toastText = ref("");
const toastWarn = ref(false);
let toastTimer: ReturnType<typeof setTimeout> | null = null;

function showToast(text: string, warn = false) {
    toastText.value = text;
    toastWarn.value = warn;
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { toastText.value = ""; }, 2500);
}

// ── 消息气泡辅助 ───────────────────────────────────────────────
function isUser(msg: Message) {
    return msg.type === "user_text" || msg.type === "user_voice";
}

function getEmotion(msg: Message): string {
    if (msg.type !== "ai_reply") return "";
    const e = msg.metadata?.emotion as string ?? "";
    return EMOTION_ICON[e] ?? "";
}

function formatTime(iso: string): string {
    const d = new Date(iso);
    const pad = (n: number) => String(n).padStart(2, "0");
    return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function formatDate(iso: string): string {
    const d = new Date(iso);
    return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}`;
}

// 插入日期分隔线：当相邻两条消息日期不同时插入
const messagesWithDateSep = computed(() => {
    const result: Array<{ type: "date"; date: string } | { type: "msg"; msg: Message }> = [];
    let lastDate = "";
    for (const msg of messages.value) {
        const d = formatDate(msg.timestamp);
        if (d !== lastDate) {
            result.push({ type: "date", date: d });
            lastDate = d;
        }
        result.push({ type: "msg", msg });
    }
    return result;
});

// ── 初始化 ─────────────────────────────────────────────────────
onMounted(async () => {
    loadCharacterName();
    await fetchSessions();
});
</script>

<template>
    <div class="history-root">

        <!-- Toast -->
        <transition name="toast">
            <div v-if="toastText" class="toast" :class="{ warn: toastWarn }">{{ toastText }}</div>
        </transition>

        <!-- 标题栏 -->
        <div class="header">
            <div class="header-icon">✦</div>
            <div class="header-title">聊天记录</div>
            <div class="header-sub">{{ characterName }} 的对话历史</div>
        </div>

        <!-- 主体：左侧会话列表 + 右侧消息区 -->
        <div class="main-layout">

            <!-- 左侧：会话列表 -->
            <div class="session-panel">
                <div class="session-panel-title">会话列表</div>
                <div class="session-list">
                    <div v-if="sessions.length === 0" class="session-empty">暂无会话记录</div>
                    <div v-for="s in sessions" :key="s.session_id"
                         class="session-item"
                         :class="{ active: selectedSession === s.session_id }"
                         @click="selectSession(s.session_id)">
                        <div class="session-time">{{ formatSession(s) }}</div>
                        <div class="session-count">{{ s.msg_count }} 条</div>
                    </div>
                </div>
            </div>

            <!-- 右侧：消息区 -->
            <div class="message-panel">

                <!-- 搜索栏 -->
                <div class="search-bar">
                    <input class="search-input" v-model="keyword"
                           placeholder="搜索聊天记录…"
                           @keydown.enter="doSearch" />
                    <button class="search-btn" @click="doSearch">搜索</button>
                    <button v-if="keyword" class="search-clear-btn" @click="clearSearch">✕</button>
                </div>

                <!-- 消息列表 -->
                <div class="message-list">
                    <div v-if="loading" class="msg-loading">加载中…</div>
                    <div v-else-if="messages.length === 0" class="msg-empty">
                        {{ selectedSession ? "这次会话没有消息" : "请选择一个会话" }}
                    </div>
                    <template v-else>
                        <template v-for="item in messagesWithDateSep" :key="item.type === 'date' ? item.date : item.msg.id">
                            <!-- 日期分隔线 -->
                            <div v-if="item.type === 'date'" class="date-sep">
                                <span>{{ item.date }}</span>
                            </div>
                            <!-- 消息气泡 -->
                            <div v-else class="msg-row" :class="{ 'msg-row-user': isUser(item.msg), 'msg-row-ai': !isUser(item.msg) }">
                                <!-- AI 头像 -->
                                <div v-if="!isUser(item.msg)" class="msg-avatar ai-avatar">
                                    {{ characterName[0] ?? "A" }}
                                </div>
                                <div class="msg-bubble-wrap">
                                    <div class="msg-bubble" :class="{ 'bubble-user': isUser(item.msg), 'bubble-ai': !isUser(item.msg) }">
                                        {{ item.msg.content }}
                                    </div>
                                    <div class="msg-meta">
                                        <span v-if="!isUser(item.msg) && getEmotion(item.msg)" class="msg-emotion">{{ getEmotion(item.msg) }}</span>
                                        <span class="msg-time">{{ formatTime(item.msg.timestamp) }}</span>
                                        <span v-if="item.msg.type === 'user_voice'" class="msg-voice-badge">🎤</span>
                                    </div>
                                </div>
                                <!-- 用户头像 -->
                                <div v-if="isUser(item.msg)" class="msg-avatar user-avatar">我</div>
                            </div>
                        </template>
                    </template>
                </div>

                <!-- 分页 -->
                <div v-if="totalPages > 1 && !keyword" class="pagination">
                    <button class="page-btn" :disabled="page <= 1" @click="fetchMessages(1)">首页</button>
                    <button class="page-btn" :disabled="page <= 1" @click="fetchMessages(page - 1)">上一页</button>
                    <span class="page-info">{{ page }} / {{ totalPages }}（共 {{ total }} 条）</span>
                    <button class="page-btn" :disabled="page >= totalPages" @click="fetchMessages(page + 1)">下一页</button>
                    <button class="page-btn" :disabled="page >= totalPages" @click="fetchMessages(totalPages)">尾页</button>
                    <input class="jump-input" v-model.number="jumpPage" type="number" min="1" :max="totalPages" @keydown.enter="jumpToPage" />
                    <button class="page-btn" @click="jumpToPage">跳转</button>
                </div>

            </div>
        </div>
    </div>
</template>

<style>
    *, *::before, *::after { margin: 0; padding: 0; box-sizing: border-box; }
    html, body {
        width: 100%; height: 100%;
        font-family: "Hiragino Sans GB", "Microsoft YaHei", "PingFang SC", sans-serif;
        -webkit-font-smoothing: antialiased;
        background: #FEF6FA;
    }
    ::-webkit-scrollbar { width: 5px; }
    ::-webkit-scrollbar-track { background: transparent; }
    ::-webkit-scrollbar-thumb { background: #FFCDD9; border-radius: 3px; }
</style>

<style scoped>
    .history-root {
        --c-bg:         #FEF6FA;
        --c-surface:    #FFFFFF;
        --c-blue:       #7EC8E3;
        --c-blue-light: #C5E8F4;
        --c-blue-mid:   #A8D8EA;
        --c-pink:       #FFB7C5;
        --c-pink-light: #FFE4EC;
        --c-pink-mid:   #FFAABB;
        --c-text:       #4A4A6A;
        --c-text-soft:  #9B8FB0;
        --c-border:     rgba(212,184,224,0.45);
        --c-shadow:     rgba(180,140,200,0.12);

        min-height: 100vh;
        background: var(--c-bg);
        display: flex;
        flex-direction: column;
        overflow: hidden;
    }

    /* ── Toast ────────────────────────────────────────────────── */
    .toast {
        position: fixed;
        top: 12px; left: 50%;
        transform: translateX(-50%);
        padding: 7px 18px;
        border-radius: 20px;
        background: linear-gradient(135deg, var(--c-blue-mid), var(--c-pink));
        color: white; font-size: 13px;
        box-shadow: 0 4px 16px rgba(126,87,194,0.2);
        z-index: 999; pointer-events: none;
    }
    .toast.warn { background: linear-gradient(135deg, #F0A0A0, #E08080); }
    .toast-enter-active { transition: opacity 0.2s ease, transform 0.2s ease; }
    .toast-leave-active { transition: opacity 0.15s ease; }
    .toast-enter-from   { opacity: 0; transform: translateX(-50%) translateY(-8px); }
    .toast-leave-to     { opacity: 0; }

    /* ── 标题栏 ───────────────────────────────────────────────── */
    .header {
        padding: 14px 20px 12px;
        background: linear-gradient(135deg, var(--c-blue-mid), var(--c-pink));
        flex-shrink: 0;
    }
    .header-icon  { font-size: 10px; color: rgba(255,255,255,0.7); letter-spacing: 2px; }
    .header-title { font-size: 17px; font-weight: 700; color: white; }
    .header-sub   { font-size: 12px; color: rgba(255,255,255,0.85); margin-top: 2px; }

    /* ── 主体布局 ─────────────────────────────────────────────── */
    .main-layout {
        flex: 1;
        display: flex;
        overflow: hidden;
    }

    /* ── 左侧会话列表 ─────────────────────────────────────────── */
    .session-panel {
        width: 160px;
        flex-shrink: 0;
        border-right: 1.5px solid var(--c-border);
        background: var(--c-surface);
        display: flex;
        flex-direction: column;
        overflow: hidden;
    }

    .session-panel-title {
        padding: 10px 12px 8px;
        font-size: 11px;
        font-weight: 600;
        color: var(--c-text-soft);
        letter-spacing: 0.5px;
        border-bottom: 1px solid var(--c-border);
        flex-shrink: 0;
    }

    .session-list {
        flex: 1;
        overflow-y: auto;
        padding: 6px 0;
    }

    .session-empty {
        padding: 16px 12px;
        font-size: 12px;
        color: var(--c-text-soft);
        text-align: center;
    }

    .session-item {
        padding: 8px 12px;
        cursor: pointer;
        transition: background 0.15s;
        border-left: 3px solid transparent;
    }

        .session-item:hover { background: var(--c-pink-light); }
        .session-item.active {
            background: linear-gradient(135deg, rgba(197,232,244,0.2), rgba(255,183,197,0.15));
            border-left-color: var(--c-pink-mid);
        }

    .session-time  { font-size: 11px; color: var(--c-text); font-weight: 500; }
    .session-count { font-size: 10px; color: var(--c-text-soft); margin-top: 2px; }

    /* ── 右侧消息区 ───────────────────────────────────────────── */
    .message-panel {
        flex: 1;
        display: flex;
        flex-direction: column;
        overflow: hidden;
    }

    /* 搜索栏 */
    .search-bar {
        display: flex;
        gap: 6px;
        padding: 10px 14px;
        border-bottom: 1.5px solid var(--c-border);
        background: var(--c-surface);
        flex-shrink: 0;
        align-items: center;
    }

    .search-input {
        flex: 1;
        height: 30px;
        border: 1.5px solid var(--c-border);
        border-radius: 8px;
        padding: 0 10px;
        font-size: 13px;
        font-family: inherit;
        color: var(--c-text);
        background: var(--c-bg);
        outline: none;
    }
        .search-input:focus { border-color: var(--c-blue); }

    .search-btn {
        height: 30px; padding: 0 12px;
        border: none; border-radius: 8px;
        background: var(--c-blue-light);
        color: var(--c-text);
        font-size: 12px; font-family: inherit;
        cursor: pointer;
    }
        .search-btn:hover { background: var(--c-blue); color: white; }

    .search-clear-btn {
        height: 30px; width: 30px;
        border: 1.5px solid var(--c-border);
        border-radius: 8px;
        background: transparent;
        color: var(--c-text-soft);
        font-size: 12px; cursor: pointer;
    }
        .search-clear-btn:hover { background: var(--c-pink-light); }

    /* 消息列表 */
    .message-list {
        flex: 1;
        overflow-y: auto;
        padding: 12px 14px;
        display: flex;
        flex-direction: column;
        gap: 4px;
    }

    .msg-loading, .msg-empty {
        text-align: center;
        padding: 32px 0;
        color: var(--c-text-soft);
        font-size: 13px;
    }

    /* 日期分隔线 */
    .date-sep {
        display: flex;
        align-items: center;
        gap: 8px;
        margin: 10px 0 6px;
        color: var(--c-text-soft);
        font-size: 11px;
    }
    .date-sep::before, .date-sep::after {
        content: "";
        flex: 1;
        height: 1px;
        background: var(--c-border);
    }

    /* 消息行 */
    .msg-row {
        display: flex;
        align-items: flex-end;
        gap: 8px;
        margin-bottom: 4px;
    }

    .msg-row-user { justify-content: flex-end; }
    .msg-row-ai   { justify-content: flex-start; }

    /* 头像 */
    .msg-avatar {
        width: 28px; height: 28px;
        border-radius: 50%;
        display: flex; align-items: center; justify-content: center;
        font-size: 11px; font-weight: 700;
        flex-shrink: 0;
    }

    .ai-avatar {
        background: linear-gradient(135deg, var(--c-blue-mid), var(--c-pink));
        color: white;
    }

    .user-avatar {
        background: var(--c-pink-light);
        color: var(--c-text-soft);
    }

    /* 气泡 */
    .msg-bubble-wrap {
        max-width: 68%;
        display: flex;
        flex-direction: column;
        gap: 3px;
    }

    .msg-row-user .msg-bubble-wrap { align-items: flex-end; }
    .msg-row-ai  .msg-bubble-wrap { align-items: flex-start; }

    .msg-bubble {
        padding: 8px 12px;
        border-radius: 14px;
        font-size: 13px;
        line-height: 1.6;
        white-space: pre-wrap;
        word-break: break-word;
    }

    .bubble-user {
        background: linear-gradient(135deg, var(--c-blue-mid), var(--c-blue));
        color: white;
        border-bottom-right-radius: 4px;
    }

    .bubble-ai {
        background: var(--c-surface);
        color: var(--c-text);
        border: 1.5px solid var(--c-border);
        border-bottom-left-radius: 4px;
    }

    .msg-meta {
        display: flex;
        align-items: center;
        gap: 4px;
    }

    .msg-time { font-size: 10px; color: var(--c-text-soft); }
    .msg-emotion { font-size: 13px; }
    .msg-voice-badge {
        font-size: 10px;
        color: var(--c-text-soft);
    }

    /* 分页 */
    .pagination {
        display: flex;
        align-items: center;
        gap: 6px;
        padding: 8px 14px;
        border-top: 1.5px solid var(--c-border);
        background: var(--c-surface);
        flex-shrink: 0;
        flex-wrap: wrap;
        justify-content: center;
    }

    .page-btn {
        height: 28px; padding: 0 10px;
        border: 1.5px solid var(--c-border);
        border-radius: 6px;
        font-size: 12px; font-family: inherit;
        background: var(--c-surface);
        color: var(--c-text-soft);
        cursor: pointer;
        transition: background 0.15s;
    }
        .page-btn:hover:not(:disabled) { background: var(--c-pink-light); }
        .page-btn:disabled { opacity: 0.35; cursor: not-allowed; }

    .page-info { font-size: 11px; color: var(--c-text-soft); padding: 0 4px; }

    .jump-input {
        width: 42px; height: 28px;
        border: 1.5px solid var(--c-border);
        border-radius: 6px;
        padding: 0 6px;
        font-size: 12px; font-family: inherit;
        color: var(--c-text); background: var(--c-bg);
        text-align: center; outline: none;
    }
</style>