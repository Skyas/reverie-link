<script setup lang="ts">
import { ref, onMounted } from "vue";

import Live2DModelPanel from "./global/Live2DModelPanel.vue";
import SizePresetPanel from "./global/SizePresetPanel.vue";
import VisionPanel from "./global/VisionPanel.vue";
import MemoryWindowPanel from "./global/MemoryWindowPanel.vue";

// ── Toast ──────────────────────────────────────────────────────────
const msgText = ref("");
const msgType = ref<"ok" | "warn">("ok");
function showMsg(text: string, type: "ok" | "warn" = "ok") {
    msgText.value = text; msgType.value = type;
    setTimeout(() => { msgText.value = ""; }, 2500);
}

// ── Live2D 模型 ─────────────────────────────────────────────────
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

async function fetchLive2DModels() {
    modelsLoading.value = true;
    console.info("[GlobalTab] fetchLive2DModels: 开始获取模型列表");
    try {
        const res = await fetch("http://localhost:18000/api/live2d/models");
        const data = await res.json();
        live2dModels.value = data.models ?? [];
        console.info("[GlobalTab] fetchLive2DModels: 找到 %s 个模型", live2dModels.value.length);
    } catch (e) {
        live2dModels.value = [];
        console.error("[GlobalTab] fetchLive2DModels: 失败", e);
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
    } catch (e) { console.warn("[GlobalTab] emit model-changed 失败:", e); }
    console.info("[GlobalTab] 模型已切换: %s", path);
    showMsg("✓ 模型已切换");
}

// ── 窗口尺寸 ───────────────────────────────────────────────────
const sizePreset = ref<string>(localStorage.getItem("rl-size") ?? "medium");

function onSizePresetChanged(preset: string) {
    sizePreset.value = preset;
    localStorage.setItem("rl-size", preset);
    emit("size-preset-changed", preset);
    showMsg("✓ 尺寸已切换");
}

// ── 视觉感知 ───────────────────────────────────────────────────
const visionEnabled = ref<boolean>(false);
const visionVlmBaseUrl = ref<string>("https://open.bigmodel.cn/api/paas/v4/");
const visionVlmApiKey = ref<string>("");
const visionVlmModel = ref<string>("glm-4.6v-flash");
const visionTalkLevel = ref<number>(1);
const visionCooldown = ref<number>(20);
const visionManualGameMode = ref<boolean>(false);

function loadVisionCfg() {
    try {
        const saved = localStorage.getItem("rl-vision");
        if (saved) {
            const d = JSON.parse(saved);
            visionEnabled.value = !!d.enabled;
            visionVlmBaseUrl.value = d.vlm_base_url ?? "https://open.bigmodel.cn/api/paas/v4/";
            visionVlmApiKey.value = d.vlm_api_key ?? "";
            visionVlmModel.value = d.vlm_model ?? "glm-4.6v-flash";
            visionTalkLevel.value = d.talk_level ?? 1;
            visionCooldown.value = d.cooldown_seconds ?? 20;
            visionManualGameMode.value = !!d.manual_game_mode;
        }
    } catch { /* ignore */ }
}

function saveVision() {
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
    console.info("[GlobalTab] saveVision: 已保存", cfg);
    showMsg("✓ 视觉感知配置已保存");
}

// ── 记忆窗口 ───────────────────────────────────────────────────
const memoryWindowIndex = ref<number>(parseInt(localStorage.getItem("rl-memory-window") ?? "1", 10));

function onMemoryWindowChanged(index: number) {
    memoryWindowIndex.value = index;
    localStorage.setItem("rl-memory-window", String(index));
    emit("memory-window-changed", index);
    showMsg(`✓ 记忆跨度已切换`);
}

// ── Emits ───────────────────────────────────────────────────────
const emit = defineEmits<{
    "vision-saved": [cfg: object];
    "memory-window-changed": [index: number];
    "size-preset-changed": [preset: string];
}>();

// ── 初始化 ─────────────────────────────────────────────────────
onMounted(async () => {
    console.info("[GlobalTab] onMounted 开始");
    loadModelDisplaySettings(selectedModelPath.value);
    loadVisionCfg();
    await fetchLive2DModels();
    console.info("[GlobalTab] onMounted 完成");
});
</script>

<template>
    <div class="tab-content">
        <!-- Toast -->
        <transition name="toast">
            <div v-if="msgText" class="toast" :class="{ warn: msgType === 'warn' }">{{ msgText }}</div>
        </transition>

        <!-- Live2D 模型 -->
        <Live2DModelPanel
            :models="live2dModels"
            :loading="modelsLoading"
            :selected-path="selectedModelPath"
            :zoom="modelZoom"
            :y="modelY"
            @fetch="fetchLive2DModels"
            @apply="applyModel"
            @update:zoom="modelZoom = $event"
            @update:y="modelY = $event"
        />

        <div class="divider"></div>

        <!-- 窗口尺寸 -->
        <SizePresetPanel v-model:size-preset="sizePreset" @change="onSizePresetChanged" />

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
        <VisionPanel
            :enabled="visionEnabled"
            :vlm_base_url="visionVlmBaseUrl"
            :vlm_api_key="visionVlmApiKey"
            :vlm_model="visionVlmModel"
            :talk_level="visionTalkLevel"
            :cooldown_seconds="visionCooldown"
            :manual_game_mode="visionManualGameMode"
            @update:enabled="visionEnabled = $event"
            @update:vlm_base_url="visionVlmBaseUrl = $event"
            @update:vlm_api_key="visionVlmApiKey = $event"
            @update:vlm_model="visionVlmModel = $event"
            @update:talk_level="visionTalkLevel = $event"
            @update:cooldown_seconds="visionCooldown = $event"
            @update:manual_game_mode="visionManualGameMode = $event"
            @save="saveVision"
        />

        <div class="divider"></div>

        <!-- 记忆设置 -->
        <MemoryWindowPanel
            :memoryWindowIndex="memoryWindowIndex"
            @change="onMemoryWindowChanged"
        />
    </div>
</template>

<style scoped>
/* toast */
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
.toast-leave-to   { opacity: 0; }
</style>
