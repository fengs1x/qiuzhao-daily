# -*- coding: utf-8 -*-
"""高校宣讲会日历：活动信息单独输出，不充当可投递岗位。"""
import json
import os
import re
from datetime import datetime, timedelta
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

from lxml import html

from common import clean, fetch
from pdf_notice import analyze

BASE = "https://career.hebut.edu.cn"
OUT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "docs", "data", "events.json"))
TITLE = re.compile(r"202[5-9]届|校园招聘|校招|秋季招聘")
WHEN = re.compile(r"举办时间[：:]\s*(20\d{2}/\d{1,2}/\d{1,2}\s+\d{1,2}:\d{2})")
WHERE = re.compile(r"举办地点[：:]\s*(.*?)\s*举办时间")


def parse_page(source):
    tree = html.fromstring(source)
    result = []
    for a in tree.xpath('//a[contains(@href,"/recruitment/content/type/2/id/")][.//p[contains(@class,"title")]]'):
        title = clean(" ".join(a.xpath('.//p[contains(@class,"title")]/text()')))
        if not TITLE.search(title) or "取消" in title:
            continue
        info = clean(" ".join(a.xpath('.//p[contains(@class,"info")]/text()')))
        when, where = WHEN.search(info), WHERE.search(info)
        href = a.get("href", "")
        if not when or not re.fullmatch(r"/recruitment/content/type/2/id/\d+\.html", href):
            continue
        try:
            at = datetime.strptime(when.group(1), "%Y/%m/%d %H:%M")
        except ValueError:
            continue
        result.append({"id": re.search(r"/id/(\d+)", href).group(1),
                       "title": title, "event_at": at.isoformat(timespec="minutes"),
                       "place": where.group(1).strip() if where else "",
                       "url": urljoin(BASE, href)})
    return result


def main():
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    events = {}
    for page in range(1, 4):
        url = BASE + ("/recruitment/index2.html" if page == 1 else "/recruitment/index2/p/%d.html" % page)
        rows = parse_page(fetch(url, retries=2))
        if page == 1 and not rows:
            raise RuntimeError("宣讲会首页未解析出校招活动")
        for row in rows:
            at = datetime.fromisoformat(row["event_at"]).replace(tzinfo=ZoneInfo("Asia/Shanghai"))
            if now - timedelta(days=1) <= at <= now + timedelta(days=90):
                events[row["id"]] = row
        print("宣讲会第 %d 页：%d 条校招活动" % (page, len(rows)), flush=True)
    if not events:
        raise RuntimeError("近期无有效宣讲会，停止覆盖已有数据")
    # 只检查少量近期活动详情；PDF 作为线索附在活动上，不据此宣称岗位仍可投。
    for event in sorted(events.values(), key=lambda x: x["event_at"])[:6]:
        try:
            detail = html.fromstring(fetch(event["url"], retries=2))
            links = [urljoin(BASE, link) for link in detail.xpath('//a[contains(translate(@href,"PDF","pdf"),".pdf")]/@href')]
            event["pdf_attachments"] = [link for link in links if link.startswith(BASE + "/")][:3]
            event["pdf_facts"] = []
            for link in event["pdf_attachments"][:1]:
                try:
                    event["pdf_facts"].append(analyze(link))
                except Exception as exc:
                    print("PDF 解析跳过 %s: %s" % (link, exc), flush=True)
        except Exception as exc:
            print("活动详情跳过 %s: %s" % (event["id"], exc), flush=True)
    result = {"generated_at": now.isoformat(timespec="seconds"),
              "source": "河北工业大学就业指导中心宣讲会", "count": len(events),
              "events": sorted(events.values(), key=lambda x: x["event_at"])}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print("宣讲会输出 %d 条（仅供活动参考）" % len(events), flush=True)


if __name__ == "__main__":
    main()
