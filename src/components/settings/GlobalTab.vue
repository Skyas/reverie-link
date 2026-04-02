<script setup lang="ts">
    import { ref, onMounted } from "vue";

    // ── Props / Emits ──────────────────────────────────────────────
    const emit = defineEmits<{
        "vision-saved": [cfg: object];
        "memory-window-changed": [index: number];
        "size-preset-changed": [preset: string];  // [FIX] 新增：尺寸切换实时生效
    }>();

    // ── Toast ──────────────────────────────────────────────────────
    const msgText = ref("");
    const msgType = ref<"ok" | "warn">("ok");
    function showMsg(text: string, type: "ok" | "warn" = "ok") {
        msgText.value = text; msgType.value = type;
        setTimeout(() => { msgText.value = ""; }, 2500);
    }

    // ── Live2D 模型 ────────────────────────────────────────────────
    interface Live2DModelInfo { folder: string; display_name: string; path: string; }

    const live2dModels = ref<Live2DModelInfo[]>([]);
    const modelsLoading = ref(false);
    const selectedModelPath = ref<string>(localStorage.getItem("rl-model-path") ?? "live2d/MO/MO.model3.json");
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
        } catch (e) { console.warn("[model switch] emit failed:", e); }
        showMsg("✓ 模型已切换");
    }

    async function applyModelSettings() {
        saveModelDisplaySettings();
        try {
            const { emit: tauriEmit } = await import("@tauri-apps/api/event");
            await tauriEmit("model-changed", { path: selectedModelPath.value });
        } catch (e) { console.warn("[model settings] emit failed:", e); }
        showMsg("✓ 显示设置已应用");
    }

    // ── 窗口尺寸 ───────────────────────────────────────────────────
    const SIZE_OPTIONS = [
        { value: "small", label: "小", desc: "200 × 270" },
        { value: "medium", label: "中（默认）", desc: "280 × 380" },
        { value: "large", label: "大", desc: "380 × 510" },
    ];
    const sizePreset = ref<string>(localStorage.getItem("rl-size") ?? "medium");

    function applySize(preset: string) {
        sizePreset.value = preset;
        localStorage.setItem("rl-size", preset);
        emit("size-preset-changed", preset);  // [FIX] 通知父组件，触发主窗口实时 resize
        showMsg("✓ 尺寸已切换");              // [FIX] 去掉"重启后生效"提示
    }

    // ── 视觉感知 ───────────────────────────────────────────────────
    const VISION_TALK_OPTIONS = [
        { value: 0, label: "话少", desc: "阈值 30，安静" },
        { value: 1, label: "适中（默认）", desc: "阈值 20，平衡" },
        { value: 2, label: "话多", desc: "阈值 12，活跃" },
    ];

    function _loadVisionCfg() {
        try { return JSON.parse(localStorage.getItem("rl-vision") || "{}"); } catch { return {}; }
    }
    const _vc = _loadVisionCfg();

    const visionEnabled = ref<boolean>(!!_vc.enabled);
    const visionVlmBaseUrl = ref<string>(_vc.vlm_base_url ?? "https://open.bigmodel.cn/api/paas/v4/");
    const visionVlmApiKey = ref<string>(_vc.vlm_api_key ?? "");
    const visionVlmModel = ref<string>(_vc.vlm_model ?? "glm-4.6v-flash");
    const visionTalkLevel = ref<number>(_vc.talk_level ?? 1);
    const visionCooldown = ref<number>(_vc.cooldown_seconds ?? 20);
    const visionManualGameMode = ref<boolean>(!!_vc.manual_game_mode);

    async function saveVision() {
        const cfg = {
            enabled: visionEnabled.value,
            vlm_base_url: visionVlmBaseUrl.value.trim(),
            vlm_api_key: visionVlmApiKey.value.trim(),
            vlm_model: visionVlmModel.value.trim() || "glm-4.6v-flash",
            talk_level: visionTalkLevel.value,
            cooldown_seconds: visionCooldown.value,
            manual_game_mode: visionManualGameMode.value,
        };
        localStorage.setItem("rl-vision", JSON.stringify(cfg));
        emit("vision-saved", cfg);
        showMsg("✓ 视觉感知配置已保存");
    }

    // ── 记忆窗口 ───────────────────────────────────────────────────
    const MEMORY_WINDOW_OPTIONS = [
        { index: 0, label: "极速省流", desc: "3分钟 / 5轮", token: "~2,000 tokens", warn: false },
        { index: 1, label: "均衡（默认）", desc: "8分钟 / 12轮", token: "~5,000 tokens", warn: false },
        { index: 2, label: "沉浸", desc: "15分钟 / 20轮", token: "~8,000 tokens", warn: false },
        { index: 3, label: "深度", desc: "20分钟 / 28轮", token: "~11,000 tokens", warn: true },
        { index: 4, label: "极限", desc: "25分钟 / 35轮", token: "~14,000 tokens", warn: true },
    ];
    const memoryWindowIndex = ref<number>(parseInt(localStorage.getItem("rl-memory-window") ?? "1", 10));

    async function applyMemoryWindow(index: number) {
        memoryWindowIndex.value = index;
        localStorage.setItem("rl-memory-window", String(index));
        emit("memory-window-changed", index);
        showMsg(`✓ 记忆跨度已切换至「${MEMORY_WINDOW_OPTIONS[index].label}」`);
    }

    // ── 初始化 ─────────────────────────────────────────────────────
    onMounted(async () => {
        loadModelDisplaySettings(selectedModelPath.value);
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
                <button class="refresh-btn" @click="fetchLive2DModels">🔄 重新扫描</button>
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

        <!-- 窗口尺寸 -->
        <div class="global-section">
            <div class="global-section-title">📐 窗口尺寸</div>
            <div class="size-options">
                <div v-for="opt in SIZE_OPTIONS" :key="opt.value"
                     class="size-card" :class="{ active: sizePreset === opt.value }"
                     @click="applySize(opt.value)">
                    <div class="size-label">{{ opt.label }}</div>
                    <div class="size-desc">{{ opt.desc }}</div>
                </div>
            </div>
            <!-- [FIX] 移除"重启后生效"提示，切换即时生效 -->
        </div>

        <div class="divider"></div>

        <!-- 语音设置（开发中） -->
        <div class="global-section global-section-disabled">
            <div class="global-section-title">🎙️ 语音设置 <span class="coming-badge">开发中</span></div>
            <div class="field-group">
                <label class="field-label">唤醒词</label>
                <input class="field-input" disabled placeholder="例如：小玲" />
            </div>
            <div class="field-group">
                <label class="field-label">音量</label>
                <input type="range" class="field-range" disabled min="0" max="100" value="80" />
            </div>
        </div>

        <div class="divider"></div>

        <!-- 视觉感知 -->
        <div class="global-section">
            <div class="global-section-title">🎮 视觉感知</div>

            <label class="toggle-row" style="margin-bottom:10px;">
                <span class="field-label">启用视觉感知</span>
                <input type="checkbox" v-model="visionEnabled" @change="saveVision" />
            </label>
            <p class="field-hint" style="color:var(--c-text-soft);margin-bottom:12px;">
                🔒 隐私说明：截图仅在内存中存在，用于实时分析后立即释放，永不保存到磁盘。
            </p>

            <template v-if="visionEnabled">
                <div class="field-group" style="margin-bottom:8px;">
                    <label class="field-label">VLM API Base URL</label>
                    <input class="field-input" v-model="visionVlmBaseUrl"
                           placeholder="https://open.bigmodel.cn/api/paas/v4/" />
                </div>
                <div class="field-group" style="margin-bottom:8px;">
                    <label class="field-label">VLM API Key</label>
                    <input class="field-input" type="password" v-model="visionVlmApiKey"
                           placeholder="填写 VLM API Key" />
                </div>
                <div class="field-group" style="margin-bottom:12px;">
                    <label class="field-label">VLM 模型名称</label>
                    <input class="field-input" v-model="visionVlmModel" placeholder="glm-4.6v-flash" />
                </div>

                <div v-if="visionEnabled && !visionVlmApiKey"
                     style="background:#fffbe6;border:1px solid #f0c040;border-radius:6px;
                            padding:8px 12px;font-size:12px;color:#8a6000;margin-bottom:12px;">
                    ⚠️ 视觉模型未配置或不可用。请填写 VLM API Key，或在「AI 模型」Tab 配置支持多模态的文本模型（如 GPT-4o）。
                </div>

                <!-- 话痨程度 -->
                <div class="field-group" style="margin-bottom:12px;">
                    <label class="field-label">话痨程度</label>
                    <div class="size-options" style="gap:8px;margin-top:6px;">
                        <div v-for="opt in VISION_TALK_OPTIONS" :key="opt.value"
                             class="size-card" :class="{ active: visionTalkLevel === opt.value }"
                             @click="visionTalkLevel = opt.value; saveVision()">
                            <div class="size-label">{{ opt.label }}</div>
                            <div class="size-desc">{{ opt.desc }}</div>
                        </div>
                    </div>
                </div>

                <!-- 冷却时间 -->
                <div class="field-group" style="margin-bottom:12px;">
                    <label class="field-label">主动发言冷却 <span class="field-note">{{ visionCooldown }} 秒</span></label>
                    <input type="range" class="field-range" min="5" max="120" step="5"
                           v-model.number="visionCooldown" @change="saveVision" />
                </div>

                <!-- 手动观战模式 -->
                <label class="toggle-row" style="margin-bottom:12px;">
                    <span class="field-label">
                        手动观战模式 <span class="field-note">强制标记当前为游戏场景</span>
                    </span>
                    <input type="checkbox" v-model="visionManualGameMode" @change="saveVision" />
                </label>

                <div class="action-row">
                    <button class="save-btn" @click="saveVision">保存视觉感知配置</button>
                </div>
            </template>
        </div>

        <div class="divider"></div>

        <!-- 记忆设置 -->
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
    .toast {
        position: fixed;
        top: 16px;
        left: 50%;
        transform: translateX(-50%);
        padding: 8px 20px;
        border-radius: 20px;
        background: linear-gradient(135deg, var(--c-blue-mid), var(--c-pink));
        color: white;
        font-size: 13px;
        font-weight: 500;
        box-shadow: 0 4px 16px rgba(126,87,194,0.2);
        z-index: 200;
        pointer-events: none;
        white-space: nowrap;
    }

        .toast.warn {
            background: linear-gradient(135deg, #F0A0A0, #E08080);
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

    /* Live2D 模型 */
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

    /* 模型显示设置 */
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

    /* 尺寸 */
    .size-options {
        display: flex;
        gap: 8px;
    }

    .size-card {
        flex: 1;
        padding: 10px 8px;
        border: 1.5px solid var(--c-border);
        border-radius: 12px;
        text-align: center;
        cursor: pointer;
        background: var(--c-surface);
        transition: border-color 0.2s, box-shadow 0.2s;
    }

        .size-card:hover {
            border-color: var(--c-pink-mid);
        }

        .size-card.active {
            border-color: var(--c-blue);
            box-shadow: 0 0 0 3px var(--c-blue-light);
        }

    .size-label {
        font-size: 13px;
        font-weight: 600;
        color: var(--c-text);
    }

    .size-desc {
        font-size: 11px;
        color: var(--c-text-soft);
        margin-top: 2px;
    }

    /* 记忆窗口 */
    .memory-window-options {
        display: flex;
        flex-direction: column;
        gap: 6px;
    }

    .memory-window-card {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 10px 14px;
        border: 1.5px solid var(--c-border);
        border-radius: 10px;
        cursor: pointer;
        background: var(--c-surface);
        transition: border-color 0.2s, box-shadow 0.2s;
    }

        .memory-window-card:hover {
            border-color: var(--c-pink-mid);
        }

        .memory-window-card.active {
            border-color: var(--c-blue);
            box-shadow: 0 0 0 3px var(--c-blue-light);
            background: linear-gradient(135deg, rgba(197,232,244,0.15), rgba(255,183,197,0.1));
        }

    .memory-window-label {
        font-size: 13px;
        font-weight: 600;
        color: var(--c-text);
        min-width: 80px;
        flex-shrink: 0;
    }

    .memory-window-desc {
        font-size: 12px;
        color: var(--c-text-soft);
        flex: 1;
    }

    .memory-window-token {
        font-size: 11px;
        color: var(--c-text-soft);
        text-align: right;
        flex-shrink: 0;
    }

        .memory-window-token.warn {
            color: #C08000;
            font-weight: 500;
        }
</style>