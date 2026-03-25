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

    interface Live2DModelInfo {
        folder: string;
        display_name: string;
        path: string;
    }

    // ── 默认头像 ───────────────────────────────────────────────────
    const DEFAULT_AVATAR = ref("");

    // ── 当前生效的预设 ID ──────────────────────────────────────────
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
            { user: "今天辛苦了", char: "哼，谁要你说这种话。……自己注意点身体就行了。[sad]" },
            { user: "你在担心我吗？", char: "想什么呢。只是觉得你这样下去会给我添麻烦而已。[angry]" },
            { user: "你真可爱", char: "……闭嘴。说什么蠢话。喵。[shy]" },
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
    const activeTab = ref<"llm" | "character" | "global">("llm");

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

    // ── 全局设置：Live2D 模型管理 ──────────────────────────────────
    const live2dModels = ref<Live2DModelInfo[]>([]);
    const modelsLoading = ref(false);
    const selectedModelPath = ref<string>(
        localStorage.getItem("rl-model-path") ?? "live2d/MO/MO.model3.json"
    );

    // 当前选中模型的 zoom/y 配置
    const MODEL_SETTINGS_KEY = "rl-model-settings";
    const modelZoom = ref<number>(1.7);
    const modelY = ref<number>(-80);

    function loadModelDisplaySettings(path: string) {
        try {
            const all = JSON.parse(localStorage.getItem(MODEL_SETTINGS_KEY) ?? "{}");
            const s = all[path];
            if (s && typeof s.zoom === "number" && typeof s.y === "number") {
                modelZoom.value = s.zoom;
                modelY.value = s.y;
                return;
            }
        } catch { /* ignore */ }
        modelZoom.value = 1.7;
        modelY.value = -80;
    }

    function saveModelDisplaySettings() {
        const path = selectedModelPath.value;
        try {
            const all = JSON.parse(localStorage.getItem(MODEL_SETTINGS_KEY) ?? "{}");
            all[path] = { zoom: modelZoom.value, y: modelY.value };
            localStorage.setItem(MODEL_SETTINGS_KEY, JSON.stringify(all));
        } catch { /* ignore */ }
    }

    async function fetchLive2DModels() {
        modelsLoading.value = true;
        try {
            const res = await fetch("http://localhost:18000/api/live2d/models");
            const data = await res.json();
            live2dModels.value = data.models ?? [];
        } catch {
            live2dModels.value = [];
            showMsg("无法连接后端，请确认 Python 服务已启动", "warn");
        } finally {
            modelsLoading.value = false;
        }
    }

    async function applyModel(path: string) {
        selectedModelPath.value = path;
        localStorage.setItem("rl-model-path", path);
        loadModelDisplaySettings(path);
        // 通知主窗口（App.vue）切换模型
        try {
            const { emit } = await import("@tauri-apps/api/event");
            await emit("model-changed", { path });
        } catch (e) {
            console.warn("[model switch] emit failed:", e);
        }
        showMsg("✓ 模型已切换");
    }

    async function applyModelSettings() {
        saveModelDisplaySettings();
        // 通知主窗口重新应用缩放设置（用 model-changed 复用现有事件）
        try {
            const { emit } = await import("@tauri-apps/api/event");
            await emit("model-changed", { path: selectedModelPath.value });
        } catch (e) {
            console.warn("[model settings] emit failed:", e);
        }
        showMsg("✓ 显示设置已应用");
    }

    // ── 全局设置：窗口尺寸档位 ────────────────────────────────────
    const SIZE_OPTIONS = [
        { value: "small", label: "小", desc: "200 × 270" },
        { value: "medium", label: "中（默认）", desc: "280 × 380" },
        { value: "large", label: "大", desc: "380 × 510" },
    ];
    const sizePreset = ref<string>(localStorage.getItem("rl-size") ?? "medium");

    function applySize(preset: string) {
        sizePreset.value = preset;
        localStorage.setItem("rl-size", preset);
        showMsg("✓ 尺寸已保存，重启后生效");
    }

    // ── Phase 3: 视觉感知配置 ─────────────────────────────────────
    const VISION_TALK_OPTIONS = [
        { value: 0, label: "话少",        desc: "阈值 30，安静" },
        { value: 1, label: "适中（默认）", desc: "阈值 20，平衡" },
        { value: 2, label: "话多",        desc: "阈值 12，活跃" },
    ];

    function _loadVisionCfg() {
        try { return JSON.parse(localStorage.getItem("rl-vision") || "{}"); } catch { return {}; }
    }
    const _vc = _loadVisionCfg();

    const visionEnabled      = ref<boolean>(!!_vc.enabled);
    const visionVlmBaseUrl   = ref<string>(_vc.vlm_base_url   ?? "https://open.bigmodel.cn/api/paas/v4/");
    const visionVlmApiKey    = ref<string>(_vc.vlm_api_key    ?? "");
    const visionVlmModel     = ref<string>(_vc.vlm_model      ?? "glm-4v-flash");
    const visionTalkLevel    = ref<number>(_vc.talk_level      ?? 1);
    const visionCooldown     = ref<number>(_vc.cooldown_seconds ?? 20);
    const visionManualGameMode = ref<boolean>(!!_vc.manual_game_mode);

    async function saveVision() {
        const cfg = {
            enabled:          visionEnabled.value,
            vlm_base_url:     visionVlmBaseUrl.value.trim(),
            vlm_api_key:      visionVlmApiKey.value.trim(),
            vlm_model:        visionVlmModel.value.trim() || "glm-4v-flash",
            talk_level:       visionTalkLevel.value,
            cooldown_seconds: visionCooldown.value,
            manual_game_mode: visionManualGameMode.value,
        };
        localStorage.setItem("rl-vision", JSON.stringify(cfg));
        const llmCfg  = JSON.parse(localStorage.getItem("rl-llm")      || "{}");
        const charCfg = JSON.parse(localStorage.getItem("rl-character") || "{}");
        await sendConfigToBackend(llmCfg, charCfg, { vision: cfg });
        showMsg("✓ 视觉感知配置已保存");
    }

    // ── 全局设置：记忆窗口档位 ────────────────────────────────────
    const MEMORY_WINDOW_OPTIONS = [
        { index: 0, label: "极速省流",    desc: "3分钟 / 5轮",  token: "~2,000 tokens",  warn: false },
        { index: 1, label: "均衡（默认）", desc: "8分钟 / 12轮", token: "~5,000 tokens",  warn: false },
        { index: 2, label: "沉浸",        desc: "15分钟 / 20轮", token: "~8,000 tokens",  warn: false },
        { index: 3, label: "深度",        desc: "20分钟 / 28轮", token: "~11,000 tokens", warn: true  },
        { index: 4, label: "极限",        desc: "25分钟 / 35轮", token: "~14,000 tokens", warn: true  },
    ];
    const memoryWindowIndex = ref<number>(
        parseInt(localStorage.getItem("rl-memory-window") ?? "1", 10)
    );
 
    async function applyMemoryWindow(index: number) {
        memoryWindowIndex.value = index;
        localStorage.setItem("rl-memory-window", String(index));
        const llmCfg  = JSON.parse(localStorage.getItem("rl-llm")      || "{}");
        const charCfg = JSON.parse(localStorage.getItem("rl-character") || "{}");
        await sendConfigToBackend(llmCfg, charCfg);
        showMsg(`✓ 记忆跨度已切换至「${MEMORY_WINDOW_OPTIONS[index].label}」`);
    }

    // ── 语音配置（ElevenLabs + 本地 RVC）────────────────────────
    const TTS_CONFIG_KEY = "rl-tts";

    const tts = reactive({
        engine: "elevenlabs" as "elevenlabs" | "rvc",
        enabled: false,
        // ElevenLabs
        el_api_key: "",
        el_voice_id: "",
        // 本地 RVC
        rvc_pth: "",
        rvc_index: "",
        rvc_edge_voice: "zh-CN-XiaoxiaoNeural",
    });

    // RVC 音色列表（从后端扫描）
    interface RVCVoice { name: string; pth: string; index: string; index_missing: boolean; }
    const rvcVoices = ref<RVCVoice[]>([]);
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
        tts.rvc_pth = voice.pth;
        tts.rvc_index = voice.index;
    }

    function saveTTS() {
        localStorage.setItem(TTS_CONFIG_KEY, JSON.stringify({
            engine: tts.engine,
            enabled: tts.enabled,
            el_api_key: tts.el_api_key.trim(),
            el_voice_id: tts.el_voice_id.trim(),
            rvc_pth: tts.rvc_pth.trim(),
            rvc_index: tts.rvc_index.trim(),
            rvc_edge_voice: tts.rvc_edge_voice.trim(),
        }));
        showMsg("✓ 语音配置已保存");
    }

    // ── 角色预设列表 ───────────────────────────────────────────────
    const presets = ref<CharacterPreset[]>([]);
    const activePreset = ref<CharacterPreset | null>(null);

    function ensureDefaultFirst(list: CharacterPreset[]): CharacterPreset[] {
        const withoutDefault = list.filter(p => p.id !== "default-rei");
        const hasDefault = list.find(p => p.id === "default-rei");
        const defaultPreset = hasDefault ?? { ...DEFAULT_PRESET };
        return [defaultPreset, ...withoutDefault];
    }

    const character = reactive<Omit<CharacterPreset, "id">>({
        name: "", description: "", identity: "",
        personality: "", address: "", style: "",
        avatar: "", examples: [{ user: "", char: "" }],
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
        character.name = ""; character.description = "";
        character.identity = ""; character.personality = "";
        character.address = ""; character.style = "";
        character.avatar = ""; character.examples = [{ user: "", char: "" }];
    }

    function addExample() { if (character.examples.length < 3) character.examples.push({ user: "", char: "" }); }
    function removeExample(i: number) { character.examples.splice(i, 1); }

    const avatarInputRef = ref<HTMLInputElement | null>(null);
    function triggerAvatarUpload() { avatarInputRef.value?.click(); }
    function onAvatarChange(e: Event) {
        const file = (e.target as HTMLInputElement).files?.[0];
        if (!file) return;
        const reader = new FileReader();
        reader.onload = () => { character.avatar = reader.result as string; };
        reader.readAsDataURL(file);
    }

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

    // ── 删除角色卡弹框状态 ─────────────────────────────────────
    const showDeleteDialog    = ref(false);
    const deleteTargetId      = ref("");
    const deleteTargetName    = ref("");
    const deleteDataLoading   = ref(false);
 
    function requestDeletePreset(id: string) {
        if (id === "default-rei") { showMsg("默认预设不可删除", "warn"); return; }
        const preset = presets.value.find(p => p.id === id);
        if (!preset) return;
        deleteTargetId.value   = id;
        deleteTargetName.value = preset.name;
        showDeleteDialog.value = true;
    }
 
    async function confirmDeleteWithExport() {
        // 先导出，再删除
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
        } catch (e) {
            console.warn("[export] failed:", e);
        }
        await _doDeletePreset(deleteTargetId.value);
    }
 
    async function confirmDeleteDirect() {
        // 直接删除，不导出
        deleteDataLoading.value = true;
        await _doDeletePreset(deleteTargetId.value);
    }
 
    async function _doDeletePreset(id: string) {
        // 1. 删除后端数据
        try {
            await fetch(`http://localhost:18000/api/character/${id}/data`, { method: "DELETE" });
        } catch (e) {
            console.warn("[delete data] failed:", e);
        }
        // 2. 删除本地预设列表
        presets.value = presets.value.filter(p => p.id !== id);
        if (activePreset.value?.id === id) loadPresetToForm(presets.value[0]);
        if (activePresetId.value === id) {
            activePresetId.value = presets.value[0]?.id ?? "";
            localStorage.setItem("rl-active-preset-id", activePresetId.value);
        }
        savePresets();
        // 3. 关闭弹框
        showDeleteDialog.value  = false;
        deleteDataLoading.value = false;
        showMsg(`「${deleteTargetName.value}」及其所有数据已删除`);
    }

    async function activatePreset(preset: CharacterPreset) {
        activePresetId.value = preset.id;
        loadPresetToForm(preset);
        const llmCfg = JSON.parse(localStorage.getItem("rl-llm") || "{}");
        const charCfg = {
            name: preset.name, identity: preset.identity,
            personality: preset.personality, address: preset.address,
            style: preset.style, examples: preset.examples,
        };
        localStorage.setItem("rl-character", JSON.stringify(charCfg));
        localStorage.setItem("rl-active-preset-id", preset.id);
        await sendConfigToBackend(llmCfg, charCfg);
        showMsg(`✓ 已切换到「${preset.name}」`);
    }

    function savePresets() {
        localStorage.setItem("rl-presets", JSON.stringify(presets.value));
    }

    async function saveLLM() {
        localStorage.setItem("rl-api-keys", JSON.stringify(apiKeys));
        const cfg = { vendor: llm.vendor, base_url: llm.base_url, model: llm.model, api_key: apiKeys[llm.vendor] ?? "" };
        localStorage.setItem("rl-llm", JSON.stringify(cfg));
        const charCfg = JSON.parse(localStorage.getItem("rl-character") || "{}");
        await sendConfigToBackend(cfg, charCfg);
        showMsg("✓ LLM 配置已保存");
    }

    /** 通知 App.vue 更新配置（通过 Tauri 事件，由 App.vue 经自己的 WS 连接发送 configure） */
    async function sendConfigToBackend(llmCfg: object, charCfg: object, extraPayload?: object) {
        try {
            const { emit } = await import("@tauri-apps/api/event");
            await emit("config-changed", {
                llm: llmCfg,
                character: charCfg,
                character_id: activePresetId.value,
                memory_window: parseInt(localStorage.getItem("rl-memory-window") ?? "1", 10),
                ...extraPayload,
            });
        } catch (e) {
            console.warn("[config] emit failed:", e);
        }
    }

    // ── 消息提示 ───────────────────────────────────────────────────
    const msgText = ref("");
    const msgType = ref<"ok" | "warn">("ok");

    function showMsg(text: string, type: "ok" | "warn" = "ok") {
        msgText.value = text; msgType.value = type;
        setTimeout(() => { msgText.value = ""; }, 2500);
    }

    // ── 初始化 ─────────────────────────────────────────────────────
    onMounted(async () => {
        try {
            const resp = await fetch("/avatar.png");
            const blob = await resp.blob();
            const reader = new FileReader();
            reader.onload = () => { DEFAULT_AVATAR.value = reader.result as string; };
            reader.readAsDataURL(blob);
        } catch { }

        const savedKeys = localStorage.getItem("rl-api-keys");
        if (savedKeys) Object.assign(apiKeys, JSON.parse(savedKeys));

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

        const savedPresets = localStorage.getItem("rl-presets");
        presets.value = savedPresets
            ? ensureDefaultFirst(JSON.parse(savedPresets))
            : [{ ...DEFAULT_PRESET }];

        const savedActiveId = localStorage.getItem("rl-active-preset-id");
        if (savedActiveId && presets.value.find(p => p.id === savedActiveId)) {
            activePresetId.value = savedActiveId;
        } else {
            activePresetId.value = presets.value[0].id;
            localStorage.setItem("rl-active-preset-id", presets.value[0].id);
        }

        const savedChar = localStorage.getItem("rl-character");
        if (savedChar) {
            const d = JSON.parse(savedChar);
            const match = presets.value.find(p => p.name === d.name);
            loadPresetToForm(match ?? presets.value[0]);
        } else {
            loadPresetToForm(presets.value[0]);
        }
        // 加载当前选中模型的显示设置
        loadModelDisplaySettings(selectedModelPath.value);

        // 加载语音配置
        const savedTTS = localStorage.getItem(TTS_CONFIG_KEY);
        if (savedTTS) {
            const d = JSON.parse(savedTTS);
            tts.engine = d.engine ?? "elevenlabs";
            tts.enabled = d.enabled ?? false;
            tts.el_api_key = d.el_api_key ?? d.api_key ?? "";
            tts.el_voice_id = d.el_voice_id ?? d.voice_id ?? "";
            tts.rvc_pth = d.rvc_pth ?? "";
            tts.rvc_index = d.rvc_index ?? "";
            tts.rvc_edge_voice = d.rvc_edge_voice ?? "zh-CN-XiaoxiaoNeural";
        }
    });

    // ══════════════════════════════════════════════════════════════
    // 步骤⑧：笔记本界面
    // ══════════════════════════════════════════════════════════════
 
    // ── 笔记本弹窗状态 ──────────────────────────────────────────
    const showNotebook      = ref(false);
    const notebookTab       = ref<"manual" | "auto">("manual");
    const notebookLoading   = ref(false);
 
    // ── 笔记本当前角色名（动态读取）──────────────────────────────
    const notebookCharName = computed(() => {
        const p = presets.value.find(p => p.id === activePresetId.value);
        return p?.name ?? "角色";
    });
 
    // ── 手动区状态 ───────────────────────────────────────────────
    interface NotebookEntry { id: string; source: string; content: string; tags: string[]; created_at: string; updated_at: string; }
 
    const manualEntries    = ref<NotebookEntry[]>([]);
    const manualTotal      = ref(0);
    const manualPage       = ref(1);
    const manualTotalPages = ref(1);
    const manualKeyword    = ref("");
    const manualSearchBy   = ref<"content" | "tag">("content");
 
    // 新增/编辑表单
    const showEntryForm  = ref(false);
    const editingEntryId = ref<string | null>(null);
    const entryContent   = ref("");
    const entryTagsRaw   = ref("");   // 逗号分隔的标签字符串
 
    // ── 自动区状态 ───────────────────────────────────────────────
    const autoEntries    = ref<NotebookEntry[]>([]);
    const autoTotal      = ref(0);
    const autoPage       = ref(1);
    const autoTotalPages = ref(1);
    const autoKeyword    = ref("");
    const autoSearchBy   = ref<"content" | "tag">("content");
 
    // ── 跳页输入 ────────────────────────────────────────────────
    const manualJumpPage = ref<number | "">(1);
    const autoJumpPage   = ref<number | "">(1);
 
    // ── 打开笔记本 ───────────────────────────────────────────────
    async function openNotebook() {
        showNotebook.value = true;
        notebookTab.value  = "manual";
        await fetchManualEntries(1);
        await fetchAutoEntries(1);
    }
 
    // ── 获取手动区条目 ───────────────────────────────────────────
    async function fetchManualEntries(page: number) {
        notebookLoading.value = true;
        try {
            const params = new URLSearchParams({
                source: "manual",
                page: String(page),
                page_size: "10",
                character_id: activePresetId.value,
            });
            if (manualKeyword.value.trim()) {
                params.set("keyword", manualKeyword.value.trim());
                params.set("search_by", manualSearchBy.value);
            }
            const res  = await fetch(`http://localhost:18000/api/notebook/entries?${params}`);
            const data = await res.json();
            manualEntries.value    = data.items ?? [];
            manualTotal.value      = data.total ?? 0;
            manualPage.value       = data.page ?? 1;
            manualTotalPages.value = data.total_pages ?? 1;
            manualJumpPage.value   = manualPage.value;
        } catch {
            showMsg("获取备忘录失败，请确认后端已启动", "warn");
        } finally {
            notebookLoading.value = false;
        }
    }
 
    // ── 获取自动区条目 ───────────────────────────────────────────
    async function fetchAutoEntries(page: number) {
        notebookLoading.value = true;
        try {
            const params = new URLSearchParams({
                source: "auto",
                page: String(page),
                page_size: "10",
                character_id: activePresetId.value,
            });
            if (autoKeyword.value.trim()) {
                params.set("keyword", autoKeyword.value.trim());
                params.set("search_by", autoSearchBy.value);
            }
            const res  = await fetch(`http://localhost:18000/api/notebook/entries?${params}`);
            const data = await res.json();
            autoEntries.value    = data.items ?? [];
            autoTotal.value      = data.total ?? 0;
            autoPage.value       = data.page ?? 1;
            autoTotalPages.value = data.total_pages ?? 1;
            autoJumpPage.value   = autoPage.value;
        } catch {
            showMsg("获取日记本失败，请确认后端已启动", "warn");
        } finally {
            notebookLoading.value = false;
        }
    }
 
    // ── 手动区：新增/编辑 ────────────────────────────────────────
    function openNewEntry() {
        editingEntryId.value = null;
        entryContent.value   = "";
        entryTagsRaw.value   = "";
        showEntryForm.value  = true;
    }
 
    function openEditEntry(entry: NotebookEntry) {
        editingEntryId.value = entry.id;
        entryContent.value   = entry.content;
        entryTagsRaw.value   = entry.tags.join("、");
        showEntryForm.value  = true;
    }
 
    async function saveEntry() {
        const content = entryContent.value.trim();
        if (!content) { showMsg("内容不能为空", "warn"); return; }
        const tags = entryTagsRaw.value.split(/[,，、]/).map(t => t.trim()).filter(Boolean);
 
        try {
            if (editingEntryId.value) {
                // 编辑
                await fetch(`http://localhost:18000/api/notebook/entries/${editingEntryId.value}`, {
                    method: "PUT",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ content, tags }),
                });
                showMsg("✓ 已更新");
            } else {
                // 新增
                await fetch("http://localhost:18000/api/notebook/entries", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ content, tags, character_id: activePresetId.value }),
                });
                showMsg("✓ 已添加");
            }
            showEntryForm.value = false;
            await fetchManualEntries(manualPage.value);
        } catch {
            showMsg("操作失败", "warn");
        }
    }
 
    // ── 删除条目（手动区和自动区均可）───────────────────────────
    async function deleteEntry(id: string, source: "manual" | "auto") {
        try {
            await fetch(`http://localhost:18000/api/notebook/entries/${id}`, { method: "DELETE" });
            showMsg("已删除");
            if (source === "manual") await fetchManualEntries(manualPage.value);
            else                     await fetchAutoEntries(autoPage.value);
        } catch {
            showMsg("删除失败", "warn");
        }
    }
 
    // ── 搜索 ────────────────────────────────────────────────────
    async function searchManual() { await fetchManualEntries(1); }
    async function searchAuto()   { await fetchAutoEntries(1); }
 
    // ── 跳页 ────────────────────────────────────────────────────
    async function jumpManualPage() {
        const p = Number(manualJumpPage.value);
        if (p >= 1 && p <= manualTotalPages.value) await fetchManualEntries(p);
    }
    async function jumpAutoPage() {
        const p = Number(autoJumpPage.value);
        if (p >= 1 && p <= autoTotalPages.value) await fetchAutoEntries(p);
    }

</script>

<template>
    <div class="settings-root">

        <!-- Toast 通知 -->
        <transition name="toast">
            <div v-if="msgText" class="toast" :class="{ warn: msgType === 'warn' }">{{ msgText }}</div>
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
            <button class="tab-btn" :class="{ active: activeTab === 'global' }" @click="activeTab = 'global'; fetchLive2DModels()">
                <span class="tab-icon">⚙️</span> 全局设置
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

                <!-- 语音合成配置 -->
                <div class="divider"></div>
                <div class="global-section-title" style="margin-bottom:8px;">🔊 语音合成</div>

                <!-- 启用开关 + 引擎选择 -->
                <div class="field-group">
                    <label class="toggle-row" style="cursor:pointer; margin-bottom:8px;">
                        <span class="field-label">启用语音合成</span>
                        <input type="checkbox" v-model="tts.enabled"
                               style="width:16px;height:16px;accent-color:var(--c-blue);" />
                    </label>
                    <div class="engine-selector">
                        <div class="engine-card"
                             :class="{ active: tts.engine === 'elevenlabs' }"
                             @click="tts.engine = 'elevenlabs'">
                            <div class="engine-name">☁️ ElevenLabs</div>
                            <div class="engine-desc">云端高质量，每月 1 万字符免费</div>
                        </div>
                        <div class="engine-card"
                             :class="{ active: tts.engine === 'rvc' }"
                             @click="tts.engine = 'rvc'; fetchRVCVoices()">
                            <div class="engine-name">🖥️ 本地 RVC</div>
                            <div class="engine-desc">完全免费，使用自训练音色</div>
                        </div>
                    </div>
                </div>

                <!-- ElevenLabs 配置区 -->
                <div v-if="tts.engine === 'elevenlabs'" class="engine-config-section">
                    <div class="field-group">
                        <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;">
                            <span class="field-label">ElevenLabs 配置</span>
                            <a class="vendor-link" href="#" @click.prevent="openUrl('https://elevenlabs.io')">
                                🔗 前往官网
                            </a>
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

                <!-- 本地 RVC 配置区 -->
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
                                命名规范：<code>.pth</code> 与 <code>.index</code> 必须同名，
                                例如 <code>Hibiki.pth</code> + <code>Hibiki.index</code>
                            </p>
                            <div v-for="v in rvcVoices" :key="v.pth"
                                 class="rvc-voice-card"
                                 :class="{ active: tts.rvc_pth === v.pth, 'index-warn': v.index_missing }"
                                 @click="selectRVCVoice(v)">
                                <div class="rvc-voice-name">🎤 {{ v.name }}</div>
                                <div class="rvc-voice-meta">
                                    <span v-if="v.index_missing" class="rvc-warn">
                                        ⚠️ 缺少同名 .index 文件，请将其改名为 {{ v.name }}.index
                                    </span>
                                    <span v-else>✓ Index 文件匹配</span>
                                </div>
                            </div>
                            <button class="refresh-btn" @click="fetchRVCVoices">🔄 重新扫描</button>
                        </div>
                    </div>
                    <div class="field-group">
                        <label class="field-label">
                            底层 TTS 语音
                            <span class="field-note">Edge-TTS 原声（变声前的底层）</span>
                        </label>
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

            <!-- ── 角色设定 Tab ── -->
            <div v-if="activeTab === 'character'" class="tab-content">
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
                                <img :src="p.avatar || DEFAULT_AVATAR" alt="" />
                                <div v-if="activePresetId === p.id" class="running-badge">生效中</div>
                            </div>
                            <div class="preset-info">
                                <div class="preset-name">{{ p.name }}</div>
                                <div class="preset-desc">{{ p.description || "暂无简介" }}</div>
                            </div>
                            <div class="preset-actions">
                                <button class="preset-activate-btn" @click.stop="activatePreset(p)" title="激活使用">▶</button>
                                <button class="preset-delete-btn" @click.stop="requestDeletePreset(p.id)" :disabled="p.id === 'default-rei'" title="删除">×</button>
                            </div>
                        </div>
                    </div>
                </div>
                
                <div class="divider"></div>

                <!-- 笔记本入口 -->
                <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;">
                    <div class="form-section-label" style="margin-bottom:0;">{{ activePreset ? `编辑：${activePreset.name}` : "新建角色预设" }}</div>
                    <button class="save-btn"
                            style="padding:6px 14px;font-size:12px;"
                            @click="openNotebook">
                        📓 {{ notebookCharName }}的笔记本
                    </button>
                </div>

                <div class="avatar-upload-row">
                    <div class="avatar-preview" @click="triggerAvatarUpload">
                        <img :src="character.avatar || DEFAULT_AVATAR" alt="头像" />
                        <div class="avatar-overlay">更换</div>
                    </div>
                    <input ref="avatarInputRef" type="file" accept="image/*" style="display:none" @change="onAvatarChange" />
                    <div class="avatar-hint">点击更换头像<br /><span class="field-note">支持 JPG / PNG，建议正方形</span></div>
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
            </div>

            <!-- ── 全局设置 Tab ── -->
            <div v-if="activeTab === 'global'" class="tab-content">

                <!-- Live2D 模型选择 -->
                <div class="global-section">
                    <div class="global-section-title">
                        🎭 Live2D 模型
                        <span class="field-note">将模型文件夹放入 public/live2d/ 即可识别</span>
                    </div>

                    <div v-if="modelsLoading" class="models-loading">扫描中…</div>

                    <div v-else-if="live2dModels.length === 0" class="models-empty">
                        <p>未找到模型</p>
                        <p class="field-note">请将 Live2D 模型文件夹放入项目的 <code>public/live2d/</code> 目录</p>
                        <button class="refresh-btn" @click="fetchLive2DModels">重新扫描</button>
                    </div>

                    <div v-else class="models-list">
                        <div v-for="m in live2dModels" :key="m.path"
                             class="model-card"
                             :class="{ active: selectedModelPath === m.path }"
                             @click="applyModel(m.path)">
                            <div class="model-icon">🪆</div>
                            <div class="model-info">
                                <div class="model-name">{{ m.display_name }}</div>
                                <div class="model-path">{{ m.path }}</div>
                            </div>
                            <div v-if="selectedModelPath === m.path" class="model-active-badge">使用中</div>
                        </div>
                        <button class="refresh-btn" @click="fetchLive2DModels">🔄 重新扫描</button>
                    </div>

                    <!-- 当前模型显示设置 -->
                    <div class="model-display-settings">
                        <div class="global-section-title" style="font-size:12px;">📐 当前模型显示调整</div>
                        <div class="field-row">
                            <div class="field-group half">
                                <label class="field-label">
                                    缩放 Zoom
                                    <span class="field-note">默认 1.7</span>
                                </label>
                                <div class="zoom-input-row">
                                    <input type="range" class="field-range"
                                           :min="0.5" :max="3.0" :step="0.05"
                                           v-model.number="modelZoom" />
                                    <span class="zoom-value">{{ modelZoom.toFixed(2) }}</span>
                                </div>
                            </div>
                            <div class="field-group half">
                                <label class="field-label">
                                    垂直偏移 Y
                                    <span class="field-note">默认 -80</span>
                                </label>
                                <div class="zoom-input-row">
                                    <input type="range" class="field-range"
                                           :min="-400" :max="200" :step="5"
                                           v-model.number="modelY" />
                                    <span class="zoom-value">{{ modelY }}</span>
                                </div>
                            </div>
                        </div>
                        <div class="action-row" style="padding-top:4px;">
                            <button class="save-btn" style="padding:6px 18px;font-size:12px;"
                                    @click="applyModelSettings">
                                应用
                            </button>
                        </div>
                    </div>
                </div>

                <div class="divider"></div>

                <!-- 窗口尺寸 -->
                <div class="global-section">
                    <div class="global-section-title">📐 窗口尺寸</div>
                    <div class="size-options">
                        <div v-for="opt in SIZE_OPTIONS" :key="opt.value"
                             class="size-card"
                             :class="{ active: sizePreset === opt.value }"
                             @click="applySize(opt.value)">
                            <div class="size-label">{{ opt.label }}</div>
                            <div class="size-desc">{{ opt.desc }}</div>
                        </div>
                    </div>
                    <p class="field-hint">尺寸变更在重启后生效。</p>
                </div>

                <div class="divider"></div>

                <!-- 语音设置（Phase 2 语音功能实现后启用） -->
                <div class="global-section global-section-disabled">
                    <div class="global-section-title">🎙️ 语音设置 <span class="coming-badge">开发中</span></div>
                    <div class="field-group">
                        <label class="field-label">唤醒词</label>
                        <input class="field-input" disabled placeholder="例如：小玲" />
                    </div>
                    <div class="field-group">
                        <label class="field-label">按住说话快捷键</label>
                        <input class="field-input" disabled placeholder="例如：Alt" />
                    </div>
                    <div class="field-group">
                        <label class="field-label">音量</label>
                        <input type="range" class="field-range" disabled min="0" max="100" value="80" />
                    </div>
                </div>

                <div class="divider"></div>

                <!-- Phase 3: 视觉感知 -->
                <div class="global-section">
                    <div class="global-section-title">🎮 视觉感知</div>

                    <!-- 总开关 -->
                    <label class="toggle-row" style="margin-bottom:10px;">
                        <span class="field-label">启用视觉感知</span>
                        <input type="checkbox" v-model="visionEnabled" @change="saveVision" />
                    </label>

                    <!-- 隐私说明 -->
                    <p class="field-hint" style="color:var(--c-text-soft);margin-bottom:12px;">
                        🔒 隐私说明：截图仅在内存中存在，用于实时分析后立即释放，永不保存到磁盘。
                    </p>

                    <template v-if="visionEnabled">
                        <!-- VLM 配置 -->
                        <div class="field-group" style="margin-bottom:8px;">
                            <label class="field-label">VLM API Base URL</label>
                            <input class="field-input" v-model="visionVlmBaseUrl"
                                   placeholder="https://open.bigmodel.cn/api/paas/v4/" />
                        </div>
                        <div class="field-group" style="margin-bottom:8px;">
                            <label class="field-label">VLM API Key</label>
                            <input class="field-input" type="password" v-model="visionVlmApiKey"
                                   placeholder="填写 VLM API Key（如 GLM-4V-Flash）" />
                        </div>
                        <div class="field-group" style="margin-bottom:12px;">
                            <label class="field-label">VLM 模型名称</label>
                            <input class="field-input" v-model="visionVlmModel"
                                   placeholder="glm-4v-flash" />
                        </div>

                        <!-- VLM 不可用提示 -->
                        <div v-if="visionEnabled && !visionVlmApiKey"
                             style="background:#fffbe6;border:1px solid #f0c040;border-radius:6px;
                                    padding:8px 12px;font-size:12px;color:#8a6000;margin-bottom:12px;">
                            ⚠️ 视觉模型未配置或不可用。请填写 VLM API Key，或在「AI 模型」Tab 配置支持多模态的文本模型（如 GPT-4o）。
                        </div>

                        <!-- 话痨程度 -->
                        <div class="field-group" style="margin-bottom:12px;">
                            <label class="field-label">话痨程度</label>
                            <div class="size-options" style="gap:8px;margin-top:6px;">
                                <div v-for="opt in VISION_TALK_OPTIONS" :key="opt.value"
                                     class="size-card"
                                     :class="{ active: visionTalkLevel === opt.value }"
                                     @click="visionTalkLevel = opt.value; saveVision()">
                                    <div class="size-label">{{ opt.label }}</div>
                                    <div class="size-desc">{{ opt.desc }}</div>
                                </div>
                            </div>
                        </div>

                        <!-- 冷却时间 -->
                        <div class="field-group" style="margin-bottom:12px;">
                            <label class="field-label">
                                主动发言冷却
                                <span class="field-note">{{ visionCooldown }} 秒</span>
                            </label>
                            <input type="range" class="field-range"
                                   min="5" max="120" step="5"
                                   v-model.number="visionCooldown"
                                   @change="saveVision" />
                        </div>

                        <!-- 手动观战模式 -->
                        <label class="toggle-row" style="margin-bottom:12px;">
                            <span class="field-label">
                                手动观战模式
                                <span class="field-note">强制标记当前为游戏场景</span>
                            </span>
                            <input type="checkbox" v-model="visionManualGameMode" @change="saveVision" />
                        </label>

                        <!-- 保存按钮 -->
                        <div class="action-row">
                            <button class="save-btn" @click="saveVision">保存视觉感知配置</button>
                        </div>
                    </template>
                </div>

                <div class="divider"></div>

                <div class="global-section">
                    <div class="global-section-title">🧠 记忆设置</div>
                    <div class="field-group">
                        <label class="field-label">短期记忆跨度</label>
                        <p class="field-hint" style="margin-bottom: 10px;">
                            ⏳ 记忆跨度越长，聊天连贯性越好，但 API Token 消耗与回复延迟也会增加。
                        </p>
                        <div class="memory-window-options">
                            <div
                                v-for="opt in MEMORY_WINDOW_OPTIONS"
                                :key="opt.index"
                                class="memory-window-card"
                                :class="{ active: memoryWindowIndex === opt.index }"
                                @click="applyMemoryWindow(opt.index)"
                            >
                                <div class="memory-window-label">{{ opt.label }}</div>
                                <div class="memory-window-desc">{{ opt.desc }}</div>
                                <div class="memory-window-token" :class="{ warn: opt.warn }">
                                    {{ opt.token }}
                                    <span v-if="opt.warn" style="margin-left:4px;">⚠️</span>
                                </div>
                            </div>
                        </div>
                        <p v-if="MEMORY_WINDOW_OPTIONS[memoryWindowIndex].warn" class="field-hint" style="margin-top:8px;color:#C08000;">
                            ⚠️ Token 消耗较高，建议搭配高性能模型使用。
                        </p>
                    </div>
                </div>
 
            </div>
        </div>

        <!-- 保存确认弹框 -->
        <transition name="dialog">
            <div v-if="showSaveDialog" class="dialog-overlay" @click.self="showSaveDialog = false">
                <div class="dialog-box">
                    <div class="dialog-title">保存角色预设</div>
                    <div class="dialog-body">
                        <label class="field-label">一句话简介 <span class="field-note">选填，显示在卡片上</span></label>
                        <input class="field-input" v-model="saveDialogDesc" placeholder="例如：傲娇猫娘，Reverie Link 默认角色" maxlength="30" />
                    </div>
                    <div class="dialog-actions">
                        <button class="dialog-cancel" @click="showSaveDialog = false">取消</button>
                        <button class="dialog-confirm" @click="confirmSave">确认保存</button>
                    </div>
                </div>
            </div>
        </transition>

        <!-- 删除角色卡确认弹框 -->
        <transition name="dialog">
            <div v-if="showDeleteDialog" class="dialog-overlay" @click.self="showDeleteDialog = false">
                <div class="dialog-box">
                    <div class="dialog-title">删除「{{ deleteTargetName }}」</div>
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
                                :disabled="deleteDataLoading"
                                @click="confirmDeleteWithExport">
                            {{ deleteDataLoading ? "处理中…" : "📥 导出后删除" }}
                        </button>
                        <button class="dialog-confirm"
                                style="width:100%;background:linear-gradient(135deg,#f28b82,#e06666);"
                                :disabled="deleteDataLoading"
                                @click="confirmDeleteDirect">
                            {{ deleteDataLoading ? "处理中…" : "🗑️ 直接删除" }}
                        </button>
                        <button class="dialog-cancel"
                                style="width:100%;text-align:center;"
                                :disabled="deleteDataLoading"
                                @click="showDeleteDialog = false">
                            取消
                        </button>
                    </div>
                </div>
            </div>
        </transition>

        <!-- ══ 笔记本弹窗 ══════════════════════════════════════════ -->
        <transition name="dialog">
            <div v-if="showNotebook" class="notebook-overlay" @click.self="showNotebook = false">
                <div class="notebook-panel">
 
                    <!-- 标题栏 -->
                    <div class="notebook-header">
                        <span class="notebook-title">📓 {{ notebookCharName }}的笔记本</span>
                        <button class="notebook-close" @click="showNotebook = false">×</button>
                    </div>
 
                    <!-- Tab 切换 -->
                    <div class="notebook-tabs">
                        <button class="nb-tab-btn"
                                :class="{ active: notebookTab === 'manual' }"
                                @click="notebookTab = 'manual'">
                            我的备忘录
                        </button>
                        <button class="nb-tab-btn"
                                :class="{ active: notebookTab === 'auto' }"
                                @click="notebookTab = 'auto'">
                            {{ notebookCharName }}的日记本
                        </button>
                    </div>
 
                    <!-- 内容区 -->
                    <div class="notebook-content">
 
                        <!-- ── 手动区 ── -->
                        <div v-if="notebookTab === 'manual'">
                            <!-- 搜索栏 -->
                            <div class="nb-search-row">
                                <input class="nb-search-input" v-model="manualKeyword"
                                       placeholder="搜索…" @keydown.enter="searchManual" />
                                <select class="nb-search-by" v-model="manualSearchBy">
                                    <option value="content">按内容</option>
                                    <option value="tag">按标签</option>
                                </select>
                                <button class="nb-search-btn" @click="searchManual">搜索</button>
                                <button class="nb-add-btn" @click="openNewEntry">+ 新增</button>
                            </div>
 
                            <!-- 条目列表 -->
                            <div v-if="notebookLoading" class="nb-loading">加载中…</div>
                            <div v-else-if="manualEntries.length === 0" class="nb-empty">
                                暂无条目，点击「+ 新增」添加
                            </div>
                            <div v-else class="nb-entries">
                                <div v-for="e in manualEntries" :key="e.id" class="nb-entry-card">
                                    <div class="nb-entry-content">{{ e.content }}</div>
                                    <div class="nb-entry-tags">
                                        <span v-for="t in e.tags" :key="t" class="nb-tag">{{ t }}</span>
                                    </div>
                                    <div class="nb-entry-actions">
                                        <button class="nb-edit-btn" @click="openEditEntry(e)">编辑</button>
                                        <button class="nb-del-btn" @click="deleteEntry(e.id, 'manual')">删除</button>
                                    </div>
                                </div>
                            </div>
 
                            <!-- 分页 -->
                            <div v-if="manualTotalPages > 1" class="nb-pagination">
                                <button class="nb-page-btn" :disabled="manualPage <= 1" @click="fetchManualEntries(1)">首页</button>
                                <button class="nb-page-btn" :disabled="manualPage <= 1" @click="fetchManualEntries(manualPage - 1)">上一页</button>
                                <span class="nb-page-info">{{ manualPage }} / {{ manualTotalPages }}</span>
                                <button class="nb-page-btn" :disabled="manualPage >= manualTotalPages" @click="fetchManualEntries(manualPage + 1)">下一页</button>
                                <button class="nb-page-btn" :disabled="manualPage >= manualTotalPages" @click="fetchManualEntries(manualTotalPages)">尾页</button>
                                <input class="nb-jump-input" v-model.number="manualJumpPage" type="number" min="1" :max="manualTotalPages" @keydown.enter="jumpManualPage" />
                                <button class="nb-page-btn" @click="jumpManualPage">跳转</button>
                            </div>
 
                            <!-- 底部提示 -->
                            <p class="nb-file-hint">💡 需要批量编辑？数据文件位于 <code>data/notebook.db</code></p>
                        </div>
 
                        <!-- ── 自动区 ── -->
                        <div v-if="notebookTab === 'auto'">
                            <!-- 搜索栏 -->
                            <div class="nb-search-row">
                                <input class="nb-search-input" v-model="autoKeyword"
                                       placeholder="搜索…" @keydown.enter="searchAuto" />
                                <select class="nb-search-by" v-model="autoSearchBy">
                                    <option value="content">按内容</option>
                                    <option value="tag">按标签</option>
                                </select>
                                <button class="nb-search-btn" @click="searchAuto">搜索</button>
                            </div>
 
                            <!-- 条目列表 -->
                            <div v-if="notebookLoading" class="nb-loading">加载中…</div>
                            <div v-else-if="autoEntries.length === 0" class="nb-empty">
                                {{ notebookCharName }}还没有记录任何事情
                            </div>
                            <div v-else class="nb-entries">
                                <div v-for="e in autoEntries" :key="e.id" class="nb-entry-card nb-entry-auto">
                                    <div class="nb-entry-content">{{ e.content }}</div>
                                    <div class="nb-entry-tags">
                                        <span v-for="t in e.tags" :key="t" class="nb-tag">{{ t }}</span>
                                    </div>
                                    <div class="nb-entry-actions">
                                        <button class="nb-del-btn" @click="deleteEntry(e.id, 'auto')" title="删除表示「这条记错了」">删除</button>
                                    </div>
                                </div>
                            </div>
 
                            <!-- 分页 -->
                            <div v-if="autoTotalPages > 1" class="nb-pagination">
                                <button class="nb-page-btn" :disabled="autoPage <= 1" @click="fetchAutoEntries(1)">首页</button>
                                <button class="nb-page-btn" :disabled="autoPage <= 1" @click="fetchAutoEntries(autoPage - 1)">上一页</button>
                                <span class="nb-page-info">{{ autoPage }} / {{ autoTotalPages }}</span>
                                <button class="nb-page-btn" :disabled="autoPage >= autoTotalPages" @click="fetchAutoEntries(autoPage + 1)">下一页</button>
                                <button class="nb-page-btn" :disabled="autoPage >= autoTotalPages" @click="fetchAutoEntries(autoTotalPages)">尾页</button>
                                <input class="nb-jump-input" v-model.number="autoJumpPage" type="number" min="1" :max="autoTotalPages" @keydown.enter="jumpAutoPage" />
                                <button class="nb-page-btn" @click="jumpAutoPage">跳转</button>
                            </div>
 
                            <!-- 底部提示 -->
                            <p class="nb-file-hint">💡 数据文件位于 <code>data/notebook.db</code></p>
                        </div>
 
                    </div>
                </div>
            </div>
        </transition>
 
        <!-- 新增/编辑条目弹框 -->
        <transition name="dialog">
            <div v-if="showEntryForm" class="dialog-overlay" @click.self="showEntryForm = false">
                <div class="dialog-box" style="width:360px;">
                    <div class="dialog-title">{{ editingEntryId ? "编辑条目" : "新增条目" }}</div>
                    <div class="dialog-body" style="gap:10px;">
                        <div>
                            <label class="field-label">内容 <span class="required">*</span></label>
                            <textarea class="field-input" v-model="entryContent"
                                      rows="3" placeholder="例如：喜欢打羽毛球"
                                      style="resize:none;margin-top:4px;" />
                        </div>
                        <div>
                            <label class="field-label">标签 <span class="field-note">用逗号或顿号分隔</span></label>
                            <input class="field-input" v-model="entryTagsRaw"
                                   placeholder="例如：运动、羽毛球" style="margin-top:4px;" />
                        </div>
                    </div>
                    <div class="dialog-actions">
                        <button class="dialog-cancel" @click="showEntryForm = false">取消</button>
                        <button class="dialog-confirm" @click="saveEntry">保存</button>
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
        box-shadow: 0 4px 16px rgba(126,87,194,0.2);
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

    /* ── 根容器 & CSS 变量 ────────────────────────────────────── */
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
        --c-border: rgba(212,184,224,0.45);
        --c-shadow: rgba(180,140,200,0.12);
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
        padding: 9px 8px;
        border: none;
        border-radius: 10px 10px 0 0;
        background: transparent;
        cursor: pointer;
        font-size: 12px;
        font-family: inherit;
        color: var(--c-text-soft);
        font-weight: 500;
        transition: all 0.2s;
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 4px;
    }

        .tab-btn:hover {
            color: var(--c-text);
            background: var(--c-pink-light);
        }

        .tab-btn.active {
            color: var(--c-text);
            font-weight: 700;
            background: linear-gradient(to bottom,var(--c-pink-light),var(--c-bg));
            border-bottom: 2.5px solid var(--c-pink-mid);
        }

    .tab-icon {
        font-size: 14px;
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

    /* ── 全局设置 ─────────────────────────────────────────────── */
    .global-section {
        display: flex;
        flex-direction: column;
        gap: 10px;
    }

    .global-section-disabled {
        opacity: 0.45;
        pointer-events: none;
    }

    .global-section-title {
        font-size: 13px;
        font-weight: 700;
        color: var(--c-text);
        display: flex;
        align-items: center;
        gap: 8px;
    }

    .coming-badge {
        font-size: 10px;
        font-weight: 600;
        color: var(--c-text-soft);
        background: var(--c-pink-light);
        padding: 2px 8px;
        border-radius: 10px;
    }

    /* ── 模型列表 ─────────────────────────────────────────────── */
    .models-loading {
        color: var(--c-text-soft);
        font-size: 13px;
        padding: 8px 0;
    }

    .models-empty {
        display: flex;
        flex-direction: column;
        gap: 6px;
        padding: 8px 0;
    }

        .models-empty p {
            font-size: 13px;
            color: var(--c-text-soft);
        }

        .models-empty code {
            font-size: 12px;
            background: var(--c-pink-light);
            padding: 1px 6px;
            border-radius: 4px;
        }

    .models-list {
        display: flex;
        flex-direction: column;
        gap: 8px;
    }

    .model-card {
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

        .model-card:hover {
            border-color: var(--c-pink-mid);
        }

        .model-card.active {
            border-color: var(--c-blue);
            box-shadow: 0 0 0 3px var(--c-blue-light);
        }

    .model-icon {
        font-size: 22px;
        flex-shrink: 0;
    }

    .model-info {
        flex: 1;
        min-width: 0;
    }

    .model-name {
        font-size: 13px;
        font-weight: 600;
        color: var(--c-text);
    }

    .model-path {
        font-size: 11px;
        color: var(--c-text-soft);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }

    .model-active-badge {
        font-size: 10px;
        font-weight: 600;
        color: white;
        background: var(--c-blue);
        padding: 2px 8px;
        border-radius: 10px;
        flex-shrink: 0;
    }

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
        transition: background 0.2s,color 0.2s;
    }

        .refresh-btn:hover {
            background: var(--c-blue);
            color: white;
        }

    /* ── 尺寸选择 ─────────────────────────────────────────────── */
    .size-options {
        display: flex;
        gap: 8px;
    }

    .size-card {
        flex: 1;
        padding: 10px 8px;
        border: 1.5px solid var(--c-border);
        border-radius: 12px;
        text-align: center;
        cursor: pointer;
        background: var(--c-surface);
        transition: border-color 0.2s, box-shadow 0.2s;
    }

        .size-card:hover {
            border-color: var(--c-pink-mid);
        }

        .size-card.active {
            border-color: var(--c-blue);
            box-shadow: 0 0 0 3px var(--c-blue-light);
        }

    .size-label {
        font-size: 13px;
        font-weight: 600;
        color: var(--c-text);
    }

    .size-desc {
        font-size: 11px;
        color: var(--c-text-soft);
        margin-top: 2px;
    }

    /* ── range 输入 ───────────────────────────────────────────── */
    .field-range {
        width: 100%;
        accent-color: var(--c-blue);
    }

    /* ── toggle 行 ───────────────────────────────────────────── */
    .toggle-row {
        display: flex;
        align-items: center;
        justify-content: space-between;
    }

    /* ── 预设列表（角色 Tab）────────────────────────────────────── */
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
        transition: background 0.2s,color 0.2s;
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
        transition: border-color 0.2s,box-shadow 0.2s;
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

        .preset-card.editing.running {
            border-color: var(--c-blue);
            box-shadow: 0 0 0 3px var(--c-blue-light);
        }

    .preset-avatar {
        position: relative;
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

    .preset-activate-btn, .preset-delete-btn {
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

    /* ── 分割线 & 表单 ────────────────────────────────────────── */
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
        transition: border-color 0.2s,box-shadow 0.2s;
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
        background: linear-gradient(135deg,var(--c-blue-mid),var(--c-pink));
        color: white;
        font-size: 13px;
        font-weight: 600;
        font-family: inherit;
        cursor: pointer;
        box-shadow: 0 3px 12px var(--c-shadow);
        transition: opacity 0.2s,transform 0.15s;
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
        background: rgba(100,80,120,0.25);
        backdrop-filter: blur(4px);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 200;
    }

    .dialog-box {
        width: 300px;
        background: var(--c-surface);
        border-radius: 18px;
        padding: 22px 20px 18px;
        box-shadow: 0 8px 32px rgba(126,87,194,0.18);
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
        background: linear-gradient(135deg,var(--c-blue-mid),var(--c-pink));
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

    /* ── 模型显示设置 ─────────────────────────────────────────── */
    .model-display-settings {
        display: flex;
        flex-direction: column;
        gap: 8px;
        padding: 10px 12px;
        background: var(--c-surface);
        border: 1.5px solid var(--c-border);
        border-radius: 12px;
        margin-top: 4px;
    }

    .zoom-input-row {
        display: flex;
        align-items: center;
        gap: 8px;
    }

        .zoom-input-row .field-range {
            flex: 1;
        }

    .zoom-value {
        font-size: 12px;
        font-weight: 600;
        color: var(--c-text);
        min-width: 38px;
        text-align: right;
        flex-shrink: 0;
    }

    /* ── 引擎选择卡片 ─────────────────────────────────────────── */
    .engine-selector {
        display: flex;
        gap: 8px;
    }

    .engine-card {
        flex: 1;
        padding: 10px;
        border: 1.5px solid var(--c-border);
        border-radius: 12px;
        cursor: pointer;
        background: var(--c-surface);
        transition: border-color 0.2s, box-shadow 0.2s;
    }

        .engine-card:hover {
            border-color: var(--c-pink-mid);
        }

        .engine-card.active {
            border-color: var(--c-blue);
            box-shadow: 0 0 0 3px var(--c-blue-light);
            background: linear-gradient(135deg, rgba(197,232,244,0.15), rgba(255,183,197,0.1));
        }

    .engine-name {
        font-size: 13px;
        font-weight: 600;
        color: var(--c-text);
    }

    .engine-desc {
        font-size: 11px;
        color: var(--c-text-soft);
        margin-top: 2px;
    }

    .engine-config-section {
        display: flex;
        flex-direction: column;
        gap: 10px;
        padding: 10px 12px;
        background: var(--c-surface);
        border: 1.5px solid var(--c-border);
        border-radius: 12px;
    }

    /* ── RVC 音色列表 ─────────────────────────────────────────── */
    .rvc-voices-list {
        display: flex;
        flex-direction: column;
        gap: 6px;
    }

    .rvc-voice-card {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 8px 12px;
        border: 1.5px solid var(--c-border);
        border-radius: 10px;
        cursor: pointer;
        background: var(--c-surface);
        transition: border-color 0.2s, box-shadow 0.2s;
    }

        .rvc-voice-card:hover {
            border-color: var(--c-pink-mid);
        }

        .rvc-voice-card.active {
            border-color: var(--c-blue);
            box-shadow: 0 0 0 3px var(--c-blue-light);
        }

    .rvc-voice-name {
        font-size: 13px;
        font-weight: 600;
        color: var(--c-text);
    }

    .rvc-voice-meta {
        font-size: 11px;
        color: var(--c-text-soft);
    }


    .rvc-voice-card.index-warn {
        border-color: #F0C060;
    }

    .rvc-warn {
        color: #C08000;
        font-weight: 500;
    }

    .rvc-voice-card.index-warn.active {
        border-color: #E0A000;
        box-shadow: 0 0 0 3px rgba(240,192,0,0.2);
    }

    /* ── 记忆窗口档位选择 ─────────────────────────────────────── */
    .memory-window-options {
        display: flex;
        flex-direction: column;
        gap: 6px;
    }
 
    .memory-window-card {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 10px 14px;
        border: 1.5px solid var(--c-border);
        border-radius: 10px;
        cursor: pointer;
        background: var(--c-surface);
        transition: border-color 0.2s, box-shadow 0.2s;
    }
 
        .memory-window-card:hover {
            border-color: var(--c-pink-mid);
        }
 
        .memory-window-card.active {
            border-color: var(--c-blue);
            box-shadow: 0 0 0 3px var(--c-blue-light);
            background: linear-gradient(135deg, rgba(197,232,244,0.15), rgba(255,183,197,0.1));
        }
 
    .memory-window-label {
        font-size: 13px;
        font-weight: 600;
        color: var(--c-text);
        min-width: 80px;
        flex-shrink: 0;
    }
 
    .memory-window-desc {
        font-size: 12px;
        color: var(--c-text-soft);
        flex: 1;
    }
 
    .memory-window-token {
        font-size: 11px;
        color: var(--c-text-soft);
        text-align: right;
        flex-shrink: 0;
    }
 
    .memory-window-token.warn {
        color: #C08000;
        font-weight: 500;
    }
    
    /* ── 笔记本弹窗 ──────────────────────────────────────────── */
    .notebook-overlay {
        position: fixed;
        inset: 0;
        background: rgba(100,80,120,0.3);
        backdrop-filter: blur(6px);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 150;
    }
 
    .notebook-panel {
        width: 560px;
        max-height: 80vh;
        background: var(--c-bg);
        border-radius: 20px;
        box-shadow: 0 12px 48px rgba(126,87,194,0.2);
        display: flex;
        flex-direction: column;
        overflow: hidden;
    }
 
    .notebook-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 16px 20px 12px;
        border-bottom: 1.5px solid var(--c-border);
        flex-shrink: 0;
    }
 
    .notebook-title {
        font-size: 15px;
        font-weight: 700;
        color: var(--c-text);
    }
 
    .notebook-close {
        width: 28px;
        height: 28px;
        border: none;
        border-radius: 50%;
        background: var(--c-pink-light);
        color: var(--c-text-soft);
        font-size: 16px;
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        transition: background 0.2s;
    }
 
        .notebook-close:hover { background: var(--c-pink); color: white; }
 
    .notebook-tabs {
        display: flex;
        gap: 0;
        padding: 10px 20px 0;
        flex-shrink: 0;
    }
 
    .nb-tab-btn {
        padding: 7px 18px;
        border: 1.5px solid var(--c-border);
        border-bottom: none;
        border-radius: 10px 10px 0 0;
        background: var(--c-pink-light);
        color: var(--c-text-soft);
        font-size: 13px;
        font-family: inherit;
        cursor: pointer;
        transition: background 0.2s, color 0.2s;
    }
 
        .nb-tab-btn.active {
            background: var(--c-surface);
            color: var(--c-text);
            font-weight: 600;
        }
 
    .notebook-content {
        flex: 1;
        overflow-y: auto;
        padding: 14px 20px 16px;
        background: var(--c-surface);
        border-top: 1.5px solid var(--c-border);
    }
 
    /* 搜索栏 */
    .nb-search-row {
        display: flex;
        gap: 6px;
        margin-bottom: 12px;
        align-items: center;
    }
 
    .nb-search-input {
        flex: 1;
        height: 32px;
        border: 1.5px solid var(--c-border);
        border-radius: 8px;
        padding: 0 10px;
        font-size: 13px;
        font-family: inherit;
        color: var(--c-text);
        background: var(--c-bg);
        outline: none;
    }
 
        .nb-search-input:focus { border-color: var(--c-blue); }
 
    .nb-search-by {
        height: 32px;
        border: 1.5px solid var(--c-border);
        border-radius: 8px;
        padding: 0 6px;
        font-size: 12px;
        font-family: inherit;
        color: var(--c-text);
        background: var(--c-bg);
        outline: none;
        cursor: pointer;
    }
 
    .nb-search-btn, .nb-add-btn {
        height: 32px;
        padding: 0 12px;
        border: none;
        border-radius: 8px;
        font-size: 12px;
        font-family: inherit;
        cursor: pointer;
        white-space: nowrap;
        transition: opacity 0.2s;
    }
 
    .nb-search-btn {
        background: var(--c-blue-light);
        color: var(--c-text);
    }
 
    .nb-add-btn {
        background: linear-gradient(135deg, var(--c-blue-mid), var(--c-pink));
        color: white;
        font-weight: 600;
    }
 
        .nb-search-btn:hover, .nb-add-btn:hover { opacity: 0.82; }
 
    /* 条目列表 */
    .nb-loading, .nb-empty {
        text-align: center;
        padding: 24px 0;
        color: var(--c-text-soft);
        font-size: 13px;
    }
 
    .nb-entries {
        display: flex;
        flex-direction: column;
        gap: 8px;
        margin-bottom: 12px;
    }
 
    .nb-entry-card {
        padding: 10px 12px;
        border: 1.5px solid var(--c-border);
        border-radius: 10px;
        background: var(--c-bg);
    }
 
    .nb-entry-auto {
        border-color: var(--c-blue-light);
        background: linear-gradient(135deg, rgba(197,232,244,0.08), rgba(255,183,197,0.05));
    }
 
    .nb-entry-content {
        font-size: 13px;
        color: var(--c-text);
        line-height: 1.55;
        margin-bottom: 6px;
    }
 
    .nb-entry-tags {
        display: flex;
        flex-wrap: wrap;
        gap: 4px;
        margin-bottom: 6px;
    }
 
    .nb-tag {
        padding: 2px 8px;
        border-radius: 20px;
        background: var(--c-pink-light);
        color: var(--c-text-soft);
        font-size: 11px;
    }
 
    .nb-entry-actions {
        display: flex;
        gap: 6px;
        justify-content: flex-end;
    }
 
    .nb-edit-btn, .nb-del-btn {
        padding: 3px 10px;
        border: 1.5px solid var(--c-border);
        border-radius: 6px;
        font-size: 11px;
        font-family: inherit;
        cursor: pointer;
        background: transparent;
        color: var(--c-text-soft);
        transition: background 0.15s, color 0.15s;
    }
 
        .nb-edit-btn:hover { background: var(--c-blue-light); color: var(--c-text); border-color: var(--c-blue); }
        .nb-del-btn:hover  { background: #FFE0E0; color: #C06060; border-color: #FFAAAA; }
 
    /* 分页 */
    .nb-pagination {
        display: flex;
        align-items: center;
        gap: 6px;
        justify-content: center;
        margin-top: 4px;
        margin-bottom: 8px;
        flex-wrap: wrap;
    }
 
    .nb-page-btn {
        padding: 4px 10px;
        border: 1.5px solid var(--c-border);
        border-radius: 6px;
        font-size: 12px;
        font-family: inherit;
        background: var(--c-surface);
        color: var(--c-text-soft);
        cursor: pointer;
        transition: background 0.15s;
    }
 
        .nb-page-btn:hover:not(:disabled) { background: var(--c-pink-light); }
        .nb-page-btn:disabled { opacity: 0.35; cursor: not-allowed; }
 
    .nb-page-info {
        font-size: 12px;
        color: var(--c-text-soft);
        padding: 0 4px;
    }
 
    .nb-jump-input {
        width: 44px;
        height: 28px;
        border: 1.5px solid var(--c-border);
        border-radius: 6px;
        padding: 0 6px;
        font-size: 12px;
        font-family: inherit;
        color: var(--c-text);
        background: var(--c-bg);
        text-align: center;
        outline: none;
    }
 
    /* 底部提示 */
    .nb-file-hint {
        font-size: 11px;
        color: var(--c-text-soft);
        text-align: center;
        margin-top: 8px;
    }
 
    .nb-file-hint code {
        background: var(--c-pink-light);
        padding: 1px 5px;
        border-radius: 4px;
        font-size: 11px;
    }
</style>