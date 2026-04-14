<script setup lang="ts">
import { ref, reactive, onMounted } from "vue";

import LLMConfigPanel from "./llm/LLMConfigPanel.vue";
import LLMSamplingPanel from "./llm/LLMSamplingPanel.vue";
import TTSConfigPanel from "./llm/TTSConfigPanel.vue";

// ── Toast ──────────────────────────────────────────────────────────
const msgText = ref("");
const msgType = ref<"ok" | "warn">("ok");
function showMsg(text: string, type: "ok" | "warn" = "ok") {
    msgText.value = text; msgType.value = type;
    setTimeout(() => { msgText.value = ""; }, 2500);
}

// ── LLM 配置 ───────────────────────────────────────────────────────
const apiKeys = reactive<Record<string, string>>({});

const llm = reactive({
    vendor:   "DeepSeek",
    base_url: "https://api.deepseek.com",
    model:    "deepseek-chat",
    editable: false,
    needKey:  true,
    temperature: 0.8,
    top_p: 0.9,
    frequency_penalty: 0.5
});

// ── 语音配置 ──────────────────────────────────────────────────────
const tts = reactive({
    engine:         "elevenlabs" as "elevenlabs" | "rvc",
    enabled:        false,
    el_api_key:     "",
    el_voice_id:    "",
    rvc_pth:        "",
    rvc_index:      "",
    rvc_edge_voice: "zh-CN-XiaoxiaoNeural",
});

// ── 保存 ──────────────────────────────────────────────────────────
const emit = defineEmits<{ "llm-saved": [cfg: object] }>();

async function saveLLM() {
    localStorage.setItem("rl-api-keys", JSON.stringify(apiKeys));
    const cfg = {
        vendor:   llm.vendor,
        base_url: llm.base_url,
        model:    llm.model,
        api_key:  apiKeys[llm.vendor] ?? "",
        temperature: llm.temperature,
        top_p: llm.top_p,
        frequency_penalty: llm.frequency_penalty
    };
    localStorage.setItem("rl-llm", JSON.stringify(cfg));
    emit("llm-saved", cfg);
    console.info("[LLMTab] LLM 配置已保存 | vendor=%s model=%s", llm.vendor, llm.model);
    showMsg("✓ LLM 配置已保存");
}

function saveTTS() {
    localStorage.setItem("rl-tts", JSON.stringify({
        engine:         tts.engine,
        enabled:        tts.enabled,
        el_api_key:     tts.el_api_key.trim(),
        el_voice_id:    tts.el_voice_id.trim(),
        rvc_pth:        tts.rvc_pth.trim(),
        rvc_index:      tts.rvc_index.trim(),
        rvc_edge_voice: tts.rvc_edge_voice.trim(),
    }));
    console.info("[LLMTab] TTS 配置已保存 | engine=%s enabled=%s", tts.engine, tts.enabled);
    showMsg("✓ 语音配置已保存");
}

// ── 初始化 ───────────────────────────────────────────────────────
onMounted(() => {
    console.info("[LLMTab] onMounted 开始");
    const savedKeys = localStorage.getItem("rl-api-keys");
    if (savedKeys) Object.assign(apiKeys, JSON.parse(savedKeys));

    const savedLLM = localStorage.getItem("rl-llm");
    if (savedLLM) {
        const d = JSON.parse(savedLLM);
        llm.vendor   = d.vendor   ?? "DeepSeek";
        llm.base_url = d.base_url ?? llm.base_url;
        llm.model    = d.model    ?? llm.model;
        llm.temperature = d.temperature ?? 0.8;
        llm.top_p = d.top_p ?? 0.9;
        llm.frequency_penalty = d.frequency_penalty ?? 0.5;
        const VENDORS = [
            { name: "DeepSeek",       editable: false, needKey: true  },
            { name: "OpenAI",         editable: false, needKey: true  },
            { name: "千问（阿里云）",   editable: false, needKey: true  },
            { name: "豆包（火山引擎）", editable: false, needKey: true  },
            { name: "硅基流动",        editable: false, needKey: true  },
            { name: "Gemini（Google）",editable: false, needKey: true  },
            { name: "OpenRouter",     editable: false, needKey: true  },
            { name: "MiniMax",        editable: false, needKey: true  },
            { name: "月之暗面（Kimi）", editable: false, needKey: true  },
            { name: "智谱AI",          editable: false, needKey: true  },
            { name: "腾讯混元",        editable: false, needKey: true  },
            { name: "百川AI",          editable: false, needKey: true  },
            { name: "启航AI",          editable: false, needKey: true  },
            { name: "Ollama（本地）",  editable: true,  needKey: false },
            { name: "自定义",          editable: true,  needKey: true  },
        ];
        const preset = VENDORS.find((v: any) => v.name === llm.vendor);
        llm.editable = preset?.editable ?? true;
        llm.needKey  = preset?.needKey  ?? true;
        if (d.api_key) apiKeys[llm.vendor] = d.api_key;
    }

    const savedTTS = localStorage.getItem("rl-tts");
    if (savedTTS) {
        const d = JSON.parse(savedTTS);
        tts.engine         = d.engine         ?? "elevenlabs";
        tts.enabled        = d.enabled        ?? false;
        tts.el_api_key     = d.el_api_key     ?? d.api_key   ?? "";
        tts.el_voice_id    = d.el_voice_id    ?? d.voice_id  ?? "";
        tts.rvc_pth        = d.rvc_pth        ?? "";
        tts.rvc_index      = d.rvc_index      ?? "";
        tts.rvc_edge_voice = d.rvc_edge_voice ?? "zh-CN-XiaoxiaoNeural";
    }
    console.info("[LLMTab] onMounted 完成");
});
</script>

<template>
    <div class="tab-content">
        <!-- Toast -->
        <transition name="toast">
            <div v-if="msgText" class="toast" :class="{ warn: msgType === 'warn' }">{{ msgText }}</div>
        </transition>

        <!-- LLM 基础配置 -->
        <LLMConfigPanel
            :api-keys="apiKeys"
            v-model:llm="llm"
        />

        <!-- LLM 采样参数 -->
        <LLMSamplingPanel v-model:llm="llm" />

        <div class="action-row">
            <button class="save-btn" @click="saveLLM">保存配置</button>
        </div>

        <!-- 分割线 + 标题 -->
        <div class="divider"></div>
        <div class="global-section-title" style="margin-bottom:8px;">🔊 语音合成</div>

        <!-- TTS 配置 -->
        <TTSConfigPanel v-model:tts="tts" />

        <div class="action-row">
            <button class="save-btn" @click="saveTTS">保存语音配置</button>
        </div>
    </div>
</template>

<style scoped>
/* 复用的 toast 样式（与 LLMTab 原始样式保持一致） */
.toast {
    position: fixed; top: 16px; left: 50%; transform: translateX(-50%);
    padding: 8px 20px; border-radius: 20px;
    background: linear-gradient(white, white) padding-box,
                linear-gradient(135deg, #A8D8EA, #FFB7C5) border-box;
    border: 2px solid transparent;
    color: #4A4A6A;
    font-size: 13px; font-weight: 600;
    box-shadow: 0 4px 20px rgba(80, 60, 120, 0.22);
    z-index: 200; pointer-events: none; white-space: nowrap;
}
.toast.warn {
    background: linear-gradient(white, white) padding-box,
                linear-gradient(135deg, #F0A0A0, #E08080) border-box;
    color: #C05050;
}
.toast-enter-active { transition: opacity 0.25s ease, transform 0.25s ease; }
.toast-leave-active { transition: opacity 0.2s ease; }
.toast-enter-from { opacity: 0; transform: translateX(-50%) translateY(-10px); }
.toast-leave-to   { opacity: 0; }
</style>
