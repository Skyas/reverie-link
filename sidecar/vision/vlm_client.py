"""
视觉感知 · VLM 客户端封装（改进版，直接替换原 vlm_client.py）

改进点：
  1. VLMResult 新增 scene_facts / scene_changed / player_state 字段
  2. JSON 解析改用括号配对，支持嵌套对象，不再被切碎
  3. scene_description 容错：VLM 返回对象/数组时自动展平为字符串
  4. game_genre 改为自由描述，不限定固定选项
  5. 新增"不确定就说 unknown"指令，减少误判
  6. 新增 player_state 字段，区分用户在操作还是在观看
  7. 增量分析新增 scene_changed 字段，检测场景内切换
"""
import base64
import json
from dataclasses import dataclass, field
from typing import Optional


# ── 结构化输出数据类 ─────────────────────────────────────────────

@dataclass
class VLMResult:
    app_name: Optional[str] = None
    scene_type: str = "unknown"        # game|video|work|browsing|idle|unknown
    game_name: Optional[str] = None
    game_genre: Optional[str] = None
    confidence: str = "low"            # high|medium|low
    interest_score: int = 1            # 1~15
    scene_description: str = ""
    scene_facts: list[str] = field(default_factory=list)    # 改进：结构化事实
    scene_changed: bool = False                              # 改进：增量模式场景质变标记
    player_state: str = "unknown"                            # 改进：playing|spectating|in_menu|cutscene|waiting|unknown

    def is_game(self) -> bool:
        return self.scene_type == "game"

    def is_player_active(self) -> bool:
        return self.player_state == "playing"


# ── 默认 VLM 配置 ────────────────────────────────────────────────

DEFAULT_VLM_BASE_URL = "https://open.bigmodel.cn/api/paas/v4/"
DEFAULT_VLM_MODEL    = "glm-4.6v-flash"


# ── Prompt 模板（改进版）─────────────────────────────────────────

_BACKGROUND_PROMPT = """\
你是一个屏幕内容分析助手。请分析以下截图的内容。

当前窗口标题：{window_title}

{prev_context}\
请以 JSON 格式返回分析结果，包含以下字段：

- app_name：当前应用名称（字符串或 null）

- scene_type：场景类型，只能是以下之一：game / video / work / browsing / idle / unknown

- game_name：如果是游戏，填写游戏名称（尽量精确，如「杀戮尖塔」「绝区零」「英雄联盟」「战舰世界」「CS2」）；否则 null

- game_genre：如果是游戏，用2-4个词自由描述游戏类型。\
示例：海战策略、战术射击FPS、卡牌Roguelike、开放世界动作RPG、\
MOBA、回合制策略、动作冒险、格斗、音乐节奏、塔防、\
模拟经营、大逃杀、平台跳跃……\
如果不是游戏则填 null

- confidence：你对判断的置信度：high / medium / low

- interest_score：画面的兴趣程度（1~15 的整数）
  评分参考：
    1 = 加载画面、静止菜单、匹配等待
    2 = 商店/设置/装备界面
    3 = 普通游戏画面（走路、探索、对话）
    5 = 比较紧张的时刻（遭遇战、关键选择）
    8 = 激烈战斗、团战、boss战
    10+ = 极度精彩时刻（多杀、通关、关键翻盘）

- player_state：用户当前的操作状态，只能是以下之一：
    playing = 用户正在操作自己的角色
    spectating = 用户正在观看他人（死亡回放、队友视角、观战）
    in_menu = 用户在菜单/商店/设置界面
    cutscene = 过场动画/剧情（不可操作）
    waiting = 加载、匹配、复活等待
    unknown = 无法判断

- scene_description：**必须是一个纯字符串**（不是对象，不是数组）。
  用1~2句**简短的**话描述当前画面（控制在50字以内）：
  · 画面里正在发生什么
  · 如果用户不在操作（死亡/观战/过场），要说明这一点
  · 可见的关键UI信息（血量/分数/倒计时/技能冷却等）
  非游戏场景用1句话描述即可，不要罗列窗口名称

- scene_facts：一个字符串数组，列出画面中值得关注的关键事实（最多3条，每条10字以内）。
  示例：
    游戏中：["血量约30%", "boss战", "队友倒地"]
    死亡中：["角色已死亡", "复活倒计时18秒"]
    菜单中：["装备商店", "金币2300"]
  非游戏场景可以为空数组 []

重要规则：
1. 请忽略截图中的敏感信息（密码、验证码、个人身份信息、财务数据、私人聊天内容）。
2. 如果你无法确定场景类型，请将 scene_type 设为 "unknown"，confidence 设为 "low"。宁可不确定，也不要猜测。
3. scene_description 必须是纯字符串，不要返回嵌套的 JSON 对象或数组。
4. 不要假设画面中的操作主体就是用户。如果画面显示的是死亡画面、回放、观战，请在 player_state 和 scene_description 中如实说明。
5. 截图中可能会出现一个桌面宠物（Live2D 角色，通常在屏幕边缘），这不是游戏或应用的一部分，请完全忽略它，不要在描述中提及。
6. 保持 JSON 紧凑，所有文本字段尽量简短。整个 JSON 应控制在 300 字以内。

只返回 JSON，不要任何其他文字。"""


_USER_TRIGGERED_PROMPT = """\
你是一个屏幕内容分析助手。用户希望你仔细观察当前屏幕画面。

当前窗口标题：{window_title}

{prev_context}\
请详细分析截图内容，以 JSON 格式返回：
- app_name：当前应用名称（字符串或 null）
- scene_type：场景类型，只能是以下之一：game / video / work / browsing / idle / unknown
- game_name：如果是游戏，填写游戏名称；否则 null
- game_genre：如果是游戏，用2-4个词自由描述游戏类型；否则 null
- confidence：你对判断的置信度：high / medium / low
- interest_score：画面的兴趣程度（1~15 的整数）
- player_state：playing / spectating / in_menu / cutscene / waiting / unknown
- scene_description：**纯字符串**，用1~2句简短的话描述当前画面内容（控制在50字以内）
- scene_facts：字符串数组，列出画面中的关键事实（最多3条，每条10字以内）

重要：请忽略截图中的敏感信息。scene_description 必须是纯字符串。\
如果无法确定场景类型，scene_type 填 "unknown"，confidence 填 "low"。

只返回 JSON，不要任何其他文字。"""


_INCREMENTAL_PROMPT = """\
你是一个屏幕内容分析助手。当前正在持续观察同一应用的画面。

当前窗口标题：{window_title}
已知场景：{scene_type}（{game_info}）

{prev_context}\
请分析当前帧，以 JSON 格式返回（只需以下字段，其余沿用上次）：

- confidence：high / medium / low
- interest_score：相对于上一帧的变化程度（1~15 的整数）
  评分参考：
    1 = 画面与上次基本相同，无明显变化
    3 = 画面有轻微变化（角色移动、普通操作）
    5 = 发生了值得注意的事件（击杀、被击杀、技能释放）
    8 = 重大事件（连杀、boss出现、团战爆发）
    10+ = 极其罕见的精彩时刻
  注意：持续的战斗画面如果和上一帧差不多，应该评 1-3 分，
  不要因为"画面里有战斗"就一直给高分。只有新发生的事件才应该高分。
- player_state：playing / spectating / in_menu / cutscene / waiting / unknown
- scene_description：**纯字符串**，1~2句简短描述当前画面（50字以内）
- scene_facts：字符串数组，列出关键事实（最多3条，每条10字以内）
- scene_changed：布尔值。以下情况返回 true：
    · 从菜单进入游戏（或反过来）
    · 从存活变为死亡（或反过来）
    · 从对话/过场进入战斗（或反过来）
    · 游戏阶段性切换（如从对线期进入团战期）
  其他情况返回 false

重要：scene_description 必须是纯字符串。不要假设画面中操作主体就是用户。
重要：如果当前画面与你上次描述的场景基本相同（同一个界面、同一场战斗、同样的元素），
请将 scene_description 填写为"画面无明显变化"，interest_score 填 1。
不要用不同的措辞重复描述已经描述过的内容。只有画面中发生了新的事件或出现了新的变化时，才需要详细描述。

只返回 JSON，不要任何其他文字。"""


# ── 前文上下文构建 ───────────────────────────────────────────────

def _build_prev_context(prev_descriptions: list[str]) -> str:
    if not prev_descriptions:
        return ""
    lines = "\n".join(f"[{i * 10}秒前] {d}" for i, d in enumerate(reversed(prev_descriptions), 1))
    return f"前文观察记录：\n{lines}\n\n"


def _build_prompt(
    prompt_type: str,
    window_title: str,
    prev_descriptions: list[str],
    scene_type: str = "unknown",
    game_name: Optional[str] = None,
    game_genre: Optional[str] = None,
) -> str:
    prev_ctx = _build_prev_context(prev_descriptions)

    if prompt_type == "user_triggered":
        return _USER_TRIGGERED_PROMPT.format(
            window_title=window_title or "（未知）",
            prev_context=prev_ctx,
        )
    elif prompt_type == "incremental":
        game_info = ""
        if game_name:
            game_info = f"{game_name}"
            if game_genre:
                game_info += f" / {game_genre}"
        return _INCREMENTAL_PROMPT.format(
            window_title=window_title or "（未知）",
            scene_type=scene_type,
            game_info=game_info or "未知游戏",
            prev_context=prev_ctx,
        )
    else:  # background
        return _BACKGROUND_PROMPT.format(
            window_title=window_title or "（未知）",
            prev_context=prev_ctx,
        )


# ── JSON 提取（改进版：支持嵌套对象）────────────────────────────

def _extract_json(raw: str) -> Optional[dict]:
    """
    从 VLM 回复中提取完整的 JSON 对象。

    原方案 re.search(r'\\{.*?\\}') 用非贪婪匹配，
    遇到第一个 } 就截断。如果 VLM 返回嵌套 JSON
    （如 scene_description 是对象），内层 } 会导致截断，
    后续 json.loads 报 "Expecting ',' delimiter" 错误。

    新方案：用括号深度配对，找到完整的 JSON 块。
    """
    # 先去掉 markdown 代码块标记
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        # 去掉开头的 ```json 和结尾的 ```
        lines = cleaned.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines)

    # 找第一个 {
    start = cleaned.find('{')
    if start == -1:
        return None

    # 括号配对
    depth = 0
    in_string = False
    escape_next = False
    end = start

    for i in range(start, len(cleaned)):
        ch = cleaned[i]

        if escape_next:
            escape_next = False
            continue

        if ch == '\\':
            escape_next = True
            continue

        if ch == '"':
            in_string = not in_string
            continue

        if in_string:
            continue

        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                end = i + 1
                break

    if depth != 0:
        return None

    try:
        return json.loads(cleaned[start:end])
    except json.JSONDecodeError:
        return None


# ── scene_description 容错处理 ───────────────────────────────────

def _normalize_scene_description(raw_desc) -> str:
    """
    VLM 有时会把 scene_description 返回为嵌套对象或数组，
    需要展平为字符串。

    处理的情况：
      "scene_description": "正常的字符串"          → 直接返回
      "scene_description": {"current_action": ...}  → 把值拼接起来
      "scene_description": ["句子1", "句子2"]       → 用分号连接
    """
    if isinstance(raw_desc, str):
        return raw_desc

    if isinstance(raw_desc, dict):
        parts = []
        for key, value in raw_desc.items():
            if isinstance(value, str) and value:
                parts.append(value)
            elif isinstance(value, list):
                parts.extend(str(v) for v in value if v)
        return "；".join(parts) if parts else ""

    if isinstance(raw_desc, list):
        return "；".join(str(item) for item in raw_desc if item)

    return str(raw_desc) if raw_desc else ""


# ── JSON → VLMResult 解析 ────────────────────────────────────────

def _parse_vlm_response(raw: str, incremental: bool = False, base: Optional[VLMResult] = None) -> VLMResult:
    """从 VLM 回复中提取 JSON 并解析为 VLMResult"""

    # 改进：用括号配对提取 JSON（支持嵌套）
    data = _extract_json(raw)
    if data is None:
        print(f"[VLM] 无法从回复中提取 JSON: {raw[:200]}")
        return base or VLMResult()

    # 改进：scene_description 容错处理
    scene_desc = _normalize_scene_description(data.get("scene_description", ""))

    # 改进：scene_facts 容错
    scene_facts = data.get("scene_facts", [])
    if not isinstance(scene_facts, list):
        scene_facts = []
    scene_facts = [str(f) for f in scene_facts if f]

    result = VLMResult(
        confidence=data.get("confidence", "low"),
        interest_score=max(1, min(15, int(data.get("interest_score", 1)))),
        scene_description=scene_desc,
        scene_facts=scene_facts,
        scene_changed=bool(data.get("scene_changed", False)),
        player_state=data.get("player_state", "unknown"),
    )

    if incremental and base:
        # 增量模式：只更新动态字段，其余沿用上次
        result.app_name   = base.app_name
        result.scene_type = base.scene_type
        result.game_name  = base.game_name
        result.game_genre = base.game_genre
    else:
        result.app_name   = data.get("app_name") or None
        result.scene_type = data.get("scene_type", "unknown")
        result.game_name  = data.get("game_name") or None
        result.game_genre = data.get("game_genre") or None

    return result


# ── VLM 客户端（与原版完全一致，无改动）─────────────────────────

class VLMClient:
    """
    VLM 调用封装。
    优先级：主模型（多模态）→ 独立配置 VLM → 不可用。
    """

    def __init__(self):
        self._vlm_base_url: str = DEFAULT_VLM_BASE_URL
        self._vlm_api_key: str  = ""
        self._vlm_model: str    = DEFAULT_VLM_MODEL
        self._main_client = None
        self._main_model: str = ""

    def configure_vlm(self, base_url: str, api_key: str, model: str):
        self._vlm_base_url = base_url or DEFAULT_VLM_BASE_URL
        self._vlm_api_key  = api_key or ""
        self._vlm_model    = model or DEFAULT_VLM_MODEL

    def set_main_client(self, client, model: str):
        """注入主文本 LLM 客户端引用，用于多模态 fallback"""
        self._main_client = client
        self._main_model  = model

    def is_available(self) -> bool:
        """检查 VLM 是否可用（主模型多模态 或 有独立 VLM API Key）"""
        return (self._main_client is not None and self._main_is_multimodal()) or bool(self._vlm_api_key)

    def _get_multimodal_models(self) -> set:
        """已知支持多模态（Vision）的主模型名称关键词"""
        return {"gpt-4o", "gpt-4-vision", "claude-3", "claude-opus", "claude-sonnet", "claude-haiku",
                "gemini", "glm-4v", "qwen-vl", "yi-vision"}

    def _main_is_multimodal(self) -> bool:
        if not self._main_model:
            return False
        model_lower = self._main_model.lower()
        return any(kw in model_lower for kw in self._get_multimodal_models())

    async def analyze(
        self,
        img_bytes: bytes,
        window_title: str = "",
        prompt_type: str = "background",
        prev_descriptions: list[str] = None,
        base_result: Optional[VLMResult] = None,
        scene_type: str = "unknown",
        game_name: Optional[str] = None,
        game_genre: Optional[str] = None,
    ) -> Optional[VLMResult]:
        """
        分析截图。自动选择最合适的 VLM：
          ① 主模型（若支持多模态）→ 无条件最高优先
          ② 独立配置的 VLM（有 API Key）
          ③ 不可用（返回 None）
        """
        from openai import AsyncOpenAI

        prev_descriptions = prev_descriptions or []
        incremental = (prompt_type == "incremental")

        prompt = _build_prompt(
            prompt_type=prompt_type,
            window_title=window_title,
            prev_descriptions=prev_descriptions,
            scene_type=scene_type,
            game_name=game_name,
            game_genre=game_genre,
        )

        img_b64 = base64.b64encode(img_bytes).decode()
        img_url = f"data:image/jpeg;base64,{img_b64}"

        client, model = self._select_client()
        if client is None:
            return None

        try:
            response = await client.chat.completions.create(
                model=model,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text",      "text": prompt},
                        {"type": "image_url", "image_url": {"url": img_url}},
                    ],
                }],
                max_tokens=1200,   # 改进：从 300 提高到 500，因为新增了 scene_facts 等字段
                temperature=0.1,
            )
            raw = response.choices[0].message.content.strip()
            return _parse_vlm_response(raw, incremental=incremental, base=base_result)
        except Exception as e:
            print(f"[VLM] 调用失败 (model={model}): {e}")
            return None

    def _select_client(self):
        """
        按优先级选择 VLM 客户端：
          ① 主模型支持多模态 → 无条件使用主模型（最高优先）
          ② 用户单独配置了 VLM（有 API Key）→ 使用配置的 VLM
          ③ 都没有 → 不可用
        """
        from openai import AsyncOpenAI

        print(f"[VLM选择] vlm_model={self._vlm_model}, vlm_base_url={self._vlm_base_url[:30]}...")
        print(f"[VLM选择] vlm_api_key={'有' if self._vlm_api_key else '无'}")
        print(f"[VLM选择] main_model={self._main_model}, main_client={'有' if self._main_client else '无'}")
        print(f"[VLM选择] main_is_multimodal={self._main_is_multimodal()}")

        # 优先级①：主模型支持多模态 → 无条件使用主模型
        if self._main_client and self._main_is_multimodal():
            print(f"[VLM选择] → 使用主模型 {self._main_model}（多模态）")
            return self._main_client, self._main_model

        # 优先级②：用户配置了独立 VLM（有 API Key）
        if self._vlm_api_key:
            print(f"[VLM选择] → 使用独立VLM {self._vlm_model}")
            client = AsyncOpenAI(api_key=self._vlm_api_key, base_url=self._vlm_base_url)
            return client, self._vlm_model

        # 无可用视觉模型
        print("[VLM选择] → 无可用视觉模型")
        return None, None