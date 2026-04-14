<script setup lang="ts">
defineProps<{
    isLocked: boolean;
    showUnlock: boolean;
}>();

defineEmits<{ unlockFromButton: [] }>();
</script>

<template>
    <transition name="unlock">
        <button v-if="isLocked && showUnlock"
                class="unlock-btn"
                @mousedown.stop
                @click.stop="$emit('unlockFromButton')">
            🔒
        </button>
    </transition>
</template>

<style scoped>
.unlock-btn {
    position: absolute;
    left: 6px;
    top: 50%;
    transform: translateY(-50%);
    width: 30px;
    height: 30px;
    border: 1.5px solid rgba(255, 255, 255, 0.6);
    border-radius: 50%;
    background: rgba(0, 0, 0, 0.45);
    backdrop-filter: blur(8px);
    cursor: pointer;
    font-size: 15px;
    display: flex;
    align-items: center;
    justify-content: center;
    pointer-events: all;
    z-index: 30;
}

.unlock-enter-active { transition: opacity 0.3s ease, transform 0.3s ease; }
.unlock-leave-active { transition: opacity 0.2s ease; }
.unlock-enter-from   { opacity: 0; transform: translate(-50%, -40%); }
.unlock-leave-to     { opacity: 0; }
</style>
