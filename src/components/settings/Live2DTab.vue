<script setup lang="ts">
    import { ref, onMounted } from "vue";
    import { revealItemInDir } from "@tauri-apps/plugin-opener";

    // ── Toast ──────────────────────────────────────────────────────
    const msgText = ref("");
    const msgType = ref<"ok" | "warn">("ok");
    function showMsg(text: string, type: "ok" | "warn" = "ok") {
        msgText.value = text; msgType.value = type;
        setTimeout(() => { msgText.value = ""; }, 2500);
    }

    // ── Live2D 模型（原 GlobalTab.vue 迁入） ───────────────────────
    interface Live2DModelInfo { folder: string; display_name: string; path: string; }

    const live2dModels = ref<Live2DModelInfo[]>([]);
    const modelsLoading = ref(false);
    const selectedModelPath = ref<string>(
        localStorage.getItem("rl-model-path") ?? "live2d/MO/MO.model3.json"
    );
    const MODEL_SETTINGS_KEY = "rl-model-settings";
    const modelZoom = ref<number>(1.7);
    const modelY = ref<number>(-80);

    function loadModelDisplaySettings(path: string) {
        try {
            const all = JSON.parse(localStorage.getItem(MODEL_SETTINGS_KEY) ?? "{}");
            const s = all[path];
            if (s && typeof s.zoom === "number" && typeof s.y === "number") {
                modelZoom.value = s.zoom; modelY.value = s.y; return;
            }
        } catch { /* ignore */ }
        modelZoom.value = 1.7; modelY.value = -80;
    }

    function saveModelDisplaySettings() {
        const path = selectedModelPath.value;
        try {
            const all = JSON.parse(localStorage.getItem(MODEL_SETTINGS_KEY) ?? "{}");
            all[path] = { zoom: modelZoom.value, y: modelY.value };
            localStorage.setItem(MODEL_SETTINGS_KEY, JSON.stringify(all));
        } catch { /* ignore */ }
    }

    async function fetchLive2DModels() {
        modelsLoading.value = true;
        try {
            const res = await fetch("http://localhost:18000/api/live2d/models");
            const data = await res.json();
            live2dModels.value = data.models ?? [];
            console.info(`[Live2DTab] 已获取 ${live2dModels.value.length} 个模型`);
        } catch {
            live2dModels.value = [];
            showMsg("无法连接后端，请确认 Python 服务已启动", "warn");
        } finally { modelsLoading.value = false; }
    }

    async function applyModel(path: string) {
        selectedModelPath.value = path;
        localStorage.setItem("rl-model-path", path);
        loadModelDisplaySettings(path);
        try {
            const { emit: tauriEmit } = await import("@tauri-apps/api/event");
            await tauriEmit("model-changed", { path });
            console.info(`[Live2DTab] 已切换模型: ${path}`);
        } catch (e) { console.warn("[Live2DTab] model-changed emit failed:", e); }
        showMsg("✓ 模型已切换");
    }

    async function applyModelSettings() {
        saveModelDisplaySettings();
        try {
            const { emit: tauriEmit } = await import("@tauri-apps/api/event");
            await tauriEmit("model-changed", { path: selectedModelPath.value });
        } catch (e) { console.warn("[Live2DTab] model settings emit failed:", e); }
        showMsg("✓ 显示设置已应用");
    }

    async function openLive2DFolder() {
        try {
            const res = await fetch("http://localhost:18000/api/folder-paths");
            const { live2d } = await res.json();
            await revealItemInDir(live2d);
            console.info("[Live2DTab] 已打开 Live2D 文件夹:", live2d);
        } catch (e) {
            console.warn("[Live2DTab] 打开文件夹失败:", e);
            showMsg("无法打开文件夹", "warn");
        }
    }

    // ── 待机动画（新增） ──────────────────────────────────────────
    const IDLE_MOTION_KEY = "rl-idle-motion";
    const idleEnabled = ref<boolean>(false);
    const idleMinInterval = ref<number>(30);
    const idleMaxInterval = ref<number>(60);

    function loadIdleMotion() {
        try {
            const raw = localStorage.getItem(IDLE_MOTION_KEY);
            if (!raw) return;
            const cfg = JSON.parse(raw);
            if (typeof cfg.enabled === "boolean") idleEnabled.value = cfg.enabled;
            if (typeof cfg.minInterval === "number") idleMinInterval.value = cfg.minInterval;
            if (typeof cfg.maxInterval === "number") idleMaxInterval.value = cfg.maxInterval;
        } catch { /* ignore */ }
    }

    async function saveIdleMotion() {
        // 校验：max 不能小于 min（UI 层自动夹取，不给用户报错）
        if (idleMaxInterval.value < idleMinInterval.value) {
            idleMaxInterval.value = idleMinInterval.value;
        }
        const cfg = {
            enabled: idleEnabled.value,
            minInterval: idleMinInterval.value,
            maxInterval: idleMaxInterval.value,
        };
        localStorage.setItem(IDLE_MOTION_KEY, JSON.stringify(cfg));
        try {
            const { emit: tauriEmit } = await import("@tauri-apps/api/event");
            await tauriEmit("idle-motion-changed", cfg);
            console.info("[Live2DTab] 待机动画配置已推送:", cfg);
        } catch (e) {
            console.warn("[Live2DTab] idle-motion-changed emit failed:", e);
        }
        showMsg(idleEnabled.value ? "✓ 待机动画已开启" : "✓ 待机动画已关闭");
    }

    // 滑条拖动中只改本地 ref，松手（@change）才保存。
    // 开关变化（@change）立即保存。
    function onIdleConfigChange() {
        saveIdleMotion();
    }

    // ── 初始化 ─────────────────────────────────────────────────────
    onMounted(async () => {
        loadModelDisplaySettings(selectedModelPath.value);
        loadIdleMotion();
        await fetchLive2DModels();
    });
</script>

<template>
    <div class="tab-content">

        <!-- Toast -->
        <transition name="toast">
            <div v-if="msgText" class="toast" :class="{ warn: msgType === 'warn' }">{{ msgText }}</div>
        </transition>

        <!-- Live2D 模型 -->
        <div class="global-section">
            <div class="global-section-title">
                🎭 Live2D 模型
                <span class="field-note">将模型文件夹放入 public/live2d/ 即可识别</span>
            </div>

            <div v-if="modelsLoading" class="models-loading">扫描中…</div>
            <div v-else-if="live2dModels.length === 0" class="models-empty">
                <p>未找到模型</p>
                <p class="field-note">请将 Live2D 模型文件夹放入项目的 <code>public/live2d/</code> 目录</p>
                <button class="refresh-btn" @click="fetchLive2DModels">重新扫描</button>
            </div>
            <div v-else class="models-list">
                <div v-for="m in live2dModels" :key="m.path"
                     class="model-card" :class="{ active: selectedModelPath === m.path }"
                     @click="applyModel(m.path)">
                    <div class="model-icon">🪆</div>
                    <div class="model-info">
                        <div class="model-name">{{ m.display_name }}</div>
                        <div class="model-path">{{ m.path }}</div>
                    </div>
                    <div v-if="selectedModelPath === m.path" class="model-active-badge">使用中</div>
                </div>
                <div style="display:flex; gap:8px;">
                    <button class="refresh-btn" @click="fetchLive2DModels">🔄 重新扫描</button>
                    <button class="refresh-btn" @click="openLive2DFolder">📂 打开文件夹</button>
                </div>
            </div>

            <!-- 模型显示调整 -->
            <div class="model-display-settings">
                <div class="global-section-title" style="font-size:12px;">📐 当前模型显示调整</div>
                <div class="field-row">
                    <div class="field-group half">
                        <label class="field-label">缩放 Zoom <span class="field-note">默认 1.7</span></label>
                        <div class="zoom-input-row">
                            <input type="range" class="field-range" :min="0.5" :max="3.0" :step="0.05"
                                   v-model.number="modelZoom" />
                            <span class="zoom-value">{{ modelZoom.toFixed(2) }}</span>
                        </div>
                    </div>
                    <div class="field-group half">
                        <label class="field-label">垂直偏移 Y <span class="field-note">默认 -80</span></label>
                        <div class="zoom-input-row">
                            <input type="range" class="field-range" :min="-400" :max="200" :step="5"
                                   v-model.number="modelY" />
                            <span class="zoom-value">{{ modelY }}</span>
                        </div>
                    </div>
                </div>
                <div class="action-row" style="padding-top:4px;">
                    <button class="save-btn" style="padding:6px 18px;font-size:12px;" @click="applyModelSettings">应用</button>
                </div>
            </div>
        </div>

        <div class="divider"></div>

        <!-- 待机动画 -->
        <div class="global-section">
            <div class="global-section-title">🎬 待机动画</div>

            <div class="idle-motion-panel">
                <!-- 开关 -->
                <div class="toggle-row">
                    <div class="toggle-label">
                        <div class="toggle-title">启用待机动画</div>
                        <div class="toggle-desc">静止时在区间内随机触发一个非 Idle 动作</div>
                    </div>
                    <label class="toggle-switch">
                        <input type="checkbox" v-model="idleEnabled" @change="onIdleConfigChange" />
                        <span class="toggle-slider"></span>
                    </label>
                </div>

                <!-- 间隔 -->
                <div class="field-row" :class="{ 'field-disabled': !idleEnabled }">
                    <div class="field-group half">
                        <label class="field-label">
                            最小间隔 <span class="field-note">{{ idleMinInterval }} 秒</span>
                        </label>
                        <div class="zoom-input-row">
                            <input type="range" class="field-range"
                                   :min="10" :max="120" :step="5"
                                   v-model.number="idleMinInterval"
                                   @change="onIdleConfigChange"
                                   :disabled="!idleEnabled" />
                        </div>
                    </div>
                    <div class="field-group half">
                        <label class="field-label">
                            最大间隔 <span class="field-note">{{ idleMaxInterval }} 秒</span>
                        </label>
                        <div class="zoom-input-row">
                            <input type="range" class="field-range"
                                   :min="20" :max="180" :step="5"
                                   v-model.number="idleMaxInterval"
                                   @change="onIdleConfigChange"
                                   :disabled="!idleEnabled" />
                        </div>
                    </div>
                </div>

                <div class="field-hint">
                    模型未提供非 Idle 动作时（如 MO），此设置无效果。
                    发言触发的动作优先级高于待机，会打断当前待机动作并重置计时。
                </div>
            </div>
        </div>

        <div class="divider"></div>

        <!-- 装扮（Stage 2 占位） -->
        <div class="global-section global-section-disabled">
            <div class="global-section-title">🎨 装扮 <span class="coming-badge">开发中</span></div>
            <div class="field-hint">
                读取模型 cdi3.json，为每个参数渲染滑条，支持配件开关。
                实时预览并保存至 public/live2d/&#123;模型文件夹&#125;/appearance.json。
            </div>
        </div>

    </div>
</template>

<style scoped>
    /* ── 与 GlobalTab 相同的颜色变量 ──────────────────────────────── */
    .tab-content {
        --c-bg: #FEF6FA;
        --c-surface: #FFFFFF;
        --c-blue: #7EC8E3;
        --c-blue-light: #C5E8F4;
        --c-blue-mid: #A8D8EA;
        --c-pink: #FFB7C5;
        --c-pink-light: #FFE4EC;
        --c-pink-mid: #FFAABB;
        --c-mint: #B5EAD7;
        --c-lavender: #D4B8E0;
        --c-text: #4A4A6A;
        --c-text-soft: #9B8FB0;
        --c-border: rgba(212,184,224,0.45);
        position: relative;
    }

    /* ── Toast（与 GlobalTab 风格一致）──────────────────────────── */
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

    .toast-enter-active {
        transition: opacity 0.25s ease, transform 0.25s ease;
    }

    .toast-leave-active {
        transition: opacity 0.2s ease;
    }

    .toast-enter-from {
        opacity: 0;
        transform: translateX(-50%) translateY(-10px);
    }

    .toast-leave-to {
        opacity: 0;
    }

    /* ── 分隔线 ───────────────────────────────────────────────────── */
    .divider {
        height: 1px;
        background: rgba(212,184,224,0.45);
        margin: 2px 0;
    }

    /* ── 通用保存按钮 ──────────────────────────────────────────── */
    .save-btn {
        border: none;
        border-radius: 20px;
        background: linear-gradient(135deg, #A8D8EA, #FFB7C5);
        color: white;
        font-size: 13px;
        font-weight: 600;
        font-family: inherit;
        cursor: pointer;
        padding: 8px 22px;
        transition: opacity 0.2s;
    }

        .save-btn:hover {
            opacity: 0.88;
        }

    /* ── Live2D 模型 ──────────────────────────────────────────────── */
    .models-loading {
        color: var(--c-text-soft);
        font-size: 13px;
        padding: 8px 0;
    }

    .models-empty {
        display: flex;
        flex-direction: column;
        gap: 6px;
        padding: 8px 0;
    }

        .models-empty p {
            font-size: 13px;
            color: var(--c-text-soft);
        }

            .models-empty code, .models-empty p code {
                font-size: 12px;
                background: var(--c-pink-light);
                padding: 1px 6px;
                border-radius: 4px;
            }

    .models-list {
        display: flex;
        flex-direction: column;
        gap: 8px;
    }

    .model-card {
        display: flex;
        align-items: center;
        gap: 10px;
        background: var(--c-surface);
        border: 1.5px solid var(--c-border);
        border-radius: 12px;
        padding: 10px 12px;
        cursor: pointer;
        transition: border-color 0.2s, box-shadow 0.2s;
    }

        .model-card:hover {
            border-color: var(--c-pink-mid);
        }

        .model-card.active {
            border-color: var(--c-blue);
            box-shadow: 0 0 0 3px var(--c-blue-light);
        }

    .model-icon {
        font-size: 22px;
        flex-shrink: 0;
    }

    .model-info {
        flex: 1;
        min-width: 0;
    }

    .model-name {
        font-size: 13px;
        font-weight: 600;
        color: var(--c-text);
    }

    .model-path {
        font-size: 11px;
        color: var(--c-text-soft);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }

    .model-active-badge {
        font-size: 10px;
        font-weight: 600;
        color: white;
        background: var(--c-blue);
        padding: 2px 8px;
        border-radius: 10px;
        flex-shrink: 0;
    }

    .refresh-btn {
        align-self: flex-start;
        margin-top: 4px;
        font-size: 12px;
        padding: 4px 14px;
        border: 1.5px solid var(--c-blue);
        border-radius: 20px;
        background: transparent;
        color: var(--c-blue);
        cursor: pointer;
        font-family: inherit;
        transition: background 0.2s, color 0.2s;
    }

        .refresh-btn:hover {
            background: var(--c-blue);
            color: white;
        }

    /* ── 模型显示设置 ────────────────────────────────────────────── */
    .model-display-settings {
        display: flex;
        flex-direction: column;
        gap: 8px;
        padding: 10px 12px;
        background: var(--c-surface);
        border: 1.5px solid var(--c-border);
        border-radius: 12px;
        margin-top: 4px;
    }

    .zoom-input-row {
        display: flex;
        align-items: center;
        gap: 8px;
    }

        .zoom-input-row .field-range {
            flex: 1;
        }

    .zoom-value {
        font-size: 12px;
        font-weight: 600;
        color: var(--c-text);
        min-width: 38px;
        text-align: right;
        flex-shrink: 0;
    }

    /* ── 待机动画面板 ────────────────────────────────────────────── */
    .idle-motion-panel {
        display: flex;
        flex-direction: column;
        gap: 12px;
        padding: 12px 14px;
        background: var(--c-surface);
        border: 1.5px solid var(--c-border);
        border-radius: 12px;
    }

    .toggle-row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
    }

    .toggle-label {
        flex: 1;
        min-width: 0;
    }

    .toggle-title {
        font-size: 13px;
        font-weight: 600;
        color: var(--c-text);
    }

    .toggle-desc {
        font-size: 11px;
        color: var(--c-text-soft);
        margin-top: 2px;
    }

    .field-disabled {
        opacity: 0.5;
        pointer-events: none;
    }
</style>