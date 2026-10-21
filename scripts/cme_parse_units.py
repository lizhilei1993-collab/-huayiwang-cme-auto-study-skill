# -*- coding: utf-8 -*-
"""解析三门课程详情页，输出单元清单（含进度/考试状态），保存为 JSON。"""
import json
import re
from pathlib import Path
from config import (data_dir as _data_dir, host as _host, origin as _origin, site as _site, site_key as _site_key, cdn_base as _cdn, user as _user, password as _pwd, alive_check as _alive_check, alive_marker as _alive_marker, courses as _courses, course_list as _course_list)  # noqa: E402

BASE = _data_dir()
# 课程清单从配置读取（config.json 的 course_list 字段：[["代码","课程名","课程ID","HTML文件名"]]）
COURSES = _course_list()

BLOCK = re.compile(r'<div class="course" data-href=.*?(?=<div class="course"|</form>|<script)', re.S)


def parse(html):
    units = []
    for m in BLOCK.finditer(html):
        seg = m.group(0)
        cwid = re.search(r"cwid=([0-9a-f\-]{36})", seg)
        idx = re.search(r'cw-index">([^<]*)<', seg)
        title = re.search(r"<strong>([^<]*)</strong>", seg)
        maxtime = re.search(r'data-maxtime="(\d+)"', seg)
        totaltime = re.search(r'data-totaltime="(\d+)"', seg)
        completed = re.search(r'data-completed="(\d)"', seg)
        state = re.search(r'data-studystate="([^"]*)"', seg)
        btn = re.search(r'<button[^>]*>([^<]*)</button>', seg)
        units.append({
            "index": (idx.group(1).strip() if idx else "?"),
            "cwid": cwid.group(1) if cwid else None,
            "title": title.group(1).strip() if title else "",
            "maxtime": int(maxtime.group(1)) if maxtime else None,
            "totaltime": int(totaltime.group(1)) if totaltime else None,
            "completed": int(completed.group(1)) if completed else None,
            "studystate": state.group(1) if state else None,
            "btn": btn.group(1).strip() if btn else None,
        })
    return units


def secs(v):
    if v is None:
        return "?"
    return "%d:%02d" % (v // 60, v % 60)


all_data = {}
for code, name, cid, fname in COURSES:
    html = (BASE / fname).read_text(encoding="utf-8")
    units = parse(html)
    all_data[code] = {"course_id": cid, "course_name": name, "units": units}
    print("==== %s %s (%d units)" % (code, name, len(units)))
    for u in units:
        print("  %-4s %-62s max=%-11s total=%-11s done=%s state=%s btn=%s" % (
            u["index"], u["title"][:60], secs(u["maxtime"]), secs(u["totaltime"]),
            u["completed"], u["studystate"], u["btn"]))

(BASE / "units_plan.json").write_text(json.dumps(all_data, ensure_ascii=False, indent=1), encoding="utf-8")
print("\nsaved units_plan.json")
