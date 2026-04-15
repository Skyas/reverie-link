<script setup lang="ts">
/**
 * TTSTab.vue — 语音合成设置（粉蓝主题，复用全局共享样式）
 *
 * 说明：
 *   - 样式严格遵循 DECISIONS.md 的水粉/水蓝主题
 *   - 表单组件复用 SettingsApp.vue 中定义的 .field-group / .field-input / .toggle-switch / .save-btn 等
 *   - 供应商选择卡片样式参考原 LLMTab.vue 的 .engine-card 样式（蓝色高亮 + 淡粉渐变）
 */
import { ref, reactive, computed, onMounted, watch } from "vue";
import { openUrl } from "@tauri-apps/plugin-opener";

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
    enabled:  false,            // 对应 mode: disabled | online
    provider: "minimax",
    voice_id: "",
    base_url: "",
});

// 每个供应商单独保存 Key / GroupID
const apiKeys  = reactive<Record<string, string>>({});
const groupIds = reactive<Record<string, string>>({});

const currentKey = computed({
    get: () => apiKeys[tts.provider] ?? "",
    set: (v) => { apiKeys[tts.provider] = v; },
});
const currentGroupId = computed({
    get: () => groupIds[tts.provider] ?? "",
    set: (v) => { groupIds[tts.provider] = v; },
});

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

// ── 音色列表 ──────────────────────────────────────────────────
const voices = ref<{ id: string; name: string; engine: string; tags: string[] }[]>([]);
const voicesLoading = ref(false);

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
        tts.voice_id = cfg.voice_id ?? "";
        tts.base_url = cfg.base_url ?? "";
        if (cfg.api_keys)  Object.assign(apiKeys,  cfg.api_keys);
        if (cfg.group_ids) Object.assign(groupIds, cfg.group_ids);
        console.log(
            "[TTSTab] 配置已加载 | enabled=", tts.enabled,
            " provider=", tts.provider,
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

// ── 拉取音色列表 ──────────────────────────────────────────────
async function fetchVoices() {
    voicesLoading.value = true;
    voices.value = [];
    try {
        const resp = await fetch(`${BACKEND_BASE}/tts/voices`);
        if (resp.ok) {
            const data = await resp.json();
            voices.value = data.voices ?? [];
            console.log("[TTSTab] 音色列表更新 | count=", voices.value.length);
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

    // 组装持久化配置
    const storedCfg = {
        mode,
        provider:  tts.provider,
        voice_id:  tts.voice_id,
        base_url:  tts.base_url,
        api_keys:  { ...apiKeys },
        group_ids: { ...groupIds },
    };
    localStorage.setItem(TTS_CONFIG_KEY, JSON.stringify(storedCfg));

    // 组装给后端的配置（只携带当前供应商的密钥）
    const backendCfg: Record<string, string> = {
        mode,
        provider: tts.provider,
        api_key:  apiKeys[tts.provider] ?? "",
        voice_id: tts.voice_id,
        base_url: tts.base_url,
    };
    if (tts.provider === "minimax") {
        backendCfg.group_id = groupIds["minimax"] ?? "";
    }

    // POST 到后端
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
            if (data.ready) await fetchVoices();
            showMsg("✓ 语音设置已保存");
        } else {
            showMsg("保存失败，请检查后端", "warn");
        }
    } catch (e) {
        showMsg("无法连接后端，配置已保存到本地", "warn");
        console.warn("[TTSTab] 后端连接失败:", e);
    }

    // 通知父组件（同步到主窗口 WebSocket）
    emit("tts-saved", backendCfg);
    console.log("[TTSTab] 配置已保存并提交后端 | mode=", mode);
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
        await saveTTS(); // 测试前先保存当前配置
        const resp = await fetch(`${BACKEND_BASE}/tts/test`, {
            method:  "POST",
            headers: { "Content-Type": "application/json" },
            body:    JSON.stringify({}),
        });
        if (resp.ok) {
            const data = await resp.json();
            showMsg(
                data.success ? "✓ 连接成功" : `✗ 连接失败：${data.message}`,
                data.success ? "ok" : "warn",
            );
        } else {
            showMsg("测试请求失败", "warn");
        }
    } catch {
        showMsg("无法连接后端", "warn");
    } finally {
        testing.value = false;
    }
}

// ── 打开供应商官网 ────────────────────────────────────────────
async function openProviderSite() {
    if (currentProvider.value.website) await openUrl(currentProvider.value.website);
}

// ── 供应商切换时清空音色 ──────────────────────────────────────
watch(() => tts.provider, () => {
    voices.value = [];
    tts.voice_id = "";
});

// ── 初始化 ────────────────────────────────────────────────────
onMounted(async () => {
    loadConfig();
    await fetchStatus();
    if (engineStatus.value.ready) await fetchVoices();
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

            <!-- 音色选择 -->
            <div class="field-group">
                <label class="field-label">音色
                    <span class="field-note">Voice</span>
                </label>
                <div class="voice-row">
                    <select v-if="voices.length" v-model="tts.voice_id" class="field-select">
                        <option value="">请选择音色…</option>
                        <option v-for="v in voices" :key="v.id" :value="v.id">
                            {{ v.name }}<span v-if="v.tags?.length"> · {{ v.tags.slice(0, 2).join(' · ') }}</span>
                        </option>
                    </select>
                    <input v-else class="field-input" v-model="tts.voice_id" type="text"
                           placeholder="手动输入音色 ID，或保存后自动加载列表" />
                    <button class="refresh-btn" @click="fetchVoices"
                            :disabled="voicesLoading" title="刷新音色列表">
                        {{ voicesLoading ? '…' : '↻' }}
                    </button>
                </div>
            </div>

            <!-- 高级选项 -->
            <div class="advanced-toggle" @click="showAdvanced = !showAdvanced">
                <span>{{ showAdvanced ? '▼' : '▶' }} 高级选项</span>
            </div>
            <div v-if="showAdvanced" class="field-group">
                <label class="field-label">自定义 API 地址
                    <span class="field-note">base_url（可选）</span>
                </label>
                <input class="field-input" v-model="tts.base_url" type="text"
                       placeholder="留空使用官方地址" />
                <p class="field-hint">适用于代理或自建中转，留空使用默认地址。</p>
            </div>

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
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 10px 14px;
    background: var(--c-surface);
    border: 1.5px solid var(--c-border);
    border-radius: 12px;
    margin-bottom: 4px;
}
.status-dot {
    width: 9px; height: 9px;
    border-radius: 50%;
    flex-shrink: 0;
}
.dot-green  { background: #7FCFA4; box-shadow: 0 0 0 3px rgba(127,207,164,0.18); }
.dot-yellow { background: #F5C46B; box-shadow: 0 0 0 3px rgba(245,196,107,0.18); }
.dot-red    { background: #E08080; box-shadow: 0 0 0 3px rgba(224,128,128,0.18); }
.dot-gray   { background: #C8BDD8; }
.status-label {
    font-size: 13px;
    color: var(--c-text);
    font-weight: 500;
}
.status-error {
    font-size: 11px;
    color: #C05050;
}

/* ── 供应商链接 ─────────────────────────────────────────── */
.vendor-link {
    display: inline-block;
    font-size: 12px;
    color: var(--c-blue);
    text-decoration: none;
    padding: 2px 0;
    transition: color 0.2s;
}
.vendor-link:hover { text-decoration: underline; }

/* ── 供应商卡片 ─────────────────────────────────────────── */
.provider-list {
    display: flex;
    flex-direction: column;
    gap: 8px;
}
.provider-card {
    padding: 10px 14px;
    border: 1.5px solid var(--c-border);
    border-radius: 12px;
    background: var(--c-surface);
    cursor: pointer;
    transition: border-color 0.2s, box-shadow 0.2s, background 0.2s;
}
.provider-card:hover {
    border-color: var(--c-pink-mid);
}
.provider-card.active {
    border-color: var(--c-blue);
    box-shadow: 0 0 0 3px var(--c-blue-light);
    background: linear-gradient(135deg, rgba(197,232,244,0.22), rgba(255,183,197,0.12));
}
.provider-header {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 4px;
}
.provider-name {
    font-size: 13px;
    font-weight: 600;
    color: var(--c-text);
}
.provider-badge {
    font-size: 10px;
    font-weight: 600;
    padding: 2px 8px;
    border-radius: 10px;
}
.badge-domestic {
    background: rgba(127,207,164,0.18);
    color: #4FA377;
}
.badge-intl {
    background: rgba(126,200,227,0.2);
    color: #3D94B8;
}
.provider-check {
    margin-left: auto;
    color: var(--c-blue);
    font-size: 14px;
    font-weight: 700;
}
.provider-desc {
    font-size: 11px;
    color: var(--c-text-soft);
    line-height: 1.55;
}

/* ── 音色选择行 ─────────────────────────────────────────── */
.voice-row {
    display: flex;
    gap: 6px;
    align-items: center;
}
.voice-row .field-input,
.voice-row .field-select {
    flex: 1;
}
.refresh-btn {
    flex-shrink: 0;
    padding: 8px 12px;
    border: 1.5px solid var(--c-border);
    border-radius: 10px;
    background: var(--c-surface);
    color: var(--c-text-soft);
    font-size: 14px;
    font-family: inherit;
    cursor: pointer;
    transition: border-color 0.2s, color 0.2s;
}
.refresh-btn:hover:not(:disabled) {
    border-color: var(--c-pink-mid);
    color: var(--c-text);
}
.refresh-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
}

/* ── 高级选项折叠 ───────────────────────────────────────── */
.advanced-toggle {
    display: inline-block;
    font-size: 12px;
    color: var(--c-text-soft);
    cursor: pointer;
    user-select: none;
    padding: 2px 4px;
    transition: color 0.2s;
}
.advanced-toggle:hover {
    color: var(--c-text);
}

/* ── 测试按钮 ───────────────────────────────────────────── */
.test-btn {
    padding: 7px 16px;
    border: 1.5px solid var(--c-border);
    border-radius: 18px;
    background: var(--c-surface);
    color: var(--c-text);
    font-size: 12px;
    font-weight: 500;
    font-family: inherit;
    cursor: pointer;
    transition: border-color 0.2s, background 0.2s;
}
.test-btn:hover:not(:disabled) {
    border-color: var(--c-blue);
    background: var(--c-pink-light);
}
.test-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
}

/* ── Toast（复用 LLMTab 风格） ───────────────────────────── */
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
