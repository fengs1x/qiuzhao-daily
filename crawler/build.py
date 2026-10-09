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
    - edu_req/is_college: 从岗位/公告文本推导学历要求（宽松口径：未明确"本科及以上"要求的记录视为专科可报）
    - 两站数据合并后按公司归一化名去重（同名多公告合并为一条卡片，聚合岗位/专业/届数/学历）
用法：python build.py
"""
import json
import calendar
import os
import re
import sys
import time
from datetime import date, datetime
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
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


def is_expired(deadline, today, post_date=""):
    if not deadline or "招满" in deadline or "为止" in deadline:
        return False
    m = re.search(r"(20\d\d)[-/.年](\d{1,2})[-/.月](\d{1,2})", deadline)
    try:
        if m:
            due = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        else:
            short = re.search(r"(?<!\d)(\d{1,2})[-/.月](\d{1,2})(?:日)?(?!\d)", deadline)
            if short:
                month, day = int(short.group(1)), int(short.group(2))
            else:
                month_only = re.search(r"(?<!\d)(?:(20\d\d)年)?(\d{1,2})月(?:底|末)?(?!\d)", deadline)
                if not month_only:
                    return False
                month = int(month_only.group(2))
                day = 0
            published = date.fromisoformat(post_date) if post_date else date.fromisoformat(today)
            year = int(month_only.group(1)) if not short and month_only.group(1) else published.year + (published.month >= 10 and month <= 3)
            if day == 0:
                day = calendar.monthrange(year, month)[1]
            due = date(year, month, day)
    except ValueError:
        return False
    return due < date.fromisoformat(today)


def is_stale(post_date, deadline, today, max_age_days=180):
    """没有明确未来截止日且长期未更新的公告，不再作为正在进行展示。"""
    if not post_date:
        return True
    try:
        age = (date.fromisoformat(today) - date.fromisoformat(post_date)).days
    except ValueError:
        return True
    if age < 0:
        return True
    if age <= max_age_days:
        return False
    m = re.search(r"(20\d\d)[-/.年](\d{1,2})[-/.月](\d{1,2})", deadline or "")
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3))) < date.fromisoformat(today)
        except ValueError:
            pass
    return True


def clean_url(value):
    """只保留可打开的 HTTP(S) 链接，避免源站脏字段变成错误投递地址。"""
    value = (value or "").strip()
    if not value or any(c.isspace() for c in value):
        return ""
    try:
        url = urlsplit(value)
        host = url.hostname or ""
        host.encode("idna").decode("ascii")
    except (ValueError, UnicodeError):
        return ""
    if url.scheme not in ("http", "https") or not host or "." not in host or url.username or url.password:
        return ""
    return value


def is_placeholder_date(d):
    """判断是否为源站占位日期（如 2026-12-31 / 2099-01-01），占位视为无效。"""
    if not d:
        return True
    if re.match(r"^\d{4}-12-31$", d) or re.match(r"^\d{4}-01-01$", d):
        return True
    if d.startswith(("2099", "9999", "2100")):
        return True
    return False


# ---------- 学历要求推导（宽松口径：未明确"本科及以上"要求的视为专科可报） ----------
# 强信号：明确的"本科及以上/硕士/博士"等学历要求句式（排除岗位名里混入的"硕士顾问/博士后研究员"等词）
BACHELOR_PLUS_RE = re.compile(
    r"本科及以上|本科以上|本科起|本科学历|本科及本科以上|本科或以上|本科及硕士|"
    r"硕士研究生及以上|硕士及以上|硕士以上|硕士学历|"
    r"博士研究生及以上|博士及以上|博士学历|"
    r"研究生学历|全日制.{0,4}(本科|硕士|博士)(?:学历|以上|及以上)|"
    r"(本科|硕士|博士)(?:及以上|以上|学历)"
)
COLLEGE_RE = re.compile(r"专科|大专|高职|职业技术|高等职业")


def parse_edu(text):
    """从岗位/公告文本推导学历要求。
    返回 (edu_req, is_college)：
    - edu_req 取值：专科及以上 / 本科及以上 / 硕士及以上 / 博士及以上 / 不限
    - is_college：宽松口径 = 未明确要求本科及以上的记录视为专科可报；
      明确提到"专科/大专/高职"的记录（即使同时提到本科及以上）视为专科可报。
    """
    if not text:
        return "不限", True
    if COLLEGE_RE.search(text):
        # 明确提到专科/大专/高职 → 有专科岗位，专科可报（如"本科及以上毕业生和主专业高职大专生"）
        return "专科及以上", True
    if BACHELOR_PLUS_RE.search(text):
        if re.search(r"博士研究生|博士及以上|博士学历", text):
            return "博士及以上", False
        if re.search(r"硕士研究生|硕士及以上|硕士以上|硕士学历", text):
            return "硕士及以上", False
        return "本科及以上", False
    return "不限", True


def main():
    now_bj = datetime.now(ZoneInfo("Asia/Shanghai"))
    today = now_bj.date().isoformat()
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

    # ---------- 1.5 今日校招公司名 -> 最新有效更新时间（修正同名记录的新增状态） ----------
    haz_latest = {}
    for h in haz_companies.values():
        upd = (h.get("update_time") or "").strip()[:10]
        if re.match(r"^\d{4}-\d{2}-\d{2}$", upd) and not is_placeholder_date(upd):
            n = normalize_name(h.get("name", ""))
            if n and (n not in haz_latest or upd > haz_latest[n]):
                haz_latest[n] = upd

    # ---------- 2. 处理 YouOffer 主记录 ----------
    out = []
    seen_names = set()
    for rec in you_companies.values():
        rt = rec.get("recruit_type", "") or ""
        if not any(k in rt for k in RECRUIT_KEYWORDS):
            continue
        post_date = (rec.get("post_date") or "").strip()[:10]
        # 无效/占位日期（如 -0001-11-30、2026-12-31）置空
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", post_date) or is_placeholder_date(post_date):
            post_date = ""
        # 若今日校招有该公司的更新（update_time 更晚），采用其更新时间以反映"今日新增"
        n0 = normalize_name(rec.get("name", ""))
        if n0 in haz_latest and haz_latest[n0] > post_date:
            post_date = haz_latest[n0]
        if is_expired(rec.get("deadline", ""), today, post_date):
            continue
        if is_stale(post_date, rec.get("deadline", ""), today):
            continue
        years = parse_years(rec.get("target_years", ""))
        is26 = "2026" in years
        positions, majors = split_positions(rec.get("position", ""))
        edu_req, is_college = parse_edu(rec.get("position", "") + " " + rec.get("name", ""))
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
            "edu_req": edu_req,
            "is_college": is_college,
            "post_date": post_date,
            "deadline": rec.get("deadline", ""),
            "apply_url": clean_url(rec.get("apply_url")) or clean_url(rec.get("notice_url")),
            "notice_url": clean_url(rec.get("notice_url")),
            "status": "today_new" if post_date == today else "ongoing",
        }
        out.append(item)
        seen_names.add(normalize_name(item["name"]))

    # ---------- 2.5 按公司归一化名合并去重 ----------
    # 同一公司在 YouOffer 中常有多个公告（不同届数/不同岗位），
    # 合并为一条卡片：聚合岗位/专业/届数/地点/截止，避免列表大量重复。
    def merge_group(items):
        all_pos, seen_pos = [], set()
        all_maj, seen_maj = [], set()
        all_loc, seen_loc = [], set()
        all_years = set()
        best_post, best_dl = "", ""
        base = next((it for it in items if it.get("is_26")), items[0])
        for it in items:
            for p in it.get("positions") or []:
                if p and p not in seen_pos:
                    seen_pos.add(p)
                    all_pos.append(p)
            for m in it.get("majors") or []:
                if m and m not in seen_maj:
                    seen_maj.add(m)
                    all_maj.append(m)
            for l in re.split(r"[,，、\s]+", it.get("location") or ""):
                if l and l not in seen_loc:
                    seen_loc.add(l)
                    all_loc.append(l)
            for y in it.get("years") or []:
                all_years.add(y)
            if (it.get("post_date") or "") > best_post:
                best_post = it["post_date"]
            dl = it.get("deadline") or ""
            if dl and "招满" not in dl and dl > best_dl:
                best_dl = dl
        m = dict(base)
        # 合并后的显示名：优先无括号注释的原始名；全带括号则去掉括号
        clean = None
        for it in items:
            if not re.search(r"[（(]", it["name"] or ""):
                clean = it["name"]
                break
        if clean is None:
            clean = re.sub(r"[（(].*?[)）]", "", items[0]["name"] or "").strip()
        m["name"] = clean
        m["positions"] = all_pos
        m["majors"] = all_maj
        m["location"] = " ".join(all_loc) if all_loc else base.get("location", "")
        m["years"] = sorted(all_years)
        m["is_26"] = any(it.get("is_26") for it in items)
        # 学历聚合（宽松口径：任一记录未明确本科及以上 → 公司专科可报）
        edu_reqs = [it.get("edu_req") for it in items if it.get("edu_req")]
        m["is_college"] = any(it.get("is_college") for it in items)
        if m["is_college"]:
            m["edu_req"] = "专科及以上" if any("专科" in (e or "") for e in edu_reqs) else "不限"
        else:
            _order = {"本科及以上": 1, "硕士及以上": 2, "博士及以上": 3}
            m["edu_req"] = max(edu_reqs, key=lambda e: _order.get(e, 0)) if edu_reqs else "不限"
        m["post_date"] = best_post
        m["deadline"] = best_dl or base.get("deadline", "")
        m["status"] = "today_new" if best_post == today else "ongoing"
        # 合并届数描述（如 2026届,2027届）
        ty = set()
        for it in items:
            for x in re.split(r"[,，]", it.get("target_years") or ""):
                x = x.strip()
                if x:
                    ty.add(x)
        m["target_years"] = ",".join(sorted(ty))
        # position 原始字符串更新为聚合岗位（详情回退与搜索用）
        if all_pos:
            m["position"] = " ".join(all_pos[:20])
        return m

    merged_out = []
    ygroups = defaultdict(list)
    for it in out:
        ygroups[normalize_name(it["name"])].append(it)
    for _, items in ygroups.items():
        if len(items) == 1:
            merged_out.append(items[0])
        else:
            merged_out.append(merge_group(items))
    out = merged_out
    seen_names = {normalize_name(it["name"]) for it in out}

    # ---------- 3. 补充 hahazhao 独有公司 ----------
    # 同一公司在 hahazhao 可能有多个年份公告，按更新时间降序处理，最新公告优先收录
    haz_sorted = sorted(
        haz_companies.values(),
        key=lambda x: (x.get("update_time") or x.get("publish_date") or ""),
        reverse=True,
    )
    for h in haz_sorted:
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
        if re.match(r"^\d{4}-\d{2}-\d{2}$", upd) and not is_placeholder_date(upd):
            post_date = upd
        else:
            post_date = pub if (re.match(r"^\d{4}-\d{2}-\d{2}$", pub) and not is_placeholder_date(pub)) else ""
        if is_expired(h.get("deadline", ""), today, post_date):
            continue
        if is_stale(post_date, h.get("deadline", ""), today):
            continue
        years = parse_years(h.get("recruit_target", ""))
        is26 = "2026" in years
        edu_req, is_college = parse_edu(h.get("title", "") + " " + name)
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
            "edu_req": edu_req,
            "is_college": is_college,
            "post_date": post_date,
            "deadline": h.get("deadline", ""),
            "apply_url": clean_url(h.get("apply_link")) or clean_url(h.get("original_link")),
            "notice_url": clean_url(h.get("original_link")),
            "status": "today_new" if post_date == today else "ongoing",
        }
        out.append(item)
        seen_names.add(n)

    # ---------- 4. 排序：今日新增按日期降序；正在进行也按更新时间降序 ----------
    out.sort(key=lambda x: (x["post_date"], x["name"]), reverse=True)

    today_new = [c for c in out if c["status"] == "today_new"]
    ongoing = [c for c in out if c["status"] == "ongoing"]
    today_new_26 = [c for c in today_new if c["is_26"]]
    today_new_college = [c for c in today_new if c["is_college"]]
    total_college = [c for c in out if c["is_college"]]

    industries = sorted({c["industry"] for c in out if c["industry"]})

    meta = {
        "app": "秋招每日通",
        "version": 1,
        "generated_at": now_bj.strftime("%Y-%m-%d %H:%M:%S"),
        "today": today,
        "total": len(out),
        "today_new": len(today_new),
        "today_new_26": len(today_new_26),
        "today_new_college": len(today_new_college),
        "total_college": len(total_college),
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
