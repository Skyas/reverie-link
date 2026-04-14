<script setup lang="ts">
// ── 记忆窗口面板 ───────────────────────────────────────────────
const MEMORY_WINDOW_OPTIONS = [
    { index: 0, label: "极速省流", desc: "3分钟 / 5轮",  token: "~2,000 tokens",  warn: false },
    { index: 1, label: "均衡（默认）", desc: "8分钟 / 12轮", token: "~5,000 tokens",  warn: false },
    { index: 2, label: "沉浸",      desc: "15分钟 / 20轮", token: "~8,000 tokens",  warn: false },
    { index: 3, label: "深度",      desc: "20分钟 / 28轮", token: "~11,000 tokens", warn: true  },
    { index: 4, label: "极限",      desc: "25分钟 / 35轮", token: "~14,000 tokens", warn: true  },
];

const memoryWindowIndex = defineModel<number>("memoryWindowIndex", { required: true });
const emit = defineEmits<{ "change": [index: number] }>();

// ── Toast ──────────────────────────────────────────────────────
import { ref } from "vue";
const msgText = ref("");
function showMsg(text: string) {
    msgText.value = text;
    setTimeout(() => { msgText.value = ""; }, 2500);
}

function applyMemoryWindow(index: number) {
    console.info(`[MemoryWindowPanel] 切换记忆窗口 | index=${index} label=${MEMORY_WINDOW_OPTIONS[index].label}`);
    memoryWindowIndex.value = index;
    emit("change", index);
    showMsg(`✓ 记忆跨度已切换至「${MEMORY_WINDOW_OPTIONS[index].label}」`);
}

defineExpose({ showMsg });
</script>

<template>
    <div class="memory-panel">
        <!-- Toast -->
        <transition name="toast">
            <div v-if="msgText" class="toast">{{ msgText }}</div>
        </transition>

        <div class="global-section">
            <div class="global-section-title">🧠 记忆设置</div>
            <div class="field-group">
                <label class="field-label">短期记忆跨度</label>
                <p class="field-hint" style="margin-bottom:10px;">
                    ⏳ 记忆跨度越长，聊天连贯性越好，但 API Token 消耗与回复延迟也会增加。
                </p>
                <div class="memory-window-options">
                    <div v-for="opt in MEMORY_WINDOW_OPTIONS" :key="opt.index"
                         class="memory-window-card" :class="{ active: memoryWindowIndex === opt.index }"
                         @click="applyMemoryWindow(opt.index)">
                        <div class="memory-window-label">{{ opt.label }}</div>
                        <div class="memory-window-desc">{{ opt.desc }}</div>
                        <div class="memory-window-token" :class="{ warn: opt.warn }">
                            {{ opt.token }}<span v-if="opt.warn" style="margin-left:4px;">⚠️</span>
                        </div>
                    </div>
                </div>
                <p v-if="MEMORY_WINDOW_OPTIONS[memoryWindowIndex].warn"
                   class="field-hint" style="margin-top:8px;color:#C08000;">
                    ⚠️ Token 消耗较高，建议搭配高性能模型使用。
                </p>
            </div>
        </div>
    </div>
</template>

<style scoped>
.memory-panel { display: flex; flex-direction: column; gap: 0; }

.toast {
    position: fixed; top: 16px; left: 50%; transform: translateX(-50%);
    padding: 8px 20px; border-radius: 20px;
    background: linear-gradient(135deg, var(--c-blue-mid), var(--c-pink));
    color: white; font-size: 13px; font-weight: 500;
    box-shadow: 0 4px 16px rgba(126,87,194,0.2);
    z-index: 200; pointer-events: none; white-space: nowrap;
}
.toast-enter-active { transition: opacity 0.25s ease, transform 0.25s ease; }
.toast-leave-active { transition: opacity 0.2s ease; }
.toast-enter-from { opacity: 0; transform: translateX(-50%) translateY(-10px); }
.toast-leave-to   { opacity: 0; }

.memory-window-options {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
}

.memory-window-card {
    flex: 1;
    min-width: calc(50% - 4px);
    padding: 8px 10px;
    border: 1.5px solid var(--c-border);
    border-radius: 10px;
    background: var(--c-surface);
    cursor: pointer;
    transition: border-color 0.2s, box-shadow 0.2s;
}
.memory-window-card:hover { border-color: var(--c-pink-mid); }
.memory-window-card.active {
    border-color: var(--c-blue);
    box-shadow: 0 0 0 3px var(--c-blue-light);
    background: linear-gradient(135deg, rgba(197,232,244,0.15), rgba(255,183,197,0.1));
}
.memory-window-label { font-size: 13px; font-weight: 600; color: var(--c-text); }
.memory-window-desc  { font-size: 11px; color: var(--c-text-soft); margin-top: 2px; }
.memory-window-token { font-size: 11px; color: var(--c-text); margin-top: 2px; }
.memory-window-token.warn { color: #C08000; font-weight: 500; }
</style>
