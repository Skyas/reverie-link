# 开发决策记录 (DECISIONS.md)

## [Phase 1 → Phase 2] 窗口控制入口

- **Phase 1 已实现**：系统托盘（Tray）菜单，提供锁定/解锁鼠标穿透、退出等基础操作。
- **Phase 2 待实现**：在 Live2D 角色旁边添加悬浮"把手"按钮（不穿透），
  点击后切换整个窗口的穿透状态，与托盘菜单功能并行共存。
  参考风格：类似音乐软件歌词面板的边缘控制条。
  对应说明书：模块1「控制机制：方案B」。

## [Phase 1] 后端消息结构

WebSocket 传输格式：
- 前端 → 后端：{"type": "chat", "message": "用户输入"}
- 后端 → 前端：{"type": "chat_response", "message": "AI回复"}

## [Phase 1] LLM接入方式

统一使用 OpenAI 兼容层，用户只需配置：
- base_url（内置常用厂商预设）
- api_key
- model_name

支持：DeepSeek、Gemini、OpenAI、硅基流动、Ollama本地部署、任意兼容厂商。

## [Phase 1] System Prompt 三层架构

- Layer 1：角色设定（每次必带，固定）
- Layer 2：记忆注入（Phase 3 实现，暂空）
- Layer 3：对话历史滑动窗口

## [Phase 1] 角色模板字段

必填：name / identity / personality / address / style
选填：examples（1-3组对话示例，进阶用）

酒馆卡片(chara_card_v2)导入功能保留但降低优先级，不在Phase 1实现。

动态角色状态切换不通过多卡实现，由Phase 3记忆模块自然体现。