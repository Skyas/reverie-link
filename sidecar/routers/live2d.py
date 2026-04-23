"""
Reverie Link · Live2D 路由

负责扫描本地 Live2D 模型文件夹，并对 model3.json 执行自动修复：
  - _auto_fix_motions：补全缺失的 Motions 字段
  - _optimize_idle_fade：检测帧切换型 idle，禁用 crossfade 防闪烁

Phase 4 新增：装扮系统接口
  - GET  /api/live2d/appearance-schema  返回 cdi3.json 解析 + 已存装扮配置
  - POST /api/live2d/appearance         保存装扮配置
"""

import os
import json
from pathlib import Path
from typing import Dict, Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

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

    print(f"[FolderPaths] live2d={live2d_path_str} rvc={rvc_path_str}")
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
            print(f"[AutoFix] {folder.name} 修复失败（跳过）: {e}")

        try:
            _optimize_idle_fade(folder, model_file)
        except Exception as e:
            print(f"[AutoFix] {folder.name} idle 优化失败（跳过）: {e}")

        display_name = folder.name.replace("_", " ").replace("-", " ")
        models.append({
            "folder":       folder.name,
            "display_name": display_name,
            "path":         f"live2d/{folder.name}/{model_file.name}",
        })

    return {"models": models}


# ════════════════════════════════════════════════════════════════
# ── Phase 4：装扮系统接口 ──────────────────────────────────────
# ════════════════════════════════════════════════════════════════

class AppearancePayload(BaseModel):
    """POST /api/live2d/appearance 的请求体"""
    folder: str
    parameters: Dict[str, float]   # { "ParamHairLength": 0.65, ... }
    parts:      Dict[str, int]     # { "PartGlasses01": 1, ... } (0/1)


def _resolve_model_folder(folder_name: str) -> Path:
    """
    安全地解析模型文件夹路径。
    防御路径穿越（folder 含 ".." / "/" / "\\" 等）。
    解析后必须真实存在且位于 LIVE2D_DIR 之下。
    """
    if not folder_name or any(ch in folder_name for ch in ("..", "/", "\\", ":")):
        raise HTTPException(status_code=400, detail=f"非法的 folder 名: {folder_name!r}")

    target = (LIVE2D_DIR / folder_name).resolve()
    base   = LIVE2D_DIR.resolve()

    # is_relative_to 是 Python 3.9+ 的方法，保险起见用字符串前缀比较
    try:
        target.relative_to(base)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"folder 越界: {folder_name!r}")

    if not target.is_dir():
        raise HTTPException(status_code=404, detail=f"模型文件夹不存在: {folder_name!r}")

    return target


def _read_cdi3(folder: Path) -> Dict[str, Any]:
    """
    读取并解析 *.cdi3.json，返回标准化结构：
      {
        "has_cdi": bool,
        "parameters":       [{id, name, group_id}, ...],
        "parameter_groups": [{id, name}, ...],
        "parts":            [{id, name}, ...],
      }
    缺失或解析失败时 has_cdi=False，三个数组均为空。
    """
    cdi_files = sorted(folder.glob("*.cdi3.json"))
    if not cdi_files:
        return {
            "has_cdi": False,
            "parameters": [],
            "parameter_groups": [],
            "parts": [],
        }

    try:
        with open(cdi_files[0], "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"[Appearance] {folder.name} cdi3.json 解析失败: {e}")
        return {
            "has_cdi": False,
            "parameters": [],
            "parameter_groups": [],
            "parts": [],
        }

    parameters = [
        {
            "id":       p.get("Id", ""),
            "name":     p.get("Name", ""),
            "group_id": p.get("GroupId", ""),
        }
        for p in data.get("Parameters", [])
        if p.get("Id")
    ]

    parameter_groups = [
        {
            "id":   g.get("Id", ""),
            "name": g.get("Name", ""),
        }
        for g in data.get("ParameterGroups", [])
        if g.get("Id")
    ]

    parts = [
        {
            "id":   p.get("Id", ""),
            "name": p.get("Name", ""),
        }
        for p in data.get("Parts", [])
        if p.get("Id")
    ]

    return {
        "has_cdi": True,
        "parameters": parameters,
        "parameter_groups": parameter_groups,
        "parts": parts,
    }


def _read_appearance(folder: Path) -> Dict[str, Any] | None:
    """
    读取 appearance.json。不存在或解析失败时返回 None。
    返回结构：{ "parameters": {id: value}, "parts": {id: 0|1} }
    """
    fp = folder / "appearance.json"
    if not fp.is_file():
        return None
    try:
        with open(fp, "r", encoding="utf-8") as f:
            data = json.load(f)
        # 形态校验
        params = data.get("parameters", {})
        parts  = data.get("parts", {})
        if not isinstance(params, dict) or not isinstance(parts, dict):
            print(f"[Appearance] {folder.name} appearance.json 结构异常，按空配置处理")
            return None
        return {"parameters": params, "parts": parts}
    except Exception as e:
        print(f"[Appearance] {folder.name} appearance.json 读取失败: {e}")
        return None


@router.get("/api/live2d/appearance-schema")
async def get_appearance_schema(folder: str = Query(..., description="模型文件夹名")):
    """
    返回指定模型的装扮 schema + 已存配置。
    前端拿到后即可渲染滑条/开关并还原数值。

    响应：
      {
        "folder": "hiyori_vts",
        "has_cdi": true,
        "parameters":       [{id, name, group_id}, ...],
        "parameter_groups": [{id, name}, ...],
        "parts":            [{id, name}, ...],
        "appearance":       {parameters: {id: v}, parts: {id: 0|1}} | null
      }
    """
    target = _resolve_model_folder(folder)

    cdi = _read_cdi3(target)
    appearance = _read_appearance(target)

    print(
        f"[Appearance] schema fetched for {folder}: "
        f"has_cdi={cdi['has_cdi']} "
        f"params={len(cdi['parameters'])} "
        f"parts={len(cdi['parts'])} "
        f"appearance={'present' if appearance else 'none'}"
    )

    return {
        "folder":           folder,
        "has_cdi":          cdi["has_cdi"],
        "parameters":       cdi["parameters"],
        "parameter_groups": cdi["parameter_groups"],
        "parts":            cdi["parts"],
        "appearance":       appearance,
    }


@router.post("/api/live2d/appearance")
async def save_appearance(payload: AppearancePayload):
    """
    全量覆盖写入 appearance.json。
    
    body:
      {
        "folder": "hiyori_vts",
        "parameters": { "ParamHairLength": 0.65, ... },
        "parts":      { "PartGlasses01": 1, ... }
      }
    
    返回：{ "ok": true, "path": "<绝对路径>" }
    """
    target = _resolve_model_folder(payload.folder)

    # 数值/类型轻校验：parameters 全为 float、parts 全为 0/1
    parameters_clean: Dict[str, float] = {}
    for k, v in payload.parameters.items():
        if not isinstance(k, str) or not k:
            continue
        try:
            parameters_clean[k] = float(v)
        except (TypeError, ValueError):
            print(f"[Appearance] 跳过非法 parameter: {k}={v!r}")

    parts_clean: Dict[str, int] = {}
    for k, v in payload.parts.items():
        if not isinstance(k, str) or not k:
            continue
        try:
            iv = int(v)
            if iv not in (0, 1):
                print(f"[Appearance] part 值非 0/1，按 bool 强转: {k}={v!r}")
                iv = 1 if iv else 0
            parts_clean[k] = iv
        except (TypeError, ValueError):
            print(f"[Appearance] 跳过非法 part: {k}={v!r}")

    out = {
        "version": 1,
        "parameters": parameters_clean,
        "parts": parts_clean,
    }

    fp = target / "appearance.json"
    try:
        with open(fp, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent="\t")
    except Exception as e:
        print(f"[Appearance] 写入 {fp} 失败: {e}")
        raise HTTPException(status_code=500, detail=f"写入失败: {e}")

    print(
        f"[Appearance] saved {payload.folder}: "
        f"params={len(parameters_clean)} parts={len(parts_clean)} → {fp}"
    )

    return {"ok": True, "path": str(fp)}


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

    print(f"[AutoFix] {folder.name}: 自动注入 Motions（idle={idle_file.name}，共 {len(motion_files)} 个动作）")


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

    print(f"[AutoFix] {folder.name}: 检测到帧切换型 idle（全部 Duration < {DURATION_THRESHOLD}s），"
          f"已精简为 1 个动作并禁用 crossfade")