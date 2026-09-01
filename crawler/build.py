# -*- coding: utf-8 -*-
"""
数据合并构建脚本
- 主数据源：YouOffer（公司/类型/地点/岗位/更新时间/截止/招聘类型/招聘对象/投递链接/公告链接）
- 补充数据源：今日校招 hahazhao（行业/规模/地点），用于：
    1) 为 YouOffer 记录补全行业字段（按公司名模糊匹配）
    2) 收录 YouOffer 中没有的公司记录（避免漏掉独有信息）
- 输出：
    app/data/data.json   （APP 在线拉取）
    app/js/data.js       （内置离线兜底数据）
- 规则：
    - 只保留 秋招/校招/校园招聘 类型（排除纯实习）
    - 已过期（投递截止早于今天且非"招满为止"）的记录排除
    - status: 今日新增 = 更新日期==今天；否则 正在进行
    - is_26: 招聘对象包含 2026 届
用法：python build.py
"""
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT, "data")
APP_DATA_DIR = os.path.normpath(os.environ.get(
    "OUTPUT_DATA_DIR", os.path.join(ROOT, "..", "docs", "data")))
APP_JS_DIR = os.path.normpath(os.environ.get(
    "OUTPUT_JS_DIR", os.path.join(ROOT, "..", "docs", "js")))

RECRUIT_KEYWORDS = ("秋招", "校招", "校园招聘", "校园")
SUFFIX_RE = re.compile(
    r"(股份有限公司|有限责任公司|股份公司|有限公司|集团公司|集团|控股|股份|公司|（中国）|\(中国\))"
)


def normalize_name(name):
    """公司名归一化，用于匹配。"""
    if not name:
        return ""
    s = name.strip().lower()
    s = re.sub(r"[（(].*?[)）]", "", s)  # 去掉括号内注释（如 华为(动力保障部) -> 华为）
    s = SUFFIX_RE.sub("", s)
    s = re.sub(r"[\s\u3000]+", "", s)
    return s


def load_json(path):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def parse_years(target):
    """从'2027届'/'2026届,2027届'/'2025,2026,2027届'中提取年份集合。"""
    if not target:
        return set()
    return set(re.findall(r"20\d\d", target))


def split_positions(p):
    """拆分岗位字段为 (岗位列表, 专业要求列表)。
    - 含反斜杠：左=岗位，右=专业要求（如 '工程师\\\\土木工程、机械'）
    - 否则按常见分隔符拆分整串为岗位
    """
    if not p:
        return [], []
    parts = re.split(r"\\+", p, maxsplit=1)  # 源用一串反斜杠分隔 岗位/专业
    if len(parts) == 2:
        pos = [s for s in re.split(r"[,，、;；\n\s]+", parts[0].strip()) if s]
        maj = [s for s in re.split(r"[,，、;；\n\s]+", parts[1].strip()) if s]
        return pos, maj
    pos = [s for s in re.split(r"[,，、;；\n\s]+", p.strip()) if s]
    return pos, []


def is_expired(deadline, today):
    if not deadline or "招满" in deadline or "为止" in deadline:
        return False
    m = re.search(r"(20\d\d)[-/.年](\d{1,2})[-/.月](\d{1,2})", deadline)
    if not m:
        return False
    try:
        d = "%s-%02d-%02d" % (m.group(1), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return False
    return d < today


def main():
    today = time.strftime("%Y-%m-%d")
    print("今天:", today)

    ystore = load_json(os.path.join(DATA_DIR, "youoffer_store.json"))
    hstore = load_json(os.path.join(DATA_DIR, "hahazhao_store.json"))
    if not ystore:
        print("缺少 youoffer_store.json，请先运行 youoffer.py")
        sys.exit(1)

    you_companies = ystore.get("companies", {})
    haz_companies = (hstore or {}).get("companies", {})

    # ---------- 1. 行业映射（hahazhao 公司名 -> 最常见行业） ----------
    ind_map = defaultdict(Counter)
    for h in haz_companies.values():
        n = normalize_name(h.get("name", ""))
        if n and h.get("industry"):
            ind_map[n][h["industry"]] += 1
    ind_best = {n: c.most_common(1)[0][0] for n, c in ind_map.items()}
    # 含"省/市/（地区）"等不带后缀的直接名也加入
    for h in haz_companies.values():
        raw = (h.get("name") or "").strip()
        n = normalize_name(raw)
        if n and h.get("industry"):
            ind_best.setdefault(n, h["industry"])

    def match_industry(name):
        n = normalize_name(name)
        if not n:
            return ""
        if n in ind_best:
            return ind_best[n]
        # 模糊：一方包含另一方（较短名至少 4 字符，避免误配）
        for key, ind in ind_best.items():
            a, b = (key, n) if len(key) <= len(n) else (n, key)
            if len(a) >= 4 and a in b:
                return ind
        return ""

    # ---------- 2. 处理 YouOffer 主记录 ----------
    out = []
    seen_names = set()
    for rec in you_companies.values():
        rt = rec.get("recruit_type", "") or ""
        if not any(k in rt for k in RECRUIT_KEYWORDS):
            continue
        post_date = (rec.get("post_date") or "").strip()[:10]
        if is_expired(rec.get("deadline", ""), today):
            continue
        years = parse_years(rec.get("target_years", ""))
        is26 = "2026" in years
        positions, majors = split_positions(rec.get("position", ""))
        item = {
            "id": rec.get("id") or rec.get("name"),
            "source": "youoffer",
            "name": rec.get("name", ""),
            "industry": match_industry(rec.get("name", "")) or "其他",
            "company_type": rec.get("company_type", ""),
            "location": rec.get("location", ""),
            "position": rec.get("position", ""),
            "positions": positions,
            "majors": majors,
            "title": "",
            "scale": "",
            "recruit_type": rt,
            "target_years": rec.get("target_years", ""),
            "years": sorted(years),
            "is_26": is26,
            "post_date": post_date,
            "deadline": rec.get("deadline", ""),
            "apply_url": rec.get("apply_url", ""),
            "notice_url": rec.get("notice_url", ""),
            "status": "today_new" if post_date == today else "ongoing",
        }
        out.append(item)
        seen_names.add(normalize_name(item["name"]))

    # ---------- 3. 补充 hahazhao 独有公司 ----------
    for h in haz_companies.values():
        rt = h.get("recruit_type", "") or ""
        if not any(k in rt for k in RECRUIT_KEYWORDS):
            continue
        name = h.get("name", "")
        n = normalize_name(name)
        if not n or n in seen_names:
            continue  # 已在 YouOffer 中出现过，跳过
        pub = (h.get("publish_date") or "").strip()[:10]
        upd = (h.get("update_time") or "").strip()[:10]
        # 源站 publish_date 未提供时会填占位日期（如 2026-12-31），需剔除；
        # 更新时间以源站 update_time 为准，缺失时才回退到真实 publish_date
        def is_placeholder(d):
            if not d:
                return True
            if re.match(r"^\d{4}-12-31$", d) or re.match(r"^\d{4}-01-01$", d):
                return True
            if d.startswith(("2099", "9999", "2100")):
                return True
            return False
        if upd:
            post_date = upd
        else:
            post_date = pub if not is_placeholder(pub) else ""
        if is_expired(h.get("deadline", ""), today):
            continue
        years = parse_years(h.get("recruit_target", ""))
        is26 = "2026" in years
        item = {
            "id": "h_" + str(h.get("id")),
            "source": "hahazhao",
            "name": name,
            "industry": h.get("industry", "") or "其他",
            "company_type": "",
            "location": h.get("work_location", ""),
            "position": h.get("title", ""),
            "positions": [],
            "majors": [],
            "title": h.get("title", ""),
            "scale": h.get("scale", ""),
            "recruit_type": rt,
            "target_years": h.get("recruit_target", ""),
            "years": sorted(years),
            "is_26": is26,
            "post_date": post_date,
            "deadline": h.get("deadline", ""),
            "apply_url": h.get("apply_link", ""),
            "notice_url": h.get("original_link", ""),
            "status": "today_new" if post_date == today else "ongoing",
        }
        out.append(item)
        seen_names.add(n)

    # ---------- 4. 排序：今日新增按日期降序；正在进行也按更新时间降序 ----------
    out.sort(key=lambda x: (x["post_date"], x["name"]), reverse=True)

    today_new = [c for c in out if c["status"] == "today_new"]
    ongoing = [c for c in out if c["status"] == "ongoing"]
    today_new_26 = [c for c in today_new if c["is_26"]]

    industries = sorted({c["industry"] for c in out if c["industry"]})

    meta = {
        "app": "秋招每日通",
        "version": 1,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "today": today,
        "total": len(out),
        "today_new": len(today_new),
        "today_new_26": len(today_new_26),
        "ongoing": len(ongoing),
        "industries": industries,
        "sources": {
            "youoffer": len(you_companies),
            "hahazhao": len(haz_companies),
        },
    }

    payload = {"meta": meta, "companies": out}

    os.makedirs(APP_DATA_DIR, exist_ok=True)
    os.makedirs(APP_JS_DIR, exist_ok=True)
    with open(os.path.join(APP_DATA_DIR, "data.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    with open(os.path.join(APP_JS_DIR, "data.js"), "w", encoding="utf-8") as f:
        f.write("window.__QIUDATA__ = ")
        json.dump(payload, f, ensure_ascii=False)
        f.write(";\n")

    print("=== 构建完成 ===")
    print(json.dumps(meta, ensure_ascii=False, indent=2))
    print("今日新增示例:", [c["name"] for c in today_new[:8]])


if __name__ == "__main__":
    main()
