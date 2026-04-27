/**
 * useVoiceInput.ts — 音频采集 + VAD（语音输入前端模块）
 *
 * 职责：
 *   - 通过 getUserMedia 采集麦克风音频
 *   - 使用 @ricky0123/vad-web (Silero VAD WASM) 检测语音起止
 *   - onSpeechStart 时通知外部（用于打断 TTS）
 *   - onSpeechEnd 时输出整段 Float32 音频 + 时长
 *   - 管理麦克风启停状态
 *
 * 依赖：
 *   npm install @ricky0123/vad-web
 */

import { ref } from "vue";

export interface VoiceInputCallbacks {
    onSpeechStart: () => void;
    onSpeechEnd: (audio: Float32Array, durationMs: number) => void;
    onError: (message: string) => void;
}

export function useVoiceInput(callbacks: VoiceInputCallbacks) {
    const isListening    = ref(false);
    const isUserSpeaking = ref(false);

    let destroyFn: (() => void) | null = null;

    /**
     * 启动麦克风监听与 VAD。
     * 需在用户手势（如点击）后调用，以满足浏览器自动播放策略。
     */
    async function startListening(): Promise<void> {
        if (isListening.value) return;

        try {
            const { MicVAD } = await import("@ricky0123/vad-web");

            const vad = await MicVAD.new({
                additionalAudioConstraints: {
                    echoCancellation: true,    // WebView2 等价于 "all"
                    noiseSuppression: true,
                    autoGainControl: true,
                } as any,
                positiveSpeechThreshold: 0.4,
                negativeSpeechThreshold: 0.35,
                minSpeechFrames: 3,
                preSpeechPadFrames: 15,     // ~1.44s 预缓冲
                redemptionFrames: 10,       // 句中停顿容忍
                onSpeechStart: () => {
                    isUserSpeaking.value = true;
                    callbacks.onSpeechStart();
                },
                onSpeechEnd: (audio: Float32Array) => {
                    isUserSpeaking.value = false;
                    const durationMs = (audio.length / 16000) * 1000;
                    callbacks.onSpeechEnd(audio, durationMs);
                },
            });

            destroyFn = () => vad.destroy();

            vad.start();
            isListening.value = true;
            console.log("[VoiceInput] 麦克风监听已启动");
        } catch (e: any) {
            console.error("[VoiceInput] 启动失败:", e);
            callbacks.onError(e?.message || "麦克风启动失败");
        }
    }

    function stopListening(): void {
        if (!isListening.value) return;

        try {
            destroyFn?.();
        } catch (e) {
            console.warn("[VoiceInput] 停止时异常:", e);
        }

        destroyFn = null;
        isListening.value = false;
        isUserSpeaking.value = false;
        console.log("[VoiceInput] 麦克风监听已停止");
    }

    function destroyVoiceInput(): void {
        stopListening();
    }

    return {
        isListening,
        isUserSpeaking,
        startListening,
        stopListening,
        destroyVoiceInput,
    };
}
