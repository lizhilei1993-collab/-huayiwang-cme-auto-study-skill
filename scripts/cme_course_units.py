# -*- coding: utf-8 -*-
"""抓取课程详情页 HTML，提取单元（cwid）清单。"""
import json
import re
import sys
from pathlib import Path
from config import (data_dir as _data_dir, host as _host, origin as _origin, site as _site, site_key as _site_key, cdn_base as _cdn, user as _user, password as _pwd, alive_check as _alive_check, alive_marker as _alive_marker, courses as _courses, course_list as _course_list)  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cme_cdp as C  # noqa

OUT = _data_dir()
# 课程清单从配置读取（config.json 的 courses 字段：{"名称": "课程ID"}）
COURSES = _courses()

c = C.page_cdp()
try:
    for name, cid in COURSES.items():
        r = C.evaluate(c, r"""(async () => {
          const r = await fetch('/pages/course.aspx?cid=%s&r=' + Math.random(), {credentials:'include'});
          const t = await r.text();
          return {status: r.status, len: t.length, body: t};
        })()""" % cid, await_promise=True)
        body = r.get("body") or ""
        (OUT / ("course_%s.html" % name)).write_text(body, encoding="utf-8")
        # 提取 HTML 中的 GUID 与可能的课件标题
        guids = sorted(set(re.findall(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", body)))
        print("==", name, cid, "status", r.get("status"), "len", r.get("len"))
        print("   guids:", len(guids))
        # 找 cwid= 引用
        cw = re.findall(r"cwid=([0-9a-f\-]{36})", body)
        print("   cwid refs:", len(cw), "unique:", len(set(cw)))
        # 找 js 里的数组数据
        m = re.search(r"course_ware_list|courseWareList|wareList|course_ware_id", body)
        print("   marker:", bool(m))
finally:
    c.close()
