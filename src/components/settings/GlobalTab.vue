<script setup lang="ts">
    import { ref } from "vue";

    // ── Props / Emits ──────────────────────────────────────────────
    const emit = defineEmits<{
        "vision-saved": [cfg: object];
        "memory-window-changed": [index: number];
        "size-preset-changed": [preset: string];  // [FIX] 尺寸切换实时生效
    }>();

    // ── Toast ──────────────────────────────────────────────────────
    const msgText = ref("");
    const msgType = ref<"ok" | "warn">("ok");
    function showMsg(text: string, type: "ok" | "warn" = "ok") {
        msgText.value = text; msgType.value = type;
        setTimeout(() => { msgText.value = ""; }, 2500);
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
        emit("size-preset-changed", preset);
        showMsg("✓ 尺寸已切换");
    }

    // ── 视觉感知 ───────────────────────────────────────────────────
    const VISION_TALK_OPTIONS = [
        { value: 0, label: "话少", desc: "阈值 30，安静" },
        { value: 1, label: "适中（默认）", desc: "阈值 20,平衡" },
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

    // ── 语音输入 ───────────────────────────────────────────────────
    function _loadVoiceCfg() {
        try { return JSON.parse(localStorage.getItem("rl-voice") || "{}"); } catch { return {}; }
    }
    const _voiceCfg = _loadVoiceCfg();

    const voiceEnabled   = ref<boolean>(!!_voiceCfg.enabled);
    const voiceWindowSec = ref<number>(_voiceCfg.window_sec ?? 15);

    async function saveVoice() {
        const cfg = {
            enabled: voiceEnabled.value,
            window_sec: voiceWindowSec.value,
        };
        localStorage.setItem("rl-voice", JSON.stringify(cfg));
        // 通过 config-changed 事件通知主窗口同步到后端
        window.dispatchEvent(new StorageEvent("storage", { key: "rl-voice" }));
        showMsg("✓ 语音输入配置已保存");
    }
</script>

<template>
    <div class="tab-content">

        <!-- Toast -->
        <transition name="toast">
            <div v-if="msgText" class="toast" :class="{ warn: msgType === 'warn' }">{{ msgText }}</div>
        </transition>

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
        </div>

        <div class="divider"></div>

        <!-- 语音输入设置 -->
        <div class="global-section">
            <div class="global-section-title">🎙️ 语音输入</div>

            <div class="toggle-row" style="margin-bottom:10px;">
                <span class="field-label">启用语音输入</span>
                <label class="toggle-switch">
                    <input type="checkbox" v-model="voiceEnabled" @change="saveVoice" />
                    <span class="toggle-slider"></span>
                </label>
            </div>
            <p class="field-hint" style="color:var(--c-text-soft);margin-bottom:12px;">
                开启后，桌宠会自动聆听你的语音并回应。无需唤醒词，通过语义判断识别对话意图。
            </p>

            <template v-if="voiceEnabled">
                <div class="field-group" style="margin-bottom:12px;">
                    <label class="field-label">
                        对话窗口时长 <span class="field-note">{{ voiceWindowSec }} 秒</span>
                    </label>
                    <input type="range" class="field-range" min="5" max="60" step="1"
                           v-model.number="voiceWindowSec" @change="saveVoice" />
                    <p class="field-hint" style="margin-top:4px;">
                        桌宠发言后，用户在该时间窗口内的语音会被直接视为回复，无需再次判断意图。
                    </p>
                </div>

                <div class="action-row">
                    <button class="save-btn" @click="saveVoice">保存语音输入配置</button>
                </div>
            </template>
        </div>

        <div class="divider"></div>

        <!-- 视觉感知 -->
        <div class="global-section">
            <div class="global-section-title">🎮 视觉感知</div>

            <div class="toggle-row" style="margin-bottom:10px;">
                <span class="field-label">启用视觉感知</span>
                <label class="toggle-switch">
                    <input type="checkbox" v-model="visionEnabled" @change="saveVision" />
                    <span class="toggle-slider"></span>
                </label>
            </div>
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
                <div class="toggle-row" style="margin-bottom:12px;">
                    <span class="field-label">
                        手动观战模式 <span class="field-note">强制标记当前为游戏场景</span>
                    </span>
                    <label class="toggle-switch">
                        <input type="checkbox" v-model="visionManualGameMode" @change="saveVision" />
                        <span class="toggle-slider"></span>
                    </label>
                </div>

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