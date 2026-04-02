/**
 * useLive2D.ts — Live2D 渲染、表情与唇音口型驱动
 *
 * 职责：
 *   - PIXI Application 初始化 / 销毁 / 模型热切换
 *   - 帧切换参数保护（stepped 插值二值化 + crossfade 禁用）
 *   - 表情系统（expression 接口 / 参数直驱 fallback）
 *   - 嘴部开合参数驱动（由 useTTS 通过 setMouthOpen 调用）
 *
 * 依赖注入：
 *   canvasRef  — HTMLCanvasElement 的 Ref，由 App.vue 传入
 *   BASE_W / BASE_H — 来自 useSizePreset 的 ComputedRef，决定 canvas / PIXI 尺寸
 *
 * 不知道 TTS、WebSocket、窗口几何的存在。
 */

import { ref, type Ref, type ComputedRef } from "vue";
import * as PIXI from "pixi.js";
import { Live2DModel } from "pixi-live2d-display/cubism4";
import { type EmotionTag } from "./utils/emotion";

// Ticker 只注册一次（模块级 flag）
let tickerRegistered = false;

// ── 模型个性化配置（localStorage） ───────────────────────────────────
const MODEL_SETTINGS_KEY   = "rl-model-settings";
const DEFAULT_MODEL_ZOOM   = 1.7;
const DEFAULT_MODEL_Y      = -80;

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
    let pixiApp: PIXI.Application | null        = null;
    let live2dModel: any                        = null;
    let live2dContainer: PIXI.Container | null  = null;
    let renderTexture: PIXI.RenderTexture | null = null;

    // 帧切换保护用
    let steppedParamIds: string[] = [];

    // 表情重置计时器
    let emotionResetTimer: ReturnType<typeof setTimeout> | null = null;

    // ── 帧切换参数保护 ────────────────────────────────────────────────
    // 某些手绘线稿模型（如 MO）用 stepped 插值在 0/1 之间跳变来切换帧。
    // pixi-live2d-display 的 crossfade 和物理引擎会破坏跳变，导致多帧叠加 / 闪烁。
    // 双保险方案：A. 归零 idle motion 的 fadeIn/Out；B. coreModel.update hook 强制二值化。
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    async function setupFrameSwitchProtection(model: any, modelPath: string) {
        steppedParamIds = [];
        let detected: string[] = [];

        // Step 1：解析 motion 文件，检测 stepped 参数
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
                let i = 2; // 跳过首个控制点 [time, value]
                while (i < segs.length) {
                    const t = segs[i];
                    if      (t === 0) i += 3;
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

        // Step 2：禁用已加载 motion 实例的 fade 权重
        try {
            const mm = model.internalModel.motionManager;
            if (mm) {
                const groups = mm.motionGroups ?? mm._motionGroups;
                if (groups) {
                    const idleMotions = groups.Idle ?? groups.idle;
                    if (Array.isArray(idleMotions)) {
                        for (const motion of idleMotions) {
                            if (!motion) continue;
                            if (typeof motion.setFadeInTime  === "function") motion.setFadeInTime(0);
                            if (typeof motion.setFadeOutTime === "function") motion.setFadeOutTime(0);
                            if ("_fadeInSeconds"  in motion) motion._fadeInSeconds  = 0;
                            if ("_fadeOutSeconds" in motion) motion._fadeOutSeconds = 0;
                        }
                        console.info(`[Live2D] 已禁用 ${idleMotions.length} 个 idle motion 的 crossfade`);
                    }
                }
                // 同时修改 definitions（影响后续新创建的实例）
                const defs = mm.definitions?.Idle ?? mm.definitions?.idle;
                if (Array.isArray(defs)) {
                    for (const def of defs) { def.FadeInTime = 0; def.FadeOutTime = 0; }
                }
                if ("_fadeInTime"  in mm) mm._fadeInTime  = 0;
                if ("_fadeOutTime" in mm) mm._fadeOutTime = 0;
            }
        } catch (e) {
            console.warn("[Live2D] fade 禁用失败（将依赖二值化钳制）:", e);
        }

        // Step 3：hook coreModel.update，在 motion+physics 之后强制二值化
        steppedParamIds = detected;
        try {
            const core = model.internalModel.coreModel;
            const originalUpdate = core.update.bind(core);
            const paramIds = core._model.parameters.ids;
            const paramVals = core._model.parameters.values;
            // 预计算参数索引，避免每帧 indexOf 查找
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
            // steppedParamIds 不清空，ticker 中的二值化作为后备
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

    /** 无表情文件时：直接操控标准参数 */
    function applyEmotionByParams(emotion: EmotionTag) {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const core: any = live2dModel?.internalModel?.coreModel;
        if (!core) return;
        const set = (id: string, v: number) => {
            try { core.setParameterValueById(id, v); } catch { /* ignore */ }
        };

        // 先全部归位
        set("ParamMouthForm",  0); set("ParamMouthOpenY", 0);
        set("ParamEyeLOpen",   1); set("ParamEyeROpen",   1);
        set("ParamBrowLY",     0); set("ParamBrowRY",     0);
        set("ParamBrowLForm",  0); set("ParamBrowRForm",  0);
        set("Param74",         0); // MO 腮红
        set("ParamCheek",      0); // 标准腮红

        switch (emotion) {
            case "happy":
                set("ParamMouthForm", 1.0);
                set("ParamEyeLOpen",  0.6); set("ParamEyeROpen", 0.6);
                set("ParamBrowLY",    0.6); set("ParamBrowRY",   0.6);
                set("Param74",        2.0); set("ParamCheek",    1.0);
                break;
            case "sad":
                set("ParamMouthForm", -1.0);
                set("ParamEyeLOpen",   0.7); set("ParamEyeROpen",  0.7);
                set("ParamBrowLY",    -1.0); set("ParamBrowRY",   -1.0);
                set("ParamBrowLForm", -1.0); set("ParamBrowRForm",-1.0);
                break;
            case "angry":
                set("ParamMouthForm", -1.0);
                set("ParamBrowLY",    -1.0); set("ParamBrowRY",   -1.0);
                set("ParamBrowLForm", -1.0); set("ParamBrowRForm",-1.0);
                set("ParamEyeLOpen",   1.4); set("ParamEyeROpen",  1.4);
                break;
            case "shy":
                set("ParamMouthForm", 0.8);
                set("ParamEyeLOpen",  0.5); set("ParamEyeROpen",  0.5);
                set("ParamBrowLY",   -0.3); set("ParamBrowRY",   -0.3);
                set("Param74",        2.0); set("ParamCheek",     1.0);
                break;
            case "surprised":
                set("ParamMouthOpenY", 0.8); set("ParamMouthForm", 0.3);
                set("ParamBrowLY",     1.0); set("ParamBrowRY",    1.0);
                set("ParamEyeLOpen",   2.0); set("ParamEyeROpen",  2.0);
                break;
            case "sigh":
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

    /**
     * 设置嘴部开合参数（由 useTTS 通过依赖注入调用）
     * @param value  0.0（闭合）~ 1.0（全开），映射到 ParamMouthOpenY（0~2.1）
     */
    function setMouthOpen(value: number) {
        if (!live2dModel || !live2dReady.value) return;
        const mapped = Math.max(0, Math.min(1, value)) * 2.1;
        try {
            live2dModel.internalModel.coreModel.setParameterValueById("ParamMouthOpenY", mapped);
        } catch { /* ignore */ }
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

        // 归位多状态手臂部件（无此 Part 的模型静默忽略）
        try {
            const core = model.internalModel.coreModel;
            core.setPartOpacityById("PartArmA", 1);
            core.setPartOpacityById("PartArmB", 0);
        } catch { /* ignore */ }
    }

    // ── 核心 API ──────────────────────────────────────────────────────
    /**
     * 初始化 PIXI + Live2D 模型。
     * ⚠️  需要 public/live2dcubismcore.min.js 已加载（见 index.html）。
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
        // preserveDrawingBuffer: true 会禁用 WebGL 前后缓冲交换，
        // 导致 DWM 截到空白帧，是闪烁的根本原因。
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

        // 第一层保护：RenderTexture（离屏渲染，DWM 完全不可见中间帧）
        renderTexture  = PIXI.RenderTexture.create({ width: w, height: h });
        const sprite   = new PIXI.Sprite(renderTexture);
        pixiApp.stage.addChild(sprite);
        live2dContainer = new PIXI.Container();

        try {
            const modelPath = localStorage.getItem("rl-model-path") ?? "live2d/MO/MO.model3.json";
            live2dModel = await Live2DModel.from("/" + modelPath, { autoInteract: false });
            mountModel(live2dModel, modelPath, w);
            setupFrameSwitchProtection(live2dModel, modelPath);
        } catch (e) {
            console.error("[Live2D] 模型加载失败:", e);
            live2dError.value = true;
            return;
        }

        // 第二层保护：Ticker 离屏渲染（DWM 永远只看前缓冲的完整帧）
        pixiApp.ticker.add(() => {
            // ticker 层 stepped 参数二值化（作为 coreModel hook 失败时的后备）
            // steppedParamIds 为空时直接跳过，零开销
            if (steppedParamIds.length > 0 && live2dModel && live2dReady.value) {
                try {
                    const core = live2dModel.internalModel.coreModel;
                    const ids  = core._model.parameters.ids;
                    const vals = core._model.parameters.values;
                    for (const id of steppedParamIds) {
                        const idx = ids.indexOf(id);
                        if (idx >= 0) vals[idx] = vals[idx] >= 0.5 ? 1 : 0;
                    }
                } catch { /* ignore */ }
            }
            renderer.render(live2dContainer!, { renderTexture: renderTexture!, clear: true });
        });

        live2dReady.value = true;
    }

    /** 销毁 PIXI 实例（onUnmounted 调用） */
    function disposeLive2D() {
        if (emotionResetTimer) clearTimeout(emotionResetTimer);
        if (live2dModel && live2dContainer) live2dContainer.removeChild(live2dModel);
        live2dContainer?.destroy({ children: true });
        renderTexture?.destroy(true);
        pixiApp?.destroy(false, { children: true });
        live2dModel     = null;
        live2dContainer = null;
        renderTexture   = null;
        pixiApp         = null;
        live2dReady.value = false;
        live2dError.value = false;
        steppedParamIds   = [];
    }

    /** 热切换模型：保留 pixiApp / canvas / ticker / renderTexture */
    async function reloadLive2D(newPath: string) {
        localStorage.setItem("rl-model-path", newPath);

        if (!pixiApp || !live2dContainer) {
            await initLive2D();
            return;
        }

        live2dReady.value = false;
        steppedParamIds   = [];

        if (live2dModel) {
            live2dContainer.removeChild(live2dModel);
            live2dModel.destroy();
            live2dModel = null;
        }

        try {
            live2dModel = await Live2DModel.from("/" + newPath, { autoInteract: false });
            mountModel(live2dModel, newPath, BASE_W.value);
            setupFrameSwitchProtection(live2dModel, newPath);
            live2dReady.value = true;
            console.info(`[Live2D] 模型切换成功 ✓  (${newPath})`);
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
        // 供设置界面读写模型缩放/偏移（如未来 Settings 组件需要）
        getModelSettings,
        saveModelSettings,
    };
}