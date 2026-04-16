<script setup lang="ts">
import { ref, onMounted, onUnmounted } from "vue";
import { listen } from "@tauri-apps/api/event";
import { invoke } from "@tauri-apps/api/core";

import { useSizePreset } from "./composables/useSizePreset";
import { useLive2D } from "./composables/useLive2D";
import { useTTS } from "./composables/useTTS";
import { useWebSocket } from "./composables/useWebSocket";
import { useWindowManager } from "./composables/useWindowManager";

import SpeechBubble from "./components/mascot/SpeechBubble.vue";
import MascotArea from "./components/mascot/MascotArea.vue";

const isDev = import.meta.env.DEV;

// ── 1. 尺寸系统 ──────────────────────────────────────────────────────
const { sizePreset, sizeConfig, BASE_W, BASE_H, INPUT_W, BUBBLE_H } = useSizePreset();

// ── 2. Live2D ────────────────────────────────────────────────────────
const canvasRef = ref<HTMLCanvasElement | null>(null);
const {
    live2dReady,
    initLive2D, disposeLive2D, reloadLive2D,
    setEmotion, setMouthOpen,
} = useLive2D(canvasRef, BASE_W, BASE_H);

// ── 3. TTS ────────────────────────────────────────────────────────────
const { speakText, stopTTS, destroyTTS } = useTTS({ setMouthOpen });

// ── 4. 静音状态 ───────────────────────────────────────────────────────
const isMuted = ref(false);

// ── 5. WebSocket ─────────────────────────────────────────────────────
const {
    isConnected, isThinking,
    connectWS, disconnectWS,
    sendMessage, sendConfigure,
} = useWebSocket({
    onChatResponse: (cleanText, emotion) => {
        if (emotion) setEmotion(emotion);
        showBubbleWithText(cleanText);
        if (!isMuted.value) speakText(cleanText);
        console.info("[App] onChatResponse | emotion=%s len=%s", emotion, cleanText.length);
    },
    onVisionSpeech: (cleanText, emotion) => {
        if (emotion) setEmotion(emotion);
        showBubbleWithText(cleanText);
        if (!isMuted.value) speakText(cleanText);
        console.info("[App] onVisionSpeech | emotion=%s len=%s", emotion, cleanText.length);
    },
    onError: (message) => {
        showBubbleWithText("呜…出错了：" + message);
        console.error("[App] onError: %s", message);
    },
});

// ── 6. 窗口管理 ───────────────────────────────────────────────────────
const {
    inputOpen, userInput, bubbleText, showBubble,
    isLocked, showControls, showUnlock, inputRef,
    showBubbleWithText, toggleInput,
    onMascotEnter, onMascotLeave,
    toggleLock, unlockFromButton,
    startDrag, initWindowPosition,
} = useWindowManager({ isThinking, BASE_W, BASE_H, INPUT_W, BUBBLE_H });

// ── 发送消息 ─────────────────────────────────────────────────────────
function handleSend() {
    const msg = userInput.value.trim();
    if (!msg) {
        console.warn("[App] handleSend: 空消息，忽略");
        return;
    }
    if (!isConnected.value) {
        console.warn("[App] handleSend: WebSocket 未连接，忽略");
        return;
    }
    if (isThinking.value) {
        console.warn("[App] handleSend: AI 正在回复中，忽略");
        return;
    }
    console.debug("[App] handleSend: len=%s", msg.length);
    showBubble.value = false;
    userInput.value = "";
    sendMessage(msg);
}

function handleKeydown(e: KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSend();
    }
}

// ── 右键上下文菜单 ──────────────────────────────────────────────────
const contextMenuVisible = ref(false);
const contextMenuX = ref(0);
const contextMenuY = ref(0);

function handleContextMenu(e: MouseEvent) {
    if (!isDev) return;
    contextMenuX.value = e.clientX;
    contextMenuY.value = e.clientY;
    contextMenuVisible.value = true;
}

function closeContextMenu() {
    contextMenuVisible.value = false;
}

async function openDevTools() {
    closeContextMenu();
    try {
        await invoke("open_devtools");
        console.info("[App] DevTools 已打开");
    } catch (e) {
        console.error("[App] 打开 DevTools 失败:", e);
    }
}

// ── 托盘菜单动态同步 ────────────────────────────────────────────────
const SIDECAR_URL = "http://localhost:18000";

async function syncTrayMenu() {
    const presetsStr = localStorage.getItem("rl-presets");
    const presets = presetsStr ? JSON.parse(presetsStr) : [];
    const characters = presets.map((p: any) => ({ id: p.id, name: p.name }));
    const activeCharacterId = localStorage.getItem("rl-active-preset-id") ?? "";
    const activeModelPath = localStorage.getItem("rl-active-model") ?? "";

    let models: { id: string; name: string }[] = [];
    try {
        const resp = await fetch(`${SIDECAR_URL}/api/live2d/models`);
        if (resp.ok) {
            const raw = await resp.text();
            const data = JSON.parse(raw);
            models = data.models.map((m: any) => ({ id: m.path, name: m.display_name }));
        } else {
            console.warn("[App] syncTrayMenu: API 返回 %s", resp.status);
        }
    } catch (e) {
        console.warn("[App] syncTrayMenu: fetch 失败", e);
    }

    try {
        await invoke("update_menu_data", {
            characters,
            models,
            activeCharacterId,
            activeModelPath,
        });
        console.info("[App] syncTrayMenu 完成: %s 角色 / %s 模型 | active=%s",
            characters.length, models.length, activeCharacterId);
    } catch (e) {
        console.error("[App] syncTrayMenu invoke 失败:", e);
    }
}

// ── 便捷窗口操作 ─────────────────────────────────────────────────────
async function openSettings() {
    console.info("[App] 打开设置");
    await invoke("open_settings");
}

async function openHistory() {
    console.info("[App] 打开历史");
    await invoke("open_history");
}

// ── 生命周期 ─────────────────────────────────────────────────────────
const unlisten: (() => void)[] = [];

const onStorageChange = (e: StorageEvent) => {
    if (e.key === "rl-presets") {
        console.debug("[App] rl-presets 变更，重新同步托盘");
        syncTrayMenu();
    }
};

onMounted(async () => {
    console.info("[App] onMounted 开始");
    connectWS();

    await Promise.all([
        (async () => {
            await initWindowPosition();
            console.debug("[App] initWindowPosition 完成");
        })(),
        (async () => {
            await initLive2D();
            console.debug("[App] initLive2D 完成");
        })(),
    ]);

    // 后端就绪后同步托盘
    setTimeout(syncTrayMenu, 2000);

    // ── Tauri 事件监听 ─────────────────────────────────────────────
    unlisten.push(await listen("config-changed", (e) => {
        const payload = e.payload as {
            llm?: object;
            character?: object;
            memory_window?: number;
            character_id?: string;
            vision?: object;
            size_preset?: "small" | "medium" | "large";
        };
        if (payload.size_preset) {
            sizePreset.value = payload.size_preset;
        }
        sendConfigure(payload);
        syncTrayMenu();
        console.debug("[App] config-changed", payload);
    }));

    unlisten.push(await listen<string>("tray-switch-character", (e) => {
        const targetId = e.payload;
        const presets = JSON.parse(localStorage.getItem("rl-presets") || "[]");
        const target = presets.find((p: any) => p.id === targetId);
        if (target) {
            const charCfg = {
                name: target.name, identity: target.identity,
                personality: target.personality, address: target.address,
                style: target.style, examples: target.examples,
            };
            localStorage.setItem("rl-character", JSON.stringify(charCfg));
            localStorage.setItem("rl-active-preset-id", targetId);
            sendConfigure({ character: charCfg, character_id: targetId });
            showBubbleWithText(`已切换角色：${target.name}`);
            syncTrayMenu();
            console.info("[App] 托盘切换角色: %s", target.name);
        }
    }));

    unlisten.push(await listen<string>("tray-switch-model", async (e) => {
        const targetPath = e.payload;
        localStorage.setItem("rl-active-model", targetPath);
        await reloadLive2D(targetPath);
        showBubbleWithText("模型已切换");
        console.info("[App] 托盘切换模型: %s", targetPath);
    }));

    unlisten.push(await listen<boolean>("toggle-mute", (e) => {
        isMuted.value = e.payload;
        if (isMuted.value) stopTTS();
        console.info("[App] 静音状态: %s", isMuted.value);
    }));

    unlisten.push(await listen("reset-position", () => {
        localStorage.removeItem("mascot-anchor");
        console.info("[App] 窗口锚点已清除，位置已重置");
    }));

    unlisten.push(await listen("mascot-hover", (e) => {
        showUnlock.value = e.payload as boolean;
    }));

    unlisten.push(await listen("open-settings", async () => {
        await invoke("open_settings");
    }));

    unlisten.push(await listen("model-changed", async (e) => {
        const path = (e.payload as { path: string }).path;
        localStorage.setItem("rl-active-model", path);
        await reloadLive2D(path);
        syncTrayMenu();
        console.debug("[App] model-changed: %s", path);
    }));

    window.addEventListener("storage", onStorageChange);
    console.info("[App] onMounted 完成");
});

onUnmounted(() => {
    window.removeEventListener("storage", onStorageChange);
    disconnectWS();
    unlisten.forEach(fn => fn());
    disposeLive2D();
    destroyTTS();
    console.info("[App] onUnmounted 完成");
});
</script>

<template>
    <div class="mascot-root"
        @contextmenu.prevent="handleContextMenu"
        :style="{
            '--mascot-w': sizeConfig.baseW  + 'px',
            '--mascot-h': sizeConfig.baseH  + 'px',
            '--input-w':  sizeConfig.inputW  + 'px',
            '--bubble-h': sizeConfig.bubbleH + 'px',
        }">

        <!-- 气泡 -->
        <SpeechBubble
            :show-bubble="showBubble"
            :is-thinking="isThinking"
            :bubble-text="bubbleText"
        />

        <!-- 底部行 -->
        <div class="bottom-row">

            <!-- 输入面板 -->
            <transition name="panel">
                <div v-if="inputOpen" class="input-panel" @click.stop>
                    <textarea ref="inputRef"
                              v-model="userInput"
                              class="chat-input"
                              placeholder="说点什么…"
                              rows="4"
                              :disabled="!isConnected || isThinking"
                              @keydown="handleKeydown" />
                    <button class="send-btn"
                            :disabled="!isConnected || isThinking || !userInput.trim()"
                            @click="handleSend">
                        {{ isThinking ? "…" : "发送" }}
                    </button>
                </div>
            </transition>

            <!-- 角色区 -->
            <MascotArea
                :live2d-ready="live2dReady"
                :is-locked="isLocked"
                :show-controls="showControls"
                :show-unlock="showUnlock"
                :is-connected="isConnected"
                @start-drag="startDrag"
                @on-mascot-enter="onMascotEnter"
                @on-mascot-leave="onMascotLeave"
                @toggle-lock="toggleLock"
                @open-settings="openSettings"
                @open-history="openHistory"
                @toggle-input="toggleInput"
                @unlock-from-button="unlockFromButton"
            />
        </div>

        <!-- 右键上下文菜单 -->
        <Transition name="ctxmenu">
            <div v-if="contextMenuVisible"
                class="context-menu"
                :style="{ left: contextMenuX + 'px', top: contextMenuY + 'px' }"
                @click.stop>
                <div v-if="isDev" class="ctx-item" @click="openDevTools">
                    🔍 打开开发者工具
                </div>
            </div>
        </Transition>
        <!-- 点击其他区域关闭菜单 -->
        <div v-if="contextMenuVisible"
            class="context-menu-mask"
            @click="closeContextMenu"
            @contextmenu.prevent="closeContextMenu" />
    </div>
</template>

<style>
    *, *::before, *::after {
        margin: 0;
        padding: 0;
        box-sizing: border-box;
    }

    html, body {
        width: 100%;
        height: 100%;
        background: transparent !important;
        font-family: "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
        -webkit-font-smoothing: antialiased;
    }
</style>

<style scoped>
    .mascot-root {
        --clr-bubble-bg: rgba(255, 255, 255, 0.93);
        --clr-bubble-bd: rgba(200, 190, 220, 0.65);
        --clr-panel-bg: rgba(248, 245, 255, 0.96);
        --clr-accent: #b39ddb;
        --clr-accent-dark: #7e57c2;
        --clr-text: #3d3450;
        --clr-text-soft: #8878a8;
        width: 100vw;
        height: 100vh;
        background: transparent;
        display: flex;
        flex-direction: column;
        align-items: flex-end;
        justify-content: flex-end;
        pointer-events: none;
    }

    .bottom-row {
        display: flex;
        flex-direction: row;
        align-items: flex-end;
        justify-content: flex-end;
        width: 100%;
        position: relative;
    }

    /* ── 输入面板 ──────────────────────────────────────────────────── */
    .input-panel {
        position: absolute;
        right: var(--mascot-w, 280px);
        top: 50%;
        transform: translateY(-50%);
        width: var(--input-w, 240px);
        height: auto;
        background: var(--clr-panel-bg);
        border: 1.5px solid var(--clr-bubble-bd);
        border-radius: 14px;
        backdrop-filter: blur(16px);
        -webkit-backdrop-filter: blur(16px);
        box-shadow: -2px 4px 16px rgba(126, 87, 194, 0.12);
        padding: 12px;
        display: flex;
        flex-direction: column;
        gap: 8px;
        pointer-events: all;
    }

    .chat-input {
        flex: 1;
        width: 100%;
        resize: none;
        border: 1px solid var(--clr-bubble-bd);
        border-radius: 8px;
        padding: 8px 10px;
        font-size: 13px;
        line-height: 1.55;
        color: var(--clr-text);
        background: rgba(255, 255, 255, 0.85);
        outline: none;
        font-family: inherit;
        transition: border-color 0.2s;
    }

    .chat-input:focus {
        border-color: var(--clr-accent-dark);
    }

    .chat-input:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }

    .chat-input::placeholder {
        color: var(--clr-text-soft);
    }

    .send-btn {
        align-self: flex-end;
        padding: 5px 16px;
        border: none;
        border-radius: 20px;
        background: var(--clr-accent-dark);
        color: white;
        font-size: 12px;
        font-family: inherit;
        cursor: pointer;
        transition: opacity 0.2s, transform 0.1s;
    }

    .send-btn:hover:not(:disabled) {
        opacity: 0.82;
    }

    .send-btn:active:not(:disabled) {
        transform: scale(0.95);
    }

    .send-btn:disabled {
        opacity: 0.38;
        cursor: not-allowed;
    }

    /* ── 过渡动画 ──────────────────────────────────────────────────── */
    .panel-enter-active {
        transition: opacity 0.2s ease, transform 0.2s ease;
    }
    .panel-leave-active {
        transition: opacity 0.15s ease, transform 0.15s ease;
    }
    .panel-enter-from,
    .panel-leave-to {
        opacity: 0;
        transform: translateX(-10px);
    }

    /* ── 右键上下文菜单 ─────────────────────────────────────────────── */
    .context-menu-mask {
        position: fixed;
        inset: 0;
        z-index: 998;
    }

    .context-menu {
        position: fixed;
        z-index: 999;
        background: rgba(255, 255, 255, 0.92);
        border: 1px solid rgba(126, 87, 194, 0.2);
        border-radius: 8px;
        padding: 4px 0;
        min-width: 160px;
        backdrop-filter: blur(12px);
        box-shadow: 0 4px 16px rgba(0, 0, 0, 0.15);
        pointer-events: all;
    }

    .ctx-item {
        padding: 7px 14px;
        font-size: 12px;
        color: var(--clr-text);
        cursor: pointer;
        transition: background 0.15s;
        white-space: nowrap;
    }

    .ctx-item:hover {
        background: rgba(126, 87, 194, 0.1);
    }

    .ctxmenu-enter-active,
    .ctxmenu-leave-active {
        transition: opacity 0.12s ease, transform 0.12s ease;
    }

    .ctxmenu-enter-from,
    .ctxmenu-leave-to {
        opacity: 0;
        transform: scale(0.95);
    }
</style>
