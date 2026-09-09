# -*- coding: utf-8 -*-
"""每日增量更新入口：抓最新数据 -> 重建 APP 数据。

容错策略：单个数据源失败不阻断整体，只要至少一个源成功就继续构建；
两个源都失败才退出非 0（触发失败通知，提醒检查数据源）。
"""
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable


def run(name, *args):
    print("==> %s %s" % (name, " ".join(args)))
    r = subprocess.run([PY, os.path.join(BASE, name)] + list(args))
    return r.returncode


def main():
    ok = 0
    for name, args in (
        ("youoffer.py", ("--daily",)),        # 抓取 YouOffer 前 5 页（今日新增/最新更新）
        ("hahazhao.py", ("--pages", "5")),    # 抓取今日校招前 5 页
    ):
        rc = run(name, *args)
        if rc == 0:
            ok += 1
        else:
            print("!! %s 失败（退出码 %d），继续尝试其他数据源" % (name, rc))
    if ok == 0:
        print("!! 两个数据源均失败，本次跳过构建")
        sys.exit(1)
    rc = run("build.py")                      # 合并重建 app/data/data.json
    if rc != 0:
        sys.exit(rc)
    print("每日更新完成。")


if __name__ == "__main__":
    main()
