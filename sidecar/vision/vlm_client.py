"""
视觉感知 · VLM 客户端封装

负责：
  - 调用 VLM API（OpenAI 兼容格式）分析截图
  - 解析结构化 JSON 输出
  - 图片 base64 编码
  - 自动 fallback 逻辑（专用 VLM → 主模型 → GLM-4V-Flash）
"""
import base64
import json
import re
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

    def is_game(self) -> bool:
        return self.scene_type == "game"


# ── 默认 VLM 配置 ────────────────────────────────────────────────

DEFAULT_VLM_BASE_URL = "https://open.bigmodel.cn/api/paas/v4/"
DEFAULT_VLM_MODEL    = "glm-4v-flash"


# ── Prompt 模板 ──────────────────────────────────────────────────

_BACKGROUND_PROMPT = """\
你是一个屏幕内容分析助手。请分析以下截图的内容。

当前窗口标题：{window_title}

{prev_context}\
请以 JSON 格式返回分析结果，包含以下字段：
- app_name：当前应用名称（字符串或 null）
- scene_type：场景类型，只能是以下之一：game / video / work / browsing / idle / unknown
- game_name：如果是游戏，填写游戏名称（尽量精确，如「杀戮尖塔」「绝区零」「英雄联盟」）；否则 null
- game_genre：如果是游戏，填写游戏类型（如 roguelike / 动作RPG / FPS / MOBA 等）；否则 null
- confidence：你对判断的置信度：high / medium / low
- interest_score：画面的兴趣程度（1~15 的整数）
  评分参考：1=静止菜单，3=普通场景，6=激烈战斗/精彩时刻，10+=高分/BOSS/通关等关键事件
- scene_description：
  · 如果是游戏：用2~3句话描述当前游戏画面，**必须**包含：正在发生什么（战斗/探索/对话/过场等）、\
可见的重要UI信息（血量/分数/关卡/手牌/技能等）、任何值得评论的有趣细节
  · 其他场景：用1句话描述即可

重要：请忽略截图中可能出现的以下敏感信息，不要在描述中提及：密码、验证码、\
个人身份信息（身份证号、手机号、邮箱地址等）、财务数据（银行卡号、余额、\
交易记录等）、私人聊天内容。仅描述画面的整体场景和视觉元素。

只返回 JSON，不要任何其他文字。"""

_USER_TRIGGERED_PROMPT = """\
你是一个屏幕内容分析助手。用户希望你仔细观察当前屏幕画面。

当前窗口标题：{window_title}

{prev_context}\
请详细分析截图内容，以 JSON 格式返回：
- app_name：当前应用名称（字符串或 null）
- scene_type：场景类型，只能是以下之一：game / video / work / browsing / idle / unknown
- game_name：如果是游戏，填写游戏名称；否则 null
- game_genre：如果是游戏，填写游戏类型；否则 null
- confidence：你对判断的置信度：high / medium / low
- interest_score：画面的兴趣程度（1~15 的整数）
- scene_description：用 2~3 句话详细描述当前画面内容，包括关键细节

重要：请忽略截图中可能出现的密码、验证码、个人身份信息、财务数据、私人聊天内容。

只返回 JSON，不要任何其他文字。"""

_INCREMENTAL_PROMPT = """\
你是一个屏幕内容分析助手。当前正在持续观察同一应用的画面。

当前窗口标题：{window_title}
已知场景：{scene_type}（{game_info}）

{prev_context}\
请分析当前帧的画面变化，以 JSON 格式返回（只需以下字段，其余字段沿用上次结果）：
- confidence：你对判断的置信度：high / medium / low
- interest_score：画面的兴趣程度（1~15 的整数）
  评分参考：1=无变化，3=普通场景变化，6=激烈战斗/技能爆发，10+=BOSS/通关/意外事件
- scene_description：
  · 如果是游戏：用2~3句话描述当前画面，包含正在发生什么和可见的关键信息（血量/分数/手牌等）
  · 其他场景：用1句话描述即可

重要：请忽略截图中的敏感信息（密码、个人信息、财务数据、私人聊天）。

只返回 JSON，不要任何其他文字。"""


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


# ── JSON 解析 ────────────────────────────────────────────────────

def _parse_vlm_response(raw: str, incremental: bool = False, base: Optional[VLMResult] = None) -> VLMResult:
    """从 VLM 回复中提取 JSON 并解析为 VLMResult"""
    # 提取 JSON 块（LLM 有时会加 markdown 代码块）
    match = re.search(r'\{.*?\}', raw, re.DOTALL)
    if not match:
        print(f"[VLM] 无法从回复中提取 JSON: {raw[:200]}")
        return base or VLMResult()

    try:
        data = json.loads(match.group())
    except json.JSONDecodeError as e:
        print(f"[VLM] JSON 解析失败: {e}, raw={raw[:200]}")
        return base or VLMResult()

    result = VLMResult(
        confidence=data.get("confidence", "low"),
        interest_score=max(1, min(15, int(data.get("interest_score", 1)))),
        scene_description=data.get("scene_description", ""),
    )

    if incremental and base:
        # 增量模式：只更新这三个字段，其余沿用上次
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


# ── VLM 客户端 ───────────────────────────────────────────────────

class VLMClient:
    """
    VLM 调用封装。
    支持自动 fallback：专用 VLM → 主模型（若多模态）→ GLM-4V-Flash。
    """

    def __init__(self):
        self._vlm_base_url: str = DEFAULT_VLM_BASE_URL
        self._vlm_api_key: str  = ""
        self._vlm_model: str    = DEFAULT_VLM_MODEL
        # 主模型引用（由外部注入，用于判断是否支持多模态）
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
        """检查 VLM 是否可用（有 API Key）"""
        return bool(self._vlm_api_key)

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
        prompt_type: str = "background",   # "background" | "user_triggered" | "incremental"
        prev_descriptions: list[str] = None,
        base_result: Optional[VLMResult] = None,
        scene_type: str = "unknown",
        game_name: Optional[str] = None,
        game_genre: Optional[str] = None,
    ) -> Optional[VLMResult]:
        """
        分析截图。自动选择最合适的 VLM：
          ① 专用 VLM（有 API Key）
          ② 主模型（若支持多模态）
          ③ GLM-4V-Flash（兜底，仍需 API Key）
          ④ 不可用（返回 None）
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

        # 图片编码
        img_b64 = base64.b64encode(img_bytes).decode()
        img_url = f"data:image/jpeg;base64,{img_b64}"

        # 选择客户端
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
                max_tokens=300,
                temperature=0.1,
            )
            raw = response.choices[0].message.content.strip()
            return _parse_vlm_response(raw, incremental=incremental, base=base_result)
        except Exception as e:
            print(f"[VLM] 调用失败 (model={model}): {e}")
            return None

    def _select_client(self):
        """按优先级选择 VLM 客户端"""
        from openai import AsyncOpenAI

        # ① 专用 VLM
        if self._vlm_api_key:
            client = AsyncOpenAI(api_key=self._vlm_api_key, base_url=self._vlm_base_url)
            return client, self._vlm_model

        # ② 主模型（若多模态）
        if self._main_client and self._main_is_multimodal():
            return self._main_client, self._main_model

        # ③ GLM-4V-Flash 兜底（无 Key 则不可用）
        return None, None
