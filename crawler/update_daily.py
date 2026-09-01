# -*- coding: utf-8 -*-
"""每日增量更新入口：抓最新数据 -> 重建 APP 数据。"""
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable


def run(name, *args):
    print("==> %s %s" % (name, " ".join(args)))
    r = subprocess.run([PY, os.path.join(BASE, name)] + list(args))
    if r.returncode != 0:
        print("!! %s 失败，退出码 %d" % (name, r.returncode))
        sys.exit(r.returncode)


def main():
    run("youoffer.py", "--daily")       # 抓取 YouOffer 前 5 页（今日新增/最新更新）
    run("hahazhao.py", "--pages", "5")  # 抓取今日校招前 5 页
    run("build.py")                      # 合并重建 app/data/data.json
    print("每日更新完成。")


if __name__ == "__main__":
    main()
