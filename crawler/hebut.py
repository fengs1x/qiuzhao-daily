# -*- coding: utf-8 -*-
"""河北工业大学就业中心公开校招公告，作为独立的高校来源。"""
import argparse
import json
import os
import re
from datetime import date, datetime, timedelta
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

from lxml import html

from common import clean, fetch


BASE = "https://career.hebut.edu.cn"
STORE = os.path.join(os.path.dirname(__file__), "data", "hebut_store.json")
CAMPUS = re.compile(r"202[5-9]届|20[2-3]\d年?校园招聘|校园招聘|校招|应届毕业生|应届生")
EXCLUDE = re.compile(r"实习生|实习招聘|社会招聘|社招|博士后")
DATE = re.compile(r"20\d{2}-\d{2}-\d{2}")
DEADLINE = re.compile(r"(?:报名|投递|网申|申请|招聘).{0,12}(?:截止|截至).{0,8}(20\d{2}[年./-]\d{1,2}[月./-]\d{1,2}日?)")


def text(node):
    return clean(" ".join(node.itertext())) if node is not None else ""


def first(nodes):
    return nodes[0] if nodes else None


def parse_list(source):
    tree = html.fromstring(source)
    rows = []
    for anchor in tree.xpath('//a[contains(@href, "/correcruit/content/id/")]'):
        parent = anchor.getparent()
        row = parent.getparent() if parent is not None else None
        title = text(anchor)
        if row is None or row.tag != "li" or not CAMPUS.search(title) or EXCLUDE.search(title):
            continue
        company = text(first(row.xpath('.//a[contains(@href, "/company/index/id/")]')))
        listed = text(first(row.xpath('.//*[contains(concat(" ", normalize-space(@class), " "), " r ")]')))
        href = anchor.get("href", "")
        if not company or not DATE.fullmatch(listed) or not re.fullmatch(r"/correcruit/content/id/\d+\.html", href):
            continue
        rows.append({"id": re.search(r"\d+", href).group(), "title": title, "name": company,
                     "listed_date": listed, "notice_url": urljoin(BASE, href)})
    return rows


def parse_detail(source, row):
    tree = html.fromstring(source)
    block = first(tree.xpath('//div[contains(concat(" ", normalize-space(@class), " "), " zpxq ")]'))
    if block is None:
        return None
    heading = text(first(block.xpath('./div[contains(@class,"title")]')))
    info = first(block.xpath('./div[contains(@class,"info")]'))
    if info is None:
        return None
    info_text = text(info)
    published = re.search(r"发布时间[：:]\s*(20\d{2}-\d{2}-\d{2})", info_text)
    if not published:
        return None
    date_value = published.group(1)
    try:
        date.fromisoformat(date_value)
    except ValueError:
        return None
    if heading and row["title"] not in heading:
        return None
    degree = re.search(r"学历要求[：:]\s*([^\s　]+)", info_text)
    location = re.search(r"工作地域[：:]\s*(.*?)\s*职位类别", info_text)
    contents = [text(node) for node in block.xpath('./div[contains(@class,"content")]')]
    description = " ".join(contents)[:12000]
    deadline = DEADLINE.search(description)
    return {"id": row["id"], "title": row["title"], "name": row["name"],
            "post_date": date_value, "location": clean(location.group(1)) if location else "",
            "edu_req": degree.group(1) if degree else "",
            "description": description, "deadline": deadline.group(1) if deadline else "",
            "notice_url": row["notice_url"]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pages", type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.pages <= 5:
        parser.error("pages must be 1..5")
    cutoff = datetime.now(ZoneInfo("Asia/Shanghai")).date() - timedelta(days=180)
    old = {}
    if os.path.exists(STORE):
        with open(STORE, encoding="utf-8") as f:
            old = json.load(f).get("companies", {})
    companies = {k: v for k, v in old.items() if v.get("post_date", "") >= cutoff.isoformat()}
    found = []
    for page in range(1, args.pages + 1):
        url = BASE + ("/correcruit/index.html" if page == 1 else "/correcruit/index/p/%d.html" % page)
        rows = parse_list(fetch(url, retries=2))
        if not rows and page == 1:
            raise RuntimeError("高校招聘首页未解析出校招记录，停止覆盖缓存")
        found.extend(rows)
        print("高校列表第 %d 页：校招候选 %d 条" % (page, len(rows)), flush=True)
    fresh = 0
    for row in found:
        if row["id"] in companies and companies[row["id"]].get("listed_date") == row["listed_date"]:
            continue
        try:
            detail = parse_detail(fetch(row["notice_url"], retries=2), row)
        except Exception as exc:
            print("详情失败 %s: %s" % (row["id"], exc), flush=True)
            continue
        if detail and detail["post_date"] >= cutoff.isoformat():
            detail["listed_date"] = row["listed_date"]
            companies[row["id"]] = detail
            fresh += 1
    if not companies:
        raise RuntimeError("高校来源没有有效公告，停止写入空缓存")
    os.makedirs(os.path.dirname(STORE), exist_ok=True)
    with open(STORE, "w", encoding="utf-8") as f:
        json.dump({"source": "hebut", "companies": companies}, f, ensure_ascii=False, indent=2)
    print("高校来源：缓存 %d 条，本次新增或更新 %d 条" % (len(companies), fresh), flush=True)


if __name__ == "__main__":
    main()
