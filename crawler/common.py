# -*- coding: utf-8 -*-
"""公共模块：HTTP 请求、限速、重试。零第三方依赖，仅用标准库。"""
import time
import urllib.request
import urllib.error
import gzip
import io
import re

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

# 抓取间隔（秒），遵守需求文档约定 >= 5 秒
REQUEST_INTERVAL = 5.0
_last_request_time = 0.0


def fetch(url, timeout=30, retries=5, interval=REQUEST_INTERVAL, use_gzip=True, accept=None):
    """带限速、重试的 GET 请求。
    use_gzip=False 时不申请 gzip；accept 可覆盖 Accept 头（个别站点对特定 Accept 返回 500）。"""
    global _last_request_time
    last_err = None
    for attempt in range(retries):
        # 限速：与上次请求至少间隔 interval 秒
        wait = interval - (time.time() - _last_request_time)
        if wait > 0:
            time.sleep(wait)
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": accept or "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Connection": "keep-alive",
        }
        if use_gzip:
            headers["Accept-Encoding"] = "gzip, deflate"
        else:
            headers["Accept-Encoding"] = "identity"
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read()
            _last_request_time = time.time()
            if data[:2] == b"\x1f\x8b":
                data = gzip.GzipFile(fileobj=io.BytesIO(data)).read()
            charset = resp.headers.get_content_charset() or "utf-8"
            try:
                return data.decode(charset, "ignore")
            except (LookupError, ValueError):
                return data.decode("utf-8", "ignore")
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError) as e:
            last_err = e
            backoff = 4 * (attempt + 1)
            if isinstance(e, urllib.error.HTTPError) and e.code in (429, 500, 502, 503, 504):
                backoff = 6 * (attempt + 1)
            time.sleep(backoff)
    raise RuntimeError("fetch failed after %d retries: %s -> %s" % (retries, url, last_err))


def clean(text):
    """去掉多余空白字符。"""
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text)
    return text.strip()
