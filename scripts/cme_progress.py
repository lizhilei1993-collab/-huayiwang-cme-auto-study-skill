# -*- coding: utf-8 -*-
"""三门课程进度总览。

用法: python cme_progress.py [cid...]
"""
import json
import sys
from pathlib import Path
from config import (data_dir as _data_dir, host as _host, origin as _origin, site as _site, site_key as _site_key, cdn_base as _cdn, user as _user, password as _pwd, alive_check as _alive_check, alive_marker as _alive_marker, courses as _courses, course_list as _course_list)  # noqa: E402

import requests
from bs4 import BeautifulSoup

BASE = _data_dir()
CK = BASE / "cookies_latest.json"
HOST = _host()

# 课程 ID -> 名称 映射从配置读取（config.json 的 courses 字段），缺省用 ID 本身
COURSES = _courses()


def session():
    raw = json.load(open(CK, "rb"))
    items = raw if isinstance(raw, list) else raw.get("cookies", [])
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"})
    for c in items:
        if _site_key() in (c.get("domain") or ""):
            s.cookies.set(c["name"], c["value"], domain=_site())
    return s


def main():
    s = session()
    cids = sys.argv[1:] or list(COURSES.keys())
    out = []
    for cid in cids:
        r = s.get(HOST + "pages/course.aspx?cid=" + cid, timeout=30)
        r.encoding = "utf-8"
        soup = BeautifulSoup(r.text, "html.parser")
        name = COURSES.get(cid, cid)
        print("=" * 70)
        print("课程:", name)
        for d in soup.select("div.cw-progress-row"):
            wrap = d.find_parent("div", class_="course") or d.find_parent()
            title = ""
            a = (wrap.find("a", class_="cw-title-link") if wrap else None)
            if a:
                title = a.get_text(" ", strip=True)[:34]
            st = d.get("data-studystate")
            rec = {
                "cid": cid, "course": name,
                "cwid": d.get("data-cwrid"), "coaid": d.get("data-coaid"),
                "title": title,
                "maxtime": int(d.get("data-maxtime") or 0),
                "totaltime": int(d.get("data-totaltime") or 0),
                "completed": int(d.get("data-completed") or 0),
                "state": st,
            }
            out.append(rec)
            print("  %-36s %-8s 进度=%s/%s" % (title, st, rec["completed"], rec["totaltime"] or rec["maxtime"]))
    (BASE / "progress.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("->", BASE / "progress.json")


if __name__ == "__main__":
    main()
