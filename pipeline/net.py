# ============================================================
# net.py — 标准库 HTTP GET（零第三方依赖：本地与 GitHub Actions 都不用 pip install）
# ============================================================
import json
import time
import urllib.request
import urllib.error

DEFAULT_TIMEOUT = 30
RETRIES = 2
UA = "seikcha-info-pipeline/1.0 (student competition project; contact via repo)"


def get_json(url: str, timeout: int = DEFAULT_TIMEOUT):
    """GET 并解析 JSON；网络/解析失败抛异常（由调用方决定降级或中止）。"""
    last_exc = None
    for attempt in range(1 + RETRIES):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
            last_exc = e
            if attempt < RETRIES:
                time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"GET 失败（已重试 {RETRIES} 次）: {url} :: {last_exc}")
