# -*- coding: utf-8 -*-
"""
今日校招 (hahazhao.com) 数据爬虫 —— 通过其公开 JSON API 抓取，补充"行业"字段。
- robots.txt：Allow /（仅禁 /profile、/login-callback），抓取列表接口合规。
- 接口：GET https://hahazhao.com/v1/recruitment/?page=N&page_size=100
- 抓取间隔 >= 5 秒（common.REQUEST_INTERVAL）。
- 输出：crawler/data/hahazhao_store.json

用法：
  python hahazhao.py            # 全量抓取
  python hahazhao.py --pages 3  # 只抓前 3 页
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import fetch  # noqa: E402

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
STORE_FILE = os.path.join(DATA_DIR, "hahazhao_store.json")
API = "https://hahazhao.com/v1/recruitment/"
PAGE_SIZE = 100


def load_store():
    if os.path.exists(STORE_FILE):
        with open(STORE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"companies": {}, "last_run": None}


def save_store(store):
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = STORE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STORE_FILE)


def normalize(rec):
    """把 API 字段转成统一结构。"""
    return {
        "source": "hahazhao",
        "id": str(rec.get("id")),
        "name": (rec.get("company_name") or "").strip(),
        "industry": (rec.get("industry") or "").strip(),
        "original_link": (rec.get("original_link") or "").strip(),
        "apply_link": (rec.get("apply_link") or "").strip(),
        "recruit_type": (rec.get("recruit_type") or "").strip(),
        "recruit_target": (rec.get("recruit_target") or "").strip(),
        "publish_date": (rec.get("publish_date") or "").strip(),
        "update_time": (rec.get("update_time") or "").strip(),
        "deadline": (rec.get("deadline") or "").strip(),
        "scale": (rec.get("scale") or "").strip(),
        "work_location": (rec.get("work_location") or "").strip(),
        "title": (rec.get("title") or "").strip(),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", type=int, default=0, help="只抓前 N 页（默认全量）")
    args = ap.parse_args()

    store = load_store()
    companies = store["companies"]

    # 先拿第一页确定总数（hahazhao API 对 gzip 与 text/html Accept 均不稳定，需用 JSON Accept + 禁用 gzip）
    first = fetch(API + "?page=1&page_size=%d" % PAGE_SIZE, use_gzip=False,
                  accept="application/json, text/html,*/*")
    data = json.loads(first)
    count = data.get("count", 0)
    total_pages = max(1, -(-count // PAGE_SIZE))
    print("共 %d 条，%d 页" % (count, total_pages))

    page_range = list(range(1, total_pages + 1))
    if args.pages:
        page_range = page_range[: args.pages]

    for idx, pno in enumerate(page_range, 1):
        if pno == 1:
            text = first
        else:
            print("[%d/%d] 抓取第 %d 页 ..." % (idx, len(page_range), pno))
            text = fetch(API + "?page=%d&page_size=%d" % (pno, PAGE_SIZE), use_gzip=False,
                         accept="application/json, text/html,*/*")
        data = json.loads(text)
        recs = data.get("results", [])
        new_cnt = 0
        for r in recs:
            n = normalize(r)
            if not n["name"]:
                continue
            if n["id"] not in companies:
                new_cnt += 1
            companies[n["id"]] = n
        store["last_run"] = time.strftime("%Y-%m-%d %H:%M:%S")
        save_store(store)
        print("    第 %d 页：解析 %d 条，新增 %d 条，累计 %d 条" % (pno, len(recs), new_cnt, len(companies)))

    store["last_run"] = time.strftime("%Y-%m-%d %H:%M:%S")
    save_store(store)
    print("完成：累计 %d 条" % len(companies))


if __name__ == "__main__":
    main()
