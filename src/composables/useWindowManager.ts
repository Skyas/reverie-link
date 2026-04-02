/**
 * useWindowManager.ts — 窗口几何管理 + UI 交互状态
 *
 * 职责：
 *   - 窗口初始位置恢复（右下角锚点）
 *   - 动态窗口缩放（输入框展开 / 气泡显示 / 思考状态）
 *   - 右下角锚点持久化（onMoved 监听）
 *   - 气泡打字机动画（showBubbleWithText）
 *   - 输入框开关
 *   - 控制栏悬停显隐
 *   - 锁定 / 解锁（调用 Tauri invoke）
 *   - 拖拽
 *
 * 依赖注入：
 *   isThinking — 来自 useWebSocket，用于 watch 触发 resizeToFit
 *   BASE_W / BASE_H / INPUT_W / BUBBLE_H — 来自 useSizePreset
 *
 * 不知道 Live2D、TTS、WebSocket 内部结构的存在。
 */

import { ref, nextTick, watch, type Ref, type ComputedRef } from "vue";
import {
    getCurrentWindow,
    PhysicalPosition,
    LogicalSize,
    primaryMonitor,
} from "@tauri-apps/api/window";
import { invoke } from "@tauri-apps/api/core";

interface WindowManagerDeps {
    isThinking: Ref<boolean>;
    BASE_W:     ComputedRef<number>;
    BASE_H:     ComputedRef<number>;
    INPUT_W:    ComputedRef<number>;
    BUBBLE_H:   ComputedRef<number>;
}

export function useWindowManager(deps: WindowManagerDeps) {
    const { isThinking, BASE_W, BASE_H, INPUT_W, BUBBLE_H } = deps;

    // ── UI 状态 ───────────────────────────────────────────────────────
    const inputOpen    = ref(false);
    const userInput    = ref("");
    const bubbleText   = ref("");
    const showBubble   = ref(false);
    const isLocked     = ref(false);
    const showControls = ref(false);
    const showUnlock   = ref(false);

    const inputRef = ref<HTMLTextAreaElement | null>(null);

    // ── 气泡 / 打字机动画 ─────────────────────────────────────────────
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

    // ── 输入框 ────────────────────────────────────────────────────────
    function toggleInput() {
        inputOpen.value = !inputOpen.value;
        if (inputOpen.value) nextTick(() => inputRef.value?.focus());
    }

    // ── 控制栏悬停 ────────────────────────────────────────────────────
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

    // ── 锁定 / 解锁 ──────────────────────────────────────────────────
    async function toggleLock() {
        const newState = await invoke<boolean>("toggle_lock");
        isLocked.value = newState;
        if (newState) {
            showControls.value = false;
            inputOpen.value    = false;
        }
    }

    async function unlockFromButton() {
        const newState = await invoke<boolean>("toggle_lock");
        isLocked.value   = newState;
        showUnlock.value = false;
    }

    // ── 拖拽 ─────────────────────────────────────────────────────────
    async function startDrag() {
        if (isLocked.value) return;
        await getCurrentWindow().startDragging();
    }

    // ── 动态窗口缩放 ──────────────────────────────────────────────────
    // 以右下角为锚点：先计算锚点坐标，再根据新尺寸计算新左上角位置。
    async function resizeToFit() {
        const win = getCurrentWindow();
        const pos = await win.outerPosition();
        const siz = await win.outerSize();
        const sf  = (await primaryMonitor())?.scaleFactor ?? 1;

        const anchorX = pos.x + siz.width;
        const anchorY = pos.y + siz.height;

        const newLogicW = BASE_W.value + (inputOpen.value ? INPUT_W.value : 0);
        const newLogicH = BASE_H.value + (showBubble.value || isThinking.value ? BUBBLE_H.value : 0);

        const newPhysW = Math.round(newLogicW * sf);
        const newPhysH = Math.round(newLogicH * sf);

        await win.setSize(new LogicalSize(newLogicW, newLogicH));
        await win.setPosition(new PhysicalPosition(anchorX - newPhysW, anchorY - newPhysH));
    }

    // isThinking 来自外部注入，不持有 WebSocket 的引用，仅消费 ref 值
    watch([inputOpen, showBubble, isThinking], resizeToFit);

    // ── 初始位置恢复 ──────────────────────────────────────────────────
    async function initWindowPosition() {
        const win = getCurrentWindow();
        const sf  = (await primaryMonitor())?.scaleFactor ?? 1;
        const w   = BASE_W.value;
        const h   = BASE_H.value;

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
                const physW  = Math.round(w * sf);
                const physH  = Math.round(h * sf);
                await win.setSize(new LogicalSize(w, h));
                await win.setPosition(new PhysicalPosition(
                    width  - physW - margin,
                    height - physH - margin,
                ));
            }
        }

        // 记录锚点（右下角），每次移动后持久化
        await win.onMoved(async () => {
            const p = await win.outerPosition();
            const s = await win.outerSize();
            localStorage.setItem("mascot-anchor", JSON.stringify({
                ax: p.x + s.width,
                ay: p.y + s.height,
            }));
        });
    }

    return {
        // 状态
        inputOpen,
        userInput,
        bubbleText,
        showBubble,
        isLocked,
        showControls,
        showUnlock,
        inputRef,
        // 方法
        showBubbleWithText,
        toggleInput,
        onMascotEnter,
        onMascotLeave,
        toggleLock,
        unlockFromButton,
        startDrag,
        resizeToFit,
        initWindowPosition,
    };
}