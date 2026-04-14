<script setup lang="ts">
import { ref } from "vue";
import ControlsBar from "./ControlsBar.vue";
import UnlockButton from "./UnlockButton.vue";

defineProps<{
    live2dReady: boolean;
    isLocked: boolean;
    showControls: boolean;
    showUnlock: boolean;
    isConnected: boolean;
}>();

const emit = defineEmits<{
    startDrag: [];
    onMascotEnter: [];
    onMascotLeave: [];
    toggleLock: [];
    openSettings: [];
    openHistory: [];
    toggleInput: [];
    unlockFromButton: [];
}>();

const canvasRef = ref<HTMLCanvasElement | null>(null);
defineExpose({ canvasRef });
</script>

<template>
    <div class="mascot-area"
         :class="{ locked: isLocked }"
         @mousedown="emit('startDrag')"
         @mouseenter="emit('onMascotEnter')"
         @mouseleave="emit('onMascotLeave')">

        <!-- Live2D 画布 -->
        <canvas ref="canvasRef" class="live2d-canvas" />

        <!-- Live2D 未就绪时显示占位剪影 -->
        <div v-if="!live2dReady" class="mascot-silhouette">
            <div class="sil-head"></div>
            <div class="sil-body"></div>
        </div>

        <!-- 控制栏 -->
        <ControlsBar
            :show-controls="showControls"
            :is-locked="isLocked"
            @toggle-lock="emit('toggleLock')"
            @open-settings="emit('openSettings')"
            @open-history="emit('openHistory')"
            @toggle-input="emit('toggleInput')"
        />

        <!-- 锁定状态解锁按钮 -->
        <UnlockButton
            :is-locked="isLocked"
            :show-unlock="showUnlock"
            @unlock-from-button="emit('unlockFromButton')"
        />

        <!-- 连接状态指示点 -->
        <div class="status-dot" :class="{ connected: isConnected }"></div>
    </div>
</template>

<style scoped>
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

.mascot-area:active { cursor: grabbing; }
.mascot-area.locked { cursor: default; }
.mascot-area.locked:active { cursor: default; }

.live2d-canvas {
    position: absolute;
    top: 0;
    left: 0;
    pointer-events: none;
    z-index: 1;
    will-change: transform;
}

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

.status-dot.connected { background: #81c784; }
</style>
