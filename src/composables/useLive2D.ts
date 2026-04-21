/**
 * useLive2D.ts — Live2D 渲染、表情、唇音、动作调度
 *
 * 职责：
 *   - PIXI Application 初始化 / 销毁 / 模型热切换
 *   - 帧切换参数保护（stepped 插值二值化 + crossfade 禁用）
 *   - 表情系统（expression 接口 / 参数直驱 fallback）
 *   - 嘴部开合参数驱动（由 useTTS 通过 setMouthOpen 调用）
 *   - 尺寸响应式更新（BASE_W 变化时自动 resize 渲染器 + 模型缩放）
 *   - 【Phase 4 新增】动作调度：
 *       · 待机随机（NORMAL 优先级，配置化间隔）
 *       · 高优先级通道 playMotion（FORCE，自动打断 + 重置待机计时）
 *
 * 依赖注入：
 *   canvasRef  — HTMLCanvasElement 的 Ref，由 App.vue 传入
 *   BASE_W / BASE_H — 来自 useSizePreset 的 ComputedRef，决定 canvas / PIXI 尺寸
 *
 * 不知道 TTS、WebSocket、窗口几何的存在。
 *
 * 性能说明：
 *   Live2DModel.from() 在 WebView2 dev 模式下需要 7~8 秒（Cubism Core 初始化 +
 *   WebGL 纹理创建的开销，与模型文件大小无关）。为避免阻塞窗口显示，initLive2D()
 *   在创建完 PIXI Application 后立即返回，模型在后台异步加载。Ticker 渲染受
 *   live2dReady 守卫保护，模型就绪前不渲染 live2dContainer，避免空容器闪烁。
 *
 * 动作调度说明（Phase 4）：
 *   三类触发源 → 两条优先级通道
 *     · 待机随机    → NORMAL
 *     · 情绪 Motion  → FORCE（未来 EMOTION_TAG 模块 A 落地时通过 playMotion 接入）
 *     · AI 指定      → FORCE（同上）
 *   FORCE 优先级由 pixi-live2d-display 底层保证打断正在播放的 NORMAL 动作。
 *   高优先级触发后，本模块额外重置待机计时，防止"紧跟着又触发一个待机"的违和。
 */

import { ref, watch, type Ref, type ComputedRef } from "vue";
import * as PIXI from "pixi.js";
import { Live2DModel, MotionPriority } from "pixi-live2d-display/cubism4";
import { type EmotionTag } from "./utils/emotion";

// Ticker 只注册一次（模块级 flag）
let tickerRegistered = false;

// ── 模型个性化配置（localStorage） ───────────────────────────────────
const MODEL_SETTINGS_KEY = "rl-model-settings";
const DEFAULT_MODEL_ZOOM = 1.7;
const DEFAULT_MODEL_Y = -80;

function getModelSettings(path: string): { zoom: number; y: number } {
    try {
        const all = JSON.parse(localStorage.getItem(MODEL_SETTINGS_KEY) ?? "{}");
        const s = all[path];
        if (s && typeof s.zoom === "number" && typeof s.y === "number") return s;
    } catch { /* corrupt data */ }
    return { zoom: DEFAULT_MODEL_ZOOM, y: DEFAULT_MODEL_Y };
}

function saveModelSettings(path: string, zoom: number, y: number) {
    try {
        const all = JSON.parse(localStorage.getItem(MODEL_SETTINGS_KEY) ?? "{}");
        all[path] = { zoom, y };
        localStorage.setItem(MODEL_SETTINGS_KEY, JSON.stringify(all));
    } catch { /* ignore */ }
}

// ── 待机动画默认配置 ─────────────────────────────────────────────────
// 与 Live2DTab.vue 保持一致
export const IDLE_MOTION_DEFAULT = {
    enabled: false,
    minInterval: 30,  // 秒
    maxInterval: 60,  // 秒
};
export type IdleMotionConfig = typeof IDLE_MOTION_DEFAULT;

// ── 主体 ──────────────────────────────────────────────────────────────
export function useLive2D(
    canvasRef: Ref<HTMLCanvasElement | null>,
    BASE_W: ComputedRef<number>,
    BASE_H: ComputedRef<number>,
) {
    // Ticker 注册（仅第一次）
    if (!tickerRegistered) {
        Live2DModel.registerTicker(PIXI.Ticker);
        tickerRegistered = true;
    }

    // ── 状态 ──────────────────────────────────────────────────────────
    const live2dReady = ref(false);
    const live2dError = ref(false);

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    let pixiApp: PIXI.Application | null = null;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    let live2dModel: any = null;
    let live2dContainer: PIXI.Container | null = null;
    let renderTexture: PIXI.RenderTexture | null = null;
    let displaySprite: PIXI.Sprite | null = null;

    // 帧切换保护用
    let steppedParamIds: string[] = [];

    // 表情重置计时器
    let emotionResetTimer: ReturnType<typeof setTimeout> | null = null;

    // ── 待机动画调度状态 ──────────────────────────────────────────────
    let idleConfig: IdleMotionConfig = { ...IDLE_MOTION_DEFAULT };
    let idleTimer: ReturnType<typeof setTimeout> | null = null;

    // ── 帧切换参数保护 ────────────────────────────────────────────────
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    async function setupFrameSwitchProtection(model: any, modelPath: string) {
        steppedParamIds = [];
        let detected: string[] = [];

        try {
            const modelRes = await fetch("/" + modelPath);
            if (!modelRes.ok) return;
            const modelData = await modelRes.json();
            const idleList = modelData?.FileReferences?.Motions?.Idle;
            if (!Array.isArray(idleList) || idleList.length === 0) return;

            const motionRel = idleList[0].File;
            if (!motionRel) return;
            const modelDir = modelPath.substring(0, modelPath.lastIndexOf("/"));
            const motionRes = await fetch("/" + modelDir + "/" + motionRel);
            if (!motionRes.ok) return;
            const motionData = await motionRes.json();

            const curves = motionData?.Curves;
            if (!Array.isArray(curves)) return;

            for (const curve of curves) {
                if (curve.Target !== "Parameter") continue;
                const segs: number[] = curve.Segments;
                if (!Array.isArray(segs)) continue;
                let hasStepped = false;
                let i = 2;
                while (i < segs.length) {
                    const t = segs[i];
                    if (t === 0) i += 3;
                    else if (t === 1) i += 7;
                    else if (t === 2 || t === 3) { hasStepped = true; i += 3; }
                    else break;
                }
                if (hasStepped) detected.push(curve.Id);
            }
        } catch (e) {
            console.warn("[Live2D] stepped 参数检测失败:", e);
            return;
        }

        if (detected.length === 0) return;

        try {
            const mm = model.internalModel.motionManager;
            if (mm) {
                const groups = mm.motionGroups ?? mm._motionGroups;
                if (groups) {
                    const idleMotions = groups.Idle ?? groups.idle;
                    if (Array.isArray(idleMotions)) {
                        for (const motion of idleMotions) {
                            if (!motion) continue;
                            if (typeof motion.setFadeInTime === "function") motion.setFadeInTime(0);
                            if (typeof motion.setFadeOutTime === "function") motion.setFadeOutTime(0);
                            if ("_fadeInSeconds" in motion) motion._fadeInSeconds = 0;
                            if ("_fadeOutSeconds" in motion) motion._fadeOutSeconds = 0;
                        }
                        console.info(`[Live2D] 已禁用 ${idleMotions.length} 个 idle motion 的 crossfade`);
                    }
                }
                const defs = mm.definitions?.Idle ?? mm.definitions?.idle;
                if (Array.isArray(defs)) {
                    for (const def of defs) { def.FadeInTime = 0; def.FadeOutTime = 0; }
                }
                if ("_fadeInTime" in mm) mm._fadeInTime = 0;
                if ("_fadeOutTime" in mm) mm._fadeOutTime = 0;
            }
        } catch (e) {
            console.warn("[Live2D] fade 禁用失败（将依赖二值化钳制）:", e);
        }

        steppedParamIds = detected;
        try {
            const core = model.internalModel.coreModel;
            const originalUpdate = core.update.bind(core);
            const paramIds = core._model.parameters.ids;
            const paramVals = core._model.parameters.values;
            const idxMap: number[] = [];
            for (const id of detected) {
                const idx = paramIds.indexOf(id);
                if (idx >= 0) idxMap.push(idx);
            }
            core.update = function () {
                for (const idx of idxMap) {
                    paramVals[idx] = paramVals[idx] >= 0.5 ? 1 : 0;
                }
                return originalUpdate();
            };
            console.info(
                `[Live2D] 帧切换保护已启用：${detected.length} 个参数 ` +
                `(${detected.join(", ")})，已 hook coreModel.update 进行二值化`
            );
        } catch (e) {
            console.warn("[Live2D] coreModel hook 失败，回退到 ticker 二值化:", e);
        }
    }

    // ── 表情系统 ──────────────────────────────────────────────────────
    function modelHasExpressions(): boolean {
        try {
            const defs = live2dModel?.internalModel?.motionManager
                ?.expressionManager?.definitions;
            return Array.isArray(defs) && defs.length > 0;
        } catch { return false; }
    }

    function applyEmotionByParams(emotion: EmotionTag) {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const core: any = live2dModel?.internalModel?.coreModel;
        if (!core) return;
        const set = (id: string, v: number) => {
            try { core.setParameterValueById(id, v); } catch { /* ignore */ }
        };

        set("ParamMouthForm", 0); set("ParamMouthOpenY", 0);
        set("ParamEyeLOpen", 1); set("ParamEyeROpen", 1);
        set("ParamBrowLY", 0); set("ParamBrowRY", 0);
        set("ParamBrowLForm", 0); set("ParamBrowRForm", 0);
        set("Param74", 0);
        set("ParamCheek", 0);

        switch (emotion) {
            case "happy":
                set("ParamMouthForm", 1.0);
                set("ParamEyeLOpen", 0.6); set("ParamEyeROpen", 0.6);
                set("ParamBrowLY", 0.6); set("ParamBrowRY", 0.6);
                set("Param74", 2.0); set("ParamCheek", 1.0);
                break;
            case "sad":
                set("ParamMouthForm", -1.0);
                set("ParamEyeLOpen", 0.7); set("ParamEyeROpen", 0.7);
                set("ParamBrowLY", -1.0); set("ParamBrowRY", -1.0);
                set("ParamBrowLForm", -1.0); set("ParamBrowRForm", -1.0);
                break;
            case "angry":
                set("ParamMouthForm", -1.0);
                set("ParamBrowLY", -1.0); set("ParamBrowRY", -1.0);
                set("ParamBrowLForm", -1.0); set("ParamBrowRForm", -1.0);
                set("ParamEyeLOpen", 1.4); set("ParamEyeROpen", 1.4);
                break;
            case "shy":
                set("ParamMouthForm", 0.8);
                set("ParamEyeLOpen", 0.5); set("ParamEyeROpen", 0.5);
                set("ParamBrowLY", -0.3); set("ParamBrowRY", -0.3);
                set("Param74", 2.0); set("ParamCheek", 1.0);
                break;
            case "surprised":
                set("ParamMouthOpenY", 0.8); set("ParamMouthForm", 0.3);
                set("ParamBrowLY", 1.0); set("ParamBrowRY", 1.0);
                set("ParamEyeLOpen", 2.0); set("ParamEyeROpen", 2.0);
                break;
            case "sigh":
            case "neutral":
            default:
                break;
        }
    }

    function setEmotion(emotion: EmotionTag) {
        if (!live2dModel || !live2dReady.value) return;
        if (emotionResetTimer) clearTimeout(emotionResetTimer);

        if (modelHasExpressions()) {
            live2dModel.expression(emotion);
        } else {
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

    function setMouthOpen(value: number) {
        if (!live2dModel || !live2dReady.value) return;
        const mapped = Math.max(0, Math.min(1, value)) * 2.1;
        try {
            live2dModel.internalModel.coreModel.setParameterValueById("ParamMouthOpenY", mapped);
        } catch { /* ignore */ }
    }

    // ── 动作调度 ──────────────────────────────────────────────────────

    /**
     * 枚举当前模型已注册的非 Idle 动作组。
     * 返回 [{group, count}, ...]，group 可能是 ""（VTS 免费模型惯例）。
     * 无可用动作时返回空数组。
     */
    function getMotionList(): { group: string; count: number }[] {
        if (!live2dModel || !live2dReady.value) return [];
        try {
            const defs = live2dModel.internalModel?.motionManager?.definitions;
            if (!defs || typeof defs !== "object") return [];
            const result: { group: string; count: number }[] = [];
            for (const [group, list] of Object.entries(defs)) {
                if (group.toLowerCase() === "idle") continue;
                if (Array.isArray(list) && list.length > 0) {
                    result.push({ group, count: list.length });
                }
            }
            return result;
        } catch (e) {
            console.warn("[Live2D] getMotionList 失败:", e);
            return [];
        }
    }

    /**
     * 高优先级动作触发通道（对外）。
     *
     * 行为：
     *   1. 用 FORCE 优先级触发指定动作 → pixi-live2d-display 底层会打断
     *      当前正在播放的 NORMAL 动作（含待机随机刚触发的动作）。
     *   2. 重置待机计时器 → 避免"高优先级动作才放完，紧接着又触发待机"。
     *
     * 调用场景（Stage 1 保留此通道，实际使用方在后续阶段接入）：
     *   - 情绪标签绑定到 motion 时（EMOTION_TAG 模块 A）
     *   - AI 回复中的 [motion:xx] 标签
     */
    function playMotion(group: string, index?: number) {
        if (!live2dModel || !live2dReady.value) {
            console.warn("[Live2D] playMotion 失败：模型未就绪");
            return;
        }
        try {
            // index 省略 → pixi-live2d-display 会在该组内随机挑一个
            const promise = live2dModel.motion(group, index, MotionPriority.FORCE);
            console.info(
                `[Live2D] playMotion: group="${group}" index=${index ?? "random"} ` +
                `priority=FORCE`
            );
            // 重置待机计时（无论动作是否成功触发，都视为"有新动作刚发生"）
            if (idleConfig.enabled) {
                rescheduleIdle();
                console.info("[Live2D] 高优先级动作触发后，待机计时已重置");
            }
            return promise;
        } catch (e) {
            console.warn("[Live2D] playMotion 异常:", e);
        }
    }

    /**
     * 待机随机触发（内部）。用 NORMAL 优先级，可被 FORCE 打断。
     */
    function fireIdleRandom() {
        if (!live2dModel || !live2dReady.value) return;
        const list = getMotionList();
        if (list.length === 0) {
            // 模型无非 Idle 动作（如 MO），静默跳过。不打 warn，避免日志刷屏。
            return;
        }
        // 先按组数均匀挑组，再组内均匀挑索引
        const group = list[Math.floor(Math.random() * list.length)];
        const index = Math.floor(Math.random() * group.count);
        try {
            live2dModel.motion(group.group, index, MotionPriority.NORMAL);
            console.info(
                `[Live2D] 待机动画触发: group="${group.group}" index=${index}/${group.count}`
            );
        } catch (e) {
            console.warn("[Live2D] 待机动画触发异常:", e);
        }
    }

    /**
     * 计算下一次待机触发的延迟并注册 timer。
     * 内部调用，前置条件：enabled = true 且 live2dReady = true
     */
    function scheduleNextIdle() {
        if (!idleConfig.enabled || !live2dReady.value) return;
        const min = Math.max(1, idleConfig.minInterval);
        const max = Math.max(min, idleConfig.maxInterval);
        const delay = (min + Math.random() * (max - min)) * 1000;
        idleTimer = setTimeout(() => {
            idleTimer = null;
            fireIdleRandom();
            scheduleNextIdle();  // 链式调度
        }, delay);
    }

    /**
     * 清除待机计时器（不改变 enabled 状态）。
     */
    function stopIdleTimer() {
        if (idleTimer !== null) {
            clearTimeout(idleTimer);
            idleTimer = null;
        }
    }

    /**
     * 重置待机计时器：停止当前 + 立刻按 enabled 条件重新调度。
     * 供 playMotion 调用、也供配置变更时调用。
     */
    function rescheduleIdle() {
        stopIdleTimer();
        scheduleNextIdle();
    }

    /**
     * 配置待机动画（对外）。
     * 由 App.vue 在启动时读 localStorage 调用一次，
     * 用户在 Live2DTab.vue 改配置后通过 Tauri 事件触发再次调用。
     */
    function configureIdleMotion(cfg: Partial<IdleMotionConfig>) {
        idleConfig = { ...idleConfig, ...cfg };
        // 规范化
        if (idleConfig.minInterval < 1) idleConfig.minInterval = 1;
        if (idleConfig.maxInterval < idleConfig.minInterval) {
            idleConfig.maxInterval = idleConfig.minInterval;
        }
        console.info(
            `[Live2D] 待机动画配置: enabled=${idleConfig.enabled} ` +
            `interval=${idleConfig.minInterval}~${idleConfig.maxInterval}s`
        );

        if (!idleConfig.enabled) {
            stopIdleTimer();
        } else {
            rescheduleIdle();
        }
    }

    // ── 内部辅助：将模型挂载到容器并应用位置 ─────────────────────────
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    function mountModel(model: any, path: string, w: number) {
        const { zoom, y } = getModelSettings(path);
        const scale = (w / model.internalModel.originalWidth) * zoom;
        model.scale.set(scale);
        model.anchor.set(0.5, 0);
        model.x = w / 2;
        model.y = y;
        live2dContainer!.addChild(model);

        // hiyori 模型特有：PartArmA/PartArmB 多状态手臂归位
        // VTS 免费模型的遗留问题，默认加载时会同时显示两套手臂。
        // 仅对 hiyori 系列模型生效（如 hiyori / hiyori_vts 等变体文件夹名），
        // 避免对其他模型无差别操作（如 MO 不存在这两个 Part）。
        if (path.toLowerCase().includes("hiyori")) {
            try {
                const core = model.internalModel.coreModel;
                core.setPartOpacityById("PartArmA", 1);
                core.setPartOpacityById("PartArmB", 0);
                console.info("[Live2D] hiyori 专属：已归位 PartArmA=1, PartArmB=0");
            } catch { /* ignore */ }
        }
    }

    // ── 内部辅助：后台加载模型 ───────────────────────────────────────
    /**
     * 异步加载 Live2D 模型到已就绪的 PIXI 容器中。
     * 由 initLive2D() 以 fire-and-forget 方式调用（不 await），
     * 使窗口可以立即显示占位剪影，模型加载完成后自然出现。
     *
     * Ticker 渲染受 live2dReady 守卫保护：
     * 模型就绪前 → Ticker 只 clear renderTexture（透明画布，剪影可见）
     * 模型就绪后 → Ticker 正常渲染 live2dContainer
     */
    async function loadModel() {
        try {
            const modelPath = localStorage.getItem("rl-model-path") ?? "live2d/MO/MO.model3.json";
            live2dModel = await Live2DModel.from("/" + modelPath, { autoInteract: false });
            live2dContainer!.removeChildren();
            mountModel(live2dModel, modelPath, BASE_W.value);
            await setupFrameSwitchProtection(live2dModel, modelPath);
            // 一切就绪后才设为 true，Ticker 才开始渲染模型
            live2dReady.value = true;
            // 模型就绪 → 按当前配置启动待机调度（若 enabled）
            if (idleConfig.enabled) {
                rescheduleIdle();
                console.info("[Live2D] 模型加载完成，待机动画已启动");
            }
        } catch (e) {
            console.error("[Live2D] 模型加载失败:", e);
            live2dError.value = true;
        }
    }

    // ── [FIX] 响应式尺寸更新 ──────────────────────────────────────────
    // 当 BASE_W / BASE_H 变化时（用户切换尺寸档位），同步更新：
    //   1. PIXI 渲染器尺寸
    //   2. RenderTexture（需销毁重建，不支持 resize）
    //   3. displaySprite 的纹理引用
    //   4. 模型缩放与位置
    function resizeLive2D(w: number, h: number) {
        if (!pixiApp || !live2dContainer || !displaySprite) return;

        pixiApp.renderer.resize(w, h);

        renderTexture?.destroy(true);
        renderTexture = PIXI.RenderTexture.create({ width: w, height: h });

        displaySprite.texture = renderTexture;

        if (live2dModel) {
            const modelPath = localStorage.getItem("rl-model-path") ?? "";
            const { zoom, y } = getModelSettings(modelPath);
            const scale = (w / live2dModel.internalModel.originalWidth) * zoom;
            live2dModel.scale.set(scale);
            live2dModel.x = w / 2;
            live2dModel.y = y;
        }

        console.info(`[Live2D] 尺寸已更新：${w} × ${h}`);
    }

    watch(BASE_W, (newW) => {
        resizeLive2D(newW, BASE_H.value);
    });

    // ── 核心 API ──────────────────────────────────────────────────────
    /**
     * 初始化 PIXI Application + RenderTexture + Ticker，然后立即返回。
     * 模型加载（Live2DModel.from()，WebView2 dev 下约 7~8 秒）在后台异步进行。
     *
     * 用户体验：窗口瞬间出现（占位剪影可见） → 数秒后模型淡入替换剪影。
     *
     * ⚠️  需要 public/live2dcubismcore.min.js 已加载（见 index.html）。
     */
    async function initLive2D() {
        if (pixiApp) {
            console.warn("[Live2D] initLive2D 重复调用，已跳过");
            return;
        }
        if (!canvasRef.value) return;

        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        if (typeof (window as any).Live2DCubismCore === "undefined") {
            console.warn("[Live2D] Cubism Core 未加载，请放入 public/ 并取消注释 index.html 中的 script 标签。");
            live2dError.value = true;
            return;
        }

        const w = BASE_W.value;
        const h = BASE_H.value;

        pixiApp = new PIXI.Application({
            view: canvasRef.value,
            backgroundAlpha: 0,
            width: w, height: h,
            antialias: true,
            resolution: 1,
            autoDensity: false,
            powerPreference: "high-performance",
        });

        const renderer = pixiApp.renderer as PIXI.Renderer;

        renderTexture = PIXI.RenderTexture.create({ width: w, height: h });
        displaySprite = new PIXI.Sprite(renderTexture);
        pixiApp.stage.addChild(displaySprite);
        live2dContainer = new PIXI.Container();

        pixiApp.ticker.add(() => {
            if (!live2dReady.value) return;

            if (steppedParamIds.length > 0 && live2dModel) {
                try {
                    const core = live2dModel.internalModel.coreModel;
                    const ids = core._model.parameters.ids;
                    const vals = core._model.parameters.values;
                    for (const id of steppedParamIds) {
                        const idx = ids.indexOf(id);
                        if (idx >= 0) vals[idx] = vals[idx] >= 0.5 ? 1 : 0;
                    }
                } catch { /* ignore */ }
            }
            renderer.render(live2dContainer!, { renderTexture: renderTexture!, clear: true });
        });

        // 模型加载在后台进行，不阻塞 initLive2D 返回
        loadModel();
    }

    function disposeLive2D() {
        if (emotionResetTimer) clearTimeout(emotionResetTimer);
        stopIdleTimer();  // [Phase 4] 清理待机计时
        if (live2dModel && live2dContainer) live2dContainer.removeChild(live2dModel);
        live2dContainer?.destroy({ children: true });
        renderTexture?.destroy(true);
        pixiApp?.destroy(false, { children: true });
        live2dModel = null;
        live2dContainer = null;
        renderTexture = null;
        displaySprite = null;
        pixiApp = null;
        live2dReady.value = false;
        live2dError.value = false;
        steppedParamIds = [];
    }

    async function reloadLive2D(newPath: string) {
        localStorage.setItem("rl-model-path", newPath);

        if (!pixiApp || !live2dContainer) {
            initLive2D();
            return;
        }

        // [Phase 4] 模型切换前先停止待机调度，避免旧计时器在新模型上触发
        stopIdleTimer();
        live2dReady.value = false;
        steppedParamIds = [];

        if (live2dModel) {
            live2dContainer.removeChild(live2dModel);
            live2dModel.destroy();
            live2dModel = null;
        }

        try {
            live2dModel = await Live2DModel.from("/" + newPath, { autoInteract: false });
            mountModel(live2dModel, newPath, BASE_W.value);
            await setupFrameSwitchProtection(live2dModel, newPath);
            live2dReady.value = true;
            console.info(`[Live2D] 模型切换成功 ✓  (${newPath})`);
            // 新模型就绪 → 按当前配置重新启动待机调度
            if (idleConfig.enabled) {
                rescheduleIdle();
                console.info("[Live2D] 模型切换后，待机动画已在新模型上重启");
            }
        } catch (e) {
            console.error("[Live2D] 模型切换失败:", e);
            live2dError.value = true;
        }
    }

    return {
        live2dReady,
        live2dError,
        initLive2D,
        disposeLive2D,
        reloadLive2D,
        setEmotion,
        setMouthOpen,
        getModelSettings,
        saveModelSettings,
        // [Phase 4] 新增
        playMotion,
        getMotionList,
        configureIdleMotion,
    };
}