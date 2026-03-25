"""
视觉感知 · 截屏与像素差异预筛模块

负责：
  - Windows 主屏幕截图（纯内存，永不落盘）
  - 前台窗口标题 + 进程信息获取
  - 缩略图直方图差异计算（像素预筛，< 5ms）
  - 截图压缩（960×540 JPEG，用于 VLM）
  - 纯黑/纯白截屏检测（反作弊拦截识别）
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


# ── 像素差异预筛 ─────────────────────────────────────────────────


def compute_pixel_diff(img1_bytes: bytes, img2_bytes: bytes) -> float:
    """
    计算两张截图的缩略图直方图差异（0~100 的百分比）。
    差异越大 = 画面变化越大。耗时 < 5ms。
    """
    from PIL import Image

    img1 = Image.open(BytesIO(img1_bytes)).convert('RGB').resize((160, 120))
    img2 = Image.open(BytesIO(img2_bytes)).convert('RGB').resize((160, 120))

    hist1 = img1.histogram()   # 256 * 3 = 768 个分量
    hist2 = img2.histogram()

    diff = sum(abs(a - b) for a, b in zip(hist1, hist2))
    max_diff = 160 * 120 * 3 * 255  # 像素数 × 通道数 × 最大灰度
    return (diff / max_diff) * 100


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
    通过像素亮度标准差判断：标准差 < 5 = 画面单一 = 截屏失败。
    """
    from PIL import Image
    thumb = Image.open(BytesIO(img_bytes)).convert('L').resize((32, 18))
    pixels = list(thumb.getdata())
    avg = sum(pixels) / len(pixels)
    variance = sum((p - avg) ** 2 for p in pixels) / len(pixels)
    std = variance ** 0.5
    return std < 5.0
