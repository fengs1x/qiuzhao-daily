# -*- coding: utf-8 -*-
"""
YouOffer (offer.playoff.cn) 秋招/校招信息爬虫
- 已核查 robots.txt：仅 Disallow /wp-admin/，本脚本只抓公开列表页，合规。
- 抓取间隔 >= 5 秒（见 common.REQUEST_INTERVAL）。
- 输出：crawler/data/youoffer_store.json（增量累积的持久化数据）

用法：
  python youoffer.py --full     # 全量抓取所有页（首次使用）
  python youoffer.py --daily    # 只抓前 3 页（每日增量，今日新增基本都在前 1~2 页）
  python youoffer.py --pages 5  # 抓前 5 页
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import fetch, clean  # noqa: E402

try:
    from lxml import html as lhtml
except ImportError:
    print("需要 lxml：请先 `pip install lxml`")
    sys.exit(1)

BASE = "https://offer.playoffer.cn/"
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
STORE_FILE = os.path.join(DATA_DIR, "youoffer_store.json")

# 关注的招聘类型（秋招/校园招聘类；纯实习不算）
WANTED_RECRUIT_KEYWORDS = ("秋招", "校招", "校园招聘", "校园")


def _record_id(src, name, post_date, apply_url, deadline):
    key = "|".join([src, name or "", post_date or "", apply_url or "", deadline or ""])
    return hashlib.md5(key.encode("utf-8")).hexdigest()[:16]


def parse_page(html_text):
    """解析一页表格，返回记录列表。"""
    doc = lhtml.fromstring(html_text)
    rows = doc.xpath("//table[contains(@class,'crt-table')]//tr[@data-id]")
    records = []
    for tr in rows:
        def td(cls):
            nodes = tr.xpath("./td[contains(@class,'%s')]" % cls)
            return nodes[0] if nodes else None

        def txt(cls):
            node = td(cls)
            return clean(node.text_content()) if node is not None else ""

        name = txt("crt-col-company")
        if not name:
            continue
        comp_type = txt("crt-col-type")
        location = txt("crt-col-location")
        position = txt("crt-col-position")
        update_time = txt("crt-col-update-time")
        deadline = txt("crt-col-deadline")
        recruit_type = txt("crt-col-recruitment-type")
        target = txt("crt-col-target")

        # 相关链接：投递 / 公告
        apply_url = ""
        notice_url = ""
        links_node = td("crt-col-links")
        if links_node is not None:
            for a in links_node.xpath(".//a[@href]"):
                href = a.get("href", "").strip()
                text = clean(a.text_content())
                if "投递" in text or "投" in text:
                    apply_url = href
                elif "公告" in text:
                    notice_url = href
                if not apply_url:
                    apply_url = href  # 兜底取第一个链接
        notice_node = td("crt-col-notice")
        if notice_node is not None:
            for a in notice_node.xpath(".//a[@href]"):
                href = a.get("href", "").strip()
                if href:
                    notice_url = href
                    break

        records.append({
            "source": "youoffer",
            "name": name,
            "company_type": comp_type,
            "location": location,
            "position": position,
            "post_date": update_time,
            "deadline": deadline,
            "recruit_type": recruit_type,
            "target_years": target,
            "apply_url": apply_url,
            "notice_url": notice_url,
        })
    return records


def total_pages(html_text):
    # 优先用"共 N 条记录"换算页数（每页 30 条）
    m2 = re.search(r'共\s*<span[^>]*class="crt-total-items"[^>]*>(\d+)</span>\s*条记录', html_text)
    if m2:
        return max(1, -(-int(m2.group(1)) // 30))
    # 兜底：分页列表里最大页码
    nums = [int(x) for x in re.findall(r'href="\?paged=(\d+)"', html_text)]
    if nums:
        return max(nums)
    return 1


def load_store():
    if os.path.exists(STORE_FILE):
        with open(STORE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"companies": {}, "pages_done": [], "last_run": None}


def save_store(store):
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = STORE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STORE_FILE)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true", help="全量抓取")
    ap.add_argument("--daily", action="store_true", help="增量抓取前 3 页")
    ap.add_argument("--pages", type=int, default=0, help="自定义抓取页数")
    args = ap.parse_args()

    store = load_store()
    companies = store["companies"]
    pages_done = set(store.get("pages_done", []))

    # 第一页：确定总页数 + 抓取
    print("[1] 抓取第 1 页 ...")
    first = fetch(BASE)
    total = total_pages(first)
    print("    共 %d 页" % total)
    page_range = []
    if args.full:
        page_range = list(range(1, total + 1))
    elif args.daily:
        page_range = list(range(1, 6))  # 今日新增基本集中在前 5 页
    elif args.pages:
        page_range = list(range(1, min(args.pages, total) + 1))
    else:
        page_range = list(range(1, total + 1))  # 默认全量

    for idx, pno in enumerate(page_range, 1):
        # 仅全量模式断点续抓时跳过已抓页；每日/指定页数模式始终重新抓取以获取更新
        if pno in pages_done and args.full:
            print("    第 %d 页已抓过，跳过" % pno)
            continue
        if pno == 1:
            html_text = first
        else:
            print("[%d/%d] 抓取第 %d 页 ..." % (idx, len(page_range), pno))
            html_text = fetch(BASE + "?paged=%d" % pno)
        recs = parse_page(html_text)
        new_cnt = 0
        for r in recs:
            rid = _record_id("youoffer", r["name"], r["post_date"], r["apply_url"], r["deadline"])
            r["id"] = rid
            if rid not in companies:
                new_cnt += 1
            companies[rid] = r
        pages_done.add(pno)
        store["pages_done"] = sorted(pages_done)
        store["last_run"] = time.strftime("%Y-%m-%d %H:%M:%S")
        save_store(store)
        print("    第 %d 页：解析 %d 条，新增 %d 条，累计 %d 条" % (pno, len(recs), new_cnt, len(companies)))

    store["last_run"] = time.strftime("%Y-%m-%d %H:%M:%S")
    save_store(store)
    print("完成：累计 %d 条，已抓页 %d/%d" % (len(companies), len(pages_done), total))


if __name__ == "__main__":
    main()
