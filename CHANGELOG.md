# Changelog

本文件记录 Reverie Link 每个版本的主要变更。  
格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)。

---

## [Unreleased] - Phase 1 完成存档

> Phase 1 开发完成，尚未发布正式版本号。以下为本阶段全部变更记录。

### 新增

**窗口与系统层**
- 透明无边框置顶窗口，支持鼠标穿透切换
- 动态窗口尺寸缩放（输入框展开/气泡显示时自动扩展，以右下角为锚点）
- 窗口拖拽，位置跨会话记忆（localStorage 存储锚点坐标）
- 系统托盘菜单：锁定/解锁穿透、打开设置、退出
- 锁定状态下鼠标悬停角色区域 1.5 秒后浮现解锁按钮（Rust 轮询线程实现）
- 控制栏：鼠标悬停角色区域时逐个滑入显示（锁定/设置/音量/输入四个按钮）

**对话与 AI**
- Python FastAPI + WebSocket 后端（端口 18000）
- OpenAI 兼容层统一接入，支持任意兼容厂商（base_url + api_key + model）
- 三层 Prompt 架构：角色设定层 + 记忆注入层（预留）+ 对话历史滑动窗口
- 漫画风对话气泡：打字机逐字动效、思考中三点跳动动画、8 秒后自动消失
- 发送超时保护（30 秒无响应自动重置 thinking 状态）
- LLM 错误友好提示（区分 API Key 无效、模型不存在、网络超时、频率限制等）

**设置窗口**
- 独立设置窗口（520×620，水蓝水粉二次元配色）
- LLM 配置 Tab：
  - 15 家厂商预设（DeepSeek / OpenAI / 千问 / 豆包 / 硅基流动 / Gemini / OpenRouter / MiniMax / Kimi / 智谱 / 混元 / 百川 / 启航AI / Ollama / 自定义）
  - 各厂商 API Key 独立存储，切换厂商自动加载对应 Key
  - 预设厂商 base_url 只读，防止误修改
  - 官网直达链接（调用系统浏览器打开）
  - 本地模型（Ollama）不显示 API Key 输入框
- 角色设定 Tab：
  - 最多 10 个角色预设，卡片式列表展示
  - 卡片显示头像、名称、一句话简介、生效中蓝色标识
  - 头像支持用户自行上传（base64 存储）
  - 保存时弹框确认并填写简介
  - 默认预设 Rei 不可删除，始终置于列表第一位
  - 激活预设自动同步到后端，跨会话记忆生效中的预设
- Toast 顶部通知（成功/警告两种样式）

**内置内容**
- 默认角色 Rei：傲娇猫娘，Reverie Link 吉祥物，内置完整角色设定与对话示例
- 默认头像（AI 生成，作者自有）

### 技术依赖

| 层 | 依赖 |
|----|------|
| Rust | `tauri 2`、`tauri-plugin-opener 2`、`enigo 0.2`、`serde`、`serde_json` |
| Node | `vue 3.5`、`@tauri-apps/api 2`、`@tauri-apps/plugin-opener 2`、`vite 6`、`vue-tsc` |
| Python | `fastapi`、`uvicorn[standard]`、`openai`、`python-dotenv` |

### 已知问题 / 待优化

- 锁定状态解锁按钮的出现/消失时机和动画仍有瑕疵（见 DECISIONS.md）
- API Key 目前存储在 localStorage，Phase 3 将迁移至 Tauri Rust 加密存储
- 音量按钮为占位，Phase 2 语音接入后实现真实音量控制

---

*更早的变更未单独记录，可参考 git 提交历史。*