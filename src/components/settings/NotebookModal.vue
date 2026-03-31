<script setup lang="ts">
import { ref, watch } from "vue";

// ── Props / Emits ──────────────────────────────────────────────
const props = defineProps<{
    visible:       boolean;
    characterId:   string;
    characterName: string;
}>();

defineEmits<{ "close": [] }>();

// ── Toast ──────────────────────────────────────────────────────
const msgText = ref("");
const msgType = ref<"ok" | "warn">("ok");
function showMsg(text: string, type: "ok" | "warn" = "ok") {
    msgText.value = text; msgType.value = type;
    setTimeout(() => { msgText.value = ""; }, 2500);
}

// ── 类型 ───────────────────────────────────────────────────────
interface NotebookEntry {
    id: string; source: string; content: string;
    tags: string[]; created_at: string; updated_at: string;
}

// ── Tab 状态 ───────────────────────────────────────────────────
const notebookTab = ref<"manual" | "auto">("manual");
const loading     = ref(false);

// ── 手动区 ─────────────────────────────────────────────────────
const manualEntries    = ref<NotebookEntry[]>([]);
const manualTotal      = ref(0);
const manualPage       = ref(1);
const manualTotalPages = ref(1);
const manualKeyword    = ref("");
const manualSearchBy   = ref<"content" | "tag">("content");
const manualJumpPage   = ref<number | "">(1);

// ── 自动区 ─────────────────────────────────────────────────────
const autoEntries    = ref<NotebookEntry[]>([]);
const autoTotal      = ref(0);
const autoPage       = ref(1);
const autoTotalPages = ref(1);
const autoKeyword    = ref("");
const autoSearchBy   = ref<"content" | "tag">("content");
const autoJumpPage   = ref<number | "">(1);

// ── 新增/编辑表单 ───────────────────────────────────────────────
const showEntryForm  = ref(false);
const editingEntryId = ref<string | null>(null);
const entryContent   = ref("");
const entryTagsRaw   = ref("");

// ── 数据获取 ───────────────────────────────────────────────────
async function fetchManualEntries(page: number) {
    loading.value = true;
    try {
        const params = new URLSearchParams({
            source: "manual", page: String(page), page_size: "10",
            character_id: props.characterId,
        });
        if (manualKeyword.value.trim()) {
            params.set("keyword",   manualKeyword.value.trim());
            params.set("search_by", manualSearchBy.value);
        }
        const data = await fetch(`http://localhost:18000/api/notebook/entries?${params}`).then(r => r.json());
        manualEntries.value    = data.items        ?? [];
        manualTotal.value      = data.total        ?? 0;
        manualPage.value       = data.page         ?? 1;
        manualTotalPages.value = data.total_pages  ?? 1;
        manualJumpPage.value   = manualPage.value;
    } catch { showMsg("获取备忘录失败，请确认后端已启动", "warn"); }
    finally   { loading.value = false; }
}

async function fetchAutoEntries(page: number) {
    loading.value = true;
    try {
        const params = new URLSearchParams({
            source: "auto", page: String(page), page_size: "10",
            character_id: props.characterId,
        });
        if (autoKeyword.value.trim()) {
            params.set("keyword",   autoKeyword.value.trim());
            params.set("search_by", autoSearchBy.value);
        }
        const data = await fetch(`http://localhost:18000/api/notebook/entries?${params}`).then(r => r.json());
        autoEntries.value    = data.items        ?? [];
        autoTotal.value      = data.total        ?? 0;
        autoPage.value       = data.page         ?? 1;
        autoTotalPages.value = data.total_pages  ?? 1;
        autoJumpPage.value   = autoPage.value;
    } catch { showMsg("获取日记本失败，请确认后端已启动", "warn"); }
    finally   { loading.value = false; }
}

// 弹窗打开时重置并加载
watch(() => props.visible, async (val) => {
    if (!val) return;
    notebookTab.value = "manual";
    manualKeyword.value = ""; autoKeyword.value = "";
    await fetchManualEntries(1);
    await fetchAutoEntries(1);
});

// ── 条目操作 ───────────────────────────────────────────────────
function openNewEntry() {
    editingEntryId.value = null;
    entryContent.value   = "";
    entryTagsRaw.value   = "";
    showEntryForm.value  = true;
}

function openEditEntry(entry: NotebookEntry) {
    editingEntryId.value = entry.id;
    entryContent.value   = entry.content;
    entryTagsRaw.value   = entry.tags.join("、");
    showEntryForm.value  = true;
}

async function saveEntry() {
    const content = entryContent.value.trim();
    if (!content) { showMsg("内容不能为空", "warn"); return; }
    const tags = entryTagsRaw.value.split(/[,，、]/).map(t => t.trim()).filter(Boolean);
    try {
        if (editingEntryId.value) {
            await fetch(`http://localhost:18000/api/notebook/entries/${editingEntryId.value}`, {
                method: "PUT", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ content, tags }),
            });
            showMsg("✓ 已更新");
        } else {
            await fetch("http://localhost:18000/api/notebook/entries", {
                method: "POST", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ content, tags, character_id: props.characterId }),
            });
            showMsg("✓ 已添加");
        }
        showEntryForm.value = false;
        await fetchManualEntries(manualPage.value);
    } catch { showMsg("操作失败", "warn"); }
}

async function deleteEntry(id: string, source: "manual" | "auto") {
    try {
        await fetch(`http://localhost:18000/api/notebook/entries/${id}`, { method: "DELETE" });
        showMsg("已删除");
        if (source === "manual") await fetchManualEntries(manualPage.value);
        else                     await fetchAutoEntries(autoPage.value);
    } catch { showMsg("删除失败", "warn"); }
}

// ── 搜索 & 跳页 ────────────────────────────────────────────────
async function searchManual() { await fetchManualEntries(1); }
async function searchAuto()   { await fetchAutoEntries(1);   }

async function jumpManualPage() {
    const p = Number(manualJumpPage.value);
    if (p >= 1 && p <= manualTotalPages.value) await fetchManualEntries(p);
}
async function jumpAutoPage() {
    const p = Number(autoJumpPage.value);
    if (p >= 1 && p <= autoTotalPages.value) await fetchAutoEntries(p);
}
</script>

<template>
    <transition name="dialog">
        <div v-if="visible" class="notebook-overlay" @click.self="$emit('close')">
            <div class="notebook-panel">

                <!-- Toast -->
                <transition name="toast">
                    <div v-if="msgText" class="nb-toast" :class="{ warn: msgType === 'warn' }">{{ msgText }}</div>
                </transition>

                <!-- 标题栏 -->
                <div class="notebook-header">
                    <span class="notebook-title">📓 {{ characterName }}的笔记本</span>
                    <button class="notebook-close" @click="$emit('close')">×</button>
                </div>

                <!-- Tab 切换 -->
                <div class="notebook-tabs">
                    <button class="nb-tab-btn" :class="{ active: notebookTab === 'manual' }"
                            @click="notebookTab = 'manual'">我的备忘录</button>
                    <button class="nb-tab-btn" :class="{ active: notebookTab === 'auto' }"
                            @click="notebookTab = 'auto'">{{ characterName }}的日记本</button>
                </div>

                <!-- 内容区 -->
                <div class="notebook-content">

                    <!-- ── 手动区 ── -->
                    <div v-if="notebookTab === 'manual'">
                        <div class="nb-search-row">
                            <input class="nb-search-input" v-model="manualKeyword"
                                   placeholder="搜索…" @keydown.enter="searchManual" />
                            <select class="nb-search-by" v-model="manualSearchBy">
                                <option value="content">按内容</option>
                                <option value="tag">按标签</option>
                            </select>
                            <button class="nb-search-btn" @click="searchManual">搜索</button>
                            <button class="nb-add-btn" @click="openNewEntry">+ 新增</button>
                        </div>

                        <div v-if="loading" class="nb-loading">加载中…</div>
                        <div v-else-if="manualEntries.length === 0" class="nb-empty">暂无条目，点击「+ 新增」添加</div>
                        <div v-else class="nb-entries">
                            <div v-for="e in manualEntries" :key="e.id" class="nb-entry-card">
                                <div class="nb-entry-content">{{ e.content }}</div>
                                <div class="nb-entry-tags">
                                    <span v-for="t in e.tags" :key="t" class="nb-tag">{{ t }}</span>
                                </div>
                                <div class="nb-entry-actions">
                                    <button class="nb-edit-btn" @click="openEditEntry(e)">编辑</button>
                                    <button class="nb-del-btn"  @click="deleteEntry(e.id, 'manual')">删除</button>
                                </div>
                            </div>
                        </div>

                        <div v-if="manualTotalPages > 1" class="nb-pagination">
                            <button class="nb-page-btn" :disabled="manualPage <= 1" @click="fetchManualEntries(1)">首页</button>
                            <button class="nb-page-btn" :disabled="manualPage <= 1" @click="fetchManualEntries(manualPage - 1)">上一页</button>
                            <span class="nb-page-info">{{ manualPage }} / {{ manualTotalPages }}</span>
                            <button class="nb-page-btn" :disabled="manualPage >= manualTotalPages" @click="fetchManualEntries(manualPage + 1)">下一页</button>
                            <button class="nb-page-btn" :disabled="manualPage >= manualTotalPages" @click="fetchManualEntries(manualTotalPages)">尾页</button>
                            <input class="nb-jump-input" v-model.number="manualJumpPage" type="number"
                                   min="1" :max="manualTotalPages" @keydown.enter="jumpManualPage" />
                            <button class="nb-page-btn" @click="jumpManualPage">跳转</button>
                        </div>
                        <p class="nb-file-hint">💡 需要批量编辑？数据文件位于 <code>data/notebook.db</code></p>
                    </div>

                    <!-- ── 自动区 ── -->
                    <div v-if="notebookTab === 'auto'">
                        <div class="nb-search-row">
                            <input class="nb-search-input" v-model="autoKeyword"
                                   placeholder="搜索…" @keydown.enter="searchAuto" />
                            <select class="nb-search-by" v-model="autoSearchBy">
                                <option value="content">按内容</option>
                                <option value="tag">按标签</option>
                            </select>
                            <button class="nb-search-btn" @click="searchAuto">搜索</button>
                        </div>

                        <div v-if="loading" class="nb-loading">加载中…</div>
                        <div v-else-if="autoEntries.length === 0" class="nb-empty">{{ characterName }}还没有记录任何事情</div>
                        <div v-else class="nb-entries">
                            <div v-for="e in autoEntries" :key="e.id" class="nb-entry-card nb-entry-auto">
                                <div class="nb-entry-content">{{ e.content }}</div>
                                <div class="nb-entry-tags">
                                    <span v-for="t in e.tags" :key="t" class="nb-tag">{{ t }}</span>
                                </div>
                                <div class="nb-entry-actions">
                                    <button class="nb-del-btn" @click="deleteEntry(e.id, 'auto')" title="删除表示「这条记错了」">删除</button>
                                </div>
                            </div>
                        </div>

                        <div v-if="autoTotalPages > 1" class="nb-pagination">
                            <button class="nb-page-btn" :disabled="autoPage <= 1" @click="fetchAutoEntries(1)">首页</button>
                            <button class="nb-page-btn" :disabled="autoPage <= 1" @click="fetchAutoEntries(autoPage - 1)">上一页</button>
                            <span class="nb-page-info">{{ autoPage }} / {{ autoTotalPages }}</span>
                            <button class="nb-page-btn" :disabled="autoPage >= autoTotalPages" @click="fetchAutoEntries(autoPage + 1)">下一页</button>
                            <button class="nb-page-btn" :disabled="autoPage >= autoTotalPages" @click="fetchAutoEntries(autoTotalPages)">尾页</button>
                            <input class="nb-jump-input" v-model.number="autoJumpPage" type="number"
                                   min="1" :max="autoTotalPages" @keydown.enter="jumpAutoPage" />
                            <button class="nb-page-btn" @click="jumpAutoPage">跳转</button>
                        </div>
                        <p class="nb-file-hint">💡 数据文件位于 <code>data/notebook.db</code></p>
                    </div>

                </div>
            </div>

            <!-- 新增/编辑条目弹框 -->
            <transition name="dialog">
                <div v-if="showEntryForm" class="dialog-overlay" @click.self="showEntryForm = false">
                    <div class="dialog-box" style="width:360px;">
                        <div class="dialog-title">{{ editingEntryId ? "编辑条目" : "新增条目" }}</div>
                        <div class="dialog-body" style="gap:10px;">
                            <div>
                                <label class="field-label">内容 <span class="required">*</span></label>
                                <textarea class="field-input" v-model="entryContent"
                                          rows="3" placeholder="例如：喜欢打羽毛球"
                                          style="resize:none;margin-top:4px;" />
                            </div>
                            <div>
                                <label class="field-label">标签 <span class="field-note">用逗号或顿号分隔</span></label>
                                <input class="field-input" v-model="entryTagsRaw"
                                       placeholder="例如：运动、羽毛球" style="margin-top:4px;" />
                            </div>
                        </div>
                        <div class="dialog-actions">
                            <button class="dialog-cancel"  @click="showEntryForm = false">取消</button>
                            <button class="dialog-confirm" @click="saveEntry">保存</button>
                        </div>
                    </div>
                </div>
            </transition>
        </div>
    </transition>
</template>

<style scoped>
.nb-toast {
    position: fixed; top: 16px; left: 50%; transform: translateX(-50%);
    padding: 8px 20px; border-radius: 20px;
    background: linear-gradient(135deg, var(--c-blue-mid), var(--c-pink));
    color: white; font-size: 13px; font-weight: 500;
    box-shadow: 0 4px 16px rgba(126,87,194,0.2);
    z-index: 500; pointer-events: none; white-space: nowrap;
}
.nb-toast.warn { background: linear-gradient(135deg, #F0A0A0, #E08080); }
.toast-enter-active { transition: opacity 0.25s ease, transform 0.25s ease; }
.toast-leave-active { transition: opacity 0.2s ease; }
.toast-enter-from { opacity: 0; transform: translateX(-50%) translateY(-10px); }
.toast-leave-to   { opacity: 0; }

.notebook-overlay {
    position: fixed; inset: 0;
    background: rgba(100,80,120,0.3); backdrop-filter: blur(6px);
    display: flex; align-items: center; justify-content: center; z-index: 150;
}
.notebook-panel {
    width: 560px; max-height: 80vh;
    background: var(--c-bg); border-radius: 20px;
    box-shadow: 0 12px 48px rgba(126,87,194,0.2);
    display: flex; flex-direction: column; overflow: hidden;
}
.notebook-header {
    display: flex; align-items: center; justify-content: space-between;
    padding: 16px 20px 12px; border-bottom: 1.5px solid var(--c-border); flex-shrink: 0;
}
.notebook-title { font-size: 15px; font-weight: 700; color: var(--c-text); }
.notebook-close {
    width: 28px; height: 28px; border: none; border-radius: 50%;
    background: var(--c-pink-light); color: var(--c-text-soft);
    font-size: 16px; cursor: pointer; display: flex; align-items: center; justify-content: center;
    transition: background 0.2s;
}
.notebook-close:hover { background: var(--c-pink); color: white; }

.notebook-tabs { display: flex; gap: 0; padding: 10px 20px 0; flex-shrink: 0; }
.nb-tab-btn {
    padding: 7px 18px; border: 1.5px solid var(--c-border); border-bottom: none;
    border-radius: 10px 10px 0 0; background: var(--c-pink-light);
    color: var(--c-text-soft); font-size: 13px; font-family: inherit;
    cursor: pointer; transition: background 0.2s, color 0.2s;
}
.nb-tab-btn.active { background: var(--c-surface); color: var(--c-text); font-weight: 600; }

.notebook-content {
    flex: 1; overflow-y: auto; padding: 14px 20px 16px;
    background: var(--c-surface); border-top: 1.5px solid var(--c-border);
}

.nb-search-row { display: flex; gap: 6px; margin-bottom: 12px; align-items: center; }
.nb-search-input {
    flex: 1; height: 32px; border: 1.5px solid var(--c-border); border-radius: 8px;
    padding: 0 10px; font-size: 13px; font-family: inherit; color: var(--c-text);
    background: var(--c-bg); outline: none;
}
.nb-search-input:focus { border-color: var(--c-blue); }
.nb-search-by {
    height: 32px; border: 1.5px solid var(--c-border); border-radius: 8px;
    padding: 0 6px; font-size: 12px; font-family: inherit;
    color: var(--c-text); background: var(--c-bg); outline: none; cursor: pointer;
}
.nb-search-btn, .nb-add-btn {
    height: 32px; padding: 0 12px; border: none; border-radius: 8px;
    font-size: 12px; font-family: inherit; cursor: pointer; white-space: nowrap; transition: opacity 0.2s;
}
.nb-search-btn { background: var(--c-blue-light); color: var(--c-text); }
.nb-add-btn    { background: linear-gradient(135deg, var(--c-blue-mid), var(--c-pink)); color: white; font-weight: 600; }
.nb-search-btn:hover, .nb-add-btn:hover { opacity: 0.82; }

.nb-loading, .nb-empty { text-align: center; padding: 24px 0; color: var(--c-text-soft); font-size: 13px; }
.nb-entries { display: flex; flex-direction: column; gap: 8px; margin-bottom: 12px; }

.nb-entry-card { padding: 10px 12px; border: 1.5px solid var(--c-border); border-radius: 10px; background: var(--c-bg); }
.nb-entry-auto { border-color: var(--c-blue-light); background: linear-gradient(135deg, rgba(197,232,244,0.08), rgba(255,183,197,0.05)); }
.nb-entry-content { font-size: 13px; color: var(--c-text); line-height: 1.55; margin-bottom: 6px; }
.nb-entry-tags { display: flex; flex-wrap: wrap; gap: 4px; margin-bottom: 6px; }
.nb-tag { padding: 2px 8px; border-radius: 20px; background: var(--c-pink-light); color: var(--c-text-soft); font-size: 11px; }
.nb-entry-actions { display: flex; gap: 6px; justify-content: flex-end; }
.nb-edit-btn, .nb-del-btn {
    padding: 3px 10px; border: 1.5px solid var(--c-border); border-radius: 6px;
    font-size: 11px; font-family: inherit; cursor: pointer;
    background: transparent; color: var(--c-text-soft); transition: background 0.15s, color 0.15s;
}
.nb-edit-btn:hover { background: var(--c-blue-light); color: var(--c-text); border-color: var(--c-blue); }
.nb-del-btn:hover  { background: #FFE0E0; color: #C06060; border-color: #FFAAAA; }

.nb-pagination {
    display: flex; align-items: center; gap: 6px; justify-content: center;
    margin-top: 4px; margin-bottom: 8px; flex-wrap: wrap;
}
.nb-page-btn {
    padding: 4px 10px; border: 1.5px solid var(--c-border); border-radius: 6px;
    font-size: 12px; font-family: inherit; background: var(--c-surface);
    color: var(--c-text-soft); cursor: pointer; transition: background 0.15s;
}
.nb-page-btn:hover:not(:disabled) { background: var(--c-pink-light); }
.nb-page-btn:disabled { opacity: 0.35; cursor: not-allowed; }
.nb-page-info { font-size: 12px; color: var(--c-text-soft); padding: 0 4px; }
.nb-jump-input {
    width: 44px; height: 28px; border: 1.5px solid var(--c-border); border-radius: 6px;
    padding: 0 6px; font-size: 12px; font-family: inherit; color: var(--c-text);
    background: var(--c-bg); text-align: center; outline: none;
}
.nb-file-hint { font-size: 11px; color: var(--c-text-soft); text-align: center; margin-top: 8px; }
.nb-file-hint code { background: var(--c-pink-light); padding: 1px 5px; border-radius: 4px; font-size: 11px; }
</style>