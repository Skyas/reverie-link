<script setup lang="ts">
defineProps<{
    showControls: boolean;
    isLocked: boolean;
}>();

defineEmits<{
    toggleLock: [];
    openSettings: [];
    openHistory: [];
    toggleInput: [];
}>();
</script>

<template>
    <transition name="controls">
        <div v-if="showControls && !isLocked" class="controls-bar">
            <button class="ctrl-btn" @mousedown.stop @click.stop="$emit('toggleLock')" title="锁定">🔓</button>
            <button class="ctrl-btn" @mousedown.stop @click.stop="$emit('openSettings')" title="设置">⚙️</button>
            <button class="ctrl-btn" @mousedown.stop @click.stop="$emit('openHistory')" title="聊天记录">📋</button>
            <button class="ctrl-btn" @mousedown.stop @click.stop title="音量">🔊</button>
            <button class="ctrl-btn" @mousedown.stop @click.stop="$emit('toggleInput')" title="输入">💬</button>
        </div>
    </transition>
</template>

<style scoped>
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

/* 5个按钮逐一错开入场动画 */
.controls-enter-active .ctrl-btn:nth-child(1) { animation: slideIn 0.2s ease forwards; }
.controls-enter-active .ctrl-btn:nth-child(2) { animation: slideIn 0.2s 0.06s ease forwards; }
.controls-enter-active .ctrl-btn:nth-child(3) { animation: slideIn 0.2s 0.12s ease forwards; }
.controls-enter-active .ctrl-btn:nth-child(4) { animation: slideIn 0.2s 0.18s ease forwards; }
.controls-enter-active .ctrl-btn:nth-child(5) { animation: slideIn 0.2s 0.24s ease forwards; }

.controls-leave-active { transition: opacity 0.15s ease; }
.controls-enter-from,
.controls-leave-to    { opacity: 0; }

@keyframes slideIn {
    from { opacity: 0; transform: translateX(10px); }
    to   { opacity: 1; transform: translateX(0); }
}
</style>
