/**
 * useWebSocket.ts — WebSocket 连接管理 + 消息收发
 *
 * 职责：
 *   - 建立 / 断开 / 自动重连 WebSocket
 *   - WS 连接建立后自动发送 configure（从 localStorage 读取）
 *   - 解析 chat_response / vision_proactive_speech / error 消息
 *   - 维护 isConnected、isThinking 状态
 *   - 响应超时保护（30s）
 *
 * 依赖注入（回调）：
 *   onChatResponse  — AI 回复到达时调用
 *   onVisionSpeech  — 视觉感知主动发言时调用
 *   onError         — 错误或超时时调用
 *
 * 不知道 Live2D、TTS、窗口几何的存在，仅通过回调通知外部。
 * parseEmotion 作为内部工具函数，不暴露给外部。
 */

import { ref } from "vue";
import { parseEmotion, type EmotionTag } from "./utils/emotion";

const WS_URL = "ws://localhost:18000/ws/chat";
const RECONNECT_DELAY_MS = 3000;
const THINKING_TIMEOUT_MS = 30000;

// ── 回调接口定义 ──────────────────────────────────────────────────────
export interface WebSocketCallbacks {
    onChatResponse: (cleanText: string, emotion: EmotionTag | null) => void;
    onVisionSpeech: (cleanText: string, emotion: EmotionTag | null) => void;
    onError:        (message: string) => void;
}

// ── configure payload 类型 ────────────────────────────────────────────
export interface ConfigurePayload {
    llm?:          object;
    character?:    object;
    memory_window?: number;
    character_id?: string;
    vision?:       object;
}

// ── 主体 ──────────────────────────────────────────────────────────────
export function useWebSocket(callbacks: WebSocketCallbacks) {
    const isConnected = ref(false);
    const isThinking  = ref(false);

    let ws:            WebSocket | null = null;
    let thinkingTimer: ReturnType<typeof setTimeout> | null = null;

    // ── 发送配置 ──────────────────────────────────────────────────────
    function sendConfigure(payload: ConfigurePayload) {
        if (!ws || ws.readyState !== WebSocket.OPEN) return;
        ws.send(JSON.stringify({
            type:         "configure",
            llm:          payload.llm          ?? {},
            character:    payload.character    ?? {},
            memory_window: payload.memory_window
                ?? parseInt(localStorage.getItem("rl-memory-window") ?? "1", 10),
            character_id: payload.character_id
                ?? localStorage.getItem("rl-active-preset-id") ?? "",
            ...(payload.vision ? { vision: payload.vision } : {}),
        }));
    }

    /** WS 连接建立后，自动推送 localStorage 中已保存的配置到后端 */
    function autoSendStoredConfig() {
        const savedLLM  = localStorage.getItem("rl-llm");
        const savedChar = localStorage.getItem("rl-character");
        if (!savedLLM && !savedChar) return;

        const llmCfg  = savedLLM  ? JSON.parse(savedLLM)  : {};
        const charCfg = savedChar ? JSON.parse(savedChar) : {};
        const windowIdx = parseInt(localStorage.getItem("rl-memory-window") ?? "1", 10);
        const charId    = localStorage.getItem("rl-active-preset-id") ?? "";

        let visionCfg: object | undefined;
        try {
            const v = localStorage.getItem("rl-vision");
            visionCfg = v ? JSON.parse(v) : undefined;
        } catch { visionCfg = undefined; }

        sendConfigure({
            llm:          llmCfg,
            character:    charCfg,
            memory_window: isNaN(windowIdx) ? 1 : windowIdx,
            character_id:  charId,
            ...(visionCfg ? { vision: visionCfg } : {}),
        });
    }

    // ── 发送消息 ──────────────────────────────────────────────────────
    function sendMessage(msg: string) {
        if (!msg.trim() || !isConnected.value || isThinking.value) return;

        isThinking.value = true;

        if (thinkingTimer) clearTimeout(thinkingTimer);
        thinkingTimer = setTimeout(() => {
            if (isThinking.value) {
                isThinking.value = false;
                callbacks.onError("响应超时了，请检查网络或配置后重试。");
            }
        }, THINKING_TIMEOUT_MS);

        ws!.send(JSON.stringify({ type: "chat", message: msg }));
    }

    // ── 消息处理 ──────────────────────────────────────────────────────
    function handleMessage(event: MessageEvent) {
        const data = JSON.parse(event.data);

        if (data.type === "chat_response") {
            isThinking.value = false;
            if (thinkingTimer) { clearTimeout(thinkingTimer); thinkingTimer = null; }
            const { cleanText, emotion } = parseEmotion(data.message);
            console.log("[chat emotion]", emotion, cleanText);
            callbacks.onChatResponse(cleanText, emotion);

        } else if (data.type === "vision_proactive_speech") {
            // 视觉感知主动发言：仅在用户未等待回复时处理（不打断思考状态）
            if (!isThinking.value) {
                const { cleanText, emotion } = parseEmotion(data.message);
                console.log('[emotion]', emotion, cleanText)
                callbacks.onVisionSpeech(cleanText, emotion);
            }

        } else if (data.type === "error") {
            isThinking.value = false;
            if (thinkingTimer) { clearTimeout(thinkingTimer); thinkingTimer = null; }
            callbacks.onError(data.message);
        }
    }

    // ── 连接管理 ──────────────────────────────────────────────────────
    function connectWS() {
        ws = new WebSocket(WS_URL);

        ws.onopen = () => {
            isConnected.value = true;
            autoSendStoredConfig();
        };

        ws.onclose = () => {
            isConnected.value = false;
            setTimeout(connectWS, RECONNECT_DELAY_MS);
        };

        ws.onerror = () => { ws?.close(); };

        ws.onmessage = handleMessage;
    }

    function disconnectWS() {
        ws?.close();
    }

    return {
        isConnected,
        isThinking,
        connectWS,
        disconnectWS,
        sendMessage,
        sendConfigure,
    };
}