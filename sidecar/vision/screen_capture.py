"""
视觉感知 · 截屏与像素差异预筛模块（改进版，直接替换原 screen_capture.py）

改进点：
  compute_pixel_diff 从直方图比较改为分块结构比较，
  能检测游戏内的局部变化（HUD 数值、准星、技能特效）。
  其余函数（capture_screen / get_foreground_* / compress_for_vlm / is_blank_screen）不变。
"""
import ctypes
import ctypes.wintypes
from io import BytesIO
from typing import Optional


# ── 截屏 ────────────────────────────────────────────────────────

def capture_screen() -> Optional[bytes]:
    """截取主屏幕，返回 PNG 字节数据（纯内存，不落盘）"""
    try:
        from PIL import ImageGrab
        img = ImageGrab.grab()
        buf = BytesIO()
        img.save(buf, format='PNG')
        return buf.getvalue()
    except Exception as e:
        print(f"[Vision] 截屏失败: {e}")
        return None


# ── 前台窗口信息 ─────────────────────────────────────────────────

def get_foreground_window_title() -> str:
    """获取当前前台窗口标题"""
    try:
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd) + 1
        buf = ctypes.create_unicode_buffer(length)
        ctypes.windll.user32.GetWindowTextW(hwnd, buf, length)
        return buf.value or ""
    except Exception:
        return ""


def get_foreground_process_info() -> dict:
    """
    获取前台窗口的进程信息。
    返回: {"process_name": str, "process_path": str, "window_title": str}
    """
    info = {"process_name": "", "process_path": "", "window_title": ""}
    info["window_title"] = get_foreground_window_title()
    try:
        import psutil
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        pid = ctypes.wintypes.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value:
            proc = psutil.Process(pid.value)
            info["process_name"] = proc.name()
            info["process_path"] = proc.exe()
    except Exception:
        pass
    return info


# ── 像素差异预筛（改进版：分块结构比较）─────────────────────────

def compute_pixel_diff(img1_bytes: bytes, img2_bytes: bytes) -> float:
    """
    分块结构差异比较。

    把画面切成 6×4=24 个格子，比较每个格子的 RGB 均值差异。
    返回 0~100 的百分比。耗时 < 10ms。

    改进说明：
      原方案用直方图比较，战舰世界这类大面积同色画面差异只有 0.1%。
      新方案能捕捉 HUD 数值变化、准星移动、局部爆炸特效等。
    """
    from PIL import Image

    GRID_COLS = 6
    GRID_ROWS = 4
    THUMB_W = GRID_COLS * 40   # 240
    THUMB_H = GRID_ROWS * 30   # 120

    img1 = Image.open(BytesIO(img1_bytes)).convert('RGB').resize((THUMB_W, THUMB_H))
    img2 = Image.open(BytesIO(img2_bytes)).convert('RGB').resize((THUMB_W, THUMB_H))

    pix1 = img1.load()
    pix2 = img2.load()

    block_h = THUMB_H // GRID_ROWS
    block_w = THUMB_W // GRID_COLS

    diffs = []
    for r in range(GRID_ROWS):
        for c in range(GRID_COLS):
            y0, y1 = r * block_h, (r + 1) * block_h
            x0, x1 = c * block_w, (c + 1) * block_w

            sum1 = [0.0, 0.0, 0.0]
            sum2 = [0.0, 0.0, 0.0]
            count = 0

            for y in range(y0, y1):
                for x in range(x0, x1):
                    p1 = pix1[x, y]
                    p2 = pix2[x, y]
                    for ch in range(3):
                        sum1[ch] += p1[ch]
                        sum2[ch] += p2[ch]
                    count += 1

            dist_sq = 0
            for ch in range(3):
                d = (sum1[ch] / count) - (sum2[ch] / count)
                dist_sq += d * d

            diff = (dist_sq ** 0.5) / (255 * (3 ** 0.5)) * 100
            diffs.append(diff)

    # 70% 最大块差异 + 30% 平均差异
    # 即使只有一个区域变了（如 HUD），也能被检测到
    max_diff = max(diffs)
    avg_diff = sum(diffs) / len(diffs)
    return max_diff * 0.7 + avg_diff * 0.3


# ── 截图预处理 ───────────────────────────────────────────────────

def compress_for_vlm(img_bytes: bytes) -> bytes:
    """压缩截图至 960×540 以内，JPEG 质量 85%，用于发送给 VLM"""
    from PIL import Image
    img = Image.open(BytesIO(img_bytes)).convert('RGB')
    img.thumbnail((960, 540), Image.LANCZOS)
    buf = BytesIO()
    img.save(buf, format='JPEG', quality=85)
    return buf.getvalue()


def is_blank_screen(img_bytes: bytes) -> bool:
    """
    检测截图是否为纯黑/纯白（反作弊系统拦截或截屏 API 失败）。
    标准差 < 5 = 画面单一 = 截屏失败。
    """
    from PIL import Image
    thumb = Image.open(BytesIO(img_bytes)).convert('L').resize((32, 18))
    pixels = list(thumb.getdata())
    avg = sum(pixels) / len(pixels)
    variance = sum((p - avg) ** 2 for p in pixels) / len(pixels)
    std = variance ** 0.5
    return std < 5.0