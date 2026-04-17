/**
 * useTTS.ts — 语音合成 + 音频播放 + 唇音同步（重构版）
 *
 * 变更记录：
 *   [FIX-⑤] getBackendTTSConfig() 传递 proxy 字段
 *   [FIX-⑥] getBackendTTSConfig() 补传 model 字段
 *           —— 修复启动同步时 model 丢失，导致阿里云等场景 voice_id 与
 *              后端默认 model 不匹配、合成/测试失败，必须重新点保存才能生效的问题。
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

        const provider = cfg.provider ?? "";

        // [FIX-⑥] model 读取顺序：
        //   1) 顶层 cfg.model —— saveTTS 每次都写，代表"保存时真正生效的 model"
        //      （自定义模型场景下，这个是 customModelTexts[provider]，
        //       不等于 cfg.models[provider]，所以必须优先读顶层）
        //   2) cfg.models[provider] —— 理论不会走到，兜底用
        //   3) "" —— 极老版本数据无 model 字段时，让后端走默认 model
        const model = cfg.model
            ?? (cfg.models ?? {})[provider]
            ?? "";

        const backendCfg: Record<string, string> = {
            mode:     cfg.mode,
            provider: provider,
            api_key:  (cfg.api_keys ?? {})[provider] ?? "",
            voice_id: cfg.voice_id ?? "",
            model:    model,
            base_url: cfg.base_url ?? "",
            // [FIX-⑤] 代理：开关开启且有地址时才传
            proxy:    (cfg.proxy_enabled && cfg.proxy_url) ? cfg.proxy_url : "",
        };
        if (provider === "minimax") {
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
    async function syncConfigToBackend(): Promise<void> {
        const cfg = getBackendTTSConfig();
        if (!cfg) {
            console.log("[TTS] 无 TTS 配置或已禁用，跳过同步");
            return;
        }
        // [FIX-⑥] 日志里把 model 也打出来，便于排查"model 丢失"类问题
        console.log(
            `[TTS] 启动同步发起 | mode=${cfg.mode} provider=${cfg.provider} `
            + `model="${cfg.model || '(空)'}" voice_id="${cfg.voice_id || '(空)'}"`
        );
        try {
            const resp = await fetch(`${BACKEND_BASE}/tts/config`, {
                method:  "POST",
                headers: { "Content-Type": "application/json" },
                body:    JSON.stringify(cfg),
            });
            if (resp.ok) {
                const data = await resp.json();
                console.log(
                    `[TTS] 启动同步成功 | mode=${data.mode} provider=${data.provider} `
                    + `ready=${data.ready}`
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
    async function speakText(text: string, emotion: string = "neutral"): Promise<void> {
        if (!text.trim()) return;

        stopTTS();

        try {
            const res = await fetch(`${BACKEND_BASE}/tts/synthesize`, {
                method:  "POST",
                headers: { "Content-Type": "application/json" },
                body:    JSON.stringify({ text: text.trim(), emotion }),
            });

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