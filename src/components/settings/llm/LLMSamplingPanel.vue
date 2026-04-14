<script setup lang="ts">
// ── 采样参数面板（无状态，纯展示） ────────────────────────────
const llm = defineModel<{
    temperature: number;
    top_p: number;
    frequency_penalty: number;
}>("llm", { required: true });
</script>

<template>
    <div class="sampling-section">
        <div class="global-section-title" style="margin-bottom:8px;">🧠 核心性格微调</div>

        <div class="field-group">
            <label class="field-label">
                🎨 脑洞大小 (Temperature): {{ llm.temperature.toFixed(2) }}
            </label>
            <input type="range" min="0" max="2" step="0.05"
                   v-model.number="llm.temperature" class="field-slider" />
            <div class="field-hint" style="display: flex; justify-content: space-between; margin-top: 4px;">
                <span>👈 小</span>
                <span style="color: var(--c-text-soft);">日常推荐 0.85</span>
                <span>大 👉</span>
            </div>
        </div>

        <div class="field-group">
            <label class="field-label">
                📖 词汇量 (Top P): {{ llm.top_p.toFixed(2) }}
            </label>
            <input type="range" min="0" max="1" step="0.05"
                   v-model.number="llm.top_p" class="field-slider" />
            <div class="field-hint" style="display: flex; justify-content: space-between; margin-top: 4px;">
                <span>👈 少</span>
                <span style="color: var(--c-text-soft);">日常推荐 0.90</span>
                <span>多 👉</span>
            </div>
        </div>

        <div class="field-group">
            <label class="field-label">
                🔀 复读机程度 (Freq Penalty): {{ llm.frequency_penalty.toFixed(2) }}
            </label>
            <input type="range" min="0" max="1" step="0.05"
                   v-model.number="llm.frequency_penalty" class="field-slider" />
            <div class="field-hint" style="display: flex; justify-content: space-between; margin-top: 4px;">
                <span>👈 人类本质</span>
                <span style="color: var(--c-text-soft);">日常推荐 0.50</span>
                <span>不准复读 👉</span>
            </div>
        </div>
    </div>
</template>

<style scoped>
.sampling-section {
    display: flex;
    flex-direction: column;
    gap: 10px;
}

.field-slider {
    width: 100%;
    margin-top: 4px;
    cursor: pointer;
    accent-color: var(--c-blue);
}
</style>
