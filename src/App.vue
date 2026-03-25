<script setup lang="ts">
    import { ref, nextTick, onMounted, onUnmounted, watch, computed } from "vue";
    import {
        getCurrentWindow,
        PhysicalPosition,
        LogicalSize,
        primaryMonitor,
    } from "@tauri-apps/api/window";
    import { listen } from "@tauri-apps/api/event";
    import { invoke } from "@tauri-apps/api/core";
    import * as PIXI from "pixi.js";
    import { Live2DModel } from "pixi-live2d-display/cubism4";

    // Live2D 需要在使用前注册 PIXI Ticker
    Live2DModel.registerTicker(PIXI.Ticker);

    // ── 尺寸档位系统 ────────────────────────────────────────────────
    const SIZE_PRESETS = {
        small: { baseW: 200, baseH: 270, inputW: 210, bubbleH: 130 },
        medium: { baseW: 280, baseH: 380, inputW: 240, bubbleH: 160 },
        large: { baseW: 380, baseH: 510, inputW: 300, bubbleH: 200 },
    } as const;

    type SizePreset = keyof typeof SIZE_PRESETS;

    const sizePreset = ref<SizePreset>(
        (localStorage.getItem("rl-size") as SizePreset) || "medium"
    );
    const sizeConfig = computed(() => SIZE_PRESETS[sizePreset.value]);

    // 动态尺寸常量（替代 Phase 1 的硬编码常量）
    const BASE_W = computed(() => sizeConfig.value.baseW);
    const BASE_H = computed(() => sizeConfig.value.baseH);
    const INPUT_W = computed(() => sizeConfig.value.inputW);
    const BUBBLE_H = computed(() => sizeConfig.value.bubbleH);

    // ── 情绪标签系统 ────────────────────────────────────────────────
    const EMOTION_TAGS = ["happy", "sad", "angry", "shy", "surprised", "neutral", "sigh"] as const;
    type EmotionTag = typeof EMOTION_TAGS[number];
    // 精确匹配已知标签
    const EMOTION_REGEX = /\[(happy|sad|angry|shy|surprised|neutral|sigh)\]/gi;
    // 兜底正则：清除 LLM 可能造出的任何未知 [xxx] 标签
    const UNKNOWN_TAG_REGEX = /\[[a-zA-Z]+\]/gi;

    /** 从 AI 回复中提取情绪标签，返回干净文本 + 情绪名称 */
    function parseEmotion(text: string): { cleanText: string; emotion: EmotionTag | null } {
        const match = text.match(EMOTION_REGEX);
        const emotion = match
            ? (match[0].slice(1, -1).toLowerCase() as EmotionTag)
            : null;
        // 先剥离已知标签，再用兜底正则清除任何残留未知标签
        const cleanText = text
            .replace(EMOTION_REGEX, "")
            .replace(UNKNOWN_TAG_REGEX, "")
            .replace(/\s{2,}/g, " ")
            .trim();
        return { cleanText, emotion };
    }

    // ── Live2D 状态 ─────────────────────────────────────────────────
    const canvasRef = ref<HTMLCanvasElement | null>(null);
    const live2dReady = ref(false);   // 模型加载成功
    const live2dError = ref(false);   // 加载失败（Core 未就绪等）

    let pixiApp: PIXI.Application | null = null;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    let live2dModel: any = null;
    let live2dContainer: PIXI.Container | null = null;
    let renderTexture: PIXI.RenderTexture | null = null;

    // ── 模型个性化配置读写 ──────────────────────────────────────
    // 以模型路径为 key，存储每个模型的 zoom/y 偏移
    // 格式：{ "live2d/hiyori_vts/hiyori.model3.json": { zoom: 1.7, y: -80 }, ... }
    const MODEL_SETTINGS_KEY = "rl-model-settings";
    const DEFAULT_MODEL_ZOOM = 1.7;
    const DEFAULT_MODEL_Y = -80;

    function getModelSettings(path: string): { zoom: number; y: number } {
        try {
            const all = JSON.parse(localStorage.getItem(MODEL_SETTINGS_KEY) ?? "{}");
            const s = all[path];
            if (s && typeof s.zoom === "number" && typeof s.y === "number") return s;
        } catch { /* corrupt data, use defaults */ }
        return { zoom: DEFAULT_MODEL_ZOOM, y: DEFAULT_MODEL_Y };
    }

    function saveModelSettings(path: string, zoom: number, y: number) {
        try {
            const all = JSON.parse(localStorage.getItem(MODEL_SETTINGS_KEY) ?? "{}");
            all[path] = { zoom, y };
            localStorage.setItem(MODEL_SETTINGS_KEY, JSON.stringify(all));
        } catch { /* ignore */ }
    }

    /**
     * 初始化 PIXI + Live2D 模型。
     * ⚠️  需要 public/live2dcubismcore.min.js 已加载（见 index.html 注释）。
     */
    async function initLive2D() {
        if (!canvasRef.value) return;

        if (typeof (window as any).Live2DCubismCore === "undefined") {
            console.warn("[Live2D] Cubism Core 未加载，请放入 public/ 并取消注释 index.html 中的 script 标签。");
            live2dError.value = true;
            return;
        }

        const w = BASE_W.value;
        const h = BASE_H.value;

        // ❌ 不设置 preserveDrawingBuffer（默认 false）
        // preserveDrawingBuffer: true 会禁用 WebGL 前后缓冲交换机制，
        // 导致 clear 瞬间 DWM 截到空白帧，是闪烁的根本原因。
        pixiApp = new PIXI.Application({
            view: canvasRef.value,
            backgroundAlpha: 0,
            width: w,
            height: h,
            antialias: true,
            resolution: 1,
            autoDensity: false,
            powerPreference: "high-performance",
        });

        const renderer = pixiApp.renderer as PIXI.Renderer;

        // 第一层保护：RenderTexture
        // Live2D 多 Draw Call → 离屏纹理（GPU 显存内，DWM 完全不可见）
        // 确保纹理内容始终是完整帧
        renderTexture = PIXI.RenderTexture.create({ width: w, height: h });
        const displaySprite = new PIXI.Sprite(renderTexture);
        pixiApp.stage.addChild(displaySprite);

        // Live2D 放在独立容器，不直接上 stage
        live2dContainer = new PIXI.Container();

        try {
            const modelPath = localStorage.getItem("rl-model-path") ?? "live2d/MO/MO.model3.json";
            live2dModel = await Live2DModel.from("/" + modelPath, {
                autoInteract: false,
            });

            const modelSettings = getModelSettings(modelPath);
            const zoom = modelSettings.zoom;
            const scale = (w / live2dModel.internalModel.originalWidth) * zoom;
            live2dModel.scale.set(scale);
            live2dModel.anchor.set(0.5, 0);
            live2dModel.x = w / 2;
            live2dModel.y = modelSettings.y;

            live2dContainer.addChild(live2dModel);

            // 直接设置 Part 透明度，归位多状态手臂部件
            // hiyori 等有 PartArmA/PartArmB 的模型：显示 A（正常垂手），隐藏 B（举手姿态）
            // 没有这些 Part 的模型调用后静默忽略
            try {
                const core = live2dModel.internalModel.coreModel;
                core.setPartOpacityById("PartArmA", 1);
                core.setPartOpacityById("PartArmB", 0);
            } catch { /* 该模型无此 Part，忽略 */ }

        } catch (e) {
            console.error("[Live2D] 模型加载失败:", e);
            live2dError.value = true;
            return;
        }

        // 第二层保护：WebGL 双缓冲（默认行为，不破坏它）
        // 用 PIXI Ticker.add() 在每帧渲染前把 Live2D 先画到离屏纹理
        // Ticker 回调先于 PIXI 自动 stage render 执行，时序有保证
        // clear canvas + draw Sprite → 后缓冲，rAF 结束原子交换到前缓冲
        // DWM 永远只看前缓冲 → 永远是完整帧
        pixiApp.ticker.add(() => {
            renderer.render(live2dContainer, { renderTexture, clear: true });
            // PIXI 随后自动把 stage（含 displaySprite）渲染到 canvas
        });

        live2dReady.value = true;
    }

    // ── 表情系统 ────────────────────────────────────────────────
    let emotionResetTimer: ReturnType<typeof setTimeout> | null = null;

    /**
     * 检测模型是否有注册表情文件（exp3.json）
     * pixi-live2d-display 把表情存在 expressionManager.definitions 里
     */
    function modelHasExpressions(): boolean {
        try {
            const defs = live2dModel?.internalModel?.motionManager
                ?.expressionManager?.definitions;
            return Array.isArray(defs) && defs.length > 0;
        } catch { return false; }
    }

    /**
     * 无表情文件时的参数回退方案。
     * 使用 Live2D 官方标准参数名直接操控面部，覆盖绝大多数标准模型。
     * 有参数不存在时 setParameterValueById 会静默忽略，不会报错。
     */
    function applyEmotionByParams(emotion: EmotionTag) {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const core: any = live2dModel?.internalModel?.coreModel;
        if (!core) return;

        const set = (id: string, v: number) => {
            try { core.setParameterValueById(id, v); } catch { /* ignore */ }
        };

        // 先归位所有情绪参数，再按情绪叠加
        set("ParamMouthForm", 0);
        set("ParamMouthOpenY", 0);
        set("ParamEyeLOpen", 1);
        set("ParamEyeROpen", 1);
        set("ParamBrowLY", 0);
        set("ParamBrowRY", 0);
        set("ParamBrowLForm", 0);
        set("ParamBrowRForm", 0);
        // 腮红/Cheek 参数：不同模型名字不同，尝试常见命名
        set("Param74", 0); // MO 模型
        set("ParamCheek", 0); // 标准命名

        switch (emotion) {
            case "happy":
                set("ParamMouthForm", 1.0);
                set("ParamEyeLOpen", 0.6);   // 眯眼笑
                set("ParamEyeROpen", 0.6);
                set("ParamBrowLY", 0.6);   // 眉毛上扬
                set("ParamBrowRY", 0.6);
                set("Param74", 2.0);   // MO 腮红
                set("ParamCheek", 1.0);   // 标准腮红
                break;
            case "sad":
                set("ParamMouthForm", -1.0);
                set("ParamEyeLOpen", 0.7);   // 眼睛微垂
                set("ParamEyeROpen", 0.7);
                set("ParamBrowLY", -1.0);  // 眉毛大幅压低
                set("ParamBrowRY", -1.0);
                set("ParamBrowLForm", -1.0);
                set("ParamBrowRForm", -1.0);
                break;
            case "angry":
                set("ParamMouthForm", -1.0);  // 更夸张的嘴角下撇
                set("ParamBrowLY", -1.0);
                set("ParamBrowRY", -1.0);
                set("ParamBrowLForm", -1.0);
                set("ParamBrowRForm", -1.0);
                set("ParamEyeLOpen", 1.4);   // 瞪眼
                set("ParamEyeROpen", 1.4);
                break;
            case "shy":
                set("ParamMouthForm", 0.8);
                set("ParamEyeLOpen", 0.5);   // 眼睛更多低垂
                set("ParamEyeROpen", 0.5);
                set("ParamBrowLY", -0.3);  // 眉毛稍降，配合害羞
                set("ParamBrowRY", -0.3);
                set("Param74", 2.0);   // 腮红全开
                set("ParamCheek", 1.0);
                break;
            case "surprised":
                set("ParamMouthOpenY", 0.8);   // 嘴张更大
                set("ParamMouthForm", 0.3);
                set("ParamBrowLY", 1.0);
                set("ParamBrowRY", 1.0);
                set("ParamEyeLOpen", 2.0);   // 眼睛尽量睁大（超过默认值）
                set("ParamEyeROpen", 2.0);
                break;
            case "sigh":
                // 暂无专属表情参数，后续 Live2D 表情匹配时补充
                // 当前效果：归位到默认状态（已在 switch 前归位）
                break;
            case "neutral":
            default:
                break; // 已在上方归位
        }
    }

    /** 触发情绪表情，3 秒后自动归位 neutral */
    function setEmotion(emotion: EmotionTag) {
        if (!live2dModel || !live2dReady.value) return;
        if (emotionResetTimer) clearTimeout(emotionResetTimer);

        if (modelHasExpressions()) {
            // 有表情文件（exp3.json）：走官方 expression 接口
            live2dModel.expression(emotion);
        } else {
            // 无表情文件：直接操控标准参数，兼容绝大多数模型
            applyEmotionByParams(emotion);
        }

        if (emotion !== "neutral") {
            emotionResetTimer = setTimeout(() => {
                if (!live2dModel || !live2dReady.value) return;
                if (modelHasExpressions()) {
                    live2dModel.expression("neutral");
                } else {
                    applyEmotionByParams("neutral");
                }
            }, 3000);
        }
    }

    /**
     * 设置嘴部开合参数（由唇音同步模块调用）
     * @param value  0.0（闭合）~ 1.0（全开），映射到 ParamMouthOpenY（0~2.1）
     */
    function setMouthOpen(value: number) {
        if (!live2dModel || !live2dReady.value) return;
        const mapped = Math.max(0, Math.min(1, value)) * 2.1;
        try {
            live2dModel.internalModel.coreModel.setParameterValueById("ParamMouthOpenY", mapped);
        } catch { /* ignore */ }
    }

    // ── TTS 语音系统 ─────────────────────────────────────────────
    const TTS_CONFIG_KEY = "rl-tts";
    let audioCtx: AudioContext | null = null;
    let lipSyncRafId = 0;
    let currentAudio: HTMLAudioElement | null = null;

    function getTTSConfig() {
        try {
            const cfg = JSON.parse(localStorage.getItem(TTS_CONFIG_KEY) ?? "{}");
            return {
                engine: (cfg.engine ?? "elevenlabs") as "elevenlabs" | "rvc",
                enabled: cfg.enabled ?? false,
                elApiKey: cfg.el_api_key ?? cfg.api_key ?? "",
                elVoiceId: cfg.el_voice_id ?? cfg.voice_id ?? "",
                rvcPth: cfg.rvc_pth ?? "",
                rvcIndex: cfg.rvc_index ?? "",
                rvcEdgeVoice: cfg.rvc_edge_voice ?? "zh-CN-XiaoxiaoNeural",
            };
        } catch {
            return {
                engine: "elevenlabs" as const, enabled: false,
                elApiKey: "", elVoiceId: "",
                rvcPth: "", rvcIndex: "", rvcEdgeVoice: "zh-CN-XiaoxiaoNeural"
            };
        }
    }

    /** 停止当前播放并取消唇音同步 */
    function stopTTS() {
        if (lipSyncRafId) { cancelAnimationFrame(lipSyncRafId); lipSyncRafId = 0; }
        if (currentAudio) { currentAudio.pause(); currentAudio = null; }
        setMouthOpen(0);
    }

    /** 播放音频 Blob 并驱动唇音同步 */
    async function playAudioBlob(blob: Blob) {
        const url = URL.createObjectURL(blob);
        const audio = new Audio(url);
        currentAudio = audio;

        if (!audioCtx || audioCtx.state === "closed") audioCtx = new AudioContext();
        const source = audioCtx.createMediaElementSource(audio);
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

        audio.addEventListener("play", () => { lipSyncRafId = requestAnimationFrame(lipSyncLoop); });
        audio.addEventListener("ended", () => { setMouthOpen(0); URL.revokeObjectURL(url); });
        audio.addEventListener("error", () => { setMouthOpen(0); URL.revokeObjectURL(url); });
        await audio.play();
    }

    /**
     * 根据用户配置的引擎合成语音并播放。
     * ElevenLabs → POST /api/tts
     * 本地 RVC   → POST /api/tts/local
     */
    async function speakText(text: string) {
        const cfg = getTTSConfig();
        if (!cfg.enabled || !text.trim()) return;
        stopTTS();
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
                        pth: cfg.rvcPth,
                        index: cfg.rvcIndex,
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

    /** 销毁 PIXI 实例（onUnmounted 或切换模型时调用） */
    function disposeLive2D() {
        if (live2dModel && live2dContainer) {
            live2dContainer.removeChild(live2dModel);
        }
        if (live2dContainer) {
            live2dContainer.destroy({ children: true });
            live2dContainer = null;
        }
        if (renderTexture) {
            renderTexture.destroy(true);
            renderTexture = null;
        }
        if (pixiApp) {
            pixiApp.destroy(false, { children: true });
            pixiApp = null;
        }
        live2dModel = null;
        live2dReady.value = false;
        live2dError.value = false;
    }

    /** 切换模型：只换模型，保留 pixiApp/canvas/ticker/renderTexture */
    async function reloadLive2D(newPath: string) {
        localStorage.setItem("rl-model-path", newPath);

        if (!pixiApp || !live2dContainer) {
            await initLive2D();
            return;
        }

        live2dReady.value = false;

        if (live2dModel) {
            live2dContainer.removeChild(live2dModel);
            live2dModel.destroy();
            live2dModel = null;
        }

        try {
            live2dModel = await Live2DModel.from("/" + newPath, { autoInteract: false });
            const w = BASE_W.value;
            const modelSettings = getModelSettings(newPath);
            const zoom = modelSettings.zoom;
            const scale = (w / live2dModel.internalModel.originalWidth) * zoom;
            live2dModel.scale.set(scale);
            live2dModel.anchor.set(0.5, 0);
            live2dModel.x = w / 2;
            live2dModel.y = modelSettings.y;
            live2dContainer.addChild(live2dModel);

            try {
                const core = live2dModel.internalModel.coreModel;
                core.setPartOpacityById("PartArmA", 1);
                core.setPartOpacityById("PartArmB", 0);
            } catch { /* 该模型无此 Part，忽略 */ }

            live2dReady.value = true;
            console.info(`[Live2D] 模型切换成功 ✓  (${newPath})`);
        } catch (e) {
            console.error("[Live2D] 模型切换失败:", e);
            live2dError.value = true;
        }
    }


    // ── 对话气泡超时保护 ────────────────────────────────────────────
    let thinkingTimer: ReturnType<typeof setTimeout> | null = null;

    // ── 窗口状态 ────────────────────────────────────────────────────
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

    // ── 控制栏悬停 ──────────────────────────────────────────────────
    let hideControlsTimer: ReturnType<typeof setTimeout> | null = null;

    function onMascotEnter() {
        if (isLocked.value) return;
        if (hideControlsTimer) clearTimeout(hideControlsTimer);
        showControls.value = true;
    }

    function onMascotLeave() {
        if (isLocked.value) return;
        hideControlsTimer = setTimeout(() => { showControls.value = false; }, 600);
    }

    // ── 锁定 / 解锁 ─────────────────────────────────────────────────
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

    // ── 设置窗口 ────────────────────────────────────────────────────
    async function openSettings() {
        await invoke("open_settings");
    }

    // ── 聊天记录窗口 ─────────────────────────────────────────────────
    async function openHistory() {
        await invoke("open_history");
    }

    // ── 动态窗口缩放 ────────────────────────────────────────────────
    async function resizeToFit() {
        const win = getCurrentWindow();
        const pos = await win.outerPosition();
        const siz = await win.outerSize();
        const sf = (await primaryMonitor())?.scaleFactor ?? 1;

        const anchorX = pos.x + siz.width;
        const anchorY = pos.y + siz.height;

        const newLogicW = BASE_W.value + (inputOpen.value ? INPUT_W.value : 0);
        const newLogicH = BASE_H.value + (showBubble.value || isThinking.value ? BUBBLE_H.value : 0);

        const newPhysW = Math.round(newLogicW * sf);
        const newPhysH = Math.round(newLogicH * sf);

        await win.setSize(new LogicalSize(newLogicW, newLogicH));
        await win.setPosition(new PhysicalPosition(anchorX - newPhysW, anchorY - newPhysH));
    }

    watch([inputOpen, showBubble, isThinking], resizeToFit);

    // ── WebSocket ───────────────────────────────────────────────────
    const WS_URL = "ws://localhost:18000/ws/chat";
    let ws: WebSocket | null = null;

    function connectWS() {
        ws = new WebSocket(WS_URL);
        ws.onopen = () => {
            isConnected.value = true;
            // WS 建立后自动把本地已保存的配置发给后端，无需用户手动保存
            const savedLLM = localStorage.getItem("rl-llm");
            const savedChar = localStorage.getItem("rl-character");
            if (savedLLM || savedChar) {
                const llmCfg = savedLLM ? JSON.parse(savedLLM) : {};
                const charCfg = savedChar ? JSON.parse(savedChar) : {};
                const savedWindowIdx = parseInt(localStorage.getItem("rl-memory-window") ?? "1", 10);
                const savedCharId = localStorage.getItem("rl-active-preset-id") ?? "";
                ws!.send(JSON.stringify({
                    type: "configure",
                    llm: llmCfg,
                    character: charCfg,
                    memory_window: isNaN(savedWindowIdx) ? 1 : savedWindowIdx,
                    character_id: savedCharId,
                }));
            }
        };
        ws.onclose = () => { isConnected.value = false; setTimeout(connectWS, 3000); };
        ws.onerror = () => { ws?.close(); };
        ws.onmessage = (event) => {
            const data = JSON.parse(event.data);

            if (data.type === "chat_response") {
                isThinking.value = false;
                if (thinkingTimer) clearTimeout(thinkingTimer);

                // ① 提取情绪标签，剥离后再显示
                const { cleanText, emotion } = parseEmotion(data.message);
                if (emotion) setEmotion(emotion);
                showBubbleWithText(cleanText);
                // ② 语音播放（配置未启用时静默跳过）
                speakText(cleanText);

            } else if (data.type === "error") {
                isThinking.value = false;
                if (thinkingTimer) clearTimeout(thinkingTimer);
                showBubbleWithText("呜…出错了：" + data.message);
            }
        };
    }

    // ── 打字机动画 ──────────────────────────────────────────────────
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

    // ── 发送消息 ────────────────────────────────────────────────────
    function sendMessage() {
        const msg = userInput.value.trim();
        if (!msg || !isConnected.value || isThinking.value) return;

        isThinking.value = true;
        showBubble.value = false;
        userInput.value = "";

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

    // ── 输入框开关 ──────────────────────────────────────────────────
    function toggleInput() {
        inputOpen.value = !inputOpen.value;
        if (inputOpen.value) nextTick(() => inputRef.value?.focus());
    }

    // ── 拖拽 ────────────────────────────────────────────────────────
    async function startDrag() {
        await getCurrentWindow().startDragging();
    }

    // ── 生命周期 ────────────────────────────────────────────────────
    const unlisten: (() => void)[] = [];

    onMounted(async () => {
        connectWS();

        const win = getCurrentWindow();
        const sf = (await primaryMonitor())?.scaleFactor ?? 1;
        const w = BASE_W.value;
        const h = BASE_H.value;

        // 恢复上次位置（以右下角为锚点）
        const saved = localStorage.getItem("mascot-anchor");
        if (saved) {
            const { ax, ay } = JSON.parse(saved);
            const physW = Math.round(w * sf);
            const physH = Math.round(h * sf);
            await win.setSize(new LogicalSize(w, h));
            await win.setPosition(new PhysicalPosition(ax - physW, ay - physH));
        } else {
            const monitor = await primaryMonitor();
            if (monitor) {
                const { width, height } = monitor.size;
                const margin = Math.round(16 * sf);
                const physW = Math.round(w * sf);
                const physH = Math.round(h * sf);
                await win.setSize(new LogicalSize(w, h));
                await win.setPosition(new PhysicalPosition(
                    width - physW - margin,
                    height - physH - margin
                ));
            }
        }

        // 记录锚点（右下角）
        await win.onMoved(async () => {
            const p = await win.outerPosition();
            const s = await win.outerSize();
            localStorage.setItem("mascot-anchor", JSON.stringify({
                ax: p.x + s.width,
                ay: p.y + s.height,
            }));
        });

        // 事件监听
        unlisten.push(await listen("config-changed", (e) => {
            const payload = e.payload as { llm?: object; character?: object; memory_window?: number; character_id?: string };
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({
                    type: "configure",
                    llm: payload.llm ?? {},
                    character: payload.character ?? {},
                    memory_window: payload.memory_window ?? parseInt(localStorage.getItem("rl-memory-window") ?? "1", 10),
                    character_id: payload.character_id ?? localStorage.getItem("rl-active-preset-id") ?? "",
        }));
    }
        }));
        unlisten.push(await listen("mascot-hover", (e) => {
            showUnlock.value = e.payload as boolean;
        }));
        unlisten.push(await listen("open-settings", async () => {
            await invoke("open_settings");
        }));

        // 监听设置界面发来的模型切换事件
        unlisten.push(await listen("model-changed", async (e) => {
            const path = (e.payload as { path: string }).path;
            await reloadLive2D(path);
        }));

        unlisten.push(await listen("config-changed", (e) => {
            const payload = e.payload as { llm?: object; character?: object };
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({
                    type: "configure",
                    llm: payload.llm ?? {},
                    character: payload.character ?? {},
                }));
            }
        }));

        // ── Live2D 初始化（最后执行，不阻塞其他逻辑）──────────────
        await initLive2D();
    });

    onUnmounted(() => {
        ws?.close();
        unlisten.forEach(fn => fn());
        disposeLive2D();
        stopTTS();
        audioCtx?.close();
    });
</script>

<template>
    <div class="mascot-root"
         :style="{
             '--mascot-w': sizeConfig.baseW + 'px',
             '--mascot-h': sizeConfig.baseH + 'px',
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
                        <button class="ctrl-btn" @mousedown.stop @click.stop="toggleLock" title="锁定">
                            🔓
                        </button>
                        <button class="ctrl-btn" @mousedown.stop @click.stop="openSettings" title="设置">
                            ⚙️
                        </button>
                        <button class="ctrl-btn" @mousedown.stop @click.stop="openHistory" title="聊天记录">
                            📋
                        </button>
                        <button class="ctrl-btn" @mousedown.stop @click.stop title="音量">
                            🔊
                        </button>
                        <button class="ctrl-btn" @mousedown.stop @click.stop="toggleInput" title="输入">
                            💬
                        </button>
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

    /* ── Live2D 画布 ──────────────────────────────────────────── */
    .live2d-canvas {
        position: absolute;
        top: 0;
        left: 0;
        pointer-events: none;
        z-index: 1;
        will-change: transform;
    }

    /* ── 占位剪影（Live2D 未就绪时显示） ─────────────────────── */
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
        width: var(--input-w, 240px);
        height: var(--mascot-h, 380px);
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