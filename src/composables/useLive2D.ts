/**
 * useLive2D.ts — Live2D 渲染、表情、唇音、动作调度、装扮系统
 *
 * 职责：
 *   - PIXI Application 初始化 / 销毁 / 模型热切换
 *   - 帧切换参数保护（stepped 插值二值化 + crossfade 禁用）
 *   - 表情系统（expression 接口 / 参数直驱 fallback）
 *   - 嘴部开合参数驱动（由 useTTS 通过 setMouthOpen 调用）
 *   - 尺寸响应式更新（BASE_W 变化时自动 resize 渲染器 + 模型缩放）
 *   - 【Phase 4】动作调度：
 *       · 待机随机（NORMAL 优先级，配置化间隔）
 *       · 高优先级通道 playMotion（FORCE，自动打断 + 重置待机计时）
 *   - 【Phase 4】装扮系统：
 *       · 模型加载完成后自动从后端拉取 appearance.json 并应用
 *       · 对外暴露 getCoreParameters / getCoreParts / applyAppearance
 *         供装扮面板实时预览和保存
 *
 * 依赖注入：
 *   canvasRef  — HTMLCanvasElement 的 Ref，由 App.vue 传入
 *   BASE_W / BASE_H — 来自 useSizePreset 的 ComputedRef，决定 canvas / PIXI 尺寸
 *
 * 不知道 TTS、WebSocket、窗口几何的存在。
 *
 * 装扮系统说明（Phase 4）：
 *   模型加载完成后（setupFrameSwitchProtection 之后、live2dReady = true 之前），
 *   自动 fetch 后端 /api/live2d/appearance-schema 获取已存的 appearance.json 内容，
 *   通过 applyAppearance 还原用户上次的装扮。
 *   装扮面板通过 getCoreParameters / getCoreParts 获取运行时参数范围，
 *   通过 applyAppearance 实时预览。
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
export const IDLE_MOTION_DEFAULT = {
    enabled: false,
    minInterval: 30,
    maxInterval: 60,
};
export type IdleMotionConfig = typeof IDLE_MOTION_DEFAULT;

// ── 装扮系统类型（Phase 4）───────────────────────────────────────────
export interface CoreParameter {
    id: string;
    min: number;
    max: number;
    default: number;
    current: number;
}

export interface CorePart {
    id: string;
    opacity: number;
}

export interface AppearanceConfig {
    parameters: Record<string, number>;
    parts: Record<string, number>;
}

// ── 后端 sidecar 地址 ───────────────────────────────────────────────
const SIDECAR_URL = "http://localhost:18000";

// ── 辅助：从模型路径中提取文件夹名 ───────────────────────────────────
// "live2d/hiyori_vts/hiyori.model3.json" → "hiyori_vts"
function _extractFolderName(modelPath: string): string {
    const parts = modelPath.replace(/\\/g, "/").split("/");
    if (parts.length >= 3 && parts[0] === "live2d") {
        return parts[1];
    }
    return parts.length >= 2 ? parts[parts.length - 2] : "";
}

// ── 主体 ──────────────────────────────────────────────────────────────
export function useLive2D(
    canvasRef: Ref<HTMLCanvasElement | null>,
    BASE_W: ComputedRef<number>,
    BASE_H: ComputedRef<number>,
) {
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

    let steppedParamIds: string[] = [];
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

    function playMotion(group: string, index?: number) {
        if (!live2dModel || !live2dReady.value) {
            console.warn("[Live2D] playMotion 失败：模型未就绪");
            return;
        }
        try {
            const promise = live2dModel.motion(group, index, MotionPriority.FORCE);
            console.info(
                `[Live2D] playMotion: group="${group}" index=${index ?? "random"} priority=FORCE`
            );
            if (idleConfig.enabled) {
                rescheduleIdle();
                console.info("[Live2D] 高优先级动作触发后，待机计时已重置");
            }
            return promise;
        } catch (e) {
            console.warn("[Live2D] playMotion 异常:", e);
        }
    }

    function fireIdleRandom() {
        if (!live2dModel || !live2dReady.value) return;
        const list = getMotionList();
        if (list.length === 0) return;
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

    function scheduleNextIdle() {
        if (!idleConfig.enabled || !live2dReady.value) return;
        const min = Math.max(1, idleConfig.minInterval);
        const max = Math.max(min, idleConfig.maxInterval);
        const delay = (min + Math.random() * (max - min)) * 1000;
        idleTimer = setTimeout(() => {
            idleTimer = null;
            fireIdleRandom();
            scheduleNextIdle();
        }, delay);
    }

    function stopIdleTimer() {
        if (idleTimer !== null) {
            clearTimeout(idleTimer);
            idleTimer = null;
        }
    }

    function rescheduleIdle() {
        stopIdleTimer();
        scheduleNextIdle();
    }

    function configureIdleMotion(cfg: Partial<IdleMotionConfig>) {
        idleConfig = { ...idleConfig, ...cfg };
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

    // ══════════════════════════════════════════════════════════════════
    // ── Phase 4：装扮系统 ─────────────────────────────────────────────
    // ══════════════════════════════════════════════════════════════════

    /**
     * 读取当前模型所有参数的运行时元数据。
     * 装扮面板需要这些数据来渲染滑条范围。
     */
    function getCoreParameters(): CoreParameter[] {
        if (!live2dModel || !live2dReady.value) return [];
        try {
            const core = live2dModel.internalModel.coreModel;
            const model = core._model;
            const ids: string[] = model.parameters.ids;
            const mins: Float32Array = model.parameters.minimumValues;
            const maxs: Float32Array = model.parameters.maximumValues;
            const defs: Float32Array = model.parameters.defaultValues;
            const vals: Float32Array = model.parameters.values;

            const result: CoreParameter[] = [];
            for (let i = 0; i < ids.length; i++) {
                result.push({
                    id: ids[i],
                    min: mins[i],
                    max: maxs[i],
                    default: defs[i],
                    current: vals[i],
                });
            }
            return result;
        } catch (e) {
            console.warn("[Live2D] getCoreParameters 失败:", e);
            return [];
        }
    }

    /**
     * 读取当前模型所有 Part 的运行时 opacity。
     * 装扮面板需要这些数据来渲染开关状态。
     */
    function getCoreParts(): CorePart[] {
        if (!live2dModel || !live2dReady.value) return [];
        try {
            const core = live2dModel.internalModel.coreModel;
            const model = core._model;
            const ids: string[] = model.parts.ids;
            const opacities: Float32Array = model.parts.opacities;

            const result: CorePart[] = [];
            for (let i = 0; i < ids.length; i++) {
                result.push({
                    id: ids[i],
                    opacity: opacities[i],
                });
            }
            return result;
        } catch (e) {
            console.warn("[Live2D] getCoreParts 失败:", e);
            return [];
        }
    }

    /**
     * 应用装扮配置到当前模型。
     * 幂等：重复调用同一份配置无副作用。
     * 实时：装扮面板拖滑条时可每帧调用。
     */
    function applyAppearance(cfg: AppearanceConfig) {
        if (!live2dModel) return;

        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const core: any = live2dModel.internalModel?.coreModel;
        if (!core) return;

        let paramCount = 0;
        let partCount = 0;

        if (cfg.parameters) {
            for (const [id, value] of Object.entries(cfg.parameters)) {
                try {
                    core.setParameterValueById(id, value);
                    paramCount++;
                } catch { /* 参数 id 不存在，静默跳过 */ }
            }
        }

        if (cfg.parts) {
            for (const [id, value] of Object.entries(cfg.parts)) {
                try {
                    core.setPartOpacityById(id, value);
                    partCount++;
                } catch { /* Part id 不存在，静默跳过 */ }
            }
        }

        console.info(
            `[Live2D] applyAppearance: ${paramCount} 参数 + ${partCount} 部件已应用`
        );
    }

    /**
     * 内部：从后端拉取 appearance.json 并应用。
     * 在 loadModel / reloadLive2D 的模型就绪后、live2dReady 设 true 之前调用。
     */
    async function _loadAndApplyAppearance(modelPath: string) {
        const folder = _extractFolderName(modelPath);
        if (!folder) {
            console.warn("[Live2D] 无法从路径提取 folder，跳过装扮还原:", modelPath);
            return;
        }

        try {
            const res = await fetch(
                `${SIDECAR_URL}/api/live2d/appearance-schema?folder=${encodeURIComponent(folder)}`
            );
            if (!res.ok) {
                console.warn(`[Live2D] 装扮 schema 请求失败: ${res.status}`);
                return;
            }
            const data = await res.json();
            if (data.appearance) {
                applyAppearance(data.appearance);
                console.info(`[Live2D] 装扮已从 appearance.json 还原 (${folder})`);
            } else {
                console.info(`[Live2D] ${folder} 无已存装扮，使用默认`);
            }
        } catch (e) {
            console.warn("[Live2D] 装扮还原失败（sidecar 未就绪？）:", e);
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
    async function loadModel() {
        try {
            const modelPath = localStorage.getItem("rl-model-path") ?? "live2d/MO/MO.model3.json";
            live2dModel = await Live2DModel.from("/" + modelPath, { autoInteract: false });
            live2dContainer!.removeChildren();
            mountModel(live2dModel, modelPath, BASE_W.value);
            await setupFrameSwitchProtection(live2dModel, modelPath);

            // [Phase 4] 装扮还原：在 live2dReady = true 之前应用，
            // 避免用户看到"先默认样 → 再切装扮样"的闪烁
            await _loadAndApplyAppearance(modelPath);

            live2dReady.value = true;

            if (idleConfig.enabled) {
                rescheduleIdle();
                console.info("[Live2D] 模型加载完成，待机动画已启动");
            }
        } catch (e) {
            console.error("[Live2D] 模型加载失败:", e);
            live2dError.value = true;
        }
    }

    // ── 响应式尺寸更新 ────────────────────────────────────────────────
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

        loadModel();
    }

    function disposeLive2D() {
        if (emotionResetTimer) clearTimeout(emotionResetTimer);
        stopIdleTimer();
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

            // [Phase 4] 装扮还原
            await _loadAndApplyAppearance(newPath);

            live2dReady.value = true;
            console.info(`[Live2D] 模型切换成功 ✓  (${newPath})`);

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
        // [Phase 4] 动作调度
        playMotion,
        getMotionList,
        configureIdleMotion,
        // [Phase 4] 装扮系统
        getCoreParameters,
        getCoreParts,
        applyAppearance,
    };
}