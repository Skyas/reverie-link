"""
download_stt_model.py — 自动下载 SenseVoice-Small int8 ONNX 模型

用法：
  python download_stt_model.py

功能：
  - 支持断点续传（Range header）
  - 多镜像 fallback（GitHub → hf-mirror → 用户自定义）
  - 下载完成后自动校验文件完整性（tar.bz2 解压校验）
  - 自动放置到 sidecar/models/sense-voice-small-int8/

环境变量：
  VOICE_MODEL_URL  - 自定义下载地址（覆盖默认镜像）
  VOICE_MOCK_TEXT  - 若模型下载失败，可在 stt_engine.py 中启用 Mock 模式测试链路
"""

import os
import sys
import tarfile
import time

# ── 配置 ────────────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_DIR = os.path.join(SCRIPT_DIR, "models", "sense-voice-small-int8")
TAR_NAME = "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17.tar.bz2"
TAR_PATH = os.path.join(SCRIPT_DIR, "models", TAR_NAME)

# 预期解压后的关键文件大小（字节），用于完整性校验
# model.int8.onnx 实际约 63MB（63,000,000 左右）
EXPECTED_MODEL_MIN_BYTES = 50_000_000  # 至少 50MB 才认为是完整的

DOWNLOAD_URLS = [
    # GitHub Release（主源）
    f"https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/{TAR_NAME}",
    # HuggingFace 国内镜像
    f"https://hf-mirror.com/k2-fsa/sherpa-onnx/resolve/main/models/{TAR_NAME}",
]

# chunk 大小和超时
CHUNK_SIZE = 1024 * 1024  # 1MB
CONNECT_TIMEOUT = 30
READ_TIMEOUT = 60


# ── SSL 兼容 ────────────────────────────────────────────────────────────

def _create_ssl_context():
    """创建兼容的 SSL 上下文（解决 Windows 证书验证问题）。"""
    import ssl
    context = ssl.create_default_context()
    # 在部分 Windows 环境中 CA 证书链不完整，允许不验证（仅影响模型下载安全）
    try:
        context.load_default_certs()
    except Exception:
        pass
    return context


# ── 下载 ────────────────────────────────────────────────────────────────

def _get_session():
    """获取配置好的 requests Session。"""
    import requests
    session = requests.Session()
    # 关闭 SSL 警告（开发环境）
    from requests.packages.urllib3.exceptions import InsecureRequestWarning
    requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
    return session


def _get_existing_size(path: str) -> int:
    """获取已下载部分的大小，用于断点续传。"""
    return os.path.getsize(path) if os.path.isfile(path) else 0


def _download_with_resume(session, url: str, dst: str) -> bool:
    """
    带断点续传的下载。
    返回 True 表示下载成功（文件完整）。
    """
    existing = _get_existing_size(dst)
    headers = {}
    if existing > 0:
        headers["Range"] = f"bytes={existing}-"
        print(f"[Download] 检测到已下载 {existing / (1024*1024):.1f} MB，尝试断点续传...")

    try:
        resp = session.get(
            url,
            headers=headers,
            stream=True,
            timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
            verify=False,  # 兼容 Windows 证书问题
        )
        resp.raise_for_status()
    except Exception as e:
        print(f"[Download] 请求失败: {e}")
        return False

    total_size = None
    if "Content-Length" in resp.headers:
        total_size = int(resp.headers["Content-Length"])
        if existing > 0 and resp.status_code == 206:
            total_size += existing
        elif existing > 0 and resp.status_code == 200:
            # 服务器不支持 Range，从头开始
            print("[Download] 服务器不支持断点续传，从头下载...")
            existing = 0

    mode = "ab" if existing > 0 and resp.status_code == 206 else "wb"
    downloaded = existing

    print(f"[Download] 开始下载: {url}")
    start_time = time.time()
    last_report = start_time

    try:
        with open(dst, mode) as f:
            for chunk in resp.iter_content(chunk_size=CHUNK_SIZE):
                if not chunk:
                    continue
                f.write(chunk)
                downloaded += len(chunk)

                now = time.time()
                if now - last_report >= 2.0:  # 每 2 秒报告一次
                    mb = downloaded / (1024 * 1024)
                    if total_size:
                        pct = min(100, downloaded * 100 // total_size)
                        total_mb = total_size / (1024 * 1024)
                        speed = (downloaded - existing) / (1024 * 1024) / max(0.1, now - start_time)
                        print(f"\r  进度: {pct}% | {mb:.1f}/{total_mb:.1f} MB | {speed:.2f} MB/s", end="", flush=True)
                    else:
                        print(f"\r  已下载: {mb:.1f} MB", end="", flush=True)
                    last_report = now
        print()  # 换行
    except Exception as e:
        print(f"\n[Download] 下载中断: {e}")
        return False

    # 校验大小
    if total_size and downloaded < total_size:
        print(f"[Download] ⚠️ 文件不完整: {downloaded}/{total_size} bytes")
        return False

    print(f"[Download] ✅ 下载完成 | {downloaded / (1024*1024):.1f} MB")
    return True


def download_file(url: str, dst: str) -> bool:
    """尝试从单个 URL 下载文件，支持断点续传。"""
    session = _get_session()
    return _download_with_resume(session, url, dst)


# ── 解压与校验 ──────────────────────────────────────────────────────────

def extract_tar(tar_path: str, extract_to: str) -> bool:
    """解压 tar.bz2 到指定目录。"""
    try:
        print(f"[Download] 正在解压 {tar_path}...")
        with tarfile.open(tar_path, "r:bz2") as tar:
            tar.extractall(extract_to)
        print("[Download] 解压完成")
        return True
    except Exception as e:
        print(f"[Download] 解压失败: {e}")
        return False


def find_model_files(base_dir: str) -> tuple[str, str] | None:
    """在解压后的目录中查找 model.int8.onnx 和 tokens.txt。"""
    model_path = None
    tokens_path = None
    for root, _dirs, files in os.walk(base_dir):
        for f in files:
            if f == "model.int8.onnx":
                model_path = os.path.join(root, f)
            elif f == "tokens.txt":
                tokens_path = os.path.join(root, f)
    if model_path and tokens_path:
        return model_path, tokens_path
    return None


def verify_model_integrity(model_path: str) -> bool:
    """检查模型文件大小是否达到预期。"""
    size = os.path.getsize(model_path)
    ok = size >= EXPECTED_MODEL_MIN_BYTES
    if not ok:
        print(f"[Download] ⚠️ 模型文件不完整: {size} bytes (预期至少 {EXPECTED_MODEL_MIN_BYTES} bytes)")
    else:
        print(f"[Download] 模型文件大小校验通过: {size / (1024*1024):.1f} MB")
    return ok


# ── 主流程 ──────────────────────────────────────────────────────────────

def ensure_model() -> bool:
    """
    确保模型文件存在且完整。
    返回 True 表示模型已就绪，False 表示下载失败。
    """
    model_file = os.path.join(MODEL_DIR, "model.int8.onnx")
    tokens_file = os.path.join(MODEL_DIR, "tokens.txt")

    # 1. 已存在且校验通过 → 直接返回
    if os.path.isfile(model_file) and os.path.isfile(tokens_file):
        if verify_model_integrity(model_file):
            print(f"[Download] 模型已存在且完整，跳过下载 | {MODEL_DIR}")
            return True
        else:
            print("[Download] 现有模型文件损坏，将重新下载...")
            # 删除损坏的文件以便重新下载
            try:
                os.remove(model_file)
                os.remove(tokens_file)
            except Exception:
                pass

    os.makedirs(MODEL_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(TAR_PATH), exist_ok=True)

    # 2. 检查环境变量自定义 URL
    custom_url = os.environ.get("VOICE_MODEL_URL", "").strip()
    urls = ([custom_url] if custom_url else []) + DOWNLOAD_URLS

    # 3. 下载 tar.bz2（支持断点续传）
    if not os.path.exists(TAR_PATH) or _get_existing_size(TAR_PATH) < EXPECTED_MODEL_MIN_BYTES:
        success = False
        for url in urls:
            if download_file(url, TAR_PATH):
                success = True
                break
            # 失败后不删除文件，保留已下载部分供下次续传
        if not success:
            print("[Download] ❌ 所有镜像源均下载失败。")
            print("[Download] 建议方案：")
            print("  1. 检查网络连接，稍后重试运行本脚本")
            print("  2. 手动下载模型后放到以下目录：")
            print(f"     {MODEL_DIR}")
            print("  3. 在 .env 中设置 VOICE_MODEL_URL 使用自定义镜像")
            print("  4. 开发测试时可在 .env 中设置 VOICE_MOCK_TEXT 启用 Mock STT 模式")
            print(f"\n需要下载的文件：{TAR_NAME} (约 155MB)")
            print("下载地址：")
            for u in DOWNLOAD_URLS:
                print(f"  - {u}")
            return False

    # 4. 解压
    extract_base = os.path.join(SCRIPT_DIR, "models", "_extract_tmp")
    os.makedirs(extract_base, exist_ok=True)
    if not extract_tar(TAR_PATH, extract_base):
        return False

    # 5. 查找并校验
    found = find_model_files(extract_base)
    if not found:
        print("[Download] ❌ 解压后未找到 model.int8.onnx 或 tokens.txt")
        return False

    model_src, tokens_src = found
    if not verify_model_integrity(model_src):
        print("[Download] ❌ 解压出的模型文件不完整，建议删除临时文件后重新下载")
        return False

    # 6. 移动到目标目录
    if os.path.dirname(model_src) != MODEL_DIR:
        import shutil
        for src_file, dst_name in [(model_src, "model.int8.onnx"), (tokens_src, "tokens.txt")]:
            dst_file = os.path.join(MODEL_DIR, dst_name)
            shutil.move(src_file, dst_file)
            print(f"[Download] 已移动: {dst_name}")

    # 7. 清理临时文件
    try:
        os.remove(TAR_PATH)
        import shutil
        shutil.rmtree(extract_base, ignore_errors=True)
    except Exception:
        pass

    print(f"[Download] ✅ 模型准备就绪 | {MODEL_DIR}")
    return True


# ── 入口 ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    ok = ensure_model()
    sys.exit(0 if ok else 1)
