<script setup lang="ts">
import { computed } from "vue";
import { openUrl } from "@tauri-apps/plugin-opener";

// ── Props / Emits ──────────────────────────────────────────────
const props = defineProps<{ apiKeys: Record<string, string> }>();
const emit = defineEmits<{
    "update:apiKeys": [keys: Record<string, string>];
    "llm-saved": [cfg: object];
}>();

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

// ── LLM 配置（受控于父组件） ──────────────────────────────────
const llm = defineModel<{
    vendor: string;
    base_url: string;
    model: string;
    editable: boolean;
    needKey: boolean;
}>("llm", { required: true });

const currentKey = computed({
    get: () => props.apiKeys[llm.value.vendor] ?? "",
    set: (val) => {
        const updated = { ...props.apiKeys, [llm.value.vendor]: val };
        emit("update:apiKeys", updated);
    },
});

const currentVendorWebsite = computed(() =>
    VENDORS.find(v => v.name === llm.value.vendor)?.website ?? ""
);

function onVendorChange() {
    console.info(`[LLMConfigPanel] 切换LLM厂商 | vendor=${llm.value.vendor}`);
    const preset = VENDORS.find(v => v.name === llm.value.vendor);
    if (preset) {
        llm.value.base_url = preset.base_url;
        llm.value.model    = preset.model;
        llm.value.editable = preset.editable;
        llm.value.needKey  = preset.needKey;
    }
}

async function openWebsite() {
    console.debug(`[LLMConfigPanel] 打开厂商官网 | ${currentVendorWebsite.value}`);
    if (currentVendorWebsite.value) await openUrl(currentVendorWebsite.value);
}
</script>

<template>
    <div class="llm-config-section">
        <div class="field-group">
            <label class="field-label">厂商选择</label>
            <select class="field-select" :value="llm.vendor" @change="onVendorChange">
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
            <input class="field-input" v-model="currentKey" type="password" placeholder="sk-xxx...xxxx" />
            <p class="field-hint">密钥仅保存在本地，不会上传到任何服务器。</p>
        </div>

        <div class="field-group">
            <label class="field-label">模型名称</label>
            <input class="field-input" v-model="llm.model" placeholder="例如：deepseek-chat" />
        </div>
    </div>
</template>

<style scoped>
.llm-config-section {
    display: flex;
    flex-direction: column;
    gap: 10px;
}

.vendor-link {
    display: inline-block;
    font-size: 12px;
    color: var(--c-blue);
    text-decoration: none;
    padding: 4px 0;
    transition: color 0.2s;
}

.vendor-link:hover { text-decoration: underline; }
</style>
