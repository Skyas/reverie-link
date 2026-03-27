"""
视觉感知 · 游戏检测模块

负责：
  - 本地 OS 级检测（进程名 / 游戏平台目录）
  - 已知游戏列表匹配（data/known_games.json）
  - 手动观战模式开关
  - 新游戏自动追加到已知列表

检测优先级（高→低）：
  手动标记 → 已知游戏列表 → 游戏平台目录 → VLM 结果
"""
import json
from pathlib import Path
from typing import Optional


# ── 已知游戏列表路径 ────────────────────────────────────────────

_KNOWN_GAMES_PATH = Path(__file__).parent.parent.parent / "data" / "known_games.json"

# 游戏平台安装目录关键词
_GAME_PLATFORM_DIRS = [
    "steam/steamapps/common/",
    "steamapps/common/",
    "epic games/",
    "wegame/",
    "riot games/",
    "battle.net/",
    "ubisoft/",
    "origin games/",
    "ea games/",
]


class GameDetector:
    """游戏检测器"""

    def __init__(self):
        self._known_games: list[dict] = []   # [{process, name}, ...]
        self._manual_game_mode: bool = False
        self._load_known_games()

    # ── 手动观战模式 ────────────────────────────────────────────

    def set_manual_game_mode(self, enabled: bool):
        self._manual_game_mode = enabled

    def is_manual_game_mode(self) -> bool:
        return self._manual_game_mode

    # ── 已知游戏列表 ────────────────────────────────────────────

    def _load_known_games(self):
        try:
            if _KNOWN_GAMES_PATH.exists():
                data = json.loads(_KNOWN_GAMES_PATH.read_text(encoding="utf-8"))
                self._known_games = data.get("games", [])
        except Exception as e:
            print(f"[GameDetector] 加载 known_games.json 失败: {e}")
            self._known_games = []

    def _save_known_games(self):
        try:
            _KNOWN_GAMES_PATH.parent.mkdir(parents=True, exist_ok=True)
            data = {"games": self._known_games}
            _KNOWN_GAMES_PATH.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
        except Exception as e:
            print(f"[GameDetector] 保存 known_games.json 失败: {e}")

    def add_known_game(self, process_name: str, game_name: str):
        """将 VLM 识别到的新游戏追加到已知列表"""
        if not process_name or not game_name:
            return
        proc_lower = process_name.lower()
        for entry in self._known_games:
            if entry.get("process", "").lower() == proc_lower:
                return  # 已存在，不重复添加
        self._known_games.append({"process": process_name, "name": game_name})
        self._save_known_games()
        print(f"[GameDetector] 新游戏已记录: {process_name} → {game_name}")

    # ── 检测逻辑 ────────────────────────────────────────────────

    def detect(self, process_info: dict, vlm_scene_type: Optional[str] = None,
               vlm_game_name: Optional[str] = None) -> dict:
        """
        综合检测当前是否在玩游戏。

        返回:
          {
            "is_game": bool,
            "game_name": str | None,  # 识别出的游戏名称
            "source": str,            # manual|known_list|platform_dir|vlm|none
          }
        """
        # ① 手动标记（最高优先）
        if self._manual_game_mode:
            return {"is_game": True, "game_name": vlm_game_name, "source": "manual"}

        process_name = process_info.get("process_name", "")
        process_path = process_info.get("process_path", "")

        # ② 已知游戏列表匹配（进程名）
        if process_name:
            proc_lower = process_name.lower()
            for entry in self._known_games:
                if entry.get("process", "").lower() == proc_lower:
                    return {"is_game": True, "game_name": entry.get("name"), "source": "known_list"}

        # ③ 游戏平台目录匹配
        if process_path:
            path_lower = process_path.replace("\\", "/").lower()
            for platform_dir in _GAME_PLATFORM_DIRS:
                if platform_dir in path_lower:
                    return {"is_game": True, "game_name": vlm_game_name, "source": "platform_dir"}

        # ④ VLM 分析结果（scene_type = game）
        if vlm_scene_type == "game":
            # 若 VLM 识别出游戏名且有进程名，尝试追加到已知列表
            if vlm_game_name and process_name:
                self.add_known_game(process_name, vlm_game_name)
            return {"is_game": True, "game_name": vlm_game_name, "source": "vlm"}

        return {"is_game": False, "game_name": None, "source": "none"}
