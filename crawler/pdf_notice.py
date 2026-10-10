# -*- coding: utf-8 -*-
"""仅从高校官网 PDF 附件提取结构化线索，不发布附件全文。"""
import io
import re
import urllib.parse
import urllib.request

from pypdf import PdfReader

from common import USER_AGENT

MAX_BYTES = 5 * 1024 * 1024


def analyze(url):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname != "career.hebut.edu.cn" or not parsed.path.lower().endswith(".pdf"):
        raise ValueError("只处理高校官网 HTTPS PDF")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as response:
        length = response.headers.get("Content-Length")
        if length and int(length) > MAX_BYTES:
            raise ValueError("PDF 超过大小限制")
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES or not data.startswith(b"%PDF"):
        raise ValueError("PDF 类型或大小不符合要求")
    reader = PdfReader(io.BytesIO(data))
    content = " ".join((page.extract_text() or "") for page in reader.pages[:5])
    years = sorted(set(re.findall(r"20\d{2}届", content)))
    degree = sorted(set(re.findall(r"专科|大专|本科|硕士|博士", content)))
    return {"url": url, "pages": len(reader.pages), "target_years": years,
            "degree_mentions": degree, "text_available": bool(content.strip())}
