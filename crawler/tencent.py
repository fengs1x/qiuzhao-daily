# -*- coding: utf-8 -*-
"""腾讯校招官网公开岗位列表。只取应届招聘项目，不取实习和社招。"""
import json
import os
import time
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

from common import USER_AGENT

API = "https://join.qq.com/api/v1"
STORE = os.path.join(os.path.dirname(__file__), "data", "tencent_store.json")


def request(path, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json, text/plain, */*",
               "Origin": "https://join.qq.com", "Referer": "https://join.qq.com/post.html"}
    if data is not None:
        headers["Content-Type"] = "application/json;charset=UTF-8"
    req = urllib.request.Request(API + path, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=25) as response:
        payload = json.load(response)
    if payload.get("status") != 0 or "data" not in payload:
        raise RuntimeError("腾讯接口返回异常: %s" % str(payload.get("message", ""))[:120])
    return payload["data"]


def campus_mapping(groups):
    ids = []
    for group in groups:
        recruit_type = group.get("recruitType")
        if recruit_type == 2:
            continue
        for sub in group.get("subProjectList") or []:
            if recruit_type == 999 and "实习" in (sub.get("projectName") or ""):
                continue
            mapping_id = sub.get("mappingId")
            if mapping_id is not None and mapping_id not in ids:
                ids.append(mapping_id)
    return ids


def main():
    ids = campus_mapping(request("/position/getProjectMapping"))
    if not ids:
        raise RuntimeError("腾讯校招项目映射为空，停止覆盖缓存")
    rows = []
    total = None
    for page in range(1, 11):
        body = {"projectIdList": [], "projectMappingIdList": ids, "keyword": "",
                "bgList": [], "workCountryType": 0, "workCityList": [],
                "recruitCityList": [], "positionFidList": [], "pageIndex": page, "pageSize": 100}
        data = request("/position/searchPosition", body)
        page_rows = data.get("positionList") or []
        if not isinstance(page_rows, list):
            raise RuntimeError("腾讯岗位列表格式变化")
        if total is None:
            total = int(data.get("count") or 0)
        rows.extend(page_rows)
        print("腾讯校招第 %d 页：%d 条" % (page, len(page_rows)), flush=True)
        if len(page_rows) < 100 or (total and len(rows) >= total):
            break
        time.sleep(5)
    if total and len(rows) < total:
        raise RuntimeError("腾讯岗位只抓到 %d/%d 条，停止覆盖缓存" % (len(rows), total))
    if not rows:
        raise RuntimeError("腾讯校招列表为空，停止覆盖缓存")
    old = {}
    if os.path.exists(STORE):
        with open(STORE, encoding="utf-8") as f:
            old = json.load(f).get("positions", {})
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    positions = {}
    for item in rows:
        post_id = str(item.get("postId") or "")
        title = (item.get("positionTitle") or "").strip()
        if not post_id.isdigit() or not title:
            continue
        project = (item.get("projectName") or "").strip()
        if "实习" in project or "实习" in title:
            continue
        positions[post_id] = {"id": post_id, "title": title, "project": project,
                              "location": (item.get("workCities") or "").strip(),
                              "first_seen": old.get(post_id, {}).get("first_seen", today),
                              "last_seen": today,
                              "url": "https://join.qq.com/post_detail.html?postid=" + post_id}
    if not positions:
        raise RuntimeError("腾讯校招无有效岗位，停止覆盖缓存")
    os.makedirs(os.path.dirname(STORE), exist_ok=True)
    with open(STORE, "w", encoding="utf-8") as f:
        json.dump({"source": "tencent", "positions": positions}, f, ensure_ascii=False, indent=2)
    print("腾讯校招：有效岗位 %d 条" % len(positions), flush=True)


if __name__ == "__main__":
    main()
