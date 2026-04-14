<script setup lang="ts">
import { ref } from "vue";

// ── Props / Emits ──────────────────────────────────────────────
const VISION_TALK_OPTIONS = [
    { value: 0, label: "话少", desc: "阈值 30，安静" },
    { value: 1, label: "适中（默认）", desc: "阈值 20，平衡" },
    { value: 2, label: "话多", desc: "阈值 12，活跃" },
];

const props = defineProps<{
    enabled: boolean;
    vlm_base_url: string;
    vlm_api_key: string;
    vlm_model: string;
    talk_level: number;
    cooldown_seconds: number;
    manual_game_mode: boolean;
}>();

const emit = defineEmits<{
    "update:enabled": [v: boolean];
    "update:vlm_base_url": [v: string];
    "update:vlm_api_key": [v: string];
    "update:vlm_model": [v: string];
    "update:talk_level": [v: number];
    "update:cooldown_seconds": [v: number];
    "update:manual_game_mode": [v: boolean];
    "save": [];
}>();

// ── Toast ──────────────────────────────────────────────────────
const msgText = ref("");
const msgType = ref<"ok" | "warn">("ok");
function showMsg(text: string, type: "ok" | "warn" = "ok") {
    msgText.value = text; msgType.value = type;
    setTimeout(() => { msgText.value = ""; }, 2500);
}

function onEnabledChange(val: boolean) {
    console.info("[VisionPanel] enabled changed: %s", val);
    emit("update:enabled", val);
}

function onTalkLevelChange(val: number) {
    console.info("[VisionPanel] talk_level changed: %s", val);
    emit("update:talk_level", val);
}

function onCooldownChange(val: number) {
    console.debug("[VisionPanel] cooldown_seconds changed: %s", val);
    emit("update:cooldown_seconds", val);
}

function onManualGameModeChange(val: boolean) {
    console.info("[VisionPanel] manual_game_mode changed: %s", val);
    emit("update:manual_game_mode", val);
}

function onSave() {
    console.info("[VisionPanel] 保存视觉配置 | enabled=%s model=%s", props.enabled, props.vlm_model);
    emit("save");
}

defineExpose({ showMsg });
</script>

<template>
    <div class="vision-panel">
        <!-- Toast -->
        <transition name="toast">
            <div v-if="msgText" class="toast" :class="{ warn: msgType === 'warn' }">{{ msgText }}</div>
        </transition>

        <div class="global-section">
            <div class="global-section-title">🎮 视觉感知</div>

            <label class="toggle-row" style="margin-bottom:10px;">
                <span class="field-label">启用视觉感知</span>
                <input type="checkbox" :checked="enabled" @change="onEnabledChange(($event.target as HTMLInputElement).checked)" />
            </label>
            <p class="field-hint" style="color:var(--c-text-soft);margin-bottom:12px;">
                🔒 隐私说明：截图仅在内存中存在，用于实时分析后立即释放，永不保存到磁盘。
            </p>

            <template v-if="enabled">
                <div class="field-group" style="margin-bottom:8px;">
                    <label class="field-label">VLM API Base URL</label>
                    <input class="field-input" :value="vlm_base_url"
                           @input="emit('update:vlm_base_url', ($event.target as HTMLInputElement).value)"
                           placeholder="https://open.bigmodel.cn/api/paas/v4/" />
                </div>
                <div class="field-group" style="margin-bottom:8px;">
                    <label class="field-label">VLM API Key</label>
                    <input class="field-input" type="password" :value="vlm_api_key"
                           @input="emit('update:vlm_api_key', ($event.target as HTMLInputElement).value)"
                           placeholder="填写 VLM API Key" />
                </div>
                <div class="field-group" style="margin-bottom:12px;">
                    <label class="field-label">VLM 模型名称</label>
                    <input class="field-input" :value="vlm_model"
                           @input="emit('update:vlm_model', ($event.target as HTMLInputElement).value)"
                           placeholder="glm-4.6v-flash" />
                </div>

                <div v-if="enabled && !vlm_api_key"
                     style="background:#fffbe6;border:1px solid #f0c040;border-radius:6px;
                            padding:8px 12px;font-size:12px;color:#8a6000;margin-bottom:12px;">
                    ⚠️ 视觉模型未配置或不可用。请填写 VLM API Key，或在「AI 模型」Tab 配置支持多模态的文本模型（如 GPT-4o）。
                </div>

                <!-- 话痨程度 -->
                <div class="field-group" style="margin-bottom:12px;">
                    <label class="field-label">话痨程度</label>
                    <div class="size-options" style="gap:8px;margin-top:6px;">
                        <div v-for="opt in VISION_TALK_OPTIONS" :key="opt.value"
                             class="size-card" :class="{ active: talk_level === opt.value }"
                             @click="onTalkLevelChange(opt.value)">
                            <div class="size-label">{{ opt.label }}</div>
                            <div class="size-desc">{{ opt.desc }}</div>
                        </div>
                    </div>
                </div>

                <!-- 冷却时间 -->
                <div class="field-group" style="margin-bottom:12px;">
                    <label class="field-label">
                        主动发言冷却 <span class="field-note">{{ cooldown_seconds }} 秒</span>
                    </label>
                    <input type="range" class="field-range" min="5" max="120" step="5"
                           :value="cooldown_seconds" @change="onCooldownChange(Number(($event.target as HTMLInputElement).value))" />
                </div>

                <!-- 手动观战模式 -->
                <label class="toggle-row" style="margin-bottom:12px;">
                    <span class="field-label">
                        手动观战模式 <span class="field-note">强制标记当前为游戏场景</span>
                    </span>
                    <input type="checkbox" :checked="manual_game_mode"
                           @change="onManualGameModeChange(($event.target as HTMLInputElement).checked)" />
                </label>

                <div class="action-row">
                    <button class="save-btn" @click="onSave">保存视觉感知配置</button>
                </div>
            </template>
        </div>
    </div>
</template>

<style scoped>
.vision-panel { display: flex; flex-direction: column; gap: 0; }

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

.size-options { display: flex; gap: 8px; }
.size-card {
    flex: 1; padding: 10px 8px;
    border: 1.5px solid var(--c-border); border-radius: 10px;
    background: var(--c-surface); cursor: pointer;
    text-align: center; transition: border-color 0.2s, box-shadow 0.2s;
}
.size-card:hover { border-color: var(--c-pink-mid); }
.size-card.active {
    border-color: var(--c-blue);
    box-shadow: 0 0 0 3px var(--c-blue-light);
    background: linear-gradient(135deg, rgba(197,232,244,0.15), rgba(255,183,197,0.1));
}
.size-label { font-size: 13px; font-weight: 600; color: var(--c-text); }
.size-desc  { font-size: 11px; color: var(--c-text-soft); margin-top: 2px; }
</style>
