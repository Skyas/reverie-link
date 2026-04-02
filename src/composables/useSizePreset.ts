/**
 * useSizePreset.ts — 窗口尺寸档位系统
 *
 * 跨模块共享的尺寸数据唯一来源（Single Source of Truth）。
 * App.vue 调用此 composable，再将 computed ref 注入给
 * useLive2D（canvas 尺寸）和 useWindowManager（resize 逻辑）。
 *
 * 修改尺寸档位只需改动本文件。
 */

import { ref, computed } from "vue";

export const SIZE_PRESETS = {
    small:  { baseW: 200, baseH: 270,  inputW: 210, bubbleH: 130 },
    medium: { baseW: 280, baseH: 380,  inputW: 240, bubbleH: 160 },
    large:  { baseW: 380, baseH: 510,  inputW: 300, bubbleH: 200 },
} as const;

export type SizePreset = keyof typeof SIZE_PRESETS;

export function useSizePreset() {
    const sizePreset = ref<SizePreset>(
        (localStorage.getItem("rl-size") as SizePreset) || "medium"
    );

    const sizeConfig  = computed(() => SIZE_PRESETS[sizePreset.value]);
    const BASE_W      = computed(() => sizeConfig.value.baseW);
    const BASE_H      = computed(() => sizeConfig.value.baseH);
    const INPUT_W     = computed(() => sizeConfig.value.inputW);
    const BUBBLE_H    = computed(() => sizeConfig.value.bubbleH);

    return { sizePreset, sizeConfig, BASE_W, BASE_H, INPUT_W, BUBBLE_H };
}