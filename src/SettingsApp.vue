<script setup lang="ts">
    import { ref, reactive, onMounted, computed } from "vue";
    import { openUrl } from "@tauri-apps/plugin-opener";

    // ── 类型定义 ───────────────────────────────────────────────────
    interface CharacterPreset {
        id: string;
        name: string;
        description: string;
        identity: string;
        personality: string;
        address: string;
        style: string;
        avatar: string;
        examples: { user: string; char: string }[];
    }

    // ── 默认头像 ───────────────────────────────────────────────────
    const DEFAULT_AVATAR = ref("");

    // ── 当前生效的预设 ID（激活≠编辑） ───────────────────────────
    const activePresetId = ref<string>("");

    // ── 默认预设 ───────────────────────────────────────────────────
    const DEFAULT_PRESET: CharacterPreset = {
        id: "default-rei",
        name: "Rei",
        description: "傲娇猫娘，Reverie Link 默认角色",
        identity: "你是用户身边的猫娘伙伴，平时住在一起",
        personality: "傲娇，表面高冷不在乎，实际上很在意用户，被关心时会别扭地否认，偶尔情绪激动时会不自觉说出一个「喵」",
        address: "你",
        style: "简短干脆，傲娇别扭，不会主动示好但会用绕弯子的方式表达关心，被夸会立刻否认，偶尔一个字的「喵」，绝对不叠用",
        avatar: "",
        examples: [
            { user: "今天辛苦了", char: "哼，谁要你说这种话。……自己注意点身体就行了。" },
            { user: "你在担心我吗？", char: "想什么呢。只是觉得你这样下去会给我添麻烦而已。" },
            { user: "你真可爱", char: "……闭嘴。说什么蠢话。喵。" },
        ],
    };

    const MAX_PRESETS = 10;

    // ── 厂商预设 ───────────────────────────────────────────────────
    const VENDORS = [
        { name: "DeepSeek", base_url: "https://api.deepseek.com", model: "deepseek-chat", website: "https://platform.deepseek.com", editable: false, needKey: true },
        { name: "OpenAI", base_url: "https://api.openai.com/v1", model: "gpt-4o-mini", website: "https://platform.openai.com", editable: false, needKey: true },
        { name: "千问（阿里云）", base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1", model: "qwen-max", website: "https://bailian.console.aliyun.com", editable: false, needKey: true },
        { name: "豆包（火山引擎）", base_url: "https://ark.cn-beijing.volces.com/api/v3", model: "doubao-pro-32k", website: "https://console.volcengine.com/ark", editable: false, needKey: true },
        { name: "硅基流动", base_url: "https://api.siliconflow.cn/v1", model: "deepseek-ai/DeepSeek-V3", website: "https://cloud.siliconflow.cn", editable: false, needKey: true },
        { name: "Gemini（Google）", base_url: "https://generativelanguage.googleapis.com/v1beta/openai/", model: "gemini-2.0-flash", website: "https://aistudio.google.com", editable: false, needKey: true },
        { name: "OpenRouter", base_url: "https://openrouter.ai/api/v1", model: "openai/gpt-4o-mini", website: "https://openrouter.ai", editable: false, needKey: true },
        { name: "MiniMax", base_url: "https://api.minimaxi.com/v1", model: "MiniMax-M2", website: "https://platform.minimaxi.com", editable: false, needKey: true },
        { name: "月之暗面（Kimi）", base_url: "https://api.moonshot.cn/v1", model: "moonshot-v1-8k", website: "https://platform.moonshot.cn", editable: false, needKey: true },
        { name: "智谱AI", base_url: "https://open.bigmodel.cn/api/paas/v4/", model: "glm-4-flash", website: "https://open.bigmodel.cn", editable: false, needKey: true },
        { name: "腾讯混元", base_url: "https://api.hunyuan.cloud.tencent.com/v1", model: "hunyuan-turbo", website: "https://cloud.tencent.com/product/hunyuan", editable: false, needKey: true },
        { name: "百川AI", base_url: "https://api.baichuan-ai.com/v1", model: "Baichuan4", website: "https://platform.baichuan-ai.com", editable: false, needKey: true },
        { name: "启航AI", base_url: "https://api.qhaigc.net/v1", model: "gpt-4o", website: "https://www.qhaigc.net", editable: false, needKey: true },
        { name: "Ollama（本地）", base_url: "http://localhost:11434/v1", model: "llama3", website: "https://ollama.com", editable: true, needKey: false },
        { name: "自定义", base_url: "", model: "", website: "", editable: true, needKey: true },
    ];

    // ── Tab 状态 ───────────────────────────────────────────────────
    const activeTab = ref<"llm" | "character">("llm");

    // ── API Key 字典 ───────────────────────────────────────────────
    const apiKeys = reactive<Record<string, string>>({});

    // ── LLM 配置 ───────────────────────────────────────────────────
    const llm = reactive({
        vendor: "DeepSeek",
        base_url: "https://api.deepseek.com",
        model: "deepseek-chat",
        editable: false,
        needKey: true,
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
            llm.model = preset.model;
            llm.editable = preset.editable;
            llm.needKey = preset.needKey;
        }
    }

    async function openWebsite() {
        if (currentVendorWebsite.value) await openUrl(currentVendorWebsite.value);
    }

    // ── 角色预设列表 ───────────────────────────────────────────────
    const presets = ref<CharacterPreset[]>([]);
    const activePreset = ref<CharacterPreset | null>(null);  // 当前编辑的预设

    // ── 确保默认预设始终在第一位 ──────────────────────────────────
    function ensureDefaultFirst(list: CharacterPreset[]): CharacterPreset[] {
        const withoutDefault = list.filter(p => p.id !== "default-rei");
        const hasDefault = list.find(p => p.id === "default-rei");
        const defaultPreset = hasDefault ?? { ...DEFAULT_PRESET };
        return [defaultPreset, ...withoutDefault];
    }

    // ── 当前编辑的角色表单 ─────────────────────────────────────────
    const character = reactive<Omit<CharacterPreset, "id">>({
        name: "",
        description: "",
        identity: "",
        personality: "",
        address: "",
        style: "",
        avatar: "",
        examples: [{ user: "", char: "" }],
    });

    function loadPresetToForm(preset: CharacterPreset) {
        activePreset.value = preset;
        character.name = preset.name;
        character.description = preset.description;
        character.identity = preset.identity;
        character.personality = preset.personality;
        character.address = preset.address;
        character.style = preset.style;
        character.avatar = preset.avatar;
        character.examples = preset.examples.length
            ? preset.examples.map(e => ({ ...e }))
            : [{ user: "", char: "" }];
    }

    function newPreset() {
        activePreset.value = null;
        character.name = "";
        character.description = "";
        character.identity = "";
        character.personality = "";
        character.address = "";
        character.style = "";
        character.avatar = "";
        character.examples = [{ user: "", char: "" }];
    }

    function addExample() {
        if (character.examples.length < 3) character.examples.push({ user: "", char: "" });
    }
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

    // ── 保存确认弹框 ───────────────────────────────────────────────
    const showSaveDialog = ref(false);
    const saveDialogDesc = ref("");

    function openSaveDialog() {
        if (!character.name.trim()) { showMsg("请先填写角色名字", "warn"); return; }
        saveDialogDesc.value = character.description;
        showSaveDialog.value = true;
    }

    function confirmSave() {
        character.description = saveDialogDesc.value.trim();
        showSaveDialog.value = false;

        const examples = character.examples.filter(e => e.user.trim() && e.char.trim());

        if (activePreset.value) {
            // 更新已有预设
            const idx = presets.value.findIndex(p => p.id === activePreset.value!.id);
            if (idx !== -1) {
                presets.value[idx] = { ...activePreset.value, ...character, examples };
                activePreset.value = presets.value[idx];
            }
        } else {
            // 新增预设
            if (presets.value.length >= MAX_PRESETS) {
                showMsg(`最多保存 ${MAX_PRESETS} 个角色预设`, "warn"); return;
            }
            const newP: CharacterPreset = {
                id: `preset-${Date.now()}`,
                ...character,
                examples,
            };
            presets.value.push(newP);
            activePreset.value = newP;
        }

        // 保持默认在第一位
        presets.value = ensureDefaultFirst(presets.value);
        savePresets();
        showMsg("✓ 预设已保存");
    }

    function deletePreset(id: string) {
        if (id === "default-rei") { showMsg("默认预设不可删除", "warn"); return; }
        presets.value = presets.value.filter(p => p.id !== id);
        // 如果删除的是当前编辑的预设，切回第一个
        if (activePreset.value?.id === id) {
            loadPresetToForm(presets.value[0]);
        }
        // 如果删除的是生效中的预设，生效标识清空
        if (activePresetId.value === id) {
            activePresetId.value = "";
        }
        savePresets();
        showMsg("已删除");
    }

    // ── 激活预设（发送到后端）─────────────────────────────────────
    function activatePreset(preset: CharacterPreset) {
        activePresetId.value = preset.id;
        loadPresetToForm(preset);
        const llmCfg = JSON.parse(localStorage.getItem("rl-llm") || "{}");
        const charCfg = {
            name: preset.name,
            identity: preset.identity,
            personality: preset.personality,
            address: preset.address,
            style: preset.style,
            examples: preset.examples,
        };
        localStorage.setItem("rl-character", JSON.stringify(charCfg));
        // 保存生效中的预设 ID
        localStorage.setItem("rl-active-preset-id", preset.id);
        sendConfigToBackend(llmCfg, charCfg);
        showMsg(`✓ 已切换到「${preset.name}」`);
    }

    // ── 持久化 ─────────────────────────────────────────────────────
    function savePresets() {
        localStorage.setItem("rl-presets", JSON.stringify(presets.value));
    }

    // ── 保存 LLM 配置 ──────────────────────────────────────────────
    function saveLLM() {
        localStorage.setItem("rl-api-keys", JSON.stringify(apiKeys));
        const cfg = {
            vendor: llm.vendor,
            base_url: llm.base_url,
            model: llm.model,
            api_key: apiKeys[llm.vendor] ?? "",
        };
        localStorage.setItem("rl-llm", JSON.stringify(cfg));
        const charCfg = JSON.parse(localStorage.getItem("rl-character") || "{}");
        sendConfigToBackend(cfg, charCfg);
        showMsg("✓ LLM 配置已保存");
    }

    // ── 发送配置到后端 ─────────────────────────────────────────────
    function sendConfigToBackend(llmCfg: object, charCfg: object) {
        try {
            const ws = new WebSocket("ws://localhost:18000/ws/chat");
            ws.onopen = () => {
                ws.send(JSON.stringify({ type: "configure", llm: llmCfg, character: charCfg }));
                ws.close();
            };
        } catch { }
    }

    // ── 消息提示 ───────────────────────────────────────────────────
    const msgText = ref("");
    const msgType = ref<"ok" | "warn">("ok");

    function showMsg(text: string, type: "ok" | "warn" = "ok") {
        msgText.value = text;
        msgType.value = type;
        setTimeout(() => { msgText.value = ""; }, 2500);
    }

    // ── 初始化 ─────────────────────────────────────────────────────
    onMounted(async () => {
        // 加载默认头像
        try {
            const resp = await fetch("/avatar.png");
            const blob = await resp.blob();
            const reader = new FileReader();
            reader.onload = () => { DEFAULT_AVATAR.value = reader.result as string; };
            reader.readAsDataURL(blob);
        } catch { }

        // 加载 Key 字典
        const savedKeys = localStorage.getItem("rl-api-keys");
        if (savedKeys) Object.assign(apiKeys, JSON.parse(savedKeys));

        // 加载 LLM 配置
        const savedLLM = localStorage.getItem("rl-llm");
        if (savedLLM) {
            const d = JSON.parse(savedLLM);
            llm.vendor = d.vendor ?? "DeepSeek";
            llm.base_url = d.base_url ?? llm.base_url;
            llm.model = d.model ?? llm.model;
            const preset = VENDORS.find(v => v.name === llm.vendor);
            llm.editable = preset?.editable ?? true;
            llm.needKey = preset?.needKey ?? true;
        }

        // 加载预设列表，确保默认预设始终在第一位
        const savedPresets = localStorage.getItem("rl-presets");
        if (savedPresets) {
            presets.value = ensureDefaultFirst(JSON.parse(savedPresets));
        } else {
            presets.value = [{ ...DEFAULT_PRESET }];
        }

        // 恢复生效中的预设 ID
        const savedActiveId = localStorage.getItem("rl-active-preset-id");
        if (savedActiveId && presets.value.find(p => p.id === savedActiveId)) {
            activePresetId.value = savedActiveId;
        } else {
            // 默认生效第一个（Rei）
            activePresetId.value = presets.value[0].id;
            localStorage.setItem("rl-active-preset-id", presets.value[0].id);
        }

        // 加载上次编辑的角色到表单
        const savedChar = localStorage.getItem("rl-character");
        if (savedChar) {
            const d = JSON.parse(savedChar);
            const match = presets.value.find(p => p.name === d.name);
            loadPresetToForm(match ?? presets.value[0]);
        } else {
            loadPresetToForm(presets.value[0]);
        }
    });
</script>

<template>
    <div class="settings-root">

        <!-- Toast 通知 -->
        <transition name="toast">
            <div v-if="msgText" class="toast" :class="{ warn: msgType === 'warn' }">
                {{ msgText }}
            </div>
        </transition>

        <!-- 顶部标题栏 -->
        <div class="header">
            <div class="header-icon">✦</div>
            <div class="header-title">Reverie Link 设置</div>
            <div class="header-sub">配置你的专属数字伴侣</div>
        </div>

        <!-- Tab 切换 -->
        <div class="tabs">
            <button class="tab-btn" :class="{ active: activeTab === 'llm' }" @click="activeTab = 'llm'">
                <span class="tab-icon">🤖</span> AI 模型
            </button>
            <button class="tab-btn" :class="{ active: activeTab === 'character' }" @click="activeTab = 'character'">
                <span class="tab-icon">🌸</span> 角色设定
            </button>
        </div>

        <!-- 内容区 -->
        <div class="content">

            <!-- ── LLM Tab ── -->
            <div v-if="activeTab === 'llm'" class="tab-content">
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
                    <input class="field-input" v-model="currentKey" type="password"
                           placeholder="sk-xxxxxxxxxxxxxxxx" />
                    <p class="field-hint">密钥仅保存在本地，不会上传到任何服务器。</p>
                </div>
                <div class="field-group">
                    <label class="field-label">模型名称</label>
                    <input class="field-input" v-model="llm.model" placeholder="例如：deepseek-chat" />
                </div>
                <div class="action-row">
                    <button class="save-btn" @click="saveLLM">保存配置</button>
                </div>
            </div>

            <!-- ── 角色设定 Tab ── -->
            <div v-if="activeTab === 'character'" class="tab-content">

                <!-- 预设卡片列表 -->
                <div class="presets-section">
                    <div class="presets-header">
                        <span class="section-label">
                            角色预设 <span class="field-note">{{ presets.length }}/{{ MAX_PRESETS }}</span>
                        </span>
                        <button class="add-preset-btn" @click="newPreset"
                                :disabled="presets.length >= MAX_PRESETS">
                            + 新建
                        </button>
                    </div>
                    <div class="presets-list">
                        <div v-for="p in presets" :key="p.id"
                             class="preset-card"
                             :class="{
                                editing: activePreset?.id === p.id,
                                running: activePresetId === p.id
                             }"
                             @click="loadPresetToForm(p)">
                            <div class="preset-avatar">
                                <img :src="p.avatar || DEFAULT_AVATAR" alt="" />
                                <div v-if="activePresetId === p.id" class="running-badge">生效中</div>
                            </div>
                            <div class="preset-info">
                                <div class="preset-name">{{ p.name }}</div>
                                <div class="preset-desc">{{ p.description || "暂无简介" }}</div>
                            </div>
                            <div class="preset-actions">
                                <button class="preset-activate-btn" @click.stop="activatePreset(p)" title="激活使用">▶</button>
                                <button class="preset-delete-btn" @click.stop="deletePreset(p.id)"
                                        :disabled="p.id === 'default-rei'" title="删除">
                                    ×
                                </button>
                            </div>
                        </div>
                    </div>
                </div>

                <div class="divider"></div>

                <!-- 编辑表单标题 -->
                <div class="form-section-label">
                    {{ activePreset ? `编辑：${activePreset.name}` : "新建角色预设" }}
                </div>

                <!-- 头像上传 -->
                <div class="avatar-upload-row">
                    <div class="avatar-preview" @click="triggerAvatarUpload">
                        <img :src="character.avatar || DEFAULT_AVATAR" alt="头像" />
                        <div class="avatar-overlay">更换</div>
                    </div>
                    <input ref="avatarInputRef" type="file" accept="image/*"
                           style="display:none" @change="onAvatarChange" />
                    <div class="avatar-hint">
                        点击更换头像<br />
                        <span class="field-note">支持 JPG / PNG，建议正方形</span>
                    </div>
                </div>

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
                        <label class="field-label">
                            对话示例 <span class="field-note">选填 · 最多3组</span>
                        </label>
                        <button v-if="character.examples.length < 3" class="add-example-btn" @click="addExample">
                            + 添加
                        </button>
                    </div>
                    <div v-for="(ex, i) in character.examples" :key="i" class="example-card">
                        <div class="example-label">示例 {{ i + 1 }}</div>
                        <div class="example-fields">
                            <input class="field-input example-input" v-model="ex.user" placeholder="用户说…" />
                            <input class="field-input example-input" v-model="ex.char"
                                   :placeholder="`${character.name || '角色'}回…`" />
                        </div>
                        <button class="remove-example-btn" @click="removeExample(i)">×</button>
                    </div>
                </div>

                <div class="action-row">
                    <button class="save-btn" @click="openSaveDialog">保存预设</button>
                </div>

            </div>
        </div>

        <!-- 保存确认弹框 -->
        <transition name="dialog">
            <div v-if="showSaveDialog" class="dialog-overlay" @click.self="showSaveDialog = false">
                <div class="dialog-box">
                    <div class="dialog-title">保存角色预设</div>
                    <div class="dialog-body">
                        <label class="field-label">
                            一句话简介 <span class="field-note">选填，显示在卡片上</span>
                        </label>
                        <input class="field-input" v-model="saveDialogDesc"
                               placeholder="例如：傲娇猫娘，Reverie Link 默认角色" maxlength="30" />
                    </div>
                    <div class="dialog-actions">
                        <button class="dialog-cancel" @click="showSaveDialog = false">取消</button>
                        <button class="dialog-confirm" @click="confirmSave">确认保存</button>
                    </div>
                </div>
            </div>
        </transition>

    </div>
</template>

<style>
    * {
        margin: 0;
        padding: 0;
        box-sizing: border-box;
    }

    html, body {
        width: 100%;
        height: 100%;
        font-family: "Hiragino Sans GB", "Microsoft YaHei", "PingFang SC", sans-serif;
        -webkit-font-smoothing: antialiased;
        background: #FEF6FA;
    }

    ::-webkit-scrollbar {
        width: 6px;
    }

    ::-webkit-scrollbar-track {
        background: transparent;
    }

    ::-webkit-scrollbar-thumb {
        background: #FFCDD9;
        border-radius: 3px;
    }
</style>

<style scoped>
    /* ── Toast ────────────────────────────────────────────────── */
    .toast {
        position: fixed;
        top: 16px;
        left: 50%;
        transform: translateX(-50%);
        padding: 8px 20px;
        border-radius: 20px;
        background: linear-gradient(135deg, var(--c-blue-mid), var(--c-pink));
        color: white;
        font-size: 13px;
        font-weight: 500;
        box-shadow: 0 4px 16px rgba(126, 87, 194, 0.2);
        z-index: 200;
        pointer-events: none;
        white-space: nowrap;
    }

        .toast.warn {
            background: linear-gradient(135deg, #F0A0A0, #E08080);
        }

    .toast-enter-active {
        transition: opacity 0.25s ease, transform 0.25s ease;
    }

    .toast-leave-active {
        transition: opacity 0.2s ease, transform 0.2s ease;
    }

    .toast-enter-from {
        opacity: 0;
        transform: translateX(-50%) translateY(-10px);
    }

    .toast-leave-to {
        opacity: 0;
        transform: translateX(-50%) translateY(-6px);
    }

    /* ── CSS 变量 & 根容器 ────────────────────────────────────── */
    .settings-root {
        --c-bg: #FEF6FA;
        --c-surface: #FFFFFF;
        --c-blue: #7EC8E3;
        --c-blue-light: #C5E8F4;
        --c-blue-mid: #A8D8EA;
        --c-pink: #FFB7C5;
        --c-pink-light: #FFE4EC;
        --c-pink-mid: #FFAABB;
        --c-mint: #B5EAD7;
        --c-lavender: #D4B8E0;
        --c-text: #4A4A6A;
        --c-text-soft: #9B8FB0;
        --c-border: rgba(212, 184, 224, 0.45);
        --c-shadow: rgba(180, 140, 200, 0.12);
        min-height: 100vh;
        background: var(--c-bg);
        display: flex;
        flex-direction: column;
        overflow: hidden;
    }

    /* ── 顶部 ─────────────────────────────────────────────────── */
    .header {
        background: linear-gradient(135deg, var(--c-blue-mid) 0%, var(--c-pink) 100%);
        padding: 20px 24px 18px;
        display: flex;
        flex-direction: column;
        gap: 3px;
        position: relative;
        overflow: hidden;
        flex-shrink: 0;
    }

        .header::before {
            content: "";
            position: absolute;
            top: -20px;
            right: -20px;
            width: 100px;
            height: 100px;
            border-radius: 50%;
            background: rgba(255,255,255,0.15);
        }

        .header::after {
            content: "";
            position: absolute;
            bottom: -30px;
            left: 40%;
            width: 120px;
            height: 120px;
            border-radius: 50%;
            background: rgba(255,255,255,0.1);
        }

    .header-icon {
        font-size: 11px;
        color: rgba(255,255,255,0.7);
        letter-spacing: 2px;
    }

    .header-title {
        font-size: 18px;
        font-weight: 700;
        color: white;
        text-shadow: 0 1px 4px rgba(0,0,0,0.1);
    }

    .header-sub {
        font-size: 12px;
        color: rgba(255,255,255,0.8);
    }

    /* ── Tab ──────────────────────────────────────────────────── */
    .tabs {
        display: flex;
        padding: 12px 20px 0;
        background: var(--c-surface);
        border-bottom: 1.5px solid var(--c-border);
        flex-shrink: 0;
    }

    .tab-btn {
        flex: 1;
        padding: 9px 12px;
        border: none;
        border-radius: 10px 10px 0 0;
        background: transparent;
        cursor: pointer;
        font-size: 13px;
        font-family: inherit;
        color: var(--c-text-soft);
        font-weight: 500;
        transition: all 0.2s;
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 6px;
    }

        .tab-btn:hover {
            color: var(--c-text);
            background: var(--c-pink-light);
        }

        .tab-btn.active {
            color: var(--c-text);
            font-weight: 700;
            background: linear-gradient(to bottom, var(--c-pink-light), var(--c-bg));
            border-bottom: 2.5px solid var(--c-pink-mid);
        }

    .tab-icon {
        font-size: 15px;
    }

    /* ── 内容区 ───────────────────────────────────────────────── */
    .content {
        flex: 1;
        overflow-y: auto;
        padding: 16px 20px 20px;
        background: var(--c-bg);
    }

    .tab-content {
        display: flex;
        flex-direction: column;
        gap: 14px;
    }

    /* ── 预设列表 ─────────────────────────────────────────────── */
    .presets-section {
        display: flex;
        flex-direction: column;
        gap: 8px;
    }

    .presets-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
    }

    .section-label {
        font-size: 12px;
        font-weight: 600;
        color: var(--c-text);
    }

    .add-preset-btn {
        font-size: 12px;
        padding: 3px 12px;
        border: 1.5px solid var(--c-blue);
        border-radius: 20px;
        background: transparent;
        color: var(--c-blue);
        cursor: pointer;
        font-family: inherit;
        transition: background 0.2s, color 0.2s;
    }

        .add-preset-btn:hover:not(:disabled) {
            background: var(--c-blue);
            color: white;
        }

        .add-preset-btn:disabled {
            opacity: 0.4;
            cursor: not-allowed;
        }

    .presets-list {
        display: flex;
        flex-direction: column;
        gap: 8px;
    }

    .preset-card {
        display: flex;
        align-items: center;
        gap: 10px;
        background: var(--c-surface);
        border: 1.5px solid var(--c-border);
        border-radius: 12px;
        padding: 10px 12px;
        cursor: pointer;
        transition: border-color 0.2s, box-shadow 0.2s;
    }

        .preset-card:hover {
            border-color: var(--c-pink-mid);
        }

        .preset-card.editing {
            border-color: var(--c-lavender);
            box-shadow: 0 0 0 3px var(--c-pink-light);
        }

        .preset-card.running {
            border-color: var(--c-blue);
            box-shadow: 0 0 0 3px var(--c-blue-light);
        }

        /* 同时编辑且生效时，蓝色优先 */
        .preset-card.editing.running {
            border-color: var(--c-blue);
            box-shadow: 0 0 0 3px var(--c-blue-light);
        }

    .preset-avatar {
        position: relative; /* 让 running-badge 可以绝对定位 */
        width: 44px;
        height: 44px;
        border-radius: 50%;
        overflow: hidden;
        border: 2px solid var(--c-border);
        background: var(--c-pink-light);
        flex-shrink: 0;
    }

        .preset-avatar img {
            width: 100%;
            height: 100%;
            object-fit: cover;
        }

    .running-badge {
        position: absolute;
        bottom: 0;
        right: -2px;
        background: var(--c-blue);
        color: white;
        font-size: 10px;
        font-weight: 600;
        padding: 2px 6px;
        border-radius: 8px;
        white-space: nowrap;
        border: 1.5px solid white;
        box-shadow: 0 1px 4px rgba(0,0,0,0.15);
    }

    .preset-info {
        flex: 1;
        min-width: 0;
    }

    .preset-name {
        font-size: 13px;
        font-weight: 600;
        color: var(--c-text);
    }

    .preset-desc {
        font-size: 11px;
        color: var(--c-text-soft);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }

    .preset-actions {
        display: flex;
        gap: 4px;
        flex-shrink: 0;
    }

    .preset-activate-btn,
    .preset-delete-btn {
        width: 26px;
        height: 26px;
        border-radius: 50%;
        border: none;
        cursor: pointer;
        font-size: 12px;
        display: flex;
        align-items: center;
        justify-content: center;
        transition: background 0.2s;
    }

    .preset-activate-btn {
        background: var(--c-blue-light);
        color: var(--c-blue);
    }

        .preset-activate-btn:hover {
            background: var(--c-blue);
            color: white;
        }

    .preset-delete-btn {
        background: var(--c-pink-light);
        color: var(--c-pink-mid);
    }

        .preset-delete-btn:hover:not(:disabled) {
            background: var(--c-pink-mid);
            color: white;
        }

        .preset-delete-btn:disabled {
            opacity: 0.3;
            cursor: not-allowed;
        }

    /* ── 分割线 & 表单标题 ────────────────────────────────────── */
    .divider {
        height: 1px;
        background: var(--c-border);
        margin: 2px 0;
    }

    .form-section-label {
        font-size: 12px;
        font-weight: 600;
        color: var(--c-text-soft);
        padding-left: 2px;
    }

    /* ── 头像上传 ─────────────────────────────────────────────── */
    .avatar-upload-row {
        display: flex;
        align-items: center;
        gap: 14px;
    }

    .avatar-preview {
        position: relative;
        width: 56px;
        height: 56px;
        border-radius: 50%;
        overflow: hidden;
        border: 2px solid var(--c-border);
        cursor: pointer;
        background: var(--c-pink-light);
        flex-shrink: 0;
    }

        .avatar-preview img {
            width: 100%;
            height: 100%;
            object-fit: cover;
        }

    .avatar-overlay {
        position: absolute;
        inset: 0;
        background: rgba(0,0,0,0.35);
        color: white;
        font-size: 11px;
        display: flex;
        align-items: center;
        justify-content: center;
        opacity: 0;
        transition: opacity 0.2s;
    }

    .avatar-preview:hover .avatar-overlay {
        opacity: 1;
    }

    .avatar-hint {
        font-size: 12px;
        color: var(--c-text);
        line-height: 1.7;
    }

    /* ── 表单 ─────────────────────────────────────────────────── */
    .field-row {
        display: flex;
        gap: 12px;
    }

    .field-group {
        display: flex;
        flex-direction: column;
        gap: 5px;
    }

        .field-group.half {
            flex: 1;
        }

    .field-label {
        font-size: 12px;
        font-weight: 600;
        color: var(--c-text);
        display: flex;
        align-items: center;
        gap: 6px;
    }

    .field-note {
        font-size: 11px;
        font-weight: 400;
        color: var(--c-text-soft);
    }

    .required {
        color: var(--c-pink-mid);
    }

    .field-input {
        width: 100%;
        padding: 9px 12px;
        border: 1.5px solid var(--c-border);
        border-radius: 10px;
        background: var(--c-surface);
        font-size: 13px;
        color: var(--c-text);
        font-family: inherit;
        outline: none;
        transition: border-color 0.2s, box-shadow 0.2s;
    }

        .field-input:focus {
            border-color: var(--c-blue);
            box-shadow: 0 0 0 3px var(--c-blue-light);
        }

        .field-input::placeholder {
            color: var(--c-text-soft);
            opacity: 0.7;
        }

    .field-readonly {
        background: rgba(200,190,220,0.12) !important;
        color: var(--c-text-soft);
        cursor: not-allowed;
    }

    .field-hint {
        font-size: 11px;
        color: var(--c-text-soft);
        padding-left: 2px;
    }

    .field-select {
        width: 100%;
        padding: 9px 12px;
        border: 1.5px solid var(--c-border);
        border-radius: 10px;
        background: var(--c-surface);
        font-size: 13px;
        color: var(--c-text);
        font-family: inherit;
        outline: none;
        cursor: pointer;
    }

        .field-select:focus {
            border-color: var(--c-blue);
        }

    .vendor-link {
        display: inline-block;
        font-size: 12px;
        color: var(--c-blue);
        text-decoration: none;
        padding: 4px 0;
        transition: color 0.2s;
    }

        .vendor-link:hover {
            text-decoration: underline;
        }

    /* ── 对话示例 ─────────────────────────────────────────────── */
    .examples-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
    }

    .add-example-btn {
        font-size: 12px;
        padding: 3px 10px;
        border: 1.5px solid var(--c-mint);
        border-radius: 20px;
        background: transparent;
        color: #5BAD8F;
        cursor: pointer;
        font-family: inherit;
    }

        .add-example-btn:hover {
            background: var(--c-mint);
        }

    .example-card {
        position: relative;
        background: var(--c-surface);
        border: 1.5px solid var(--c-border);
        border-radius: 12px;
        padding: 10px 36px 10px 12px;
        display: flex;
        flex-direction: column;
        gap: 6px;
    }

    .example-label {
        font-size: 11px;
        color: var(--c-text-soft);
        font-weight: 600;
    }

    .example-fields {
        display: flex;
        flex-direction: column;
        gap: 6px;
    }

    .example-input {
        font-size: 12px;
    }

    .remove-example-btn {
        position: absolute;
        top: 8px;
        right: 8px;
        width: 20px;
        height: 20px;
        border: none;
        border-radius: 50%;
        background: var(--c-pink-light);
        color: var(--c-pink-mid);
        cursor: pointer;
        font-size: 13px;
        display: flex;
        align-items: center;
        justify-content: center;
    }

        .remove-example-btn:hover {
            background: var(--c-pink);
            color: white;
        }

    /* ── 操作行 ───────────────────────────────────────────────── */
    .action-row {
        display: flex;
        align-items: center;
        justify-content: flex-end;
        gap: 12px;
        padding-top: 4px;
    }

    .save-btn {
        padding: 9px 24px;
        border: none;
        border-radius: 20px;
        background: linear-gradient(135deg, var(--c-blue-mid), var(--c-pink));
        color: white;
        font-size: 13px;
        font-weight: 600;
        font-family: inherit;
        cursor: pointer;
        box-shadow: 0 3px 12px var(--c-shadow);
        transition: opacity 0.2s, transform 0.15s;
    }

        .save-btn:hover {
            opacity: 0.88;
        }

        .save-btn:active {
            transform: scale(0.97);
        }

    /* ── 弹框 ─────────────────────────────────────────────────── */
    .dialog-overlay {
        position: fixed;
        inset: 0;
        background: rgba(100, 80, 120, 0.25);
        backdrop-filter: blur(4px);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 100;
    }

    .dialog-box {
        width: 300px;
        background: var(--c-surface);
        border-radius: 18px;
        padding: 22px 20px 18px;
        box-shadow: 0 8px 32px rgba(126, 87, 194, 0.18);
        display: flex;
        flex-direction: column;
        gap: 14px;
    }

    .dialog-title {
        font-size: 15px;
        font-weight: 700;
        color: var(--c-text);
    }

    .dialog-body {
        display: flex;
        flex-direction: column;
        gap: 8px;
    }

    .dialog-actions {
        display: flex;
        gap: 10px;
        justify-content: flex-end;
    }

    .dialog-cancel {
        padding: 7px 18px;
        border: 1.5px solid var(--c-border);
        border-radius: 20px;
        background: transparent;
        color: var(--c-text-soft);
        font-size: 13px;
        font-family: inherit;
        cursor: pointer;
    }

        .dialog-cancel:hover {
            background: var(--c-pink-light);
        }

    .dialog-confirm {
        padding: 7px 18px;
        border: none;
        border-radius: 20px;
        background: linear-gradient(135deg, var(--c-blue-mid), var(--c-pink));
        color: white;
        font-size: 13px;
        font-weight: 600;
        font-family: inherit;
        cursor: pointer;
    }

        .dialog-confirm:hover {
            opacity: 0.88;
        }

    .dialog-enter-active {
        transition: opacity 0.2s ease;
    }

    .dialog-leave-active {
        transition: opacity 0.15s ease;
    }

    .dialog-enter-from, .dialog-leave-to {
        opacity: 0;
    }
</style>