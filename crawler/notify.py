# -*- coding: utf-8 -*-
"""通知文件写入：有新增岗位时写 docs/latest_notify.json（供 APP 内轮询展示）。"""
import json
import os
import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "..", "docs", "data", "data.json")
STATE = os.path.join(BASE, "..", "docs", "notify-state.json")
NOTIFY = os.path.join(BASE, "..", "docs", "latest_notify.json")


def now_bj():
    return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))


def main():
    try:
        d = json.load(open(DATA, encoding="utf-8"))
    except Exception as e:
        print("读取 data.json 失败：", e)
        return 0

    meta = d.get("meta", {})
    today = now_bj().strftime("%Y-%m-%d")
    companies = d.get("companies", [])
    today_new = [c for c in companies if c.get("status") == "today_new"]
    n = len(today_new)
    n26 = len([c for c in today_new if c.get("is_26")])
    gen = meta.get("generated_at", "")

    try:
        st = json.load(open(STATE, encoding="utf-8")) if os.path.exists(STATE) else {}
    except Exception:
        st = {}
    st_date = st.get("date", "")
    st_count = int(st.get("today_new_count", 0))

    should_notify = False
    if today != st_date:
        if n > 0:
            should_notify = True
    elif n > st_count:
        should_notify = True

    if not should_notify:
        print("无新增岗位，不写通知（date=%s 今日新增=%d 上次=%s/%d）" % (today, n, st_date, st_count))
        return 0

    msg = "今日新增 %d 家公司，其中 26 届可投 %d 家。" % (n, n26)
    if gen:
        msg += "（数据更新于 %s）" % gen

    nf = {
        "id": int(now_bj().timestamp()),
        "title": "🎯 秋招有新岗位",
        "msg": msg,
        "at": now_bj().strftime("%Y-%m-%d %H:%M:%S")
    }
    json.dump(nf, open(NOTIFY, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    json.dump({"date": today, "today_new_count": n}, open(STATE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("已写入通知文件：", NOTIFY, "→", msg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
