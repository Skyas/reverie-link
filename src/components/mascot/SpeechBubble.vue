<script setup lang="ts">
defineProps<{
    showBubble: boolean;
    isThinking: boolean;
    bubbleText: string;
}>();
</script>

<template>
    <transition name="bubble">
        <div v-if="showBubble || isThinking" class="speech-bubble">
            <span v-if="isThinking" class="thinking-dots">
                <span></span><span></span><span></span>
            </span>
            <span v-else class="bubble-text">{{ bubbleText }}</span>
            <div class="bubble-tail"></div>
        </div>
    </transition>
</template>

<style scoped>
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

.thinking-dots span:nth-child(2) { animation-delay: 0.2s; }
.thinking-dots span:nth-child(3) { animation-delay: 0.4s; }

@keyframes bounce {
    0%, 80%, 100% { transform: translateY(0); opacity: 0.4; }
    40%           { transform: translateY(-5px); opacity: 1; }
}

.bubble-enter-active { transition: opacity 0.25s ease, transform 0.22s ease; }
.bubble-leave-active { transition: opacity 0.2s ease, transform 0.18s ease; }
.bubble-enter-from  { opacity: 0; transform: translateY(8px); }
.bubble-leave-to    { opacity: 0; transform: translateY(-4px); }
</style>
