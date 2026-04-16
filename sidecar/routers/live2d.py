"""
Reverie Link · Live2D 路由

负责扫描本地 Live2D 模型文件夹，并对 model3.json 执行自动修复：
  - _auto_fix_motions：补全缺失的 Motions 字段
  - _optimize_idle_fade：检测帧切换型 idle，禁用 crossfade 防闪烁
"""

import os
import json
from pathlib import Path

from fastapi import APIRouter
import logging
logger = logging.getLogger(__name__)

# ── 路径常量（相对于项目根目录）─────────────────────────────────
# 本文件位于 sidecar/routers/live2d.py，向上三层到项目根
LIVE2D_DIR = Path(__file__).parent.parent.parent / "public" / "live2d"

router = APIRouter()


@router.get("/api/folder-paths")
async def get_folder_paths():
    base = Path(__file__).parent.parent.parent  # sidecar/../.. = 项目根
    live2d_dir = (base / "public" / "live2d").resolve()
    rvc_dir    = (base / "public" / "rvc").resolve()
    
    # 【核心修复】确保物理目录存在，避免操作系统找不到路径而报错
    live2d_dir.mkdir(parents=True, exist_ok=True)
    rvc_dir.mkdir(parents=True, exist_ok=True)
    
    live2d_path_str = os.path.normpath(str(live2d_dir))
    rvc_path_str = os.path.normpath(str(rvc_dir))

    logger.info("[FolderPaths] live2d=%s rvc=%s", live2d_path_str, rvc_path_str)
    return {
        "live2d": live2d_path_str,
        "rvc":    rvc_path_str,
    }
    
@router.get("/api/live2d/models")
async def list_live2d_models():
    """
    扫描 public/live2d/ 目录，返回所有可用模型列表。
    每个子文件夹只要包含 *.model3.json 就被识别为一个模型。
    自动执行 motions 补全和 idle fade 优化（用户无感）。
    """
    if not LIVE2D_DIR.exists():
        return {"models": [], "error": f"目录不存在：{LIVE2D_DIR}"}

    models = []
    for folder in sorted(LIVE2D_DIR.iterdir()):
        if not folder.is_dir():
            continue

        model_files = sorted(folder.glob("*.model3.json"))
        if not model_files:
            continue

        model_file = model_files[0]

        try:
            _auto_fix_motions(folder, model_file)
        except Exception as e:
            logger.warning("[AutoFix] %s 修复失败（跳过）: %s", folder.name, e)

        try:
            _optimize_idle_fade(folder, model_file)
        except Exception as e:
            logger.warning("[AutoFix] %s idle 优化失败（跳过）: %s", folder.name, e)

        display_name = folder.name.replace("_", " ").replace("-", " ")
        models.append({
            "folder":       folder.name,
            "display_name": display_name,
            "path":         f"live2d/{folder.name}/{model_file.name}",
        })

    return {"models": models}


# ── 内部工具函数 ───────────────────────────────────────────────

def _auto_fix_motions(folder: Path, model_file: Path) -> None:
    """
    检查 model3.json 是否缺少 Motions 字段。
    若缺少，且存在 animations/ 或 motion/ 子目录，则自动将其中的
    motion3.json 文件注册进去，idle 动画优先（文件名含 idle 或排序第一个）。
    已有 Motions 字段的模型跳过，不做修改。
    """
    with open(model_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    file_refs = data.get("FileReferences", {})

    if file_refs.get("Motions"):
        return

    motion_dir = None
    for candidate in ["animations", "motion"]:
        p = folder / candidate
        if p.is_dir():
            motion_dir = p
            break

    if motion_dir is None:
        return

    motion_files = sorted(motion_dir.glob("*.motion3.json"))
    if not motion_files:
        return

    idle_candidates = [f for f in motion_files if "idle" in f.name.lower()]
    idle_file = idle_candidates[0] if idle_candidates else motion_files[0]

    rel_dir = motion_dir.name

    file_refs["Motions"] = {
        "Idle": [{"File": f"{rel_dir}/{idle_file.name}", "FadeInTime": 0.5, "FadeOutTime": 0.5}],
        "":     [{"File": f"{rel_dir}/{f.name}", "FadeInTime": 0.3, "FadeOutTime": 0.3}
                 for f in motion_files if f != idle_file],
    }
    data["FileReferences"] = file_refs

    with open(model_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent="\t")

    logger.info("[AutoFix] %s: 自动注入 Motions（idle=%s，共 %s 个动作）", folder.name, idle_file.name, len(motion_files))


def _optimize_idle_fade(folder: Path, model_file: Path) -> None:
    """
    检测 idle 动作是否为「帧切换型」（线稿逐帧抖动等），自动优化 model3.json。

    判定规则：idle 动作数 > 1 且所有 idle motion 的 Duration 均 < 2 秒。
    此类动作依赖 stepped 插值做 0/1 跳变来切换绘画帧，
    pixi-live2d-display 的 crossfade 会将跳变值线性混合，
    导致多帧叠加显示（视觉上表现为闪烁）。

    修复策略：只保留第一个 idle，FadeInTime/FadeOutTime 设为 0。
    """
    with open(model_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    file_refs = data.get("FileReferences", {})
    motions   = file_refs.get("Motions", {})
    idle_list = motions.get("Idle", [])

    if len(idle_list) <= 1:
        return

    DURATION_THRESHOLD = 2.0

    for motion_entry in idle_list:
        motion_rel  = motion_entry.get("File", "")
        if not motion_rel:
            return
        motion_path = folder / motion_rel
        if not motion_path.exists():
            return
        try:
            with open(motion_path, "r", encoding="utf-8") as f:
                motion_data = json.load(f)
            duration = motion_data.get("Meta", {}).get("Duration", 999)
            if duration >= DURATION_THRESHOLD:
                return
        except Exception:
            return

    first_idle = idle_list[0].copy()
    first_idle["FadeInTime"]  = 0
    first_idle["FadeOutTime"] = 0
    motions["Idle"]           = [first_idle]
    file_refs["Motions"]      = motions
    data["FileReferences"]    = file_refs

    with open(model_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent="\t")

    logger.info("[AutoFix] %s: 检测到帧切换型 idle（全部 Duration < %ss），已精简为 1 个动作并禁用 crossfade", folder.name, DURATION_THRESHOLD)