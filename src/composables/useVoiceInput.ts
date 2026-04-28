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
 *
 * 注意：
 *   - 首次启动时需从 CDN 下载 ~2MB ONNX 模型 + ~10MB WASM 文件，可能需要几秒
 *   - 生产环境若需离线使用，应将模型和 WASM 文件放入 public/ 目录并配置本地路径
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
    // 用于防止竞态条件：startListening() 异步初始化期间被 stopListening() 打断
    let _shouldBeRunning = false;

    /**
     * 启动麦克风监听与 VAD。
     * 需在用户手势（如点击）后调用，以满足浏览器自动播放策略。
     */
    async function startListening(): Promise<void> {
        if (isListening.value || _shouldBeRunning) {
            console.log("[VoiceInput] 已经在监听中或正在启动，跳过");
            return;
        }
        _shouldBeRunning = true;

        console.log("[VoiceInput] 开始启动麦克风监听...");

        try {
            // 1. 获取麦克风权限与音频流
            console.log("[VoiceInput] 请求 getUserMedia...");
            const stream = await navigator.mediaDevices.getUserMedia({
                audio: {
                    echoCancellation: true,
                    noiseSuppression: true,
                    autoGainControl: true,
                    sampleRate: 16000,
                    channelCount: 1,
                },
            });
            console.log("[VoiceInput] getUserMedia 成功，已获取音频流");

            // 2. 动态导入 VAD 库
            console.log("[VoiceInput] 正在动态导入 @ricky0123/vad-web...");
            const { MicVAD } = await import("@ricky0123/vad-web");
            console.log("[VoiceInput] @ricky0123/vad-web 导入成功");

            // 3. 初始化 MicVAD（使用本地模型，无需 CDN）
            console.log("[VoiceInput] 正在初始化 MicVAD（使用本地模型）...");
            const vad = await MicVAD.new({
                stream,
                baseAssetPath: "/",
                onnxWASMBasePath: "/",
                positiveSpeechThreshold: 0.4,
                negativeSpeechThreshold: 0.35,
                minSpeechFrames: 3,
                preSpeechPadFrames: 15,     // ~1.44s 预缓冲
                redemptionFrames: 10,       // 句中停顿容忍
                onSpeechStart: () => {
                    console.log("[VoiceInput] VAD 检测到 speech start");
                    isUserSpeaking.value = true;
                    callbacks.onSpeechStart();
                },
                onSpeechEnd: (audio: Float32Array) => {
                    const durationMs = (audio.length / 16000) * 1000;
                    console.log(`[VoiceInput] VAD 检测到 speech end | 音频长度=${audio.length} samples | 时长=${durationMs.toFixed(1)}ms`);
                    isUserSpeaking.value = false;
                    callbacks.onSpeechEnd(audio, durationMs);
                },
            });
            console.log("[VoiceInput] MicVAD 初始化成功");

            // 【关键修复】初始化完成后检查是否已被取消
            if (!_shouldBeRunning) {
                console.log("[VoiceInput] 初始化完成后检测到已取消，立即销毁资源");
                try { stream.getTracks().forEach((t) => t.stop()); } catch (e) { /* ignore */ }
                vad.destroy();
                return;
            }

            destroyFn = () => {
                console.log("[VoiceInput] 正在销毁 MicVAD...");
                try {
                    stream.getTracks().forEach((t) => t.stop());
                } catch (e) {
                    console.warn("[VoiceInput] 停止音频流时异常:", e);
                }
                vad.destroy();
            };

            vad.start();
            isListening.value = true;
            console.log("[VoiceInput] ✅ 麦克风监听已启动");
        } catch (e: any) {
            console.error("[VoiceInput] ❌ 启动失败:", e);
            callbacks.onError(e?.message || "麦克风启动失败");
        } finally {
            _shouldBeRunning = false;
        }
    }

    function stopListening(): void {
        if (!isListening.value && !_shouldBeRunning) {
            console.log("[VoiceInput] 当前未在监听，跳过停止");
            return;
        }

        _shouldBeRunning = false;

        try {
            destroyFn?.();
        } catch (e) {
            console.warn("[VoiceInput] 停止时异常:", e);
        }

        destroyFn = null;
        isListening.value = false;
        isUserSpeaking.value = false;
        console.log("[VoiceInput] ⏹ 麦克风监听已停止");
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
