<script setup lang="ts">
/**
 * AppearancePanel.vue — Live2D 装扮面板
 *
 * 位于独立窗口 AppearanceApp.vue 内，窗口打开即挂载。
 *
 * 通信链路：
 *   - schema + 已存配置 → GET /api/live2d/appearance-schema（后端）
 *   - 参数 min/max/default → Tauri 事件 request-core-params → 主窗口响应
 *   - 实时预览 → Tauri 事件 apply-appearance → 主窗口 applyAppearance
 *   - 持久化 → POST /api/live2d/appearance（后端，防抖 500ms）
 *   - 全部重置 → 恢复到模型加载时的初始值（非全部设 1）
 */

import { ref, onMounted, onUnmounted } from "vue";
import { emit as tauriEmit, listen } from "@tauri-apps/api/event";

const SIDECAR_URL = "http://localhost:18000";

// ── 数据类型 ────────────────────────────────────────────────────
interface SchemaParam { id: string; name: string; group_id: string; }
interface SchemaPart { id: string; name: string; }
interface CoreParam { id: string; min: number; max: number; default: number; current: number; }
interface CorePart { id: string; opacity: number; }

interface ParamRow {
    id: string;
    name: string;
    min: number;
    max: number;
    default: number;
    initial: number;   // 模型加载时的值（用于重置）
    value: number;
    step: number;
}

interface PartRow {
    id: string;
    name: string;
    initialOpacity: number;  // 模型加载时的值（用于重置）
    opacity: number;
}

// ── 状态 ─────────────────────────────────────────────────────────
const loading = ref(true);
const errorMsg = ref("");
const paramRows = ref<ParamRow[]>([]);
const partRows = ref<PartRow[]>([]);
const showResetDialog = ref(false);
const currentFolder = ref("");

let saveTimer: ReturnType<typeof setTimeout> | null = null;
const unlisteners: (() => void)[] = [];

// ── Toast ────────────────────────────────────────────────────────
const toastText = ref("");
const toastType = ref<"ok" | "warn">("ok");
function showToast(text: string, type: "ok" | "warn" = "ok") {
    toastText.value = text;
    toastType.value = type;
    setTimeout(() => { toastText.value = ""; }, 2500);
}

// ── 初始化 ────────────────────────────────────────────────────────
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let schemaCache: any = null;

onMounted(async () => {
    // 1. 确定当前模型 folder
    const modelPath = localStorage.getItem("rl-model-path") ?? "";
    const parts = modelPath.replace(/\\/g, "/").split("/");
    if (parts.length >= 3 && parts[0] === "live2d") {
        currentFolder.value = parts[1];
    } else if (parts.length >= 2) {
        currentFolder.value = parts[parts.length - 2];
    }

    if (!currentFolder.value) {
        errorMsg.value = "未检测到当前模型";
        loading.value = false;
        return;
    }

    // 2. 监听主窗口返回的 core params
    unlisteners.push(
        await listen<{ params: CoreParam[]; parts: CorePart[] }>(
            "core-params-response",
            (event) => { onCoreParamsReceived(event.payload.params, event.payload.parts); }
        )
    );

    // 3. 拉 schema
    try {
        const res = await fetch(
            `${SIDECAR_URL}/api/live2d/appearance-schema?folder=${encodeURIComponent(currentFolder.value)}`
        );
        if (!res.ok) {
            errorMsg.value = `后端返回 ${res.status}`;
            loading.value = false;
            return;
        }
        const schema = await res.json();
        schemaCache = schema;

        if (!schema.has_cdi && (!schema.parts || schema.parts.length === 0)) {
            errorMsg.value = "该模型未提供装扮参数（无 cdi3.json）";
            loading.value = false;
            return;
        }

        // 4. 向主窗口请求运行时参数范围
        await tauriEmit("request-core-params");
        console.info("[Appearance] 已请求 core params");

        // 超时兜底
        setTimeout(() => {
            if (loading.value) {
                console.warn("[Appearance] core-params-response 超时，使用 fallback");
                onCoreParamsReceived([], []);
            }
        }, 3000);

    } catch (e) {
        errorMsg.value = "无法连接后端";
        loading.value = false;
        console.warn("[Appearance] schema fetch 失败:", e);
    }
});

onUnmounted(() => {
    unlisteners.forEach(fn => fn());
    if (saveTimer) clearTimeout(saveTimer);
});

// ── core params 收到后合并渲染 ────────────────────────────────────
function onCoreParamsReceived(coreParams: CoreParam[], coreParts: CorePart[]) {
    if (!schemaCache) return;

    const paramMap = new Map<string, CoreParam>();
    for (const cp of coreParams) paramMap.set(cp.id, cp);

    const partMap = new Map<string, CorePart>();
    for (const cp of coreParts) partMap.set(cp.id, cp);

    const savedParams: Record<string, number> = schemaCache.appearance?.parameters ?? {};
    const savedParts: Record<string, number> = schemaCache.appearance?.parts ?? {};

    // 参数行
    const rows: ParamRow[] = [];
    for (const sp of (schemaCache.parameters as SchemaParam[])) {
        const core = paramMap.get(sp.id);
        const min = core?.min ?? 0;
        const max = core?.max ?? 1;
        const def = core?.default ?? 0;
        // initial = 模型加载时 core 里的实际值（包含 hiyori 专属归位等效果）
        const initial = core?.current ?? def;
        const value = sp.id in savedParams ? savedParams[sp.id] : initial;
        const range = max - min;
        const step = range > 0 ? Math.max(0.01, +(range / 100).toFixed(4)) : 0.01;
        rows.push({ id: sp.id, name: sp.name || sp.id, min, max, default: def, initial, value, step });
    }
    paramRows.value = rows;

    // Part 行
    const prows: PartRow[] = [];
    for (const sp of (schemaCache.parts as SchemaPart[])) {
        const core = partMap.get(sp.id);
        // initial = 模型加载时 core 里的实际 opacity（hiyori PartArmB 为 0）
        const initialOpacity = core ? (core.opacity >= 0.5 ? 1 : 0) : 1;
        const opacity = sp.id in savedParts ? savedParts[sp.id] : initialOpacity;
        prows.push({ id: sp.id, name: sp.name || sp.id, initialOpacity, opacity: opacity >= 0.5 ? 1 : 0 });
    }
    partRows.value = prows;

    loading.value = false;
    console.info(
        `[Appearance] 面板就绪: ${rows.length} 参数 + ${prows.length} 部件 ` +
        `(core 数据: ${coreParams.length > 0 ? "有" : "fallback"})`
    );
}

// ── 滑条变化 → 实时预览 + 防抖保存 ──────────────────────────────
function onParamInput(_row: ParamRow) {
    emitPreview();
    debounceSave();
}

function onPartToggle(row: PartRow) {
    row.opacity = row.opacity ? 0 : 1;
    emitPreview();
    debounceSave();
}

function emitPreview() {
    const parameters: Record<string, number> = {};
    for (const r of paramRows.value) parameters[r.id] = r.value;
    const parts: Record<string, number> = {};
    for (const r of partRows.value) parts[r.id] = r.opacity;
    tauriEmit("apply-appearance", { parameters, parts });
}

function debounceSave() {
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = setTimeout(() => saveToBackend(), 500);
}

async function saveToBackend() {
    const parameters: Record<string, number> = {};
    for (const r of paramRows.value) parameters[r.id] = r.value;
    const parts: Record<string, number> = {};
    for (const r of partRows.value) parts[r.id] = r.opacity;

    try {
        const res = await fetch(`${SIDECAR_URL}/api/live2d/appearance`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ folder: currentFolder.value, parameters, parts }),
        });
        if (res.ok) {
            console.info("[Appearance] 已保存 appearance.json");
        } else {
            console.warn("[Appearance] 保存失败:", res.status);
        }
    } catch (e) {
        console.warn("[Appearance] 保存请求失败:", e);
    }
}

// ── 全部重置 ─────────────────────────────────────────────────────
function requestReset() {
    showResetDialog.value = true;
}

async function confirmReset() {
    showResetDialog.value = false;

    // 恢复到模型加载时的初始值（不是全部设 1）
    for (const r of paramRows.value) {
        r.value = r.initial;
    }
    for (const r of partRows.value) {
        r.opacity = r.initialOpacity;
    }

    emitPreview();

    // 清空 appearance.json
    try {
        await fetch(`${SIDECAR_URL}/api/live2d/appearance`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ folder: currentFolder.value, parameters: {}, parts: {} }),
        });
    } catch (e) {
        console.warn("[Appearance] 重置保存失败:", e);
    }

    showToast("✓ 已重置为默认");
}
</script>

<template>
    <div class="appearance-panel">

        <!-- Toast -->
        <transition name="toast">
            <div v-if="toastText" class="toast" :class="{ warn: toastType === 'warn' }">
                {{ toastText }}
            </div>
        </transition>

        <!-- 加载中 -->
        <div v-if="loading" class="appearance-loading">
            <div class="loading-spinner"></div>
            <span>加载模型参数中…</span>
        </div>

        <!-- 错误 -->
        <div v-else-if="errorMsg" class="appearance-empty">{{ errorMsg }}</div>

        <!-- 正常面板 -->
        <template v-else>

            <!-- 顶部栏 -->
            <div class="appearance-header">
                <span class="appearance-count">
                    {{ paramRows.length }} 参数 · {{ partRows.length }} 部件
                </span>
                <button class="reset-btn" @click="requestReset">↺ 全部重置</button>
            </div>

            <!-- 参数区 -->
            <div v-if="paramRows.length > 0" class="param-section">
                <div v-for="row in paramRows" :key="row.id" class="param-row">
                    <div class="param-label">
                        <span class="param-name" :title="row.id">{{ row.name }}</span>
                        <span class="param-value">{{ row.value.toFixed(2) }}</span>
                    </div>
                    <input type="range" class="param-slider"
                           :min="row.min" :max="row.max" :step="row.step"
                           v-model.number="row.value"
                           @input="onParamInput(row)" />
                </div>
            </div>

            <!-- 分隔线 -->
            <div v-if="paramRows.length > 0 && partRows.length > 0" class="section-divider">
                <span class="section-divider-text">部件开关</span>
            </div>

            <!-- Part 区 -->
            <div v-if="partRows.length > 0" class="part-section">
                <div v-for="row in partRows" :key="row.id" class="part-row"
                     @click="onPartToggle(row)">
                    <span class="part-name" :title="row.id">{{ row.name }}</span>
                    <span class="part-toggle" :class="{ on: row.opacity === 1 }">
                        {{ row.opacity === 1 ? "显示" : "隐藏" }}
                    </span>
                </div>
            </div>

        </template>

        <!-- 重置确认弹窗 -->
        <transition name="dialog">
            <div v-if="showResetDialog" class="dialog-overlay" @click.self="showResetDialog = false">
                <div class="dialog-box">
                    <div class="dialog-title">确认重置</div>
                    <div class="dialog-body">
                        <p style="font-size:13px;color:#4A4A6A;">
                            确定要将所有装扮和外观参数重置为默认值吗？此操作不可撤销。
                        </p>
                    </div>
                    <div class="dialog-actions">
                        <button class="dialog-cancel" @click="showResetDialog = false">取消</button>
                        <button class="dialog-confirm" @click="confirmReset">确认重置</button>
                    </div>
                </div>
            </div>
        </transition>
    </div>
</template>

<style scoped>
    .appearance-panel {
        display: flex;
        flex-direction: column;
        gap: 12px;
        position: relative;
    }

    /* ── Toast ──────────────────────────────────────────────── */
    .toast {
        position: fixed; top: 16px; left: 50%; transform: translateX(-50%);
        padding: 8px 20px; border-radius: 20px;
        background: linear-gradient(white, white) padding-box,
                    linear-gradient(135deg, #A8D8EA, #FFB7C5) border-box;
        border: 2px solid transparent;
        color: #4A4A6A;
        font-size: 13px; font-weight: 600;
        box-shadow: 0 4px 20px rgba(80, 60, 120, 0.22);
        z-index: 200; pointer-events: none; white-space: nowrap;
    }
    .toast.warn {
        background: linear-gradient(white, white) padding-box,
                    linear-gradient(135deg, #F0A0A0, #E08080) border-box;
        color: #C05050;
    }
    .toast-enter-active { transition: opacity 0.25s ease, transform 0.25s ease; }
    .toast-leave-active { transition: opacity 0.2s ease; }
    .toast-enter-from { opacity: 0; transform: translateX(-50%) translateY(-10px); }
    .toast-leave-to { opacity: 0; }

    /* ── 加载 / 空 ─────────────────────────────────────────── */
    .appearance-loading {
        display: flex; align-items: center; gap: 10px;
        padding: 40px 0; justify-content: center;
        color: #9B8FB0; font-size: 14px;
    }
    .loading-spinner {
        width: 18px; height: 18px;
        border: 2px solid rgba(168,216,234,0.3);
        border-top-color: #A8D8EA;
        border-radius: 50%;
        animation: spin 0.8s linear infinite;
    }
    @keyframes spin { to { transform: rotate(360deg); } }

    .appearance-empty {
        padding: 40px 0; text-align: center;
        color: #9B8FB0; font-size: 14px;
    }

    /* ── 顶部栏 ────────────────────────────────────────────── */
    .appearance-header {
        display: flex; align-items: center;
        justify-content: space-between;
        padding: 0 4px;
    }
    .appearance-count {
        font-size: 13px; color: #9B8FB0;
    }
    .reset-btn {
        font-size: 12px; font-weight: 600; font-family: inherit;
        color: #FFAABB; background: #FFE4EC;
        border: 1.5px solid rgba(255,170,187,0.4);
        border-radius: 16px; padding: 5px 14px;
        cursor: pointer; transition: background 0.2s, color 0.2s;
    }
    .reset-btn:hover { background: #FFAABB; color: white; }

    /* ── 参数滑条 ───────────────────────────────────────────── */
    .param-section {
        display: flex; flex-direction: column; gap: 10px;
    }
    .param-row {
        display: flex; flex-direction: column; gap: 3px;
        padding: 0 4px;
    }
    .param-label {
        display: flex; align-items: center; justify-content: space-between;
    }
    .param-name {
        font-size: 12px; color: #4A4A6A;
        white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
        max-width: 320px;
    }
    .param-value {
        font-size: 12px; font-weight: 600; color: #9B8FB0;
        min-width: 48px; text-align: right; flex-shrink: 0;
    }
    .param-slider {
        width: 100%; accent-color: #7EC8E3;
        height: 6px; cursor: pointer;
    }

    /* ── 分隔线 ─────────────────────────────────────────────── */
    .section-divider {
        display: flex; align-items: center; gap: 10px;
        margin: 8px 0;
    }
    .section-divider::before,
    .section-divider::after {
        content: ""; flex: 1; height: 1px;
        background: rgba(212,184,224,0.45);
    }
    .section-divider-text {
        font-size: 12px; font-weight: 600; color: #9B8FB0;
        white-space: nowrap;
    }

    /* ── Part 开关 ──────────────────────────────────────────── */
    .part-section {
        display: flex; flex-direction: column; gap: 2px;
    }
    .part-row {
        display: flex; align-items: center; justify-content: space-between;
        padding: 8px 12px; border-radius: 10px;
        cursor: pointer; transition: background 0.15s;
    }
    .part-row:hover { background: rgba(168,216,234,0.1); }
    .part-name {
        font-size: 13px; color: #4A4A6A;
        white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
        max-width: 320px;
    }
    .part-toggle {
        font-size: 11px; font-weight: 600;
        padding: 3px 10px; border-radius: 12px;
        transition: all 0.2s;
        background: rgba(200,190,220,0.25); color: #9B8FB0;
    }
    .part-toggle.on {
        background: linear-gradient(135deg, #A8D8EA, #FFB7C5);
        color: white;
    }
</style>