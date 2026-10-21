# -*- coding: utf-8 -*-
"""打开指定课件页并检查播放器状态 / 续播位置（含服务器端进度查询）。"""
import json
import sys
import time
from pathlib import Path
from config import (data_dir as _data_dir, host as _host, origin as _origin, site as _site, site_key as _site_key, cdn_base as _cdn, user as _user, password as _pwd, alive_check as _alive_check, alive_marker as _alive_marker, courses as _courses, course_list as _course_list)  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cme_cdp as C  # noqa

CWID = sys.argv[1] if len(sys.argv) > 1 else ""
URL = (_host() + "course_ware/course_ware_polyv.aspx?ff=0&ft=0&cwid=%s&t=0") % CWID
OUT = _data_dir()
OUT.mkdir(parents=True, exist_ok=True)

c = C.page_cdp()
try:
    print("navigating:", URL)
    C.evaluate(c, "location.href=%s" % json.dumps(URL))
    for _ in range(60):
        time.sleep(1)
        st = C.evaluate(c, "document.readyState")
        if st == "complete":
            break
    time.sleep(3)

    # 页面与播放器状态
    info = C.evaluate(c, r"""(() => {
      const out = {url: location.href, title: document.title};
      const v = document.querySelector('video');
      out.video = v ? {t: v.currentTime, d: v.duration, paused: v.paused, ready: v.readyState} : null;
      out.hasPolyv = typeof player !== 'undefined';
      try {
        out.ls = {}; 
        for (let i=0;i<localStorage.length;i++){ const k=localStorage.key(i); if(/play|prog|max|time|course|ware/i.test(k)) out.ls[k]= (localStorage.getItem(k)||'').slice(0,100); }
      } catch(e) { out.ls = String(e); }
      out.buttons = [...document.querySelectorAll('a,button,div,span')].filter(e=>e.offsetParent && /继续|开始|播放|学习/.test(e.innerText||'') && (e.innerText||'').length<12).slice(0,8).map(e=>({tag:e.tagName,id:e.id,cls:(e.className||'').toString().slice(0,30),txt:(e.innerText||'').trim().slice(0,12)}));
      return out;
    })()""")
    print("PAGE:", json.dumps(info, ensure_ascii=False)[:1500])

    # 服务器端进度
    server = C.evaluate(c, r"""(async () => {
      try {
        const r = await fetch('/ashx/get_course_ware_process.ashx?cwid=%s&video_type=polyv&r=' + Math.random(), {credentials:'include'});
        const t = await r.text();
        return t.slice(0, 500);
      } catch (e) { return 'ERR ' + e; }
    })()""" % CWID, await_promise=True)
    print("SERVER:", json.dumps(server, ensure_ascii=False)[:800])
finally:
    c.close()
