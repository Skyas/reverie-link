/**
 * useTTS.ts — 语音合成 + 音频播放 + 唇音同步（重构版）
 *
 * 职责：
 *   - 从 localStorage 读取 TTS 配置，在应用启动时同步给后端
 *   - 调用后端统一接口 POST /tts/synthesize 获取音频
 *   - AudioContext + AnalyserNode 驱动唇音同步
 *   - 无语音模式（后端返回 204）静默处理，不影响文字气泡
 *
 * 配置存储 Key：rl-tts-v2（新格式，与旧版 rl-tts 区分）
 *
 * 依赖注入：
 *   setMouthOpen — 来自 useLive2D，通过参数传入，使本模块对 Live2D 完全无感知。
 *
 * 不知道 WebSocket、窗口、Live2D 内部结构的存在。
 */

const TTS_CONFIG_KEY_V2 = "rl-tts-v2";
const BACKEND_BASE = "http://localhost:18000";

interface TTSDeps {
    setMouthOpen: (value: number) => void;
}

/** 从 localStorage 读取 TTS 后端配置（用于启动时同步） */
function getBackendTTSConfig(): Record<string, string> | null {
    try {
        const raw = localStorage.getItem(TTS_CONFIG_KEY_V2);
        if (!raw) return null;
        const cfg = JSON.parse(raw);
        if (!cfg.mode || cfg.mode === "disabled") return null;

        const backendCfg: Record<string, string> = {
            mode:     cfg.mode,
            provider: cfg.provider ?? "",
            api_key:  (cfg.api_keys ?? {})[cfg.provider ?? ""] ?? "",
            voice_id: cfg.voice_id ?? "",
            base_url: cfg.base_url ?? "",
        };
        if (cfg.provider === "minimax") {
            backendCfg.group_id = (cfg.group_ids ?? {})["minimax"] ?? "";
        }
        return backendCfg;
    } catch {
        return null;
    }
}

export function useTTS({ setMouthOpen }: TTSDeps) {
    let audioCtx:     AudioContext | null      = null;
    let lipSyncRafId: number                   = 0;
    let currentAudio: HTMLAudioElement | null  = null;

    // ── 启动时同步配置到后端 ──────────────────────────────────────
    /**
     * 在 onMounted 后调用，将 localStorage 中保存的 TTS 配置推送给后端。
     * 避免后端重启后配置丢失导致的无语音状态。
     */
    async function syncConfigToBackend(): Promise<void> {
        const cfg = getBackendTTSConfig();
        if (!cfg) {
            console.log("[TTS] 无 TTS 配置或已禁用，跳过同步");
            return;
        }
        try {
            const resp = await fetch(`${BACKEND_BASE}/tts/config`, {
                method:  "POST",
                headers: { "Content-Type": "application/json" },
                body:    JSON.stringify(cfg),
            });
            if (resp.ok) {
                const data = await resp.json();
                console.log(
                    `[TTS] 启动同步成功 | mode=${data.mode} provider=${data.provider} ready=${data.ready}`
                );
            } else {
                console.warn("[TTS] 启动同步失败 status=", resp.status);
            }
        } catch (e) {
            console.warn("[TTS] 启动同步请求异常:", e);
        }
    }

    // ── 停止当前播放 ──────────────────────────────────────────────
    function stopTTS() {
        if (lipSyncRafId) { cancelAnimationFrame(lipSyncRafId); lipSyncRafId = 0; }
        if (currentAudio) { currentAudio.pause(); currentAudio = null; }
        setMouthOpen(0);
    }

    // ── 播放 Blob + 唇音同步 ──────────────────────────────────────
    async function playAudioBlob(blob: Blob): Promise<void> {
        const url   = URL.createObjectURL(blob);
        const audio = new Audio(url);
        currentAudio = audio;

        if (!audioCtx || audioCtx.state === "closed") {
            audioCtx = new AudioContext();
        }
        const source   = audioCtx.createMediaElementSource(audio);
        const analyser = audioCtx.createAnalyser();
        analyser.fftSize = 256;
        source.connect(analyser);
        analyser.connect(audioCtx.destination);

        const dataArray = new Uint8Array(analyser.frequencyBinCount);

        function lipSyncLoop() {
            if (!currentAudio || currentAudio.paused || currentAudio.ended) {
                setMouthOpen(0); lipSyncRafId = 0; return;
            }
            analyser.getByteFrequencyData(dataArray);
            const avg = dataArray.slice(0, 16).reduce((a, b) => a + b, 0) / 16;
            setMouthOpen(Math.min(1, avg / 80));
            lipSyncRafId = requestAnimationFrame(lipSyncLoop);
        }

        audio.addEventListener("play",  () => { lipSyncRafId = requestAnimationFrame(lipSyncLoop); });
        audio.addEventListener("ended", () => { setMouthOpen(0); URL.revokeObjectURL(url); });
        audio.addEventListener("error", () => { setMouthOpen(0); URL.revokeObjectURL(url); });

        await audio.play();
    }

    // ── 合成并播放（新版，调用统一后端接口）─────────────────────
    /**
     * 合成语音并播放。
     * @param text    已从 LLM 回复中提取的文本（含或不含情感标签均可，后端会忽略）
     * @param emotion 标准情感标签（由前端从 LLM 回复中解析），缺省 "neutral"
     */
    async function speakText(text: string, emotion: string = "neutral"): Promise<void> {
        if (!text.trim()) return;

        stopTTS(); // 停止上一条语音

        try {
            const res = await fetch(`${BACKEND_BASE}/tts/synthesize`, {
                method:  "POST",
                headers: { "Content-Type": "application/json" },
                body:    JSON.stringify({ text: text.trim(), emotion }),
            });

            // 204 = 无语音模式，静默跳过
            if (res.status === 204) {
                console.debug("[TTS] 无语音模式，跳过播放");
                return;
            }

            if (!res.ok) {
                console.warn("[TTS] 合成请求失败:", res.status);
                return;
            }

            const blob = await res.blob();
            if (blob.size === 0) {
                console.warn("[TTS] 收到空音频，跳过播放");
                return;
            }

            await playAudioBlob(blob);
        } catch (e) {
            console.warn("[TTS] 播放失败:", e);
            setMouthOpen(0);
        }
    }

    // ── 销毁（onUnmounted 调用）──────────────────────────────────
    function destroyTTS(): void {
        stopTTS();
        audioCtx?.close();
    }

    return { speakText, stopTTS, destroyTTS, syncConfigToBackend };
}
