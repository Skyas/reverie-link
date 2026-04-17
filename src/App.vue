<script setup lang="ts">
import { ref, onMounted, onUnmounted } from "vue";
import { listen } from "@tauri-apps/api/event";
import { invoke } from "@tauri-apps/api/core";

import { useSizePreset } from "./composables/useSizePreset";
import { useLive2D } from "./composables/useLive2D";
import { useTTS } from "./composables/useTTS";
import { useWebSocket } from "./composables/useWebSocket";
import { useWindowManager } from "./composables/useWindowManager";

const isDev = import.meta.env.DEV;

// ── 1. 尺寸系统（跨模块共享的唯一数据源） ────────────────────────────
const { sizePreset, sizeConfig, BASE_W, BASE_H, INPUT_W, BUBBLE_H } = useSizePreset();

// ── 2. Live2D ──────────────────────────────────────────────────────────
const canvasRef = ref<HTMLCanvasElement | null>(null);
const {
    live2dReady, live2dError,
    initLive2D, disposeLive2D, reloadLive2D,
    setEmotion, setMouthOpen,
} = useLive2D(canvasRef, BASE_W, BASE_H);

// ── 3. TTS ─────────────────────────────────────────────────────────────
const { speakText, stopTTS, destroyTTS, syncConfigToBackend } = useTTS({ setMouthOpen });

// ── 4. 静音状态（由托盘菜单控制，前端音频层生效）────────────────────────
const isMuted = ref(false);

// ── 5. WebSocket ───────────────────────────────────────────────────────
const {
    isConnected, isThinking,
    connectWS, disconnectWS,
    sendMessage, sendConfigure,
} = useWebSocket({
    onChatResponse: (cleanText, emotion) => {
        if (emotion) setEmotion(emotion);
        showBubbleWithText(cleanText);
        if (!isMuted.value) speakText(cleanText, emotion || "neutral");
    },
    onVisionSpeech: (cleanText, emotion) => {
        if (emotion) setEmotion(emotion);
        showBubbleWithText(cleanText);
        if (!isMuted.value) speakText(cleanText, emotion || "neutral");
    },
    onError: (message) => {
        showBubbleWithText("呜…出错了：" + message);
    },
});

// ── 6. 窗口管理 ────────────────────────────────────────────────────────
const {
    inputOpen, userInput, bubbleText, showBubble,
    isLocked, showControls, showUnlock, inputRef,
    showBubbleWithText, toggleInput,
    onMascotEnter, onMascotLeave,
    toggleLock, unlockFromButton,
    startDrag, initWindowPosition,
} = useWindowManager({ isThinking, BASE_W, BASE_H, INPUT_W, BUBBLE_H });

// ── 发送消息 ───────────────────────────────────────────────────────────
function handleSend() {
    const msg = userInput.value.trim();
    if (!msg || !isConnected.value || isThinking.value) return;
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

// ── 右键上下文菜单（DevTools 入口，开发期专用）────────────────────────
// 正式版保留此结构，未来可扩展菜单项；DevTools 项仅在 DEV 模式下渲染
const contextMenuVisible = ref(false);
const contextMenuX = ref(0);
const contextMenuY = ref(0);

function handleContextMenu(e: MouseEvent) {
    // 仅开发模式下显示菜单（正式版暂无菜单项，直接 return）
    if (!import.meta.env.DEV) return;
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
        console.log("[App] DevTools 已打开");
    } catch (e) {
        console.error("[App] 打开 DevTools 失败:", e);
    }
}

// ── 托盘菜单动态同步 ──────────────────────────────────────────────────
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
            console.log("[syncTrayMenu] API 原始响应:", raw); // ← 问题3调试用
            const data = JSON.parse(raw);
            models = data.models.map((m: any) => ({ id: m.path, name: m.display_name }));
        } else {
            console.warn("[syncTrayMenu] API 返回非 200:", resp.status);
        }
    } catch (e) {
        console.warn("[syncTrayMenu] fetch 失败:", e);
    }

    try {
        await invoke("update_menu_data", {
            characters,
            models,
            activeCharacterId,
            activeModelPath,
        });
        console.log(`[syncTrayMenu] 同步完成: ${characters.length} 角色 / ${models.length} 模型 | 激活角色=${activeCharacterId} 激活模型=${activeModelPath}`);
    } catch (e) {
        console.error("[syncTrayMenu] invoke 失败:", e);
    }
}

// ── 便捷窗口操作 ───────────────────────────────────────────────────────
async function openSettings() { await invoke("open_settings"); }
async function openHistory() { await invoke("open_history"); }

// ── 生命周期 ───────────────────────────────────────────────────────────
const unlisten: (() => void)[] = [];

const onStorageChange = (e: StorageEvent) => {
    if (e.key === "rl-presets") {
        console.log("[App] presets 变更检测到，重新同步托盘");
        syncTrayMenu();
        }
    };

onMounted(async () => {
    console.time("[⏱ onMounted 总耗时]");
    connectWS();

    // TTS：将 localStorage 中保存的配置同步给后端（后端重启时恢复状态）
    syncConfigToBackend().catch(e => console.warn("[TTS] 启动同步失败:", e));

    // 并行：窗口位置初始化 + Live2D 初始化
    await Promise.all([
        (async () => {
            console.time("[⏱ initWindowPosition]");
            await initWindowPosition();
            console.timeEnd("[⏱ initWindowPosition]");
        })(),
        (async () => {
            console.time("[⏱ initLive2D]");
            await initLive2D();
            console.timeEnd("[⏱ initLive2D]");
        })(),
    ]);

    // 后端就绪后同步托盘（延迟 2s 确保 sidecar 已启动）
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
        // 配置变更时重新同步（如角色增删、模型增删）
        syncTrayMenu();
    }));

    // 托盘：切换角色
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
        syncTrayMenu(); // ← 新增：更新勾选
        console.log(`[App] 托盘切换角色: ${target.name}`);
        }
    }));

    // 托盘：切换模型
    unlisten.push(await listen<string>("tray-switch-model", async (e) => {
        const targetPath = e.payload;
        localStorage.setItem("rl-active-model", targetPath); // ← 新增：持久化激活状态
        await reloadLive2D(targetPath);
        showBubbleWithText("模型已切换");
        console.log(`[App] 托盘切换模型: ${targetPath}`);
        // 勾选已在 Rust 侧立即更新，无需再调 syncTrayMenu
    }));    

    // 托盘：静音 / 取消静音（前端音频层控制，不影响后端 TTS 生成）
    unlisten.push(await listen<boolean>("toggle-mute", (e) => {
        isMuted.value = e.payload;
        if (isMuted.value) stopTTS(); // 立即停止当前正在播放的音频
        console.log(`[App] 静音状态: ${isMuted.value}`);
    }));

    // 托盘：重置位置（Rust 已完成 center，前端清除保存的锚点防止重启后恢复旧位置）
    unlisten.push(await listen("reset-position", () => {
        localStorage.removeItem("mascot-anchor");
        console.log("[App] 窗口锚点已清除，位置已重置");
    }));

    unlisten.push(await listen("mascot-hover", (e) => {
        showUnlock.value = e.payload as boolean;
    }));

    unlisten.push(await listen("open-settings", async () => {
        await invoke("open_settings");
    }));

    unlisten.push(await listen("model-changed", async (e) => {
        const path = (e.payload as { path: string }).path;
        localStorage.setItem("rl-active-model", path); // ← 新增
        await reloadLive2D(path);
        syncTrayMenu(); // 通知 Rust 侧更新勾选
    }));
    
    window.addEventListener("storage", onStorageChange);

    console.timeEnd("[⏱ onMounted 总耗时]");
});

onUnmounted(() => {
    window.removeEventListener("storage", onStorageChange);
    disconnectWS();
    unlisten.forEach(fn => fn());
    disposeLive2D();
    destroyTTS();
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
        <transition name="bubble">
            <div v-if="showBubble || isThinking" class="speech-bubble">
                <span v-if="isThinking" class="thinking-dots">
                    <span></span><span></span><span></span>
                </span>
                <span v-else class="bubble-text">{{ bubbleText }}</span>
                <div class="bubble-tail"></div>
            </div>
        </transition>

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
            <div class="mascot-area"
                 :class="{ locked: isLocked }"
                 @mousedown="startDrag"
                 @mouseenter="onMascotEnter"
                 @mouseleave="onMascotLeave">

                <!-- Live2D 画布 -->
                <canvas ref="canvasRef" class="live2d-canvas" />

                <!-- Live2D 未就绪时显示占位剪影 -->
                <div v-if="!live2dReady" class="mascot-silhouette">
                    <div class="sil-head"></div>
                    <div class="sil-body"></div>
                </div>

                <!-- 控制栏（未锁定时悬停显示） -->
                <transition name="controls">
                    <div v-if="showControls && !isLocked" class="controls-bar">
                        <button class="ctrl-btn" @mousedown.stop @click.stop="toggleLock" title="锁定">🔓</button>
                        <button class="ctrl-btn" @mousedown.stop @click.stop="openSettings" title="设置">⚙️</button>
                        <button class="ctrl-btn" @mousedown.stop @click.stop="openHistory" title="聊天记录">📋</button>
                        <button class="ctrl-btn" @mousedown.stop @click.stop title="音量">🔊</button>
                        <button class="ctrl-btn" @mousedown.stop @click.stop="toggleInput" title="输入">💬</button>
                    </div>
                </transition>

                <!-- 锁定状态解锁按钮 -->
                <transition name="unlock">
                    <button v-if="isLocked && showUnlock"
                            class="unlock-btn"
                            @mousedown.stop
                            @click.stop="unlockFromButton">
                        🔒
                    </button>
                </transition>

                <div class="status-dot" :class="{ connected: isConnected }"></div>
            </div>
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

    /* ── 角色区 ───────────────────────────────────────────────── */
    .mascot-area {
        position: relative;
        width: var(--mascot-w, 280px);
        height: var(--mascot-h, 380px);
        flex-shrink: 0;
        display: flex;
        align-items: flex-end;
        justify-content: center;
        pointer-events: all;
        cursor: grab;
    }

        .mascot-area:active {
            cursor: grabbing;
        }

        .mascot-area.locked {
            cursor: default;
        }

            .mascot-area.locked:active {
                cursor: default;
            }

    /* ── Live2D 画布 ──────────────────────────────────────────── */
    .live2d-canvas {
        position: absolute;
        top: 0;
        left: 0;
        pointer-events: none;
        z-index: 1;
        will-change: transform;
    }

    /* ── 占位剪影 ─────────────────────────────────────────────── */
    .mascot-silhouette {
        position: absolute;
        bottom: 12px;
        display: flex;
        flex-direction: column;
        align-items: center;
        opacity: 0.15;
        z-index: 1;
        pointer-events: none;
    }

    .sil-head {
        width: 60px;
        height: 60px;
        border-radius: 50%;
        background: var(--clr-accent-dark);
    }

    .sil-body {
        width: 90px;
        height: 140px;
        border-radius: 45px 45px 22px 22px;
        background: var(--clr-accent-dark);
    }

    /* ── 状态指示点 ───────────────────────────────────────────── */
    .status-dot {
        position: absolute;
        bottom: 6px;
        right: 8px;
        width: 7px;
        height: 7px;
        border-radius: 50%;
        background: #ccc;
        transition: background 0.4s;
        pointer-events: none;
        z-index: 10;
    }

        .status-dot.connected {
            background: #81c784;
        }

    /* ── 控制栏 ───────────────────────────────────────────────── */
    .controls-bar {
        position: absolute;
        left: 6px;
        top: 50%;
        transform: translateY(-50%);
        display: flex;
        flex-direction: column;
        gap: 6px;
        z-index: 20;
    }

    .ctrl-btn {
        width: 30px;
        height: 30px;
        border: 1.5px solid var(--clr-bubble-bd);
        border-radius: 50%;
        background: rgba(255, 255, 255, 0.9);
        backdrop-filter: blur(8px);
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 14px;
        transition: background 0.2s, transform 0.15s;
        pointer-events: all;
        box-shadow: 0 2px 8px rgba(126, 87, 194, 0.15);
    }

        .ctrl-btn:hover {
            background: var(--clr-accent);
            transform: scale(1.1);
        }

    /* 控制栏按钮逐一错开入场动画 */
    .controls-enter-active .ctrl-btn:nth-child(1) {
        animation: slideIn 0.2s ease forwards;
    }

    .controls-enter-active .ctrl-btn:nth-child(2) {
        animation: slideIn 0.2s 0.06s ease forwards;
    }

    .controls-enter-active .ctrl-btn:nth-child(3) {
        animation: slideIn 0.2s 0.12s ease forwards;
    }

    .controls-enter-active .ctrl-btn:nth-child(4) {
        animation: slideIn 0.2s 0.18s ease forwards;
    }

    .controls-enter-active .ctrl-btn:nth-child(5) {
        animation: slideIn 0.2s 0.24s ease forwards;
    }

    .controls-leave-active {
        transition: opacity 0.15s ease;
    }

    .controls-enter-from {
        opacity: 0;
    }

    .controls-leave-to {
        opacity: 0;
    }

    @keyframes slideIn {
        from {
            opacity: 0;
            transform: translateX(10px);
        }

        to {
            opacity: 1;
            transform: translateX(0);
        }
    }

    /* ── 解锁按钮 ─────────────────────────────────────────────── */
    .unlock-btn {
        position: absolute;
        left: 6px;
        top: 50%;
        transform: translateY(-50%);
        width: 30px;
        height: 30px;
        border: 1.5px solid rgba(255, 255, 255, 0.6);
        border-radius: 50%;
        background: rgba(0, 0, 0, 0.45);
        backdrop-filter: blur(8px);
        cursor: pointer;
        font-size: 15px;
        display: flex;
        align-items: center;
        justify-content: center;
        pointer-events: all;
        z-index: 30;
    }

    .unlock-enter-active {
        transition: opacity 0.3s ease, transform 0.3s ease;
    }

    .unlock-leave-active {
        transition: opacity 0.2s ease;
    }

    .unlock-enter-from {
        opacity: 0;
        transform: translate(-50%, -40%);
    }

    .unlock-leave-to {
        opacity: 0;
    }

    /* ── 输入面板 ─────────────────────────────────────────────── */
    .input-panel {
        position: absolute;
        right: var(--mascot-w, 280px);
        top: 50%;
        transform: translateY(-50%);
        width: var(--input-w, 240px);
        height: auto;
        background: var(--clr-panel-bg);
        border: 1.5px solid var(--clr-bubble-bd);
        border-radius: 14px 14px 14px 14px;
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

    /* ── 气泡 ─────────────────────────────────────────────────── */
    .speech-bubble {
        width: calc(var(--mascot-w, 280px) - 12px);
        min-height: 60px;
        margin-right: 6px;
        margin-bottom: 4px;
        background: var(--clr-bubble-bg);
        border: 1.5px solid var(--clr-bubble-bd);
        border-radius: 14px;
        padding: 10px 13px;
        backdrop-filter: blur(12px);
        -webkit-backdrop-filter: blur(12px);
        box-shadow: 0 4px 18px rgba(126, 87, 194, 0.11);
        pointer-events: none;
        position: relative;
        align-self: flex-end;
    }

    .bubble-text {
        font-size: 13px;
        line-height: 1.65;
        color: var(--clr-text);
        white-space: pre-wrap;
        word-break: break-all;
    }

    .bubble-tail {
        position: absolute;
        bottom: -8px;
        right: 24px;
        width: 0;
        height: 0;
        border-left: 7px solid transparent;
        border-right: 7px solid transparent;
        border-top: 8px solid var(--clr-bubble-bg);
    }

    .thinking-dots {
        display: flex;
        gap: 5px;
        padding: 4px 0;
    }

        .thinking-dots span {
            width: 6px;
            height: 6px;
            border-radius: 50%;
            background: var(--clr-accent);
            animation: bounce 1.2s infinite ease-in-out;
        }

            .thinking-dots span:nth-child(2) {
                animation-delay: 0.2s;
            }

            .thinking-dots span:nth-child(3) {
                animation-delay: 0.4s;
            }

    @keyframes bounce {
        0%, 80%, 100% {
            transform: translateY(0);
            opacity: 0.4;
        }

        40% {
            transform: translateY(-5px);
            opacity: 1;
        }
    }

    .bubble-enter-active {
        transition: opacity 0.25s ease, transform 0.22s ease;
    }

    .bubble-leave-active {
        transition: opacity 0.2s ease, transform 0.18s ease;
    }

    .bubble-enter-from {
        opacity: 0;
        transform: translateY(8px);
    }

    .bubble-leave-to {
        opacity: 0;
        transform: translateY(-4px);
    }

    .panel-enter-active {
        transition: opacity 0.2s ease, transform 0.2s ease;
    }

    .panel-leave-active {
        transition: opacity 0.15s ease, transform 0.15s ease;
    }

    .panel-enter-from {
        opacity: 0;
        transform: translateX(-10px);
    }

    .panel-leave-to {
        opacity: 0;
        transform: translateX(-10px);
    }

    /* ── 右键上下文菜单 ─────────────────────────────────────────── */
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