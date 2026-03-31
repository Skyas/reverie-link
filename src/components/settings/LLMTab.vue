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
    };
    localStorage.setItem("rl-llm", JSON.stringify(cfg));
    emit("llm-saved", cfg);
    showMsg("✓ LLM 配置已保存");
}

// ── 语音配置 ───────────────────────────────────────────────────
const TTS_CONFIG_KEY = "rl-tts";

interface RVCVoice { name: string; pth: string; index: string; index_missing: boolean; }

const tts = reactive({
    engine:         "elevenlabs" as "elevenlabs" | "rvc",
    enabled:        false,
    el_api_key:     "",
    el_voice_id:    "",
    rvc_pth:        "",
    rvc_index:      "",
    rvc_edge_voice: "zh-CN-XiaoxiaoNeural",
});

const rvcVoices  = ref<RVCVoice[]>([]);
const rvcLoading = ref(false);

async function fetchRVCVoices() {
    rvcLoading.value = true;
    try {
        const res = await fetch("http://localhost:18000/api/rvc/voices");
        const data = await res.json();
        rvcVoices.value = data.voices ?? [];
    } catch {
        rvcVoices.value = [];
        showMsg("无法扫描音色，请确认后端已启动", "warn");
    } finally {
        rvcLoading.value = false;
    }
}

function selectRVCVoice(voice: RVCVoice) {
    tts.rvc_pth   = voice.pth;
    tts.rvc_index = voice.index;
}

function saveTTS() {
    localStorage.setItem(TTS_CONFIG_KEY, JSON.stringify({
        engine:         tts.engine,
        enabled:        tts.enabled,
        el_api_key:     tts.el_api_key.trim(),
        el_voice_id:    tts.el_voice_id.trim(),
        rvc_pth:        tts.rvc_pth.trim(),
        rvc_index:      tts.rvc_index.trim(),
        rvc_edge_voice: tts.rvc_edge_voice.trim(),
    }));
    showMsg("✓ 语音配置已保存");
}

// ── 初始化 ─────────────────────────────────────────────────────
onMounted(() => {
    const savedKeys = localStorage.getItem("rl-api-keys");
    if (savedKeys) Object.assign(apiKeys, JSON.parse(savedKeys));

    const savedLLM = localStorage.getItem("rl-llm");
    if (savedLLM) {
        const d = JSON.parse(savedLLM);
        llm.vendor   = d.vendor   ?? "DeepSeek";
        llm.base_url = d.base_url ?? llm.base_url;
        llm.model    = d.model    ?? llm.model;
        const preset = VENDORS.find(v => v.name === llm.vendor);
        llm.editable = preset?.editable ?? true;
        llm.needKey  = preset?.needKey  ?? true;
        if (d.api_key) apiKeys[llm.vendor] = d.api_key;
    }

    const savedTTS = localStorage.getItem(TTS_CONFIG_KEY);
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
        <div class="action-row">
            <button class="save-btn" @click="saveLLM">保存配置</button>
        </div>

        <!-- 语音合成 -->
        <div class="divider"></div>
        <div class="global-section-title" style="margin-bottom:8px;">🔊 语音合成</div>

        <div class="field-group">
            <label class="toggle-row" style="cursor:pointer; margin-bottom:8px;">
                <span class="field-label">启用语音合成</span>
                <input type="checkbox" v-model="tts.enabled"
                       style="width:16px;height:16px;accent-color:var(--c-blue);" />
            </label>
            <div class="engine-selector">
                <div class="engine-card" :class="{ active: tts.engine === 'elevenlabs' }"
                     @click="tts.engine = 'elevenlabs'">
                    <div class="engine-name">☁️ ElevenLabs</div>
                    <div class="engine-desc">云端高质量，每月 1 万字符免费</div>
                </div>
                <div class="engine-card" :class="{ active: tts.engine === 'rvc' }"
                     @click="tts.engine = 'rvc'; fetchRVCVoices()">
                    <div class="engine-name">🖥️ 本地 RVC</div>
                    <div class="engine-desc">完全免费，使用自训练音色</div>
                </div>
            </div>
        </div>

        <!-- ElevenLabs 配置 -->
        <div v-if="tts.engine === 'elevenlabs'" class="engine-config-section">
            <div class="field-group">
                <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;">
                    <span class="field-label">ElevenLabs 配置</span>
                    <a class="vendor-link" href="#" @click.prevent="openUrl('https://elevenlabs.io')">🔗 前往官网</a>
                </div>
            </div>
            <div class="field-group">
                <label class="field-label">API Key</label>
                <input class="field-input" v-model="tts.el_api_key" type="password"
                       placeholder="sk_xxxxxxxxxxxxxxxxxxxxxxxx" />
                <p class="field-hint">密钥仅保存在本地，不会上传到任何服务器。</p>
            </div>
            <div class="field-group">
                <label class="field-label">Voice ID</label>
                <input class="field-input" v-model="tts.el_voice_id"
                       placeholder="在 ElevenLabs → Voices 里找到对应 ID" />
                <p class="field-hint">每个音色都有唯一 ID，如 <code>21m00Tcm4TlvDq8ikWAM</code></p>
            </div>
        </div>

        <!-- 本地 RVC 配置 -->
        <div v-if="tts.engine === 'rvc'" class="engine-config-section">
            <div class="field-group">
                <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:6px;">
                    <span class="field-label">RVC 音色</span>
                    <span class="field-note">将 .pth 和 .index 放入 public/rvc/</span>
                </div>
                <div v-if="rvcLoading" class="models-loading">扫描中…</div>
                <div v-else-if="rvcVoices.length === 0" class="models-empty">
                    <p class="field-note">未找到音色文件</p>
                    <button class="refresh-btn" @click="fetchRVCVoices">重新扫描</button>
                </div>
                <div v-else class="rvc-voices-list">
                    <p class="field-hint" style="margin-bottom:4px;">
                        命名规范：<code>.pth</code> 与 <code>.index</code> 必须同名，例如 <code>Hibiki.pth</code> + <code>Hibiki.index</code>
                    </p>
                    <div v-for="v in rvcVoices" :key="v.pth"
                         class="rvc-voice-card"
                         :class="{ active: tts.rvc_pth === v.pth, 'index-warn': v.index_missing }"
                         @click="selectRVCVoice(v)">
                        <div class="rvc-voice-name">🎤 {{ v.name }}</div>
                        <div class="rvc-voice-meta">
                            <span v-if="v.index_missing" class="rvc-warn">⚠️ 缺少同名 .index 文件</span>
                            <span v-else>✓ Index 文件匹配</span>
                        </div>
                    </div>
                    <button class="refresh-btn" @click="fetchRVCVoices">🔄 重新扫描</button>
                </div>
            </div>
            <div class="field-group">
                <label class="field-label">底层 TTS 语音 <span class="field-note">Edge-TTS 原声</span></label>
                <select class="field-select" v-model="tts.rvc_edge_voice">
                    <option value="zh-CN-XiaoxiaoNeural">晓晓（温柔女声）</option>
                    <option value="zh-CN-XiaohanNeural">晓涵（活泼少女）</option>
                    <option value="zh-CN-XiaoyiNeural">晓伊（可爱元气）</option>
                    <option value="zh-CN-YunxiNeural">云希（男声）</option>
                </select>
                <p class="field-hint">底层原声音调会影响变声效果，建议选择与模型训练音色性别一致的声音。</p>
            </div>
        </div>

        <div class="action-row">
            <button class="save-btn" @click="saveTTS">保存语音配置</button>
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

.engine-selector { display: flex; gap: 8px; }
.engine-card {
    flex: 1; padding: 10px;
    border: 1.5px solid var(--c-border); border-radius: 12px;
    cursor: pointer; background: var(--c-surface);
    transition: border-color 0.2s, box-shadow 0.2s;
}
.engine-card:hover { border-color: var(--c-pink-mid); }
.engine-card.active {
    border-color: var(--c-blue);
    box-shadow: 0 0 0 3px var(--c-blue-light);
    background: linear-gradient(135deg, rgba(197,232,244,0.15), rgba(255,183,197,0.1));
}
.engine-name { font-size: 13px; font-weight: 600; color: var(--c-text); }
.engine-desc { font-size: 11px; color: var(--c-text-soft); margin-top: 2px; }

.engine-config-section {
    display: flex; flex-direction: column; gap: 10px;
    padding: 10px 12px;
    background: var(--c-surface);
    border: 1.5px solid var(--c-border); border-radius: 12px;
}

.models-loading { color: var(--c-text-soft); font-size: 13px; padding: 8px 0; }
.models-empty { display: flex; flex-direction: column; gap: 6px; padding: 8px 0; }
.models-empty p { font-size: 13px; color: var(--c-text-soft); }

.rvc-voices-list { display: flex; flex-direction: column; gap: 6px; }
.rvc-voice-card {
    display: flex; align-items: center; justify-content: space-between;
    padding: 8px 12px;
    border: 1.5px solid var(--c-border); border-radius: 10px;
    cursor: pointer; background: var(--c-surface);
    transition: border-color 0.2s, box-shadow 0.2s;
}
.rvc-voice-card:hover { border-color: var(--c-pink-mid); }
.rvc-voice-card.active { border-color: var(--c-blue); box-shadow: 0 0 0 3px var(--c-blue-light); }
.rvc-voice-card.index-warn { border-color: #F0C060; }
.rvc-voice-card.index-warn.active { border-color: #E0A000; box-shadow: 0 0 0 3px rgba(240,192,0,0.2); }
.rvc-voice-name { font-size: 13px; font-weight: 600; color: var(--c-text); }
.rvc-voice-meta { font-size: 11px; color: var(--c-text-soft); }
.rvc-warn { color: #C08000; font-weight: 500; }

/* toast（复用全局样式） */
.toast {
    position: fixed; top: 16px; left: 50%; transform: translateX(-50%);
    padding: 8px 20px; border-radius: 20px;
    background: linear-gradient(135deg, var(--c-blue-mid), var(--c-pink));
    color: white; font-size: 13px; font-weight: 500;
    box-shadow: 0 4px 16px rgba(126,87,194,0.2);
    z-index: 200; pointer-events: none; white-space: nowrap;
}
.toast.warn { background: linear-gradient(135deg, #F0A0A0, #E08080); }
.toast-enter-active { transition: opacity 0.25s ease, transform 0.25s ease; }
.toast-leave-active { transition: opacity 0.2s ease; }
.toast-enter-from { opacity: 0; transform: translateX(-50%) translateY(-10px); }
.toast-leave-to   { opacity: 0; }
</style>