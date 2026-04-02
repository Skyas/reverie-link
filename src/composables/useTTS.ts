/**
 * useTTS.ts — 语音合成 + 音频播放 + 唇音同步
 *
 * 职责：
 *   - 读取 localStorage 中的 TTS 配置
 *   - ElevenLabs（云端）/ 本地 RVC 双引擎切换
 *   - AudioContext + AnalyserNode 驱动唇音同步
 *
 * 依赖注入：
 *   setMouthOpen — 来自 useLive2D，通过参数传入，使本模块对 Live2D 完全无感知。
 *
 * 不知道 WebSocket、窗口、Live2D 内部结构的存在。
 */

const TTS_CONFIG_KEY = "rl-tts";

interface TTSDeps {
    setMouthOpen: (value: number) => void;
}

export function useTTS({ setMouthOpen }: TTSDeps) {
    let audioCtx:     AudioContext | null      = null;
    let lipSyncRafId: number                   = 0;
    let currentAudio: HTMLAudioElement | null  = null;

    // ── 配置读取 ──────────────────────────────────────────────────────
    function getTTSConfig() {
        try {
            const cfg = JSON.parse(localStorage.getItem(TTS_CONFIG_KEY) ?? "{}");
            return {
                engine:      (cfg.engine ?? "elevenlabs") as "elevenlabs" | "rvc",
                enabled:      cfg.enabled ?? false,
                elApiKey:     cfg.el_api_key   ?? cfg.api_key  ?? "",
                elVoiceId:    cfg.el_voice_id  ?? cfg.voice_id ?? "",
                rvcPth:       cfg.rvc_pth       ?? "",
                rvcIndex:     cfg.rvc_index     ?? "",
                rvcEdgeVoice: cfg.rvc_edge_voice ?? "zh-CN-XiaoxiaoNeural",
            };
        } catch {
            return {
                engine: "elevenlabs" as const, enabled: false,
                elApiKey: "", elVoiceId: "",
                rvcPth: "", rvcIndex: "", rvcEdgeVoice: "zh-CN-XiaoxiaoNeural",
            };
        }
    }

    // ── 停止当前播放 ──────────────────────────────────────────────────
    function stopTTS() {
        if (lipSyncRafId) { cancelAnimationFrame(lipSyncRafId); lipSyncRafId = 0; }
        if (currentAudio) { currentAudio.pause(); currentAudio = null; }
        setMouthOpen(0);
    }

    // ── 播放 Blob + 唇音同步 ──────────────────────────────────────────
    async function playAudioBlob(blob: Blob) {
        const url   = URL.createObjectURL(blob);
        const audio = new Audio(url);
        currentAudio = audio;

        if (!audioCtx || audioCtx.state === "closed") audioCtx = new AudioContext();
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

    // ── 合成并播放 ────────────────────────────────────────────────────
    /**
     * 根据用户配置的引擎合成语音并播放。
     * ElevenLabs → POST /api/tts
     * 本地 RVC   → POST /api/tts/local
     */
    async function speakText(text: string) {
        const cfg = getTTSConfig();
        if (!cfg.enabled || !text.trim()) return;

        stopTTS(); // 停止上一条语音

        try {
            let res: Response;
            if (cfg.engine === "elevenlabs") {
                if (!cfg.elApiKey || !cfg.elVoiceId) return;
                res = await fetch("http://localhost:18000/api/tts", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ text, api_key: cfg.elApiKey, voice_id: cfg.elVoiceId }),
                });
            } else {
                if (!cfg.rvcPth) return;
                res = await fetch("http://localhost:18000/api/tts/local", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        text,
                        pth:        cfg.rvcPth,
                        index:      cfg.rvcIndex,
                        edge_voice: cfg.rvcEdgeVoice,
                    }),
                });
            }

            if (!res.ok) { console.warn("[TTS] 请求失败:", res.status); return; }
            await playAudioBlob(await res.blob());
        } catch (e) {
            console.warn("[TTS] 播放失败:", e);
            setMouthOpen(0);
        }
    }

    // ── 销毁（onUnmounted 调用） ──────────────────────────────────────
    function destroyTTS() {
        stopTTS();
        audioCtx?.close();
    }

    return { speakText, stopTTS, destroyTTS };
}