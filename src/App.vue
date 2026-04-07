<script setup lang="ts">
    import { ref, onMounted, onUnmounted } from "vue";
    import { listen } from "@tauri-apps/api/event";
    import { invoke } from "@tauri-apps/api/core";

    import { useSizePreset } from "./composables/useSizePreset";
    import { useLive2D } from "./composables/useLive2D";
    import { useTTS } from "./composables/useTTS";
    import { useWebSocket } from "./composables/useWebSocket";
    import { useWindowManager } from "./composables/useWindowManager";

    // ── 1. 尺寸系统（跨模块共享的唯一数据源） ────────────────────────────
    // [FIX] 额外解构 sizePreset，用于响应 config-changed 中的尺寸切换
    const { sizePreset, sizeConfig, BASE_W, BASE_H, INPUT_W, BUBBLE_H } = useSizePreset();

    // ── 2. Live2D（表情 + 口型驱动，对其他模块无感知） ───────────────────
    const canvasRef = ref<HTMLCanvasElement | null>(null);
    const {
        live2dReady, live2dError,
        initLive2D, disposeLive2D, reloadLive2D,
        setEmotion, setMouthOpen,
    } = useLive2D(canvasRef, BASE_W, BASE_H);

    // ── 3. TTS（通过依赖注入接收 setMouthOpen，对 Live2D 无感知） ────────
    const { speakText, stopTTS, destroyTTS } = useTTS({ setMouthOpen });

    // ── 4. WebSocket（通过回调联结各模块，自身不引用任何其他 composable） ──
    // 注意：回调中引用的 showBubbleWithText 在下方第 5 步定义。
    // 由于回调是闭包（仅在消息到达时执行），到那时 showBubbleWithText 已初始化，安全。
    const {
        isConnected, isThinking,
        connectWS, disconnectWS,
        sendMessage, sendConfigure,
    } = useWebSocket({
        onChatResponse: (cleanText, emotion) => {
            if (emotion) setEmotion(emotion);
            showBubbleWithText(cleanText);
            speakText(cleanText);
        },
        onVisionSpeech: (cleanText, emotion) => {
            // 视觉感知主动发言：已在 useWebSocket 内部过滤 isThinking，此处直接处理
            if (emotion) setEmotion(emotion);
            showBubbleWithText(cleanText);
            speakText(cleanText);
        },
        onError: (message) => {
            showBubbleWithText("呜…出错了：" + message);
        },
    });

    // ── 5. 窗口管理（接收 isThinking 用于 resizeToFit watch） ─────────────
    const {
        inputOpen, userInput, bubbleText, showBubble,
        isLocked, showControls, showUnlock, inputRef,
        showBubbleWithText, toggleInput,
        onMascotEnter, onMascotLeave,
        toggleLock, unlockFromButton,
        startDrag, initWindowPosition,
    } = useWindowManager({ isThinking, BASE_W, BASE_H, INPUT_W, BUBBLE_H });

    // ── 发送消息（在 App.vue 层组合 WS 发送 + 本地 UI 状态重置） ─────────
    function handleSend() {
        const msg = userInput.value.trim();
        if (!msg || !isConnected.value || isThinking.value) return;
        showBubble.value = false;  // 立即隐藏旧气泡
        userInput.value = "";
        sendMessage(msg);           // 内部设置 isThinking = true 并发送
    }

    function handleKeydown(e: KeyboardEvent) {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            handleSend();
        }
    }

    // ── 便捷窗口操作（保持在 App.vue 层，逻辑极简不值得单独 composable） ─
    async function openSettings() { await invoke("open_settings"); }
    async function openHistory() { await invoke("open_history"); }

    // ── 生命周期 ──────────────────────────────────────────────────────
    const unlisten: (() => void)[] = [];

    onMounted(async () => {
        console.time("[⏱ onMounted 总耗时]");
        connectWS();

        const [,, ...unlisteners] = await Promise.all([
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
            listen("config-changed", (e) => {
                const payload = e.payload as {
                    llm?: object; character?: object;
                    memory_window?: number; character_id?: string; vision?: object;
                };
                sendConfigure(payload);
            }),
            listen("mascot-hover", (e) => {
                showUnlock.value = e.payload as boolean;
            }),
            listen("open-settings", async () => {
                await invoke("open_settings");
            }),
            listen("model-changed", async (e) => {
                const path = (e.payload as { path: string }).path;
                await reloadLive2D(path);
            }),
        ]);

        unlisten.push(...unlisteners);
        console.timeEnd("[⏱ onMounted 总耗时]");
        // Tauri 事件监听
        unlisten.push(await listen("config-changed", (e) => {
            const payload = e.payload as {
                llm?: object;
                character?: object;
                memory_window?: number;
                character_id?: string;
                vision?: object;
                // [FIX] 新增尺寸预设字段，由 SettingsApp.vue 在保存时填入
                size_preset?: "small" | "medium" | "large";
            };

            // [FIX] 尺寸切换：直接更新 sizePreset ref，
            // BASE_W/INPUT_W 等 computed 会自动联动，
            // useWindowManager 内部的 watch(BASE_W) 会触发 resizeToFit()
            if (payload.size_preset) {
                sizePreset.value = payload.size_preset;
            }

            sendConfigure(payload);
        }));

        unlisten.push(await listen("mascot-hover", (e) => {
            showUnlock.value = e.payload as boolean;
        }));

        unlisten.push(await listen("open-settings", async () => {
            await invoke("open_settings");
        }));

        unlisten.push(await listen("model-changed", async (e) => {
            const path = (e.payload as { path: string }).path;
            await reloadLive2D(path);
        }));

        // Live2D 初始化（最后执行，不阻塞上方逻辑）
        await initLive2D();
    });

    onUnmounted(() => {
        disconnectWS();
        unlisten.forEach(fn => fn());
        disposeLive2D();
        destroyTTS();
    });
</script>

<template>
    <div class="mascot-root"
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
                              rows="3"
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
        bottom: 0;
        width: var(--input-w, 240px);
        height: var(--mascot-h, 380px);
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
</style>