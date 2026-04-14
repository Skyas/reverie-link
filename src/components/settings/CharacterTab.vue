<script setup lang="ts">
import { ref, reactive, computed, onMounted } from "vue";
import DeleteCharDialog from "./DeleteCharDialog.vue";

// ── 类型定义 ───────────────────────────────────────────────────
interface CharacterPreset {
    id: string; name: string; description: string;
    identity: string; personality: string;
    address: string; style: string; avatar: string;
    examples: { user: string; char: string }[];
}

// ── Props / Emits ──────────────────────────────────────────────
const props = defineProps<{
    activePresetId: string;
    defaultAvatar:  string;
}>();

const emit = defineEmits<{
    "activated":    [presetId: string, charCfg: object];
    "deleted":      [newActiveId: string];
    "open-notebook":[characterId: string, characterName: string];
}>();

// ── Toast ──────────────────────────────────────────────────────
const msgText = ref("");
const msgType = ref<"ok" | "warn">("ok");
function showMsg(text: string, type: "ok" | "warn" = "ok") {
    msgText.value = text; msgType.value = type;
    setTimeout(() => { msgText.value = ""; }, 2500);
}

// ── 常量 ───────────────────────────────────────────────────────
const MAX_PRESETS = 10;

const DEFAULT_PRESET: CharacterPreset = {
    id: "default-rei", name: "Rei",
    description: "傲娇猫娘，Reverie Link 默认角色",
    identity: "你是用户身边的猫娘伙伴，平时住在一起",
    personality: "傲娇，表面高冷不在乎，实际上很在意用户，被关心时会别扭地否认，偶尔情绪激动时会不自觉说出一个「喵」",
    address: "主人",
    style: "简短干脆，傲娇别扭，不会主动示好但会用绕弯子的方式表达关心。被夸会别扭地承认然后非常害羞，偶尔一个字的「喵」，绝对不叠用",
    avatar: "",
    examples: [
        { user: "今天辛苦了",   char: "哼，谁要你说这种话。……自己注意点身体就行了。[sad]"           },
        { user: "你在担心我吗？", char: "想什么呢。只是觉得你这样下去会给我添麻烦而已。才没有在担心你呢。[angry]" },
        { user: "你真可爱",     char: "哼…哼~。你终于知道我的好了。喵~。[shy]"                  },
    ],
};

// ── 预设列表状态 ───────────────────────────────────────────────
const presets     = ref<CharacterPreset[]>([]);
const activePreset = ref<CharacterPreset | null>(null);

function ensureDefaultFirst(list: CharacterPreset[]): CharacterPreset[] {
    const withoutDefault = list.filter(p => p.id !== "default-rei");
    const hasDefault     = list.find(p => p.id === "default-rei");
    return [hasDefault ?? { ...DEFAULT_PRESET }, ...withoutDefault];
}

function savePresets() {
    localStorage.setItem("rl-presets", JSON.stringify(presets.value));
}

// ── 表单状态 ───────────────────────────────────────────────────
const character = reactive<Omit<CharacterPreset, "id">>({
    name: "", description: "", identity: "", personality: "",
    address: "", style: "", avatar: "", examples: [{ user: "", char: "" }],
});

function loadPresetToForm(preset: CharacterPreset) {
    activePreset.value    = preset;
    character.name        = preset.name;
    character.description = preset.description;
    character.identity    = preset.identity;
    character.personality = preset.personality;
    character.address     = preset.address;
    character.style       = preset.style;
    character.avatar      = preset.avatar;
    character.examples    = preset.examples.length
        ? preset.examples.map(e => ({ ...e }))
        : [{ user: "", char: "" }];
}

function newPreset() {
    activePreset.value = null;
    character.name = ""; character.description = ""; character.identity = "";
    character.personality = ""; character.address = ""; character.style = "";
    character.avatar = ""; character.examples = [{ user: "", char: "" }];
}

function addExample()          { if (character.examples.length < 3) character.examples.push({ user: "", char: "" }); }
function removeExample(i: number) { character.examples.splice(i, 1); }

// ── 头像上传 ───────────────────────────────────────────────────
const avatarInputRef = ref<HTMLInputElement | null>(null);
function triggerAvatarUpload() { avatarInputRef.value?.click(); }
function onAvatarChange(e: Event) {
    const file = (e.target as HTMLInputElement).files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => { character.avatar = reader.result as string; };
    reader.readAsDataURL(file);
}

// ── 保存预设弹框 ───────────────────────────────────────────────
const showSaveDialog  = ref(false);
const saveDialogDesc  = ref("");

function openSaveDialog() {
    if (!character.name.trim()) { showMsg("请先填写角色名字", "warn"); return; }
    saveDialogDesc.value = character.description;
    showSaveDialog.value = true;
}

function confirmSave() {
    character.description = saveDialogDesc.value.trim();
    showSaveDialog.value  = false;
    const examples = character.examples.filter(e => e.user.trim() && e.char.trim());

    if (activePreset.value) {
        const idx = presets.value.findIndex(p => p.id === activePreset.value!.id);
        if (idx !== -1) {
            presets.value[idx] = { ...activePreset.value, ...character, examples };
            activePreset.value = presets.value[idx];
        }
    } else {
        if (presets.value.length >= MAX_PRESETS) { showMsg(`最多保存 ${MAX_PRESETS} 个角色预设`, "warn"); return; }
        const newP: CharacterPreset = { id: `preset-${Date.now()}`, ...character, examples };
        presets.value.push(newP);
        activePreset.value = newP;
    }
    presets.value = ensureDefaultFirst(presets.value);
    savePresets();
    showMsg("✓ 预设已保存");
}

// ── 激活预设 ───────────────────────────────────────────────────
async function activatePreset(preset: CharacterPreset) {
    loadPresetToForm(preset);
    const llmCfg = JSON.parse(localStorage.getItem("rl-llm") || "{}");
    const charCfg = {
        name: preset.name, identity: preset.identity,
        personality: preset.personality, address: preset.address,
        style: preset.style, examples: preset.examples,
    };
    localStorage.setItem("rl-character",       JSON.stringify(charCfg));
    localStorage.setItem("rl-active-preset-id", preset.id);
    emit("activated", preset.id, charCfg);
    showMsg(`✓ 已切换到「${preset.name}」`);
}

// ── 删除预设 ───────────────────────────────────────────────────
const showDeleteDialog  = ref(false);
const deleteTargetId    = ref("");
const deleteTargetName  = ref("");
const deleteDataLoading = ref(false);

function requestDeletePreset(id: string) {
    if (id === "default-rei") { showMsg("默认预设不可删除", "warn"); return; }
    const preset = presets.value.find(p => p.id === id);
    if (!preset) return;
    deleteTargetId.value   = id;
    deleteTargetName.value = preset.name;
    showDeleteDialog.value = true;
}

async function confirmDeleteWithExport() {
    deleteDataLoading.value = true;
    try {
        const res = await fetch(`http://localhost:18000/api/character/${deleteTargetId.value}/export`);
        if (res.ok) {
            const blob = await res.blob();
            const url  = URL.createObjectURL(blob);
            const a    = document.createElement("a");
            a.href     = url;
            a.download = `reverie_export_${deleteTargetId.value.slice(0, 16)}.json`;
            a.click();
            URL.revokeObjectURL(url);
        }
    } catch (e) { console.warn("[export] failed:", e); }
    await _doDeletePreset(deleteTargetId.value);
}

async function confirmDeleteDirect() {
    deleteDataLoading.value = true;
    await _doDeletePreset(deleteTargetId.value);
}

async function _doDeletePreset(id: string) {
    try {
        await fetch(`http://localhost:18000/api/character/${id}/data`, { method: "DELETE" });
    } catch (e) { console.warn("[delete data] failed:", e); }

    presets.value = presets.value.filter(p => p.id !== id);
    if (activePreset.value?.id === id) loadPresetToForm(presets.value[0]);

    const newActiveId = props.activePresetId === id
        ? (presets.value[0]?.id ?? "")
        : props.activePresetId;
    if (props.activePresetId === id) {
        localStorage.setItem("rl-active-preset-id", newActiveId);
    }

    savePresets();
    showDeleteDialog.value  = false;
    deleteDataLoading.value = false;
    showMsg(`「${deleteTargetName.value}」及其所有数据已删除`);
    emit("deleted", newActiveId);
}

// ── 笔记本入口 ─────────────────────────────────────────────────
const notebookCharName = computed(() => {
    const p = presets.value.find(p => p.id === props.activePresetId);
    return p?.name ?? "角色";
});

function openNotebook() {
    emit("open-notebook", props.activePresetId, notebookCharName.value);
}

// ── 初始化 ─────────────────────────────────────────────────────
onMounted(() => {
    const savedPresets = localStorage.getItem("rl-presets");
    presets.value = savedPresets
        ? ensureDefaultFirst(JSON.parse(savedPresets))
        : [{ ...DEFAULT_PRESET }];

    const savedChar = localStorage.getItem("rl-character");
    if (savedChar) {
        const d     = JSON.parse(savedChar);
        const match = presets.value.find(p => p.name === d.name);
        loadPresetToForm(match ?? presets.value[0]);
    } else {
        loadPresetToForm(presets.value[0]);
    }
});
</script>

<template>
    <div class="tab-content">

        <!-- Toast -->
        <transition name="toast">
            <div v-if="msgText" class="toast" :class="{ warn: msgType === 'warn' }">{{ msgText }}</div>
        </transition>

        <!-- 预设列表 -->
        <div class="presets-section">
            <div class="presets-header">
                <span class="section-label">角色预设 <span class="field-note">{{ presets.length }}/{{ MAX_PRESETS }}</span></span>
                <button class="add-preset-btn" @click="newPreset" :disabled="presets.length >= MAX_PRESETS">+ 新建</button>
            </div>
            <div class="presets-list">
                <div v-for="p in presets" :key="p.id"
                     class="preset-card"
                     :class="{ editing: activePreset?.id === p.id, running: activePresetId === p.id }"
                     @click="loadPresetToForm(p)">
                    <div class="preset-avatar">
                        <img :src="p.avatar || defaultAvatar" alt="" />
                        <div v-if="activePresetId === p.id" class="running-badge">生效中</div>
                    </div>
                    <div class="preset-info">
                        <div class="preset-name">{{ p.name }}</div>
                        <div class="preset-desc">{{ p.description || "暂无简介" }}</div>
                    </div>
                    <div class="preset-actions">
                        <button class="preset-activate-btn" @click.stop="activatePreset(p)" title="激活使用">▶</button>
                        <button class="preset-delete-btn"   @click.stop="requestDeletePreset(p.id)"
                                :disabled="p.id === 'default-rei'" title="删除">×</button>
                    </div>
                </div>
            </div>
        </div>

        <div class="divider"></div>

        <!-- 笔记本入口 + 表单标题 -->
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;">
            <div class="form-section-label" style="margin-bottom:0;">
                {{ activePreset ? `编辑：${activePreset.name}` : "新建角色预设" }}
            </div>
            <button class="save-btn" style="padding:6px 14px;font-size:12px;" @click="openNotebook">
                📓 {{ notebookCharName }}的笔记本
            </button>
        </div>

        <!-- 头像 -->
        <div class="avatar-upload-row">
            <div class="avatar-preview" @click="triggerAvatarUpload">
                <img :src="character.avatar || defaultAvatar" alt="头像" />
                <div class="avatar-overlay">更换</div>
            </div>
            <input ref="avatarInputRef" type="file" accept="image/*" style="display:none" @change="onAvatarChange" />
            <div class="avatar-hint">点击更换头像<br /><span class="field-note">支持 JPG / PNG，建议正方形</span></div>
        </div>

        <!-- 基本信息 -->
        <div class="field-row">
            <div class="field-group half">
                <label class="field-label">角色名字 <span class="required">*</span></label>
                <input class="field-input" v-model="character.name" placeholder="例如：Rei" />
            </div>
            <div class="field-group half">
                <label class="field-label">称呼用户为 <span class="required">*</span></label>
                <input class="field-input" v-model="character.address" placeholder="例如：你" />
            </div>
        </div>
        <div class="field-group">
            <label class="field-label">角色身份 <span class="required">*</span></label>
            <input class="field-input" v-model="character.identity" placeholder="例如：你身边的猫娘伙伴，平时住在一起" />
        </div>
        <div class="field-group">
            <label class="field-label">核心性格 <span class="required">*</span></label>
            <input class="field-input" v-model="character.personality" placeholder="例如：傲娇，表面高冷，实际很在意用户" />
        </div>
        <div class="field-group">
            <label class="field-label">说话风格 <span class="required">*</span></label>
            <input class="field-input" v-model="character.style" placeholder="例如：简短干脆，偶尔别扭地关心" />
        </div>

        <!-- 对话示例 -->
        <div class="field-group">
            <div class="examples-header">
                <label class="field-label">对话示例 <span class="field-note">选填 · 最多3组</span></label>
                <button v-if="character.examples.length < 3" class="add-example-btn" @click="addExample">+ 添加</button>
            </div>
            <div v-for="(ex, i) in character.examples" :key="i" class="example-card">
                <div class="example-label">示例 {{ i + 1 }}</div>
                <div class="example-fields">
                    <input class="field-input example-input" v-model="ex.user" placeholder="用户说…" />
                    <input class="field-input example-input" v-model="ex.char" :placeholder="`${character.name || '角色'}回…`" />
                </div>
                <button class="remove-example-btn" @click="removeExample(i)">×</button>
            </div>
        </div>

        <div class="action-row">
            <button class="save-btn" @click="openSaveDialog">保存预设</button>
        </div>

        <!-- 保存确认弹框 -->
        <transition name="dialog">
            <div v-if="showSaveDialog" class="dialog-overlay" @click.self="showSaveDialog = false">
                <div class="dialog-box">
                    <div class="dialog-title">保存角色预设</div>
                    <div class="dialog-body">
                        <label class="field-label">一句话简介 <span class="field-note">选填</span></label>
                        <input class="field-input" v-model="saveDialogDesc"
                               placeholder="例如：傲娇猫娘，Reverie Link 默认角色" maxlength="30" />
                    </div>
                    <div class="dialog-actions">
                        <button class="dialog-cancel"  @click="showSaveDialog = false">取消</button>
                        <button class="dialog-confirm" @click="confirmSave">确认保存</button>
                    </div>
                </div>
            </div>
        </transition>

        <!-- 删除确认弹框 -->
        <DeleteCharDialog
            :visible="showDeleteDialog"
            :target-name="deleteTargetName"
            :loading="deleteDataLoading"
            @confirm-export="confirmDeleteWithExport"
            @confirm-direct="confirmDeleteDirect"
            @cancel="showDeleteDialog = false"
        />
    </div>
</template>

<style scoped>
/* toast */
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

/* 预设列表 */
.presets-section { display: flex; flex-direction: column; gap: 8px; }
.presets-header  { display: flex; align-items: center; justify-content: space-between; }
.section-label   { font-size: 12px; font-weight: 600; color: var(--c-text); }
.add-preset-btn {
    font-size: 12px; padding: 3px 12px;
    border: 1.5px solid var(--c-blue); border-radius: 20px;
    background: transparent; color: var(--c-blue);
    cursor: pointer; font-family: inherit;
    transition: background 0.2s, color 0.2s;
}
.add-preset-btn:hover:not(:disabled) { background: var(--c-blue); color: white; }
.add-preset-btn:disabled { opacity: 0.4; cursor: not-allowed; }

.presets-list { display: flex; flex-direction: column; gap: 8px; }
.preset-card {
    display: flex; align-items: center; gap: 10px;
    background: var(--c-surface); border: 1.5px solid var(--c-border);
    border-radius: 12px; padding: 10px 12px;
    cursor: pointer; transition: border-color 0.2s, box-shadow 0.2s;
}
.preset-card:hover   { border-color: var(--c-pink-mid); }
.preset-card.editing { border-color: var(--c-lavender); box-shadow: 0 0 0 3px var(--c-pink-light); }
.preset-card.running { border-color: var(--c-blue);     box-shadow: 0 0 0 3px var(--c-blue-light); }
.preset-card.editing.running { border-color: var(--c-blue); box-shadow: 0 0 0 3px var(--c-blue-light); }

.preset-avatar {
    position: relative; width: 44px; height: 44px;
    border-radius: 50%; overflow: hidden;
    border: 2px solid var(--c-border); background: var(--c-pink-light); flex-shrink: 0;
}
.preset-avatar img { width: 100%; height: 100%; object-fit: cover; }
.running-badge {
    position: absolute; bottom: 0; right: -2px;
    background: var(--c-blue); color: white;
    font-size: 10px; font-weight: 600;
    padding: 2px 6px; border-radius: 8px;
    white-space: nowrap; border: 1.5px solid white;
    box-shadow: 0 1px 4px rgba(0,0,0,0.15);
}

.preset-info   { flex: 1; min-width: 0; }
.preset-name   { font-size: 13px; font-weight: 600; color: var(--c-text); }
.preset-desc   { font-size: 11px; color: var(--c-text-soft); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.preset-actions { display: flex; gap: 4px; flex-shrink: 0; }

.preset-activate-btn, .preset-delete-btn {
    width: 26px; height: 26px; border-radius: 50%; border: none;
    cursor: pointer; font-size: 12px;
    display: flex; align-items: center; justify-content: center;
    transition: background 0.2s;
}
.preset-activate-btn { background: var(--c-blue-light); color: var(--c-blue); }
.preset-activate-btn:hover { background: var(--c-blue); color: white; }
.preset-delete-btn { background: var(--c-pink-light); color: var(--c-pink-mid); }
.preset-delete-btn:hover:not(:disabled) { background: var(--c-pink-mid); color: white; }
.preset-delete-btn:disabled { opacity: 0.3; cursor: not-allowed; }

/* 表单 */
.form-section-label { font-size: 12px; font-weight: 600; color: var(--c-text-soft); padding-left: 2px; }
.avatar-upload-row  { display: flex; align-items: center; gap: 14px; }
.avatar-preview {
    position: relative; width: 56px; height: 56px;
    border-radius: 50%; overflow: hidden;
    border: 2px solid var(--c-border); cursor: pointer;
    background: var(--c-pink-light); flex-shrink: 0;
}
.avatar-preview img   { width: 100%; height: 100%; object-fit: cover; }
.avatar-overlay {
    position: absolute; inset: 0;
    background: rgba(0,0,0,0.35); color: white;
    font-size: 11px; display: flex; align-items: center; justify-content: center;
    opacity: 0; transition: opacity 0.2s;
}
.avatar-preview:hover .avatar-overlay { opacity: 1; }
.avatar-hint { font-size: 12px; color: var(--c-text); line-height: 1.7; }

/* 示例 */
.examples-header { display: flex; align-items: center; justify-content: space-between; }
.add-example-btn {
    font-size: 12px; padding: 3px 10px;
    border: 1.5px solid var(--c-mint); border-radius: 20px;
    background: transparent; color: #5BAD8F; cursor: pointer; font-family: inherit;
}
.add-example-btn:hover { background: var(--c-mint); }
.example-card {
    position: relative;
    background: var(--c-surface); border: 1.5px solid var(--c-border);
    border-radius: 12px; padding: 10px 36px 10px 12px;
    display: flex; flex-direction: column; gap: 6px;
}
.example-label  { font-size: 11px; color: var(--c-text-soft); font-weight: 600; }
.example-fields { display: flex; flex-direction: column; gap: 6px; }
.example-input  { font-size: 12px; }
.remove-example-btn {
    position: absolute; top: 8px; right: 8px;
    width: 20px; height: 20px; border: none; border-radius: 50%;
    background: var(--c-pink-light); color: var(--c-pink-mid);
    cursor: pointer; font-size: 13px;
    display: flex; align-items: center; justify-content: center;
}
.remove-example-btn:hover { background: var(--c-pink); color: white; }
</style>