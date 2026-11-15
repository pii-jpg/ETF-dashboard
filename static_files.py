"""静态资源响应：gzip 压缩 + ETag 协商缓存。

标准库 ``SimpleHTTPRequestHandler`` 按原样发送文件：9MB 的 JSON 每次全量传输，
且没有协商缓存。本模块在它前面加一层压缩与协商，路由与响应语义保持不变，
不接管的请求原样回退给标准库。
"""

from __future__ import annotations

import gzip
import threading
from pathlib import Path

# 只压缩文本类后缀；图片等本身已压缩的格式不重复压
COMPRESSIBLE_SUFFIXES = {".html", ".js", ".css", ".json", ".svg", ".md", ".txt"}
MIN_COMPRESS_BYTES = 1024
# 缓存条目上限：按首次插入顺序淘汰最旧一条（不是 LRU）
MAX_CACHE_ENTRIES = 32

# 确定性 Content-Type：不依赖 Windows 注册表里的 MIME 映射
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
}

# 压缩结果按 (mtime_ns, size) 缓存；文件重建后 mtime 变化，旧缓存自然失效
_gzip_cache: dict[str, tuple[tuple[int, int], bytes]] = {}
_gzip_lock = threading.Lock()


def _accepts_gzip(handler) -> bool:
    return "gzip" in handler.headers.get("Accept-Encoding", "").lower()


def _compressed(path: Path, stamp: tuple[int, int]) -> bytes | None:
    key = str(path)
    with _gzip_lock:
        cached = _gzip_cache.get(key)
        if cached and cached[0] == stamp:
            return cached[1]
    try:
        payload = gzip.compress(path.read_bytes(), compresslevel=6)
    except OSError:
        # 文件正在被重建：交回标准库，不让异常穿成 500
        return None
    with _gzip_lock:
        if len(_gzip_cache) >= MAX_CACHE_ENTRIES and key not in _gzip_cache:
            _gzip_cache.pop(next(iter(_gzip_cache)), None)
        _gzip_cache[key] = (stamp, payload)
    return payload


def compress_body(handler, body: bytes) -> tuple[bytes, str]:
    """按需压缩一段内存正文，返回 (正文, Content-Encoding 或空串)。"""
    if len(body) >= MIN_COMPRESS_BYTES and _accepts_gzip(handler):
        return gzip.compress(body, compresslevel=6), "gzip"
    return body, ""


def _resolve(root: Path, url_path: str) -> Path | None:
    # 查询串不参与文件名解析：带 ?v= 的 URL 一样走压缩与协商，不静默回退
    relative = url_path.split("?", 1)[0].lstrip("/")
    if not relative:
        return None
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    return candidate


def try_serve(handler, root: Path, url_path: str) -> bool:
    """接管可压缩的静态文件；返回 True 表示响应已发出。"""
    path = _resolve(root, url_path)
    if path is None or not path.is_file():
        return False
    suffix = path.suffix.lower()
    if suffix not in COMPRESSIBLE_SUFFIXES:
        return False

    stat = path.stat()
    stamp = (stat.st_mtime_ns, stat.st_size)
    etag = f'W/"{stamp[0]}-{stamp[1]}"'

    if etag in (handler.headers.get("If-None-Match") or ""):
        handler.send_response(304)
        handler.send_header("ETag", etag)
        handler.send_header("Cache-Control", "no-cache")
        handler.end_headers()
        return True

    gzipped = _accepts_gzip(handler) and stat.st_size >= MIN_COMPRESS_BYTES
    if gzipped:
        body = _compressed(path, stamp)
        if body is None:
            return False
    else:
        try:
            body = path.read_bytes()
        except OSError:
            return False

    handler.send_response(200)
    handler.send_header("Content-Type", CONTENT_TYPES[suffix])
    if gzipped:
        handler.send_header("Content-Encoding", "gzip")
        handler.send_header("Vary", "Accept-Encoding")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("ETag", etag)
    # no-cache：允许浏览器存副本，但每次必须回源校验 —— 数据文件每天重建，
    # 强缓存会把旧数据显示一整天
    handler.send_header("Cache-Control", "no-cache")
    handler.end_headers()
    handler.wfile.write(body)
    return True
