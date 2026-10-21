# -*- coding: utf-8 -*-
"""在当前已登录页面内 fetch 接口，导出课程与单元清单。"""
import json
import sys
from pathlib import Path
from config import (data_dir as _data_dir, host as _host, origin as _origin, site as _site, site_key as _site_key, cdn_base as _cdn, user as _user, password as _pwd, alive_check as _alive_check, alive_marker as _alive_marker, courses as _courses, course_list as _course_list)  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cme_cdp as C  # noqa

OUT = _data_dir()

c = C.page_cdp()
try:
    # 1) 学习记录列表
    r = C.evaluate(c, r"""(async () => {
      const tries = [
        '/ashx/getStudyList.ashx?year=2026',
        '/ashx/getStudyList.ashx',
      ];
      const out = [];
      for (const u of tries) {
        try {
          const r = await fetch(u + '&r=' + Math.random(), {credentials:'include'});
          const t = await r.text();
          out.push({u, status: r.status, len: t.length, body: t.slice(0, 60000)});
        } catch (e) { out.push({u, err: String(e)}); }
      }
      return out;
    })()""", await_promise=True)
    (OUT / "studylist_raw.json").write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
    for item in r:
        print("== ", item.get("u"), item.get("status"), item.get("len"), item.get("err", ""))
        if item.get("body"):
            print(item["body"][:1200])
            print("...")
finally:
    c.close()
