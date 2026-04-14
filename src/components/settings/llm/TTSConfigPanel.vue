<script setup lang="ts">
import { ref } from "vue";
import { openUrl } from "@tauri-apps/plugin-opener";

// ── Props / Emits ──────────────────────────────────────────────
interface RVCVoice { name: string; pth: string; index: string; index_missing: boolean; }

const tts = defineModel<{
    engine: "elevenlabs" | "rvc";
    enabled: boolean;
    el_api_key: string;
    el_voice_id: string;
    rvc_pth: string;
    rvc_index: string;
    rvc_edge_voice: string;
}>("tts", { required: true });

// ── Toast（透传） ─────────────────────────────────────────────
const msgText = ref("");
const msgType = ref<"ok" | "warn">("ok");
function showMsg(text: string, type: "ok" | "warn" = "ok") {
    msgText.value = text; msgType.value = type;
    setTimeout(() => { msgText.value = ""; }, 2500);
}

// ── RVC 音色 ───────────────────────────────────────────────────
const rvcVoices  = ref<RVCVoice[]>([]);
const rvcLoading = ref(false);

async function fetchRVCVoices() {
    console.info("[TTSConfigPanel] 扫描RVC音色文件...");
    rvcLoading.value = true;
    try {
        const res = await fetch("http://localhost:18000/api/rvc/voices");
        const data = await res.json();
        rvcVoices.value = data.voices ?? [];
        console.info(`[TTSConfigPanel] RVC音色扫描完成 | 找到 ${rvcVoices.value.length} 个`);
    } catch (e) {
        console.error("[TTSConfigPanel] ❌ RVC音色扫描失败:", e);
        rvcVoices.value = [];
        showMsg("无法扫描音色，请确认后端已启动", "warn");
    } finally {
        rvcLoading.value = false;
    }
}

function selectRVCVoice(voice: RVCVoice) {
    console.info(`[TTSConfigPanel] 选择RVC音色 | name=${voice.name} pth=${voice.pth}`);
    tts.value.rvc_pth   = voice.pth;
    tts.value.rvc_index = voice.index;
}

// ── 暴露 Toast 给父组件 ────────────────────────────────────────
defineExpose({ showMsg });
</script>

<template>
    <div class="tts-section">
        <!-- Toast -->
        <transition name="toast">
            <div v-if="msgText" class="toast" :class="{ warn: msgType === 'warn' }">{{ msgText }}</div>
        </transition>

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
                       placeholder="sk_xxx...xxxx" />
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
    </div>
</template>

<style scoped>
.tts-section {
    display: flex;
    flex-direction: column;
    gap: 10px;
}

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

.refresh-btn {
    align-self: flex-start;
    margin-top: 4px;
    font-size: 12px;
    padding: 4px 14px;
    border: 1.5px solid var(--c-blue);
    border-radius: 20px;
    background: transparent;
    color: var(--c-blue);
    cursor: pointer;
    font-family: inherit;
    transition: background 0.2s, color 0.2s;
}
.refresh-btn:hover { background: var(--c-blue); color: white; }

.vendor-link {
    display: inline-block;
    font-size: 12px;
    color: var(--c-blue);
    text-decoration: none;
    padding: 4px 0;
    transition: color 0.2s;
}
.vendor-link:hover { text-decoration: underline; }

/* toast */
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
