/**
 * useLive2D.ts — Live2D 渲染、表情与唇音口型驱动
 *
 * 职责：
 *   - PIXI Application 初始化 / 销毁 / 模型热切换
 *   - 帧切换参数保护（stepped 插值二值化 + crossfade 禁用）
 *   - 表情系统（expression 接口 / 参数直驱 fallback）
 *   - 嘴部开合参数驱动（由 useTTS 通过 setMouthOpen 调用）
 *   - 尺寸响应式更新（BASE_W 变化时自动 resize 渲染器 + 模型缩放）
 *
 * 依赖注入：
 *   canvasRef  — HTMLCanvasElement 的 Ref，由 App.vue 传入
 *   BASE_W / BASE_H — 来自 useSizePreset 的 ComputedRef，决定 canvas / PIXI 尺寸
 *
 * 不知道 TTS、WebSocket、窗口几何的存在。
 */

import { ref, watch, type Ref, type ComputedRef } from "vue";
import * as PIXI from "pixi.js";
import { Live2DModel } from "pixi-live2d-display/cubism4";
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
    let live2dModel: any = null;
    let live2dContainer: PIXI.Container | null = null;
    let renderTexture: PIXI.RenderTexture | null = null;
    // [FIX] 将 sprite 提升为模块变量，供 resizeLive2D 更新纹理引用
    let displaySprite: PIXI.Sprite | null = null;

    // 帧切换保护用
    let steppedParamIds: string[] = [];

    // 表情重置计时器
    let emotionResetTimer: ReturnType<typeof setTimeout> | null = null;

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

        try {
            const core = model.internalModel.coreModel;
            core.setPartOpacityById("PartArmA", 1);
            core.setPartOpacityById("PartArmB", 0);
        } catch { /* ignore */ }
    }

    // ── [FIX] 响应式尺寸更新 ──────────────────────────────────────────
    // 当 BASE_W / BASE_H 变化时（用户切换尺寸档位），同步更新：
    //   1. PIXI 渲染器尺寸
    //   2. RenderTexture（需销毁重建，不支持 resize）
    //   3. displaySprite 的纹理引用
    //   4. 模型缩放与位置
    function resizeLive2D(w: number, h: number) {
        if (!pixiApp || !live2dContainer || !displaySprite) return;

        // 1. 渲染器 resize（同时更新 canvas 的 width/height attribute）
        pixiApp.renderer.resize(w, h);

        // 2. 销毁旧 RenderTexture，重建新尺寸的
        renderTexture?.destroy(true);
        renderTexture = PIXI.RenderTexture.create({ width: w, height: h });

        // 3. 更新 sprite 的纹理引用
        displaySprite.texture = renderTexture;

        // 4. 重算模型缩放与位置
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

    // [FIX] 监听 BASE_W 变化，自动触发 resizeLive2D
    // BASE_W 与 BASE_H / INPUT_W / BUBBLE_H 同档联动，监听一个即可。
    watch(BASE_W, (newW) => {
        resizeLive2D(newW, BASE_H.value);
    });

    // ── 核心 API ──────────────────────────────────────────────────────
    async function initLive2D() {
        if (!canvasRef.value) return;

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
        // [FIX] 将 sprite 赋给模块变量 displaySprite，供 resizeLive2D 使用
        displaySprite = new PIXI.Sprite(renderTexture);
        pixiApp.stage.addChild(displaySprite);
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

        pixiApp.ticker.add(() => {
            if (steppedParamIds.length > 0 && live2dModel && live2dReady.value) {
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

        live2dReady.value = true;
    }

    function disposeLive2D() {
        if (emotionResetTimer) clearTimeout(emotionResetTimer);
        if (live2dModel && live2dContainer) live2dContainer.removeChild(live2dModel);
        live2dContainer?.destroy({ children: true });
        renderTexture?.destroy(true);
        pixiApp?.destroy(false, { children: true });
        live2dModel = null;
        live2dContainer = null;
        renderTexture = null;
        displaySprite = null;   // [FIX] 同步清理
        pixiApp = null;
        live2dReady.value = false;
        live2dError.value = false;
        steppedParamIds = [];
    }

    async function reloadLive2D(newPath: string) {
        localStorage.setItem("rl-model-path", newPath);

        if (!pixiApp || !live2dContainer) {
            await initLive2D();
            return;
        }

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
        getModelSettings,
        saveModelSettings,
    };
}