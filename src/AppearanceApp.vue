<script setup lang="ts">
/**
 * AppearanceApp.vue — 装扮独立窗口
 *
 * 独立的 Tauri webview 窗口，从 Live2D Tab 的"装扮"按钮打开。
 * 内部承载 AppearancePanel 组件，提供完整的窗口框架（标题栏 + 样式）。
 */
import { ref, onMounted } from "vue";
import AppearancePanel from "./components/settings/Appearancepanel.vue";

const modelFolder = ref("");

onMounted(() => {
    const modelPath = localStorage.getItem("rl-model-path") ?? "";
    const parts = modelPath.replace(/\\/g, "/").split("/");
    if (parts.length >= 3 && parts[0] === "live2d") {
        modelFolder.value = parts[1];
    } else if (parts.length >= 2) {
        modelFolder.value = parts[parts.length - 2];
    }
});
</script>

<template>
    <div class="appearance-root">
        <div class="header">
            <div class="header-icon">🎨</div>
            <div class="header-title">装扮调整</div>
            <div class="header-sub" v-if="modelFolder">{{ modelFolder }}</div>
        </div>
        <div class="content">
            <AppearancePanel />
        </div>
    </div>
</template>

<style>
    *, *::before, *::after {
        margin: 0; padding: 0; box-sizing: border-box;
    }
    html, body {
        width: 100%; height: 100%;
        font-family: "Hiragino Sans GB", "Microsoft YaHei", "PingFang SC", sans-serif;
        -webkit-font-smoothing: antialiased;
        background: #FEF6FA;
    }
    ::-webkit-scrollbar { width: 6px; }
    ::-webkit-scrollbar-track { background: transparent; }
    ::-webkit-scrollbar-thumb { background: #FFCDD9; border-radius: 3px; }

    /* 全局表单样式（AppearancePanel 需要） */
    .field-hint {
        font-size: 11px;
        color: #9B8FB0;
        padding-left: 2px;
    }

    /* 弹框样式（重置确认弹窗需要） */
    .dialog-overlay {
        position: fixed; inset: 0;
        background: rgba(100,80,120,0.25);
        backdrop-filter: blur(4px);
        display: flex; align-items: center; justify-content: center;
        z-index: 200;
    }
    .dialog-box {
        width: 300px; background: #FFFFFF;
        border-radius: 18px; padding: 22px 20px 18px;
        box-shadow: 0 8px 32px rgba(126,87,194,0.18);
        display: flex; flex-direction: column; gap: 14px;
    }
    .dialog-title {
        font-size: 15px; font-weight: 700; color: #4A4A6A;
    }
    .dialog-body {
        display: flex; flex-direction: column; gap: 8px;
    }
    .dialog-actions {
        display: flex; gap: 10px; justify-content: flex-end;
    }
    .dialog-cancel {
        padding: 7px 18px; border: 1.5px solid rgba(212,184,224,0.45);
        border-radius: 20px; background: transparent; color: #9B8FB0;
        font-size: 13px; font-family: inherit; cursor: pointer;
    }
    .dialog-cancel:hover { background: #FFE4EC; }
    .dialog-confirm {
        padding: 7px 18px; border: none; border-radius: 20px;
        background: linear-gradient(135deg, #A8D8EA, #FFB7C5);
        color: white; font-size: 13px; font-weight: 600;
        font-family: inherit; cursor: pointer;
    }
    .dialog-confirm:hover { opacity: 0.88; }
    .dialog-enter-active { transition: opacity 0.2s ease; }
    .dialog-leave-active { transition: opacity 0.15s ease; }
    .dialog-enter-from, .dialog-leave-to { opacity: 0; }
</style>

<style scoped>
    .appearance-root {
        min-height: 100vh;
        display: flex;
        flex-direction: column;
        overflow: hidden;
    }

    .header {
        background: linear-gradient(135deg, #A8D8EA 0%, #FFB7C5 100%);
        padding: 16px 24px 14px;
        display: flex;
        align-items: center;
        gap: 10px;
        position: relative;
        overflow: hidden;
        flex-shrink: 0;
    }
    .header::before {
        content: ""; position: absolute; top: -20px; right: -20px;
        width: 80px; height: 80px; border-radius: 50%;
        background: rgba(255,255,255,0.15);
    }
    .header-icon { font-size: 18px; }
    .header-title {
        font-size: 16px; font-weight: 700; color: white;
        text-shadow: 0 1px 4px rgba(0,0,0,0.1);
    }
    .header-sub {
        font-size: 12px; color: rgba(255,255,255,0.8);
        margin-left: auto;
    }

    .content {
        flex: 1;
        overflow-y: auto;
        padding: 16px 20px 20px;
    }
</style>