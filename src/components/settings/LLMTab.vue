<script setup lang="ts">
import { ref, reactive, computed, onMounted } from "vue";
import { openUrl } from "@tauri-apps/plugin-opener";

// ── 厂商预设 ──────────────────────────────────────────────────
const VENDORS = [
    { name: "DeepSeek",       base_url: "https://api.deepseek.com",                               model: "deepseek-chat",              website: "https://platform.deepseek.com",             editable: false, needKey: true  },
    { name: "OpenAI",         base_url: "https://api.openai.com/v1",                              model: "gpt-4o-mini",                 website: "https://platform.openai.com",               editable: false, needKey: true  },
    { name: "千问（阿里云）",   base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1",     model: "qwen-max",                   website: "https://bailian.console.aliyun.com",        editable: false, needKey: true  },
    { name: "豆包（火山引擎）", base_url: "https://ark.cn-beijing.volces.com/api/v3",              model: "doubao-pro-32k",              website: "https://console.volcengine.com/ark",        editable: false, needKey: true  },
    { name: "硅基流动",        base_url: "https://api.siliconflow.cn/v1",                         model: "deepseek-ai/DeepSeek-V3",     website: "https://cloud.siliconflow.cn",              editable: false, needKey: true  },
    { name: "Gemini（Google）",base_url: "https://generativelanguage.googleapis.com/v1beta/openai/", model: "gemini-2.0-flash",          website: "https://aistudio.google.com",               editable: false, needKey: true  },
    { name: "OpenRouter",     base_url: "https://openrouter.ai/api/v1",                           model: "openai/gpt-4o-mini",          website: "https://openrouter.ai",                     editable: false, needKey: true  },
    { name: "MiniMax",        base_url: "https://api.minimaxi.com/v1",                            model: "MiniMax-M2",                  website: "https://platform.minimaxi.com",             editable: false, needKey: true  },
    { name: "月之暗面（Kimi）", base_url: "https://api.moonshot.cn/v1",                           model: "moonshot-v1-8k",              website: "https://platform.moonshot.cn",              editable: false, needKey: true  },
    { name: "智谱AI",          base_url: "https://open.bigmodel.cn/api/paas/v4/",                 model: "glm-4-flash",                 website: "https://open.bigmodel.cn",                  editable: false, needKey: true  },
    { name: "腾讯混元",        base_url: "https://api.hunyuan.cloud.tencent.com/v1",              model: "hunyuan-turbo",               website: "https://cloud.tencent.com/product/hunyuan", editable: false, needKey: true  },
    { name: "百川AI",          base_url: "https://api.baichuan-ai.com/v1",                        model: "Baichuan4",                   website: "https://platform.baichuan-ai.com",          editable: false, needKey: true  },
    { name: "启航AI",          base_url: "https://api.qhaigc.net/v1",                             model: "gpt-4o",                      website: "https://www.qhaigc.net",                    editable: false, needKey: true  },
    { name: "Ollama（本地）",   base_url: "http://localhost:11434/v1",                             model: "llama3",                      website: "https://ollama.com",                        editable: true,  needKey: false },
    { name: "自定义",          base_url: "",                                                       model: "",                            website: "",                                          editable: true,  needKey: true  },
];

// ── Toast ──────────────────────────────────────────────────────
const msgText = ref("");
const msgType = ref<"ok" | "warn">("ok");
function showMsg(text: string, type: "ok" | "warn" = "ok") {
    msgText.value = text; msgType.value = type;
    setTimeout(() => { msgText.value = ""; }, 2500);
}

// ── LLM 配置 ───────────────────────────────────────────────────
const apiKeys = reactive<Record<string, string>>({});

const llm = reactive({
    vendor:   "DeepSeek",
    base_url: "https://api.deepseek.com",
    model:    "deepseek-chat",
    editable: false,
    needKey:  true,
    // 【新增】LLM 采样参数
    temperature: 0.8,
    top_p: 0.9,
    frequency_penalty: 0.5
});

const currentKey = computed({
    get: () => apiKeys[llm.vendor] ?? "",
    set: (val) => { apiKeys[llm.vendor] = val; },
});

const currentVendorWebsite = computed(() =>
    VENDORS.find(v => v.name === llm.vendor)?.website ?? ""
);

function onVendorChange() {
    const preset = VENDORS.find(v => v.name === llm.vendor);
    if (preset) {
        llm.base_url = preset.base_url;
        llm.model    = preset.model;
        llm.editable = preset.editable;
        llm.needKey  = preset.needKey;
    }
}

async function openWebsite() {
    if (currentVendorWebsite.value) await openUrl(currentVendorWebsite.value);
}

const emit = defineEmits<{
    "llm-saved": [cfg: object];
}>();

async function saveLLM() {
    localStorage.setItem("rl-api-keys", JSON.stringify(apiKeys));
    const cfg = {
        vendor:   llm.vendor,
        base_url: llm.base_url,
        model:    llm.model,
        api_key:  apiKeys[llm.vendor] ?? "",
        // 【新增】保存采样参数
        temperature: llm.temperature,
        top_p: llm.top_p,
        frequency_penalty: llm.frequency_penalty
    };
    localStorage.setItem("rl-llm", JSON.stringify(cfg));
    emit("llm-saved", cfg);
    showMsg("✓ LLM 配置已保存");
}

// ── 初始化 ─────────────────────────────────────────────────────
// 【2026-04-15】语音合成模块已迁移至独立的 TTSTab.vue，不再在此处配置
onMounted(() => {
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
        const preset = VENDORS.find(v => v.name === llm.vendor);
        llm.editable = preset?.editable ?? true;
        llm.needKey  = preset?.needKey  ?? true;
        if (d.api_key) apiKeys[llm.vendor] = d.api_key;
    }
});
</script>

<template>
    <div class="tab-content">

        <!-- Toast -->
        <transition name="toast">
            <div v-if="msgText" class="toast" :class="{ warn: msgType === 'warn' }">{{ msgText }}</div>
        </transition>

        <!-- LLM 配置 -->
        <div class="field-group">
            <label class="field-label">厂商选择</label>
            <select class="field-select" v-model="llm.vendor" @change="onVendorChange">
                <option v-for="v in VENDORS" :key="v.name" :value="v.name">{{ v.name }}</option>
            </select>
        </div>
        <div class="field-group" v-if="currentVendorWebsite">
            <a class="vendor-link" href="#" @click.prevent="openWebsite">
                🔗 前往 {{ llm.vendor }} 官网获取 API Key
            </a>
        </div>
        <div class="field-group">
            <label class="field-label">API 地址 <span class="field-note">base_url</span></label>
            <input class="field-input" v-model="llm.base_url"
                   :disabled="!llm.editable" :class="{ 'field-readonly': !llm.editable }"
                   placeholder="https://api.example.com/v1" />
        </div>
        <div class="field-group" v-if="llm.needKey">
            <label class="field-label">API Key</label>
            <input class="field-input" v-model="currentKey" type="password" placeholder="sk-xxxxxxxxxxxxxxxx" />
            <p class="field-hint">密钥仅保存在本地，不会上传到任何服务器。</p>
        </div>
        <div class="field-group">
            <label class="field-label">模型名称</label>
            <input class="field-input" v-model="llm.model" placeholder="例如：deepseek-chat" />
        </div>

        <div class="divider"></div>
        <div class="global-section-title" style="margin-bottom:8px;">🧠 核心性格微调</div>

        <div class="field-group">
            <label class="field-label">🎨 脑洞大小 (Temperature): {{ llm.temperature.toFixed(2) }}</label>
            <input type="range" min="0" max="2" step="0.05" v-model.number="llm.temperature" class="field-slider" />
            <div class="field-hint" style="display: flex; justify-content: space-between; margin-top: 4px;">
                <span>👈 小</span>
                <span style="color: var(--c-text-soft);">日常推荐 0.85</span>
                <span>大 👉</span>
            </div>
        </div>

        <div class="field-group">
            <label class="field-label">📖 词汇量 (Top P): {{ llm.top_p.toFixed(2) }}</label>
            <input type="range" min="0" max="1" step="0.05" v-model.number="llm.top_p" class="field-slider" />
            <div class="field-hint" style="display: flex; justify-content: space-between; margin-top: 4px;">
                <span>👈 少</span>
                <span style="color: var(--c-text-soft);">日常推荐 0.90</span>
                <span>多 👉</span>
            </div>
        </div>

        <div class="field-group">
            <label class="field-label">🔀 复读机程度 (Freq Penalty): {{ llm.frequency_penalty.toFixed(2) }}</label>
            <input type="range" min="0" max="1" step="0.05" v-model.number="llm.frequency_penalty" class="field-slider" />
            <div class="field-hint" style="display: flex; justify-content: space-between; margin-top: 4px;">
                <span>👈 人类本质</span>
                <span style="color: var(--c-text-soft);">日常推荐 0.50</span>
                <span>不准复读 👉</span>
            </div>
        </div>

        <div class="action-row">
            <button class="save-btn" @click="saveLLM">保存配置</button>
        </div>
    </div>
</template>

<style scoped>
.vendor-link {
    display: inline-block;
    font-size: 12px;
    color: var(--c-blue);
    text-decoration: none;
    padding: 4px 0;
    transition: color 0.2s;
}
.vendor-link:hover { text-decoration: underline; }

/* toast（复用全局样式） */
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

.field-slider {
    width: 100%;
    margin-top: 4px;
    cursor: pointer;
    accent-color: var(--c-blue);
}
</style>