<script setup lang="ts">
/**
 * TTSTab.vue — 语音合成设置（粉蓝主题，复用全局共享样式）
 *
 * 修复与增强：
 *   [FIX-③]  音色选择改为「下拉快选 + 自定义输入」共存
 *   [FIX-③b] voice_id 按供应商独立存储，切换厂商再切回时恢复
 *   [FIX-④]  MiniMax / 阿里云 内置音色列表前端化
 *   [FIX-⑤]  高级选项中新增 HTTP 代理配置（带开关 + 地址输入）
 *   [FIX-②]  openUrl fallback：plugin-opener 失败时退回 window.open()
 *   [FEAT-①] 模型选择：下拉预设 + 自定义输入，按供应商独立存储
 *            阿里云：音色按模型分组（不同模型支持的音色不同）
 */
import { ref, reactive, computed, onMounted, watch } from "vue";

// ── openUrl 兼容封装 ───────────────────────────────────────────
async function safeOpenUrl(url: string) {
    try {
        const { openUrl } = await import("@tauri-apps/plugin-opener");
        await openUrl(url);
    } catch (e) {
        console.warn("[TTSTab] plugin-opener 失败，fallback window.open:", e);
        window.open(url, "_blank");
    }
}

// ── 供应商预设 ─────────────────────────────────────────────────
const PROVIDERS = [
    {
        id: "minimax",
        name: "MiniMax Speech",
        badge: "国内推荐",
        desc: "国内首选，全球 TTS 评测领先，延迟 <250ms，情感控制完整。",
        website: "https://platform.minimaxi.com",
        needGroupId: true,
        domestic: true,
    },
    {
        id: "aliyun_cosyvoice",
        name: "阿里云 CosyVoice",
        badge: "国内可用",
        desc: "中文音质优秀，情感通过自然语言指令控制，首包延迟约 400ms。",
        website: "https://bailian.console.aliyun.com/",
        needGroupId: false,
        domestic: true,
    },
    {
        id: "elevenlabs",
        name: "ElevenLabs",
        badge: "国际推荐",
        desc: "情感表现顶尖，英文场景最优，国内访问需要代理。",
        website: "https://elevenlabs.io",
        needGroupId: false,
        domestic: false,
    },
];

// ── [FEAT-①] 模型预设（推荐模型带 ⭐） ──────────────────────────
interface ModelOption {
    id: string;
    label: string;
    recommended?: boolean;
    note?: string;
}

const MODEL_PRESETS: Record<string, ModelOption[]> = {
    minimax: [
        { id: "speech-2.8-turbo",  label: "Speech 2.8 Turbo", recommended: true, note: "最新旗舰，低延迟流式" },
        { id: "speech-2.8-hd",     label: "Speech 2.8 HD",                       note: "最新旗舰，播音级音质" },
        { id: "speech-2.6-turbo",  label: "Speech 2.6 Turbo",                    note: "经典稳定版" },
        { id: "speech-2.6-hd",     label: "Speech 2.6 HD" },
        { id: "speech-02-turbo",   label: "Speech 02 Turbo" },
        { id: "speech-02-hd",      label: "Speech 02 HD" },
        { id: "speech-01-turbo",   label: "Speech 01 Turbo" },
    ],
    elevenlabs: [
        { id: "eleven_flash_v2_5",     label: "Flash v2.5",       recommended: true, note: "极速流式 ~75ms，推荐实时场景" },
        { id: "eleven_multilingual_v2",label: "Multilingual v2",                     note: "多语言高质量，情感丰富" },
        { id: "eleven_turbo_v2_5",     label: "Turbo v2.5",                          note: "与 Flash v2.5 等价，略慢" },
        { id: "eleven_v3",             label: "Eleven v3",                           note: "最强音质（不适合实时对话）" },
        { id: "eleven_flash_v2",       label: "Flash v2",                            note: "英文专用极速版" },
        { id: "eleven_turbo_v2",       label: "Turbo v2" },
    ],
    aliyun_cosyvoice: [
        { id: "cosyvoice-v3-flash",    label: "CosyVoice v3 Flash", recommended: true, note: "当前主力，流式稳定" },
        { id: "cosyvoice-v3.5-flash",  label: "CosyVoice v3.5 Flash",                 note: "最新升级版" },
        { id: "cosyvoice-v3-plus",     label: "CosyVoice v3 Plus",                    note: "质量优先" },
        { id: "cosyvoice-v3.5-plus",   label: "CosyVoice v3.5 Plus",                  note: "最新旗舰" },
        { id: "cosyvoice-v2",          label: "CosyVoice v2",                         note: "兼容旧音色（如 longxiaochun_v2）" },
    ],
};

// ── [FEAT-①] 阿里云按模型分组的音色列表 ───────────────────────
// 阿里云特殊：每个模型的音色 ID 不通用，必须配对使用
const ALIYUN_VOICES_BY_MODEL: Record<string, { id: string; name: string; tags: string[] }[]> = {
    "cosyvoice-v3-flash": [
        { id: "longanyang",    name: "龙安洋",   tags: ["中文", "男声", "阳光"] },
        { id: "longanhuan",    name: "龙安欢",   tags: ["中文", "女声", "元气"] },
        { id: "longhuhu_v3",   name: "龙呼呼",   tags: ["中文", "女声", "童声"] },
    ],
    "cosyvoice-v3.5-flash": [
    ],
    "cosyvoice-v3-plus": [
        { id: "longanyang",    name: "龙安洋",   tags: ["中文", "男声", "阳光"] },
        { id: "longanhuan",    name: "龙安欢",   tags: ["中文", "女声", "元气"] },
    ],
    "cosyvoice-v3.5-plus": [
    ],
    "cosyvoice-v2": [
        { id: "longxiaochun_v2", name: "龙小淳 V2", tags: ["中文", "女声", "温柔"] },
        { id: "longwan_v2",      name: "龙婉 V2",   tags: ["中文", "女声", "成熟"] },
        { id: "loongstella_v2",  name: "Stella V2", tags: ["中英文", "女声"] },
    ],
};

// ── MiniMax 内置音色（与模型无关） ────────────────────────────
const MINIMAX_VOICES = [
    { id: "female-shaonv",      name: "少女音",      tags: ["中文", "女声", "清甜"] },
    { id: "female-yujie",       name: "御姐音",      tags: ["中文", "女声", "成熟"] },
    { id: "female-tianmei",     name: "甜美音",      tags: ["中文", "女声", "甜美"] },
    { id: "female-qingxin",     name: "清新音",      tags: ["中文", "女声", "清新"] },
    { id: "male-qn-jingying",   name: "精英男声",    tags: ["中文", "男声", "成熟"] },
    { id: "male-qn-badao",      name: "霸道男声",    tags: ["中文", "男声", "霸气"] },
    { id: "male-qn-qingse",     name: "青涩男声",    tags: ["中文", "男声", "青涩"] },
];

const TTS_CONFIG_KEY = "rl-tts-v2";
const BACKEND_BASE   = "http://localhost:18000";

// ── Toast ──────────────────────────────────────────────────────
const msgText = ref("");
const msgType = ref<"ok" | "warn">("ok");
function showMsg(text: string, type: "ok" | "warn" = "ok") {
    msgText.value = text;
    msgType.value = type;
    setTimeout(() => { msgText.value = ""; }, 2500);
}

// ── TTS 配置状态 ──────────────────────────────────────────────
const tts = reactive({
    enabled:  false,
    provider: "minimax",
    base_url: "",
    proxy_enabled: false,
    proxy_url: "",
});

// 每个供应商单独保存 Key / GroupID / VoiceID / Model
const apiKeys  = reactive<Record<string, string>>({});
const groupIds = reactive<Record<string, string>>({});
const voiceIds = reactive<Record<string, string>>({});
// [FEAT-①] 每个供应商独立保存模型
const models   = reactive<Record<string, string>>({});

const currentKey = computed({
    get: () => apiKeys[tts.provider] ?? "",
    set: (v) => { apiKeys[tts.provider] = v; },
});
const currentGroupId = computed({
    get: () => groupIds[tts.provider] ?? "",
    set: (v) => { groupIds[tts.provider] = v; },
});
const currentVoiceId = computed({
    get: () => voiceIds[tts.provider] ?? "",
    set: (v) => { voiceIds[tts.provider] = v; },
});

// [FEAT-①] 当前供应商的模型
const currentModel = computed({
    get: () => models[tts.provider] ?? getDefaultModel(tts.provider),
    set: (v) => { models[tts.provider] = v; },
});

// 获取某供应商的默认模型（推荐项）
function getDefaultModel(provider: string): string {
    const preset = MODEL_PRESETS[provider] ?? [];
    const recommended = preset.find(m => m.recommended);
    return recommended?.id ?? preset[0]?.id ?? "";
}

const currentProvider = computed(
    () => PROVIDERS.find(p => p.id === tts.provider)!,
);

// ── 引擎状态（从后端查询）────────────────────────────────────
const engineStatus = ref<{
    mode: string; provider: string; ready: boolean; label: string; error: string;
}>({ mode: "disabled", provider: "", ready: false, label: "语音未启用", error: "" });

const statusDotClass = computed(() => {
    if (engineStatus.value.error) return "dot-red";
    if (engineStatus.value.ready) return "dot-green";
    if (engineStatus.value.mode !== "disabled") return "dot-yellow";
    return "dot-gray";
});

// ── [FEAT-①] 模型自定义状态（按供应商独立记忆） ────────────────
const customModelFlags = reactive<Record<string, boolean>>({});
const customModelTexts = reactive<Record<string, string>>({});

const useCustomModel = computed({
    get: () => customModelFlags[tts.provider] ?? false,
    set: (v) => { customModelFlags[tts.provider] = v; },
});
const customModelId = computed({
    get: () => customModelTexts[tts.provider] ?? "",
    set: (v) => { customModelTexts[tts.provider] = v; },
});

const effectiveModel = computed(() => {
    if (useCustomModel.value) return customModelId.value.trim();
    return currentModel.value;
});

// ── 音色列表 ──────────────────────────────────────────────────
const voices = ref<{ id: string; name: string; tags: string[] }[]>([]);
const voicesLoading = ref(false);
const customVoiceFlags = reactive<Record<string, boolean>>({});
const customVoiceTexts = reactive<Record<string, string>>({});

const useCustomVoice = computed({
    get: () => customVoiceFlags[tts.provider] ?? false,
    set: (v) => { customVoiceFlags[tts.provider] = v; },
});
const customVoiceId = computed({
    get: () => customVoiceTexts[tts.provider] ?? "",
    set: (v) => { customVoiceTexts[tts.provider] = v; },
});

const effectiveVoiceId = computed(() => {
    if (useCustomVoice.value) return customVoiceId.value.trim();
    return currentVoiceId.value;
});

// ── 测试连接 / 高级选项 ──────────────────────────────────────
const testing       = ref(false);
const showAdvanced  = ref(false);

// ── emit ──────────────────────────────────────────────────────
const emit = defineEmits<{
    "tts-saved": [cfg: object];
}>();

// ── 加载配置 ──────────────────────────────────────────────────
function loadConfig() {
    try {
        const raw = localStorage.getItem(TTS_CONFIG_KEY);
        if (!raw) return;
        const cfg = JSON.parse(raw);
        tts.enabled  = (cfg.mode ?? "disabled") === "online";
        tts.provider = cfg.provider ?? "minimax";
        tts.base_url = cfg.base_url ?? "";
        tts.proxy_enabled = cfg.proxy_enabled ?? false;
        tts.proxy_url     = cfg.proxy_url ?? "";
        if (cfg.api_keys)  Object.assign(apiKeys,  cfg.api_keys);
        if (cfg.group_ids) Object.assign(groupIds, cfg.group_ids);
        if (cfg.voice_ids) {
            Object.assign(voiceIds, cfg.voice_ids);
        } else if (cfg.voice_id && cfg.provider) {
            voiceIds[cfg.provider] = cfg.voice_id;
        }
        if (cfg.custom_voice_flags) Object.assign(customVoiceFlags, cfg.custom_voice_flags);
        if (cfg.custom_voice_texts) Object.assign(customVoiceTexts, cfg.custom_voice_texts);

        // [FEAT-①] 恢复各供应商的模型
        if (cfg.models) Object.assign(models, cfg.models);
        if (cfg.custom_model_flags) Object.assign(customModelFlags, cfg.custom_model_flags);
        if (cfg.custom_model_texts) Object.assign(customModelTexts, cfg.custom_model_texts);

        // 兼容旧数据：如果某供应商没有 model，不做处理，留空则使用推荐默认值
        // 如果 voice_id 不在内置列表中，标记为自定义
        if (!(tts.provider in customVoiceFlags)) {
            const vid = voiceIds[tts.provider] ?? "";
            const builtinIds = getBuiltinVoicesFor(tts.provider, effectiveModel.value).map(v => v.id);
            if (vid && !builtinIds.includes(vid)) {
                customVoiceFlags[tts.provider] = true;
                customVoiceTexts[tts.provider] = vid;
            }
        }

        // 如果 model 不在预设列表中，标记为自定义
        if (!(tts.provider in customModelFlags)) {
            const mid = models[tts.provider] ?? "";
            const presetIds = (MODEL_PRESETS[tts.provider] ?? []).map(m => m.id);
            if (mid && !presetIds.includes(mid)) {
                customModelFlags[tts.provider] = true;
                customModelTexts[tts.provider] = mid;
            }
        }

        console.log(
            "[TTSTab] 配置已加载 | enabled=", tts.enabled,
            " provider=", tts.provider,
            " model=", effectiveModel.value,
            " voice_id=", effectiveVoiceId.value,
            " proxy_enabled=", tts.proxy_enabled,
        );
    } catch (e) {
        console.warn("[TTSTab] 配置加载失败:", e);
    }
}

// ── 查询后端状态 ──────────────────────────────────────────────
async function fetchStatus() {
    try {
        const resp = await fetch(`${BACKEND_BASE}/tts/status`);
        if (resp.ok) engineStatus.value = await resp.json();
    } catch {
        // 后端未启动时忽略
    }
}

// ── [FEAT-①] 获取指定供应商+模型的内置音色列表 ─────────────────
function getBuiltinVoicesFor(provider: string, model: string): { id: string; name: string; tags: string[] }[] {
    if (provider === "minimax") return MINIMAX_VOICES;
    if (provider === "aliyun_cosyvoice") {
        return ALIYUN_VOICES_BY_MODEL[model] ?? [];
    }
    return [];  // elevenlabs 等动态拉取
}

function loadVoicesForProviderAndModel(provider: string, model: string) {
    const builtin = getBuiltinVoicesFor(provider, model);
    if (builtin.length > 0) {
        voices.value = builtin;
        console.log(`[TTSTab] 内置音色列表加载 | provider=${provider} model=${model} count=${builtin.length}`);
        return;
    }
    voices.value = [];
}

async function fetchVoicesFromBackend() {
    voicesLoading.value = true;
    try {
        const resp = await fetch(`${BACKEND_BASE}/tts/voices`);
        if (resp.ok) {
            const data = await resp.json();
            const fetched = (data.voices ?? []).map((v: any) => ({
                id: v.id, name: v.name, tags: v.tags ?? [],
            }));
            if (fetched.length > 0) {
                voices.value = fetched;
                console.log(`[TTSTab] 后端音色列表更新 | count=${fetched.length}`);
            }
        }
    } catch (e) {
        console.warn("[TTSTab] 拉取音色列表失败:", e);
    } finally {
        voicesLoading.value = false;
    }
}

// ── 保存并应用配置 ────────────────────────────────────────────
async function saveTTS() {
    const mode = tts.enabled ? "online" : "disabled";
    const finalVoiceId = effectiveVoiceId.value;
    const finalModel   = effectiveModel.value;
    const proxyValue = (tts.proxy_enabled && tts.proxy_url.trim()) ? tts.proxy_url.trim() : "";

    console.log(
        `[TTSTab] saveTTS | provider=${tts.provider} model="${finalModel}" `
        + `voice="${finalVoiceId}" proxy="${proxyValue || '(空)'}"`
    );

    // 组装持久化配置
    const storedCfg = {
        mode,
        provider:           tts.provider,
        voice_id:           finalVoiceId,
        model:              finalModel,
        voice_ids:          { ...voiceIds },
        models:             { ...models },
        custom_voice_flags: { ...customVoiceFlags },
        custom_voice_texts: { ...customVoiceTexts },
        custom_model_flags: { ...customModelFlags },
        custom_model_texts: { ...customModelTexts },
        base_url:           tts.base_url,
        proxy_enabled:      tts.proxy_enabled,
        proxy_url:          tts.proxy_url,
        api_keys:           { ...apiKeys },
        group_ids:          { ...groupIds },
    };
    localStorage.setItem(TTS_CONFIG_KEY, JSON.stringify(storedCfg));

    // 组装给后端的配置
    const backendCfg: Record<string, string> = {
        mode,
        provider: tts.provider,
        api_key:  apiKeys[tts.provider] ?? "",
        voice_id: finalVoiceId,
        model:    finalModel,
        base_url: tts.base_url,
        proxy:    proxyValue,
    };
    if (tts.provider === "minimax") {
        backendCfg.group_id = groupIds["minimax"] ?? "";
    }

    console.log("[TTSTab] → 后端配置:", JSON.stringify(backendCfg));

    try {
        const resp = await fetch(`${BACKEND_BASE}/tts/config`, {
            method:  "POST",
            headers: { "Content-Type": "application/json" },
            body:    JSON.stringify(backendCfg),
        });
        if (resp.ok) {
            const data = await resp.json();
            engineStatus.value = {
                mode:     data.mode,
                provider: data.provider,
                ready:    data.ready,
                label:    data.label,
                error:    data.error ?? "",
            };
            if (data.ready && tts.provider === "elevenlabs") {
                await fetchVoicesFromBackend();
            }
            showMsg("✓ 语音设置已保存");
        } else {
            showMsg("保存失败，请检查后端", "warn");
        }
    } catch (e) {
        showMsg("无法连接后端，配置已保存到本地", "warn");
        console.warn("[TTSTab] 后端连接失败:", e);
    }

    emit("tts-saved", backendCfg);
    console.log("[TTSTab] 配置已保存并提交后端");
}

// ── 测试连接 ──────────────────────────────────────────────────
async function testConnection() {
    if (!tts.enabled) {
        showMsg("请先开启「启用语音合成」", "warn");
        return;
    }
    if (!apiKeys[tts.provider]) {
        showMsg("请先填写 API Key", "warn");
        return;
    }
    testing.value = true;
    try {
        await saveTTS();
        const resp = await fetch(`${BACKEND_BASE}/tts/test`, {
            method:  "POST",
            headers: { "Content-Type": "application/json" },
            body:    JSON.stringify({}),
        });
        if (resp.ok) {
            const data = await resp.json();
            showMsg(
                data.success ? "✓ 连接成功" : `✗ ${data.message}`,
                data.success ? "ok" : "warn",
            );
            if (data.success && tts.provider === "elevenlabs") {
                await fetchVoicesFromBackend();
            }
        } else {
            showMsg("测试请求失败", "warn");
        }
    } catch {
        showMsg("无法连接后端", "warn");
    } finally {
        testing.value = false;
    }
}

// ── [FIX-②] 打开供应商官网 ───────────────────────────────────
async function openProviderSite() {
    if (currentProvider.value.website) {
        await safeOpenUrl(currentProvider.value.website);
    }
}

// ── [FIX-④③b] 供应商切换时重新加载音色列表 ───────────────────
watch(() => tts.provider, (newProvider) => {
    loadVoicesForProviderAndModel(newProvider, effectiveModel.value);
    console.log(
        `[TTSTab] 供应商切换 → ${newProvider} | model="${effectiveModel.value}" `
        + `voice="${currentVoiceId.value}"`
    );
});

// ── [FEAT-①] 阿里云模型切换时重新加载音色列表 ─────────────────
watch(effectiveModel, (newModel, oldModel) => {
    if (tts.provider !== "aliyun_cosyvoice") return;
    if (!newModel || newModel === oldModel) return;

    const newVoices = ALIYUN_VOICES_BY_MODEL[newModel] ?? [];
    voices.value = newVoices;
    console.log(`[TTSTab] 阿里云模型切换 → ${newModel} | 音色数=${newVoices.length}`);

    // 如果当前选中的 voice_id 不在新模型的音色列表中，清空选择
    const currentVid = currentVoiceId.value;
    if (currentVid && !newVoices.find(v => v.id === currentVid)) {
        console.log(`[TTSTab] voice_id "${currentVid}" 不支持模型 ${newModel}，已清空`);
        currentVoiceId.value = "";
    }
});

// ── 切换自定义模式时同步 ─────────────────────────────────────
watch(useCustomVoice, (isCustom) => {
    if (!isCustom) {
        const match = voices.value.find(v => v.id === customVoiceId.value.trim());
        if (match) currentVoiceId.value = match.id;
    }
});

watch(useCustomModel, (isCustom) => {
    if (!isCustom) {
        const presets = MODEL_PRESETS[tts.provider] ?? [];
        const match = presets.find(m => m.id === customModelId.value.trim());
        if (match) currentModel.value = match.id;
    }
});

// ── 刷新音色按钮 ─────────────────────────────────────────────
async function onRefreshVoices() {
    if (tts.provider === "elevenlabs") {
        await fetchVoicesFromBackend();
    } else {
        loadVoicesForProviderAndModel(tts.provider, effectiveModel.value);
        showMsg("音色列表已刷新");
    }
}

// ── 初始化 ────────────────────────────────────────────────────
onMounted(async () => {
    loadConfig();
    loadVoicesForProviderAndModel(tts.provider, effectiveModel.value);
    await fetchStatus();
    if (engineStatus.value.ready && tts.provider === "elevenlabs") {
        await fetchVoicesFromBackend();
    }
});
</script>

<template>
    <div class="tab-content">

        <!-- Toast -->
        <transition name="toast">
            <div v-if="msgText" class="toast" :class="{ warn: msgType === 'warn' }">
                {{ msgText }}
            </div>
        </transition>

        <!-- ── 顶部状态栏 ──────────────────────────────────── -->
        <div class="status-bar">
            <span class="status-dot" :class="statusDotClass"></span>
            <span class="status-label">{{ engineStatus.label }}</span>
            <span v-if="engineStatus.error" class="status-error">· {{ engineStatus.error }}</span>
        </div>

        <!-- ── 启用开关 ────────────────────────────────────── -->
        <div class="field-group">
            <div class="toggle-row">
                <span class="field-label">🔊 启用语音合成</span>
                <label class="toggle-switch">
                    <input type="checkbox" v-model="tts.enabled" />
                    <span class="toggle-slider"></span>
                </label>
            </div>
            <p class="field-hint">关闭时，桌宠回复只显示文字，不播放语音。</p>
        </div>

        <!-- ── 在线配置区 ──────────────────────────────────── -->
        <template v-if="tts.enabled">
            <div class="divider"></div>
            <div class="global-section-title" style="margin-bottom:4px;">☁️ 在线供应商</div>

            <!-- 供应商选择卡片 -->
            <div class="provider-list">
                <div v-for="p in PROVIDERS" :key="p.id"
                     class="provider-card"
                     :class="{ active: tts.provider === p.id }"
                     @click="tts.provider = p.id">
                    <div class="provider-header">
                        <span class="provider-name">{{ p.name }}</span>
                        <span class="provider-badge"
                              :class="p.domestic ? 'badge-domestic' : 'badge-intl'">
                            {{ p.badge }}
                        </span>
                        <span v-if="tts.provider === p.id" class="provider-check">✓</span>
                    </div>
                    <div class="provider-desc">{{ p.desc }}</div>
                </div>
            </div>

            <!-- 官网链接 -->
            <div class="field-group" v-if="currentProvider.website">
                <a class="vendor-link" href="#" @click.prevent="openProviderSite">
                    🔗 前往 {{ currentProvider.name }} 官网获取 API Key
                </a>
            </div>

            <!-- API Key -->
            <div class="field-group">
                <label class="field-label">API Key</label>
                <input class="field-input" v-model="currentKey" type="password"
                       placeholder="粘贴 API Key…" />
                <p class="field-hint">密钥仅保存在本地，不会上传到任何服务器。</p>
            </div>

            <!-- MiniMax 专属 Group ID -->
            <div class="field-group" v-if="currentProvider.needGroupId">
                <label class="field-label">Group ID</label>
                <input class="field-input" v-model="currentGroupId" type="text"
                       placeholder="MiniMax 平台的 Group ID" />
                <p class="field-hint">仅 MiniMax 需要此参数，可在平台账户页面查询。</p>
            </div>

            <!-- ── [FEAT-①] 模型选择 ───────────────────────── -->
            <div class="field-group">
                <label class="field-label">模型
                    <span class="field-note">Model</span>
                </label>

                <!-- 下拉选择区 -->
                <div v-if="!useCustomModel" class="voice-row">
                    <select v-model="currentModel" class="field-select">
                        <option v-for="m in MODEL_PRESETS[tts.provider] ?? []"
                                :key="m.id" :value="m.id">
                            {{ m.recommended ? '⭐ ' : '' }}{{ m.label }}
                            <template v-if="m.note"> · {{ m.note }}</template>
                        </option>
                    </select>
                </div>

                <!-- 自定义输入区 -->
                <div v-else class="voice-row">
                    <input class="field-input" v-model="customModelId" type="text"
                           :placeholder="`手动输入模型 ID（如 ${getDefaultModel(tts.provider)}）`" />
                </div>

                <!-- 自定义切换 -->
                <div class="custom-voice-toggle"
                     @click="useCustomModel = !useCustomModel">
                    {{ useCustomModel ? '↩ 返回预设选择' : '✏️ 手动输入模型 ID' }}
                </div>

                <p class="field-hint">
                    ⚠️ 请确保所填模型支持流式输出（Streaming），否则会导致合成失败。
                </p>
            </div>

            <!-- ── 音色选择 ────────────────────────────────── -->
            <div class="field-group">
                <label class="field-label">音色
                    <span class="field-note">Voice</span>
                </label>

                <!-- 下拉选择区 -->
                <div v-if="!useCustomVoice && voices.length > 0" class="voice-row">
                    <select v-model="currentVoiceId" class="field-select">
                        <option value="">请选择音色…</option>
                        <option v-for="v in voices" :key="v.id" :value="v.id">
                            {{ v.name }}
                            <template v-if="v.tags?.length"> · {{ v.tags.slice(0, 2).join(' · ') }}</template>
                        </option>
                    </select>
                    <button class="refresh-btn" @click="onRefreshVoices"
                            :disabled="voicesLoading" title="刷新音色列表">
                        {{ voicesLoading ? '…' : '↻' }}
                    </button>
                </div>

                <!-- 自定义输入区 -->
                <div v-if="useCustomVoice || voices.length === 0" class="voice-row">
                    <input class="field-input" v-model="customVoiceId" type="text"
                           placeholder="手动输入音色 ID" />
                    <button v-if="voices.length > 0"
                            class="refresh-btn" @click="onRefreshVoices"
                            :disabled="voicesLoading" title="刷新音色列表">
                        {{ voicesLoading ? '…' : '↻' }}
                    </button>
                </div>

                <!-- 自定义开关 -->
                <div v-if="voices.length > 0" class="custom-voice-toggle"
                     @click="useCustomVoice = !useCustomVoice">
                    {{ useCustomVoice ? '↩ 返回列表选择' : '✏️ 手动输入音色 ID' }}
                </div>

                <p v-if="useCustomVoice" class="field-hint">
                    可直接填写供应商提供的音色 ID，适用于克隆音色或列表中未包含的音色。
                </p>
                <p v-else-if="tts.provider === 'aliyun_cosyvoice'" class="field-hint">
                    ℹ️ cosyvoice-3.5-plus/flash仅支持音色设计和音色克隆。
                </p>
            </div>

            <!-- ── 高级选项 ────────────────────────────────── -->
            <div class="advanced-toggle" @click="showAdvanced = !showAdvanced">
                <span>{{ showAdvanced ? '▼' : '▶' }} 高级选项</span>
            </div>
            <template v-if="showAdvanced">
                <div class="field-group">
                    <label class="field-label">自定义 API 地址
                        <span class="field-note">base_url（可选）</span>
                    </label>
                    <input class="field-input" v-model="tts.base_url" type="text"
                           placeholder="留空使用官方地址" />
                    <p class="field-hint">适用于三方代理或自建中转，留空使用默认地址。</p>
                </div>

                <div class="field-group">
                    <div class="toggle-row">
                        <label class="field-label">🌐 HTTP 代理</label>
                        <label class="toggle-switch">
                            <input type="checkbox" v-model="tts.proxy_enabled" />
                            <span class="toggle-slider"></span>
                        </label>
                    </div>
                    <input class="field-input" v-model="tts.proxy_url" type="text"
                           :disabled="!tts.proxy_enabled"
                           :class="{ 'field-readonly': !tts.proxy_enabled }"
                           placeholder="http://127.0.0.1:7890" />
                    <p class="field-hint">
                        ElevenLabs 等境外服务通常需要代理才能访问。
                        填入代理地址后开启开关即可生效，无需代理时关闭即可。
                    </p>
                </div>
            </template>

            <!-- 测试连接 -->
            <div class="action-row" style="justify-content:flex-start; padding-top:4px;">
                <button class="test-btn" @click="testConnection" :disabled="testing">
                    {{ testing ? '测试中…' : '🔗 测试连接' }}
                </button>
            </div>
        </template>

        <!-- ── 保存按钮 ──────────────────────────────────── -->
        <div class="action-row">
            <button class="save-btn" @click="saveTTS">保存配置</button>
        </div>

    </div>
</template>

<style scoped>
/* ── 状态栏 ─────────────────────────────────────────────── */
.status-bar {
    display: flex; align-items: center; gap: 8px;
    padding: 10px 14px;
    background: var(--c-surface);
    border: 1.5px solid var(--c-border);
    border-radius: 12px;
    margin-bottom: 4px;
}
.status-dot { width: 9px; height: 9px; border-radius: 50%; flex-shrink: 0; }
.dot-green  { background: #7FCFA4; box-shadow: 0 0 0 3px rgba(127,207,164,0.18); }
.dot-yellow { background: #F5C46B; box-shadow: 0 0 0 3px rgba(245,196,107,0.18); }
.dot-red    { background: #E08080; box-shadow: 0 0 0 3px rgba(224,128,128,0.18); }
.dot-gray   { background: #C8BDD8; }
.status-label { font-size: 13px; color: var(--c-text); font-weight: 500; }
.status-error { font-size: 11px; color: #C05050; }

/* ── 供应商链接 ─────────────────────────────────────────── */
.vendor-link {
    display: inline-block; font-size: 12px; color: var(--c-blue);
    text-decoration: none; padding: 2px 0; transition: color 0.2s;
}
.vendor-link:hover { text-decoration: underline; }

/* ── 供应商卡片 ─────────────────────────────────────────── */
.provider-list { display: flex; flex-direction: column; gap: 8px; }
.provider-card {
    padding: 10px 14px;
    border: 1.5px solid var(--c-border);
    border-radius: 12px;
    background: var(--c-surface);
    cursor: pointer;
    transition: border-color 0.2s, box-shadow 0.2s, background 0.2s;
}
.provider-card:hover { border-color: var(--c-pink-mid); }
.provider-card.active {
    border-color: var(--c-blue);
    box-shadow: 0 0 0 3px var(--c-blue-light);
    background: linear-gradient(135deg, rgba(197,232,244,0.22), rgba(255,183,197,0.12));
}
.provider-header { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
.provider-name { font-size: 13px; font-weight: 600; color: var(--c-text); }
.provider-badge { font-size: 10px; font-weight: 600; padding: 2px 8px; border-radius: 10px; }
.badge-domestic { background: rgba(127,207,164,0.18); color: #4FA377; }
.badge-intl { background: rgba(126,200,227,0.2); color: #3D94B8; }
.provider-check { margin-left: auto; color: var(--c-blue); font-size: 14px; font-weight: 700; }
.provider-desc { font-size: 11px; color: var(--c-text-soft); line-height: 1.55; }

/* ── 音色/模型选择行 ────────────────────────────────────── */
.voice-row { display: flex; gap: 6px; align-items: center; }
.voice-row .field-input,
.voice-row .field-select { flex: 1; }
.refresh-btn {
    flex-shrink: 0; padding: 8px 12px;
    border: 1.5px solid var(--c-border);
    border-radius: 10px;
    background: var(--c-surface);
    color: var(--c-text-soft);
    font-size: 14px; font-family: inherit; cursor: pointer;
    transition: border-color 0.2s, color 0.2s;
}
.refresh-btn:hover:not(:disabled) { border-color: var(--c-pink-mid); color: var(--c-text); }
.refresh-btn:disabled { opacity: 0.5; cursor: not-allowed; }

/* ── 自定义切换按钮（音色 + 模型共用） ─────────────────── */
.custom-voice-toggle {
    display: inline-block; font-size: 11px; color: var(--c-blue);
    cursor: pointer; user-select: none;
    padding: 2px 4px; transition: color 0.2s;
}
.custom-voice-toggle:hover { color: var(--c-pink-mid); text-decoration: underline; }

/* ── 高级选项折叠 ───────────────────────────────────────── */
.advanced-toggle {
    display: inline-block; font-size: 12px; color: var(--c-text-soft);
    cursor: pointer; user-select: none;
    padding: 2px 4px; transition: color 0.2s;
}
.advanced-toggle:hover { color: var(--c-text); }

/* ── 测试按钮 ───────────────────────────────────────────── */
.test-btn {
    padding: 7px 16px;
    border: 1.5px solid var(--c-border);
    border-radius: 18px;
    background: var(--c-surface);
    color: var(--c-text);
    font-size: 12px; font-weight: 500; font-family: inherit; cursor: pointer;
    transition: border-color 0.2s, background 0.2s;
}
.test-btn:hover:not(:disabled) { border-color: var(--c-blue); background: var(--c-pink-light); }
.test-btn:disabled { opacity: 0.5; cursor: not-allowed; }

/* ── Toast ───────────────────────────────────────────────── */
.toast {
    position: fixed; top: 16px; left: 50%; transform: translateX(-50%);
    padding: 8px 20px; border-radius: 20px;
    background: linear-gradient(white, white) padding-box,
                linear-gradient(135deg, #A8D8EA, #FFB7C5) border-box;
    border: 2px solid transparent; color: #4A4A6A;
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