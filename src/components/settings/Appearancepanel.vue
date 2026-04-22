<script setup lang="ts">
/**
 * AppearancePanel.vue — Live2D 装扮面板
 *
 * 位于设置窗口的 Live2D Tab 内，用户展开"装扮"区后才加载。
 *
 * 通信链路：
 *   - schema + 已存配置 → 直接 GET /api/live2d/appearance-schema（后端）
 *   - 参数 min/max/default → Tauri 事件 request-core-params → 主窗口响应
 *   - 实时预览 → Tauri 事件 apply-appearance → 主窗口 applyAppearance
 *   - 持久化 → 直接 POST /api/live2d/appearance（后端，防抖 500ms）
 *   - 全部重置 → Tauri 事件 reset-appearance → 主窗口 applyAppearance(空)
 *                + POST 空配置到后端
 */

import { ref, onMounted, onUnmounted, nextTick } from "vue";
import { emit as tauriEmit, listen } from "@tauri-apps/api/event";

const SIDECAR_URL = "http://localhost:18000";

// ── 数据类型 ────────────────────────────────────────────────────
interface SchemaParam {
    id: string;
    name: string;
    group_id: string;
}

interface SchemaPart {
    id: string;
    name: string;
}

interface CoreParam {
    id: string;
    min: number;
    max: number;
    default: number;
    current: number;
}

interface CorePart {
    id: string;
    opacity: number;
}

// 合并后用于渲染的参数行
interface ParamRow {
    id: string;
    name: string;       // cdi3 的 Name
    min: number;
    max: number;
    default: number;
    value: number;       // 当前滑条值
    step: number;        // 步进
}

// 合并后用于渲染的 Part 行
interface PartRow {
    id: string;
    name: string;        // cdi3 的 Name
    opacity: number;     // 当前值 0 或 1
}

// ── 状态 ─────────────────────────────────────────────────────────
const loading = ref(true);
const errorMsg = ref("");
const hasCdi = ref(false);

const paramRows = ref<ParamRow[]>([]);
const partRows = ref<PartRow[]>([]);

// 全部重置确认弹窗
const showResetDialog = ref(false);

// 当前模型的 folder
const currentFolder = ref("");

// 防抖 timer
let saveTimer: ReturnType<typeof setTimeout> | null = null;

// Tauri 事件清理
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
            (event) => {
                onCoreParamsReceived(event.payload.params, event.payload.parts);
            }
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
        hasCdi.value = schema.has_cdi;

        if (!schema.has_cdi || schema.parameters.length === 0) {
            // 无 cdi3.json 或无参数，仍可能有 parts
            if (schema.parts.length === 0) {
                errorMsg.value = "该模型未提供装扮参数（无 cdi3.json）";
                loading.value = false;
                return;
            }
        }

        // 暂存 schema 数据，等 core params 返回后合并
        schemaCache = schema;

        // 4. 向主窗口请求运行时参数范围
        await tauriEmit("request-core-params");
        console.info("[Appearance] 已请求 core params");

        // 超时兜底：3 秒没收到 core-params-response 就用 fallback
        setTimeout(() => {
            if (loading.value) {
                console.warn("[Appearance] core-params-response 超时，使用 fallback 范围");
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

// ── schema 缓存 ──────────────────────────────────────────────────
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let schemaCache: any = null;

// ── core params 收到后合并渲染 ────────────────────────────────────
function onCoreParamsReceived(coreParams: CoreParam[], coreParts: CorePart[]) {
    if (!schemaCache) return;

    // 构建 id → core 数据的 map
    const paramMap = new Map<string, CoreParam>();
    for (const cp of coreParams) paramMap.set(cp.id, cp);

    const partMap = new Map<string, CorePart>();
    for (const cp of coreParts) partMap.set(cp.id, cp);

    // 已存的 appearance
    const savedParams: Record<string, number> = schemaCache.appearance?.parameters ?? {};
    const savedParts: Record<string, number> = schemaCache.appearance?.parts ?? {};

    // 合并参数行
    const rows: ParamRow[] = [];
    for (const sp of (schemaCache.parameters as SchemaParam[])) {
        const core = paramMap.get(sp.id);
        const min = core?.min ?? 0;
        const max = core?.max ?? 1;
        const def = core?.default ?? 0;
        const current = sp.id in savedParams ? savedParams[sp.id] : (core?.current ?? def);
        // step: 范围 / 100，至少 0.01
        const range = max - min;
        const step = range > 0 ? Math.max(0.01, +(range / 100).toFixed(4)) : 0.01;
        rows.push({ id: sp.id, name: sp.name || sp.id, min, max, default: def, value: current, step });
    }
    paramRows.value = rows;

    // 合并 Part 行
    const prows: PartRow[] = [];
    for (const sp of (schemaCache.parts as SchemaPart[])) {
        const core = partMap.get(sp.id);
        const opacity = sp.id in savedParts ? savedParts[sp.id] : (core?.opacity ?? 1);
        prows.push({ id: sp.id, name: sp.name || sp.id, opacity: opacity >= 0.5 ? 1 : 0 });
    }
    partRows.value = prows;

    loading.value = false;
    console.info(
        `[Appearance] 面板就绪: ${rows.length} 参数 + ${prows.length} 部件 ` +
        `(core 数据: ${coreParams.length > 0 ? "有" : "fallback"})`
    );
}

// ── 滑条变化 → 实时预览 + 防抖保存 ──────────────────────────────
function onParamChange(row: ParamRow) {
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
            body: JSON.stringify({
                folder: currentFolder.value,
                parameters,
                parts,
            }),
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

    // 把每个参数值恢复到 default
    for (const r of paramRows.value) {
        r.value = r.default;
    }
    // Part 恢复到 1（全部显示）
    for (const r of partRows.value) {
        r.opacity = 1;
    }

    // 推送预览
    emitPreview();

    // 保存空配置到后端（清掉 appearance.json 里的自定义值）
    try {
        await fetch(`${SIDECAR_URL}/api/live2d/appearance`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                folder: currentFolder.value,
                parameters: {},
                parts: {},
            }),
        });
    } catch (e) {
        console.warn("[Appearance] 重置保存失败:", e);
    }

    showToast("✓ 已重置为默认");
}
</script>

<template>
    <div class="appearance-root">

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
        <div v-else-if="errorMsg" class="appearance-empty">
            {{ errorMsg }}
        </div>

        <!-- 正常面板 -->
        <template v-else>

            <!-- 顶部栏：标题 + 重置按钮 -->
            <div class="appearance-header">
                <div class="appearance-title">
                    <span class="appearance-count">
                        {{ paramRows.length }} 参数 · {{ partRows.length }} 部件
                    </span>
                </div>
                <button class="reset-btn" @click="requestReset">↺ 全部重置</button>
            </div>

            <!-- 滚动区域 -->
            <div class="appearance-scroll">

                <!-- 参数滑条 -->
                <div v-if="paramRows.length > 0" class="param-section">
                    <div v-for="row in paramRows" :key="row.id" class="param-row">
                        <div class="param-label">
                            <span class="param-name" :title="row.id">{{ row.name }}</span>
                            <span class="param-value">{{ row.value.toFixed(2) }}</span>
                        </div>
                        <input type="range" class="param-slider"
                               :min="row.min" :max="row.max" :step="row.step"
                               v-model.number="row.value"
                               @input="onParamChange(row)" />
                    </div>
                </div>

                <!-- 分隔线 -->
                <div v-if="paramRows.length > 0 && partRows.length > 0" class="section-divider">
                    <span class="section-divider-text">部件开关</span>
                </div>

                <!-- Part 开关 -->
                <div v-if="partRows.length > 0" class="part-section">
                    <div v-for="row in partRows" :key="row.id" class="part-row"
                         @click="onPartToggle(row)">
                        <span class="part-name" :title="row.id">{{ row.name }}</span>
                        <span class="part-toggle" :class="{ on: row.opacity === 1 }">
                            {{ row.opacity === 1 ? "显示" : "隐藏" }}
                        </span>
                    </div>
                </div>

            </div>
        </template>

        <!-- 重置确认弹窗（复用全局样式） -->
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
    .appearance-root {
        display: flex;
        flex-direction: column;
        gap: 0;
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
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 20px 0;
        color: #9B8FB0;
        font-size: 13px;
    }
    .loading-spinner {
        width: 16px; height: 16px;
        border: 2px solid rgba(168,216,234,0.3);
        border-top-color: #A8D8EA;
        border-radius: 50%;
        animation: spin 0.8s linear infinite;
    }
    @keyframes spin { to { transform: rotate(360deg); } }

    .appearance-empty {
        padding: 20px 0;
        color: #9B8FB0;
        font-size: 13px;
    }

    /* ── 顶部栏 ────────────────────────────────────────────── */
    .appearance-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding-bottom: 8px;
    }
    .appearance-title {
        display: flex;
        align-items: center;
        gap: 8px;
    }
    .appearance-count {
        font-size: 12px;
        color: #9B8FB0;
    }
    .reset-btn {
        font-size: 11px;
        font-weight: 600;
        font-family: inherit;
        color: #FFAABB;
        background: #FFE4EC;
        border: 1.5px solid rgba(255,170,187,0.4);
        border-radius: 14px;
        padding: 4px 12px;
        cursor: pointer;
        transition: background 0.2s, color 0.2s;
    }
    .reset-btn:hover {
        background: #FFAABB;
        color: white;
    }

    /* ── 滚动区 ────────────────────────────────────────────── */
    .appearance-scroll {
        max-height: 420px;
        overflow-y: auto;
        padding-right: 2px;
    }

    /* ── 参数滑条 ───────────────────────────────────────────── */
    .param-section {
        display: flex;
        flex-direction: column;
        gap: 6px;
    }
    .param-row {
        display: flex;
        flex-direction: column;
        gap: 2px;
    }
    .param-label {
        display: flex;
        align-items: center;
        justify-content: space-between;
    }
    .param-name {
        font-size: 11px;
        color: #4A4A6A;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        max-width: 200px;
    }
    .param-value {
        font-size: 11px;
        font-weight: 600;
        color: #9B8FB0;
        min-width: 42px;
        text-align: right;
        flex-shrink: 0;
    }
    .param-slider {
        width: 100%;
        accent-color: #7EC8E3;
        height: 4px;
        cursor: pointer;
    }

    /* ── 分隔线 ─────────────────────────────────────────────── */
    .section-divider {
        display: flex;
        align-items: center;
        gap: 8px;
        margin: 14px 0 10px;
    }
    .section-divider::before,
    .section-divider::after {
        content: "";
        flex: 1;
        height: 1px;
        background: rgba(212,184,224,0.45);
    }
    .section-divider-text {
        font-size: 11px;
        font-weight: 600;
        color: #9B8FB0;
        white-space: nowrap;
    }

    /* ── Part 开关 ──────────────────────────────────────────── */
    .part-section {
        display: flex;
        flex-direction: column;
        gap: 4px;
    }
    .part-row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 6px 10px;
        border-radius: 8px;
        cursor: pointer;
        transition: background 0.15s;
    }
    .part-row:hover {
        background: rgba(168,216,234,0.1);
    }
    .part-name {
        font-size: 12px;
        color: #4A4A6A;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        max-width: 200px;
    }
    .part-toggle {
        font-size: 10px;
        font-weight: 600;
        padding: 2px 8px;
        border-radius: 10px;
        transition: all 0.2s;
        background: rgba(200,190,220,0.25);
        color: #9B8FB0;
    }
    .part-toggle.on {
        background: linear-gradient(135deg, #A8D8EA, #FFB7C5);
        color: white;
    }
</style>