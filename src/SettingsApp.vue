<script setup lang="ts">
    import { ref, onMounted } from "vue";
    import LLMTab from "./components/settings/LLMTab.vue";
    import CharacterTab from "./components/settings/CharacterTab.vue";
    import GlobalTab from "./components/settings/GlobalTab.vue";
    import NotebookModal from "./components/settings/NotebookModal.vue";

    // ── 全局状态（需跨组件共享的最小集合）────────────────────────
    const activeTab = ref<"llm" | "character" | "global">("llm");
    const activePresetId = ref<string>("");
    const defaultAvatar = ref<string>("");

    // ── 笔记本弹窗 ────────────────────────────────────────────────
    const showNotebook = ref(false);
    const notebookCharId = ref("");
    const notebookCharName = ref("");

    function onOpenNotebook(charId: string, charName: string) {
        notebookCharId.value = charId;
        notebookCharName.value = charName;
        showNotebook.value = true;
    }

    // ── 发送配置到后端（唯一的全局通信函数）─────────────────────
    async function sendConfigToBackend(llmCfg: object, charCfg: object, extraPayload?: object) {
        try {
            const { emit } = await import("@tauri-apps/api/event");
            await emit("config-changed", {
                llm: llmCfg,
                character: charCfg,
                character_id: activePresetId.value,
                memory_window: parseInt(localStorage.getItem("rl-memory-window") ?? "1", 10),
                ...extraPayload,
            });
        } catch (e) {
            console.warn("[config] emit failed:", e);
        }
    }

    // ── 子组件事件处理 ────────────────────────────────────────────

    // LLMTab 保存 LLM 配置
    function onLLMSaved(llmCfg: object) {
        const charCfg = JSON.parse(localStorage.getItem("rl-character") || "{}");
        sendConfigToBackend(llmCfg, charCfg);
    }

    // CharacterTab 激活预设
    function onActivated(presetId: string, charCfg: object) {
        activePresetId.value = presetId;
        const llmCfg = JSON.parse(localStorage.getItem("rl-llm") || "{}");
        sendConfigToBackend(llmCfg, charCfg);
    }

    // CharacterTab 删除预设（可能导致 activePresetId 变化）
    function onDeleted(newActiveId: string) {
        activePresetId.value = newActiveId;
    }

    // GlobalTab 保存视觉感知
    function onVisionSaved(visionCfg: object) {
        const llmCfg = JSON.parse(localStorage.getItem("rl-llm") || "{}");
        const charCfg = JSON.parse(localStorage.getItem("rl-character") || "{}");
        sendConfigToBackend(llmCfg, charCfg, { vision: visionCfg });
    }

    // GlobalTab 切换记忆窗口
    function onMemoryWindowChanged(index: number) {
        const llmCfg = JSON.parse(localStorage.getItem("rl-llm") || "{}");
        const charCfg = JSON.parse(localStorage.getItem("rl-character") || "{}");
        sendConfigToBackend(llmCfg, charCfg);
    }

    // [FIX] GlobalTab 切换窗口尺寸 → 通过 config-changed 通知主窗口实时 resize
    function onSizePresetChanged(preset: string) {
        const llmCfg = JSON.parse(localStorage.getItem("rl-llm") || "{}");
        const charCfg = JSON.parse(localStorage.getItem("rl-character") || "{}");
        sendConfigToBackend(llmCfg, charCfg, { size_preset: preset });
    }

    // ── 初始化 ────────────────────────────────────────────────────
    onMounted(async () => {
        // 加载默认头像
        try {
            const resp = await fetch("/avatar.png");
            const blob = await resp.blob();
            const reader = new FileReader();
            reader.onload = () => { defaultAvatar.value = reader.result as string; };
            reader.readAsDataURL(blob);
        } catch { /* ignore */ }

        // 恢复 activePresetId
        const savedId = localStorage.getItem("rl-active-preset-id");
        if (savedId) activePresetId.value = savedId;
    });
</script>

<template>
    <div class="settings-root">

        <!-- 顶部标题栏 -->
        <div class="header">
            <div class="header-icon">✦</div>
            <div class="header-title">Reverie Link 设置</div>
            <div class="header-sub">配置你的专属数字伴侣</div>
        </div>

        <!-- Tab 切换 -->
        <div class="tabs">
            <button class="tab-btn" :class="{ active: activeTab === 'llm' }"
                    @click="activeTab = 'llm'">
                <span class="tab-icon">🤖</span> AI 模型
            </button>
            <button class="tab-btn" :class="{ active: activeTab === 'character' }"
                    @click="activeTab = 'character'">
                <span class="tab-icon">🌸</span> 角色设定
            </button>
            <button class="tab-btn" :class="{ active: activeTab === 'global' }"
                    @click="activeTab = 'global'">
                <span class="tab-icon">⚙️</span> 全局设置
            </button>
        </div>

        <!-- 内容区 -->
        <div class="content">
            <LLMTab v-if="activeTab === 'llm'"
                    @llm-saved="onLLMSaved" />
            <CharacterTab v-if="activeTab === 'character'"
                          :active-preset-id="activePresetId"
                          :default-avatar="defaultAvatar"
                          @activated="onActivated"
                          @deleted="onDeleted"
                          @open-notebook="onOpenNotebook" />
            <GlobalTab v-if="activeTab === 'global'"
                       @vision-saved="onVisionSaved"
                       @memory-window-changed="onMemoryWindowChanged"
                       @size-preset-changed="onSizePresetChanged" />
        </div>

        <!-- 笔记本弹窗 -->
        <NotebookModal :visible="showNotebook"
                       :character-id="notebookCharId"
                       :character-name="notebookCharName"
                       @close="showNotebook = false" />

    </div>
</template>

<style>
    /* ── 全局重置（与原版一致）──────────────────────────────────── */
    *, *::before, *::after {
        margin: 0;
        padding: 0;
        box-sizing: border-box;
    }

    html, body {
        width: 100%;
        height: 100%;
        font-family: "Hiragino Sans GB", "Microsoft YaHei", "PingFang SC", sans-serif;
        -webkit-font-smoothing: antialiased;
        background: #FEF6FA;
    }

    ::-webkit-scrollbar {
        width: 6px;
    }

    ::-webkit-scrollbar-track {
        background: transparent;
    }

    ::-webkit-scrollbar-thumb {
        background: #FFCDD9;
        border-radius: 3px;
    }

    /* ── 共享表单样式（供所有子组件使用，非 scoped）────────────── */
    .field-group {
        display: flex;
        flex-direction: column;
        gap: 5px;
    }

        .field-group.half {
            flex: 1;
        }

    .field-label {
        font-size: 12px;
        font-weight: 600;
        color: #4A4A6A;
        display: flex;
        align-items: center;
        gap: 6px;
    }

    .field-note {
        font-size: 11px;
        font-weight: 400;
        color: #9B8FB0;
    }

    .required {
        color: #FFAABB;
    }

    .field-hint {
        font-size: 11px;
        color: #9B8FB0;
        padding-left: 2px;
    }

    .field-input {
        width: 100%;
        padding: 9px 12px;
        border: 1.5px solid rgba(212,184,224,0.45);
        border-radius: 10px;
        background: #FFFFFF;
        font-size: 13px;
        color: #4A4A6A;
        font-family: inherit;
        outline: none;
        transition: border-color 0.2s, box-shadow 0.2s;
    }

        .field-input:focus {
            border-color: #7EC8E3;
            box-shadow: 0 0 0 3px #C5E8F4;
        }

        .field-input::placeholder {
            color: #9B8FB0;
            opacity: 0.7;
        }

        .field-input:disabled {
            background: rgba(200,190,220,0.12);
            cursor: not-allowed;
        }

    .field-readonly {
        background: rgba(200,190,220,0.12) !important;
        color: #9B8FB0;
        cursor: not-allowed;
    }

    .field-select {
        width: 100%;
        padding: 9px 12px;
        border: 1.5px solid rgba(212,184,224,0.45);
        border-radius: 10px;
        background: #FFFFFF;
        font-size: 13px;
        color: #4A4A6A;
        font-family: inherit;
        outline: none;
        cursor: pointer;
    }

        .field-select:focus {
            border-color: #7EC8E3;
        }

    .field-range {
        width: 100%;
        accent-color: #7EC8E3;
    }

    .field-row {
        display: flex;
        gap: 12px;
    }

    .toggle-row {
        display: flex;
        align-items: center;
        justify-content: space-between;
    }

    .action-row {
        display: flex;
        align-items: center;
        justify-content: flex-end;
        gap: 12px;
        padding-top: 4px;
    }

    .save-btn {
        padding: 9px 24px;
        border: none;
        border-radius: 20px;
        background: linear-gradient(135deg, #A8D8EA, #FFB7C5);
        color: white;
        font-size: 13px;
        font-weight: 600;
        font-family: inherit;
        cursor: pointer;
        box-shadow: 0 3px 12px rgba(180,140,200,0.12);
        transition: opacity 0.2s, transform 0.15s;
    }

        .save-btn:hover {
            opacity: 0.88;
        }

        .save-btn:active {
            transform: scale(0.97);
        }

    .divider {
        height: 1px;
        background: rgba(212,184,224,0.45);
        margin: 2px 0;
    }

    .global-section {
        display: flex;
        flex-direction: column;
        gap: 10px;
    }

    .global-section-disabled {
        opacity: 0.45;
        pointer-events: none;
    }

    .global-section-title {
        font-size: 13px;
        font-weight: 700;
        color: #4A4A6A;
        display: flex;
        align-items: center;
        gap: 8px;
    }

    .coming-badge {
        font-size: 10px;
        font-weight: 600;
        color: #9B8FB0;
        background: #FFE4EC;
        padding: 2px 8px;
        border-radius: 10px;
    }

    /* 弹框 */
    .dialog-overlay {
        position: fixed;
        inset: 0;
        background: rgba(100,80,120,0.25);
        backdrop-filter: blur(4px);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 200;
    }

    .dialog-box {
        width: 300px;
        background: #FFFFFF;
        border-radius: 18px;
        padding: 22px 20px 18px;
        box-shadow: 0 8px 32px rgba(126,87,194,0.18);
        display: flex;
        flex-direction: column;
        gap: 14px;
    }

    .dialog-title {
        font-size: 15px;
        font-weight: 700;
        color: #4A4A6A;
    }

    .dialog-body {
        display: flex;
        flex-direction: column;
        gap: 8px;
    }

    .dialog-actions {
        display: flex;
        gap: 10px;
        justify-content: flex-end;
    }

    .dialog-cancel {
        padding: 7px 18px;
        border: 1.5px solid rgba(212,184,224,0.45);
        border-radius: 20px;
        background: transparent;
        color: #9B8FB0;
        font-size: 13px;
        font-family: inherit;
        cursor: pointer;
    }

        .dialog-cancel:hover {
            background: #FFE4EC;
        }

    .dialog-confirm {
        padding: 7px 18px;
        border: none;
        border-radius: 20px;
        background: linear-gradient(135deg, #A8D8EA, #FFB7C5);
        color: white;
        font-size: 13px;
        font-weight: 600;
        font-family: inherit;
        cursor: pointer;
    }

        .dialog-confirm:hover {
            opacity: 0.88;
        }

        .dialog-confirm:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }

    .dialog-enter-active {
        transition: opacity 0.2s ease;
    }

    .dialog-leave-active {
        transition: opacity 0.15s ease;
    }

    .dialog-enter-from, .dialog-leave-to {
        opacity: 0;
    }

    /* ── Toggle 开关（供所有子组件使用）────────────────────────── */
    .toggle-switch {
        position: relative;
        width: 40px;
        height: 22px;
        flex-shrink: 0;
    }

    .toggle-switch input {
        position: absolute;
        opacity: 0;
        width: 0;
        height: 0;
    }

    .toggle-slider {
        position: absolute;
        inset: 0;
        background: rgba(200, 190, 220, 0.4);
        border-radius: 11px;
        cursor: pointer;
        transition: background 0.25s;
    }

    .toggle-slider::before {
        content: "";
        position: absolute;
        width: 16px;
        height: 16px;
        left: 3px;
        top: 3px;
        border-radius: 50%;
        background: white;
        box-shadow: 0 1px 4px rgba(0, 0, 0, 0.18);
        transition: transform 0.25s;
    }

    .toggle-switch input:checked + .toggle-slider {
        background: linear-gradient(135deg, #A8D8EA, #FFB7C5);
    }

    .toggle-switch input:checked + .toggle-slider::before {
        transform: translateX(18px);
    }
</style>

<style scoped>
    .settings-root {
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
        --c-shadow: rgba(180,140,200,0.12);
        min-height: 100vh;
        background: var(--c-bg);
        display: flex;
        flex-direction: column;
        overflow: hidden;
    }

    .header {
        background: linear-gradient(135deg, var(--c-blue-mid) 0%, var(--c-pink) 100%);
        padding: 20px 24px 18px;
        display: flex;
        flex-direction: column;
        gap: 3px;
        position: relative;
        overflow: hidden;
        flex-shrink: 0;
    }

        .header::before {
            content: "";
            position: absolute;
            top: -20px;
            right: -20px;
            width: 100px;
            height: 100px;
            border-radius: 50%;
            background: rgba(255,255,255,0.15);
        }

        .header::after {
            content: "";
            position: absolute;
            bottom: -30px;
            left: 40%;
            width: 120px;
            height: 120px;
            border-radius: 50%;
            background: rgba(255,255,255,0.1);
        }

    .header-icon {
        font-size: 11px;
        color: rgba(255,255,255,0.7);
        letter-spacing: 2px;
    }

    .header-title {
        font-size: 18px;
        font-weight: 700;
        color: white;
        text-shadow: 0 1px 4px rgba(0,0,0,0.1);
    }

    .header-sub {
        font-size: 12px;
        color: rgba(255,255,255,0.8);
    }

    .tabs {
        display: flex;
        padding: 12px 20px 0;
        background: var(--c-surface);
        border-bottom: 1.5px solid var(--c-border);
        flex-shrink: 0;
    }

    .tab-btn {
        flex: 1;
        padding: 9px 8px;
        border: none;
        border-radius: 10px 10px 0 0;
        background: transparent;
        cursor: pointer;
        font-size: 12px;
        font-family: inherit;
        color: var(--c-text-soft);
        font-weight: 500;
        transition: all 0.2s;
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 4px;
    }

        .tab-btn:hover {
            color: var(--c-text);
            background: var(--c-pink-light);
        }

        .tab-btn.active {
            color: var(--c-text);
            font-weight: 700;
            background: linear-gradient(to bottom, var(--c-pink-light), var(--c-bg));
            border-bottom: 2.5px solid var(--c-pink-mid);
        }

    .tab-icon {
        font-size: 14px;
    }

    .content {
        flex: 1;
        overflow-y: auto;
        padding: 16px 20px 20px;
        background: var(--c-bg);
    }

    /* tab-content 由各子组件自己渲染，父组件只提供外层容器 */
    :deep(.tab-content) {
        display: flex;
        flex-direction: column;
        gap: 14px;
    }
</style>