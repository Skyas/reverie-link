<script setup lang="ts">
// ── 窗口尺寸面板 ───────────────────────────────────────────────
const SIZE_OPTIONS = [
    { value: "small",  label: "小",        desc: "200 × 270" },
    { value: "medium", label: "中（默认）", desc: "280 × 380" },
    { value: "large",  label: "大",        desc: "380 × 510" },
];

const sizePreset = defineModel<string>("sizePreset", { required: true });
const emit = defineEmits<{ "change": [preset: string] }>();

function applySize(preset: string) {
    console.info(`[SizePresetPanel] 切换尺寸预设 | preset=${preset}`);
    sizePreset.value = preset;
    emit("change", preset);
}
</script>

<template>
    <div class="size-panel">
        <div class="global-section-title" style="margin-bottom:8px;">📐 窗口尺寸</div>
        <div class="size-options">
            <div v-for="opt in SIZE_OPTIONS" :key="opt.value"
                 class="size-card" :class="{ active: sizePreset === opt.value }"
                 @click="applySize(opt.value)">
                <div class="size-label">{{ opt.label }}</div>
                <div class="size-desc">{{ opt.desc }}</div>
            </div>
        </div>
    </div>
</template>

<style scoped>
.size-panel { display: flex; flex-direction: column; gap: 0; }

.size-options {
    display: flex;
    gap: 8px;
}

.size-card {
    flex: 1;
    padding: 10px 8px;
    border: 1.5px solid var(--c-border);
    border-radius: 10px;
    background: var(--c-surface);
    cursor: pointer;
    text-align: center;
    transition: border-color 0.2s, box-shadow 0.2s;
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
