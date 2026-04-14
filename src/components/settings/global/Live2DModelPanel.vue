<script setup lang="ts">
import { ref } from "vue";

// ── Props / Emits ──────────────────────────────────────────────
interface Live2DModelInfo { folder: string; display_name: string; path: string; }

const props = defineProps<{
    models: Live2DModelInfo[];
    loading: boolean;
    selectedPath: string;
    zoom: number;
    y: number;
}>();

const emit = defineEmits<{
    "fetch": [];
    "apply": [path: string];
    "apply-settings": [];
    "update:zoom": [v: number];
    "update:y": [v: number];
}>();

// Local copies we can write to
const localZoom = ref(props.zoom);
const localY = ref(props.y);

// ── Toast（透传） ──────────────────────────────────────────────
const msgText = ref("");
const msgType = ref<"ok" | "warn">("ok");
function showMsg(text: string, type: "ok" | "warn" = "ok") {
    msgText.value = text; msgType.value = type;
    setTimeout(() => { msgText.value = ""; }, 2500);
}

defineExpose({ showMsg });
</script>

<template>
    <div class="live2d-panel">
        <!-- Toast -->
        <transition name="toast">
            <div v-if="msgText" class="toast" :class="{ warn: msgType === 'warn' }">{{ msgText }}</div>
        </transition>

        <div class="global-section">
            <div class="global-section-title">
                🎭 Live2D 模型
                <span class="field-note">将模型文件夹放入 public/live2d/ 即可识别</span>
            </div>

            <div v-if="loading" class="models-loading">扫描中…</div>
            <div v-else-if="models.length === 0" class="models-empty">
                <p>未找到模型</p>
                <p class="field-note">请将 Live2D 模型文件夹放入项目的 <code>public/live2d/</code> 目录</p>
                <button class="refresh-btn" @click="emit('fetch')">重新扫描</button>
            </div>
            <div v-else class="models-list">
                <div v-for="m in models" :key="m.path"
                     class="model-card" :class="{ active: selectedPath === m.path }"
                     @click="emit('apply', m.path)">
                    <div class="model-icon">🪆</div>
                    <div class="model-info">
                        <div class="model-name">{{ m.display_name }}</div>
                        <div class="model-path">{{ m.path }}</div>
                    </div>
                    <div v-if="selectedPath === m.path" class="model-active-badge">使用中</div>
                </div>
                <button class="refresh-btn" @click="emit('fetch')">🔄 重新扫描</button>
            </div>

            <!-- 模型显示调整 -->
            <div class="model-display-settings">
                <div class="global-section-title" style="font-size:12px;">📐 当前模型显示调整</div>
                <div class="field-row">
                    <div class="field-group half">
                        <label class="field-label">缩放 Zoom <span class="field-note">默认 1.7</span></label>
                        <div class="zoom-input-row">
                            <input type="range" class="field-range" :min="0.5" :max="3.0" :step="0.05"
                                   :value="localZoom"
                                   @input="localZoom = +($event.target as HTMLInputElement).value; emit('update:zoom', localZoom)" />
                            <span class="zoom-value">{{ localZoom.toFixed(2) }}</span>
                        </div>
                    </div>
                    <div class="field-group half">
                        <label class="field-label">垂直偏移 Y <span class="field-note">默认 -80</span></label>
                        <div class="zoom-input-row">
                            <input type="range" class="field-range" :min="-400" :max="200" :step="5"
                                   :value="localY"
                                   @input="localY = +($event.target as HTMLInputElement).value; emit('update:y', localY)" />
                            <span class="zoom-value">{{ localY }}</span>
                        </div>
                    </div>
                </div>
                <div class="action-row" style="padding-top:4px;">
                    <button class="save-btn" style="padding:6px 18px;font-size:12px;"
                            @click="emit('apply-settings')">应用</button>
                </div>
            </div>
        </div>
    </div>
</template>

<style scoped>
.live2d-panel { display: flex; flex-direction: column; gap: 0; }

.toast {
    position: fixed; top: 16px; left: 50%; transform: translateX(-50%);
    padding: 8px 20px; border-radius: 20px;
    background: linear-gradient(135deg, var(--c-blue-mid), var(--c-pink));
    color: white; font-size: 13px; font-weight: 500;
    box-shadow: 0 4px 16px rgba(126,87,194,0.2);
    z-index: 200; pointer-events: none; white-space: nowrap;
}
.toast.warn { background: linear-gradient(135deg, #F0A0A0, #E08080); }
.toast-enter-active { transition: opacity 0.25s ease, transform 0.25s ease; }
.toast-leave-active { transition: opacity 0.2s ease; }
.toast-enter-from { opacity: 0; transform: translateX(-50%) translateY(-10px); }
.toast-leave-to   { opacity: 0; }

.models-loading { color: var(--c-text-soft); font-size: 13px; padding: 8px 0; }
.models-empty { display: flex; flex-direction: column; gap: 6px; padding: 8px 0; }
.models-empty p { font-size: 13px; color: var(--c-text-soft); }
.models-empty code, .models-empty p code {
    font-size: 12px;
    background: var(--c-pink-light);
    padding: 1px 6px;
    border-radius: 4px;
}

.models-list { display: flex; flex-direction: column; gap: 8px; }

.model-card {
    display: flex; align-items: center; gap: 10px;
    background: var(--c-surface);
    border: 1.5px solid var(--c-border);
    border-radius: 12px;
    padding: 10px 12px;
    cursor: pointer;
    transition: border-color 0.2s, box-shadow 0.2s;
}
.model-card:hover { border-color: var(--c-pink-mid); }
.model-card.active { border-color: var(--c-blue); box-shadow: 0 0 0 3px var(--c-blue-light); }
.model-icon { font-size: 22px; flex-shrink: 0; }
.model-info { flex: 1; min-width: 0; }
.model-name { font-size: 13px; font-weight: 600; color: var(--c-text); }
.model-path { font-size: 11px; color: var(--c-text-soft); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.model-active-badge {
    font-size: 10px; font-weight: 600; color: white;
    background: var(--c-blue); padding: 2px 8px;
    border-radius: 10px; flex-shrink: 0;
}

.refresh-btn {
    align-self: flex-start; margin-top: 4px;
    font-size: 12px; padding: 4px 14px;
    border: 1.5px solid var(--c-blue); border-radius: 20px;
    background: transparent; color: var(--c-blue);
    cursor: pointer; font-family: inherit;
    transition: background 0.2s, color 0.2s;
}
.refresh-btn:hover { background: var(--c-blue); color: white; }

.model-display-settings {
    display: flex; flex-direction: column; gap: 8px;
    padding: 10px 12px;
    background: var(--c-surface);
    border: 1.5px solid var(--c-border);
    border-radius: 12px;
}

.zoom-input-row { display: flex; align-items: center; gap: 8px; }
.zoom-value { font-size: 12px; color: var(--c-text-soft); min-width: 36px; text-align: right; }
</style>
