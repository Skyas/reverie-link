<script setup lang="ts">
    let thinkingTimer: ReturnType<typeof setTimeout> | null = null;
    import { ref, nextTick, onMounted, onUnmounted, watch } from "vue";
    import {
        getCurrentWindow,
        PhysicalPosition,
        LogicalSize,
        primaryMonitor,
    } from "@tauri-apps/api/window";
    import { listen } from "@tauri-apps/api/event";
    import { invoke } from "@tauri-apps/api/core";

    // ── 窗口尺寸常量 ───────────────────────────────────────────────
    const BASE_W = 160;
    const BASE_H = 185;
    const INPUT_W = 210;
    const BUBBLE_H = 145;

    // ── 状态 ───────────────────────────────────────────────────────
    const isConnected = ref(false);
    const isThinking = ref(false);
    const inputOpen = ref(false);
    const userInput = ref("");
    const bubbleText = ref("");
    const showBubble = ref(false);
    const inputRef = ref<HTMLTextAreaElement | null>(null);
    const isLocked = ref(false);
    const showControls = ref(false);
    const showUnlock = ref(false);

    // ── 控制栏悬停显示 ─────────────────────────────────────────────
    let hideControlsTimer: ReturnType<typeof setTimeout> | null = null;

    function onMascotEnter() {
        if (isLocked.value) return;
        if (hideControlsTimer) clearTimeout(hideControlsTimer);
        showControls.value = true;
    }

    function onMascotLeave() {
        if (isLocked.value) return;
        hideControlsTimer = setTimeout(() => {
            showControls.value = false;
        }, 600);
    }

    // ── 锁定/解锁 ─────────────────────────────────────────────────
    async function toggleLock() {
        const newState = await invoke<boolean>("toggle_lock");
        isLocked.value = newState;
        if (newState) {
            showControls.value = false;
            inputOpen.value = false;
        }
    }

    async function unlockFromButton() {
        const newState = await invoke<boolean>("toggle_lock");
        isLocked.value = newState;
        showUnlock.value = false;
    }

    // ── 打开设置窗口 ───────────────────────────────────────────────
    async function openSettings() {
        await invoke("open_settings");
    }

    // ── 窗口动态缩放 ───────────────────────────────────────────────
    async function resizeToFit() {
        const win = getCurrentWindow();
        const pos = await win.outerPosition();
        const siz = await win.outerSize();
        const sf = (await primaryMonitor())?.scaleFactor ?? 1;

        const anchorX = pos.x + siz.width;
        const anchorY = pos.y + siz.height;

        const newLogicW = BASE_W + (inputOpen.value ? INPUT_W : 0);
        const newLogicH = BASE_H + (showBubble.value || isThinking.value ? BUBBLE_H : 0);

        const newPhysW = Math.round(newLogicW * sf);
        const newPhysH = Math.round(newLogicH * sf);

        await win.setSize(new LogicalSize(newLogicW, newLogicH));
        await win.setPosition(new PhysicalPosition(anchorX - newPhysW, anchorY - newPhysH));
    }

    watch([inputOpen, showBubble, isThinking], resizeToFit);

    // ── WebSocket ──────────────────────────────────────────────────
    const WS_URL = "ws://localhost:18000/ws/chat";
    let ws: WebSocket | null = null;

    function connectWS() {
        ws = new WebSocket(WS_URL);
        ws.onopen = () => { isConnected.value = true; };
        ws.onclose = () => { isConnected.value = false; setTimeout(connectWS, 3000); };
        ws.onerror = () => { ws?.close(); };
        ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            if (data.type === "chat_response") {
                isThinking.value = false;
                if (thinkingTimer) clearTimeout(thinkingTimer);
                showBubbleWithText(data.message);
            } else if (data.type === "error") {
                isThinking.value = false;
                if (thinkingTimer) clearTimeout(thinkingTimer);
                showBubbleWithText("呜…出错了：" + data.message);
            }
        };
    }

    // ── 打字机 ─────────────────────────────────────────────────────
    let typeTimer: ReturnType<typeof setTimeout> | null = null;
    let hideTimer: ReturnType<typeof setTimeout> | null = null;

    function showBubbleWithText(text: string) {
        if (typeTimer) clearTimeout(typeTimer);
        if (hideTimer) clearTimeout(hideTimer);
        bubbleText.value = "";
        showBubble.value = true;
        let i = 0;
        function typeNext() {
            if (i < text.length) {
                bubbleText.value += text[i++];
                typeTimer = setTimeout(typeNext, 40);
            } else {
                hideTimer = setTimeout(() => { showBubble.value = false; }, 8000);
            }
        }
        typeNext();
    }

    // ── 发送消息 ───────────────────────────────────────────────────
    function sendMessage() {
        const msg = userInput.value.trim();
        if (!msg || !isConnected.value || isThinking.value) return;

        isThinking.value = true;
        showBubble.value = false;
        userInput.value = "";

        // 30秒超时保护
        if (thinkingTimer) clearTimeout(thinkingTimer);
        thinkingTimer = setTimeout(() => {
            if (isThinking.value) {
                isThinking.value = false;
                showBubbleWithText("响应超时了，请检查网络或配置后重试。");
            }
        }, 30000);

        ws!.send(JSON.stringify({ type: "chat", message: msg }));
    }

    function handleKeydown(e: KeyboardEvent) {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    }

    // ── 输入框开关 ─────────────────────────────────────────────────
    function toggleInput() {
        inputOpen.value = !inputOpen.value;
        if (inputOpen.value) nextTick(() => inputRef.value?.focus());
    }

    // ── 拖拽 ───────────────────────────────────────────────────────
    async function startDrag() {
        await getCurrentWindow().startDragging();
    }

    // ── 初始化 ─────────────────────────────────────────────────────
    const unlisten: (() => void)[] = [];

    onMounted(async () => {
        connectWS();
        const win = getCurrentWindow();

        const saved = localStorage.getItem("mascot-anchor");
        const sf = (await primaryMonitor())?.scaleFactor ?? 1;

        if (saved) {
            const { ax, ay } = JSON.parse(saved);
            const physW = Math.round(BASE_W * sf);
            const physH = Math.round(BASE_H * sf);
            await win.setSize(new LogicalSize(BASE_W, BASE_H));
            await win.setPosition(new PhysicalPosition(ax - physW, ay - physH));
        } else {
            const monitor = await primaryMonitor();
            if (monitor) {
                const { width, height } = monitor.size;
                const margin = Math.round(16 * sf);
                const physW = Math.round(BASE_W * sf);
                const physH = Math.round(BASE_H * sf);
                await win.setSize(new LogicalSize(BASE_W, BASE_H));
                await win.setPosition(new PhysicalPosition(
                    width - physW - margin,
                    height - physH - margin
                ));
            }
        }

        await win.onMoved(async () => {
            const p = await win.outerPosition();
            const s = await win.outerSize();
            localStorage.setItem("mascot-anchor", JSON.stringify({
                ax: p.x + s.width,
                ay: p.y + s.height,
            }));
        });

        unlisten.push(await listen("passthrough-changed", (e) => {
            isLocked.value = e.payload as boolean;
            if (isLocked.value) {
                showControls.value = false;
                inputOpen.value = false;
            }
        }));

        unlisten.push(await listen("mascot-hover", (e) => {
            showUnlock.value = e.payload as boolean;
        }));

        unlisten.push(await listen("open-settings", async () => {
            await invoke("open_settings");
        }));
    });

    onUnmounted(() => {
        ws?.close();
        unlisten.forEach(fn => fn());
    });
</script>

<template>
    <div class="mascot-root">

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
                              rows="3"
                              :disabled="!isConnected || isThinking"
                              @keydown="handleKeydown" />
                    <button class="send-btn"
                            :disabled="!isConnected || isThinking || !userInput.trim()"
                            @click="sendMessage">
                        {{ isThinking ? "…" : "发送" }}
                    </button>
                </div>
            </transition>

            <!-- 角色区 -->
            <div class="mascot-area"
                 @mousedown="startDrag"
                 @mouseenter="onMascotEnter"
                 @mouseleave="onMascotLeave">
                <!-- 控制栏（未锁定时悬停显示） -->
                <transition name="controls">
                    <div v-if="showControls && !isLocked" class="controls-bar">
                        <button class="ctrl-btn" @mousedown.stop @click.stop="toggleLock" title="锁定">
                            🔓
                        </button>
                        <button class="ctrl-btn" @mousedown.stop @click.stop="openSettings" title="设置">
                            ⚙️
                        </button>
                        <button class="ctrl-btn" @mousedown.stop @click.stop title="音量">
                            🔊
                        </button>
                        <button class="ctrl-btn" @mousedown.stop @click.stop="toggleInput" title="输入">
                            💬
                        </button>
                    </div>
                </transition>

                <!-- 锁定状态下的解锁按钮（Rust轮询触发） -->
                <transition name="unlock">
                    <button v-if="isLocked && showUnlock"
                            class="unlock-btn"
                            @mousedown.stop
                            @click.stop="unlockFromButton">
                        🔒
                    </button>
                </transition>

                <!-- 角色占位 -->
                <div class="mascot-silhouette">
                    <div class="sil-head"></div>
                    <div class="sil-body"></div>
                </div>

                <div class="status-dot" :class="{ connected: isConnected }"></div>
            </div>
        </div>
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
        overflow: hidden;
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
    }

    /* ── 角色区 ───────────────────────────────────────────────── */
    .mascot-area {
        position: relative;
        width: 160px;
        height: 185px;
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

    .mascot-silhouette {
        display: flex;
        flex-direction: column;
        align-items: center;
        opacity: 0.18;
        margin-bottom: 8px;
    }

    .sil-head {
        width: 46px;
        height: 46px;
        border-radius: 50%;
        background: var(--clr-accent-dark);
    }

    .sil-body {
        width: 72px;
        height: 106px;
        border-radius: 36px 36px 18px 18px;
        background: var(--clr-accent-dark);
    }

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

    /* 逐个延迟滑入动画 */
    .controls-bar .ctrl-btn:nth-child(1) {
        transition-delay: 0s;
    }

    .controls-bar .ctrl-btn:nth-child(2) {
        transition-delay: 0.05s;
    }

    .controls-bar .ctrl-btn:nth-child(3) {
        transition-delay: 0.1s;
    }

    .controls-enter-active .ctrl-btn:nth-child(1) {
        animation: slideIn 0.2s ease forwards;
    }

    .controls-enter-active .ctrl-btn:nth-child(2) {
        animation: slideIn 0.2s 0.06s ease forwards;
    }

    .controls-enter-active .ctrl-btn:nth-child(3) {
        animation: slideIn 0.2s 0.12s ease forwards;
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

    /* ── 解锁按钮（锁定状态） ─────────────────────────────────── */
    .unlock-btn {
        position: absolute;
        left: 6px;
        top: 50%;
        transform: translateY(-50%);
        width: 30px;
        height: 30px;
        border: 1.5px solid rgba(255,255,255,0.6);
        border-radius: 50%;
        background: rgba(0,0,0,0.45);
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
        flex-shrink: 0;
        width: 200px;
        height: 185px;
        background: var(--clr-panel-bg);
        border: 1.5px solid var(--clr-bubble-bd);
        border-radius: 14px 14px 4px 14px;
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
        width: 155px;
        min-height: 60px;
        margin-right: 4px;
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

    /* ── 设置面板 ─────────────────────────────────────────────── */
    .settings-overlay {
        position: fixed;
        inset: 0;
        background: rgba(0,0,0,0.3);
        backdrop-filter: blur(4px);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 200;
        pointer-events: all;
    }

    .settings-panel {
        width: 320px;
        background: var(--clr-panel-bg);
        border: 1.5px solid var(--clr-bubble-bd);
        border-radius: 16px;
        box-shadow: 0 8px 32px rgba(126, 87, 194, 0.2);
        overflow: hidden;
    }

    .settings-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 14px 16px;
        border-bottom: 1px solid var(--clr-bubble-bd);
        font-size: 14px;
        font-weight: 600;
        color: var(--clr-text);
    }

    .close-btn {
        width: 24px;
        height: 24px;
        border: none;
        border-radius: 50%;
        background: rgba(0,0,0,0.08);
        cursor: pointer;
        font-size: 14px;
        display: flex;
        align-items: center;
        justify-content: center;
        color: var(--clr-text);
        transition: background 0.2s;
    }

        .close-btn:hover {
            background: rgba(0,0,0,0.15);
        }

    .settings-body {
        padding: 24px 16px;
    }

    .settings-placeholder {
        color: var(--clr-text-soft);
        font-size: 13px;
        text-align: center;
    }

    .settings-enter-active {
        transition: opacity 0.2s ease;
    }

    .settings-leave-active {
        transition: opacity 0.15s ease;
    }

    .settings-enter-from {
        opacity: 0;
    }

    .settings-leave-to {
        opacity: 0;
    }
</style>