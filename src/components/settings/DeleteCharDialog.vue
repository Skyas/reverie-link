<script setup lang="ts">
defineProps<{
    visible:    boolean;
    targetName: string;
    loading:    boolean;
}>();

defineEmits<{
    "confirm-export": [];
    "confirm-direct": [];
    "cancel":         [];
}>();
</script>

<template>
    <transition name="dialog">
        <div v-if="visible" class="dialog-overlay" @click.self="$emit('cancel')">
            <div class="dialog-box">
                <div class="dialog-title">删除「{{ targetName }}」</div>
                <div class="dialog-body">
                    <p style="font-size:13px;color:var(--c-text);line-height:1.6;">
                        删除角色卡将同时删除与她相关的所有
                        <strong>聊天记录</strong>和<strong>记忆数据</strong>，此操作不可恢复。
                    </p>
                    <p style="font-size:12px;color:var(--c-text-soft);margin-top:6px;">
                        如需保留数据，请先选择「导出后删除」。
                    </p>
                </div>
                <div class="dialog-actions" style="flex-direction:column;gap:8px;">
                    <button class="dialog-confirm"
                            style="width:100%;background:linear-gradient(135deg,#7ec8e3,#b0d4f1);"
                            :disabled="loading"
                            @click="$emit('confirm-export')">
                        {{ loading ? "处理中…" : "📥 导出后删除" }}
                    </button>
                    <button class="dialog-confirm"
                            style="width:100%;background:linear-gradient(135deg,#f28b82,#e06666);"
                            :disabled="loading"
                            @click="$emit('confirm-direct')">
                        {{ loading ? "处理中…" : "🗑️ 直接删除" }}
                    </button>
                    <button class="dialog-cancel"
                            style="width:100%;text-align:center;"
                            :disabled="loading"
                            @click="$emit('cancel')">
                        取消
                    </button>
                </div>
            </div>
        </div>
    </transition>
</template>