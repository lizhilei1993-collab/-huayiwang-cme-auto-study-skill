# -*- coding: utf-8 -*-
"""纯 HTTP 版讲义下载（用 cookie 文件直连，不占用浏览器）。

用法: python cme_slides_http.py c2:1 c2:2 ...
"""
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from config import (data_dir as _data_dir, host as _host, origin as _origin, site as _site, site_key as _site_key, cdn_base as _cdn, user as _user, password as _pwd, alive_check as _alive_check, alive_marker as _alive_marker, courses as _courses, course_list as _course_list)  # noqa: E402

import requests

BASE = _data_dir()
PLAN = json.loads((BASE / "units_plan.json").read_text(encoding="utf-8"))

HDR = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36",
    "Referer": _host(),
}


def cookie_jar():
    cookies = json.loads((BASE / "cookies_latest.json").read_text(encoding="utf-8"))
    jar = {}
    for c in cookies:
        if _site_key() in (c.get("domain") or ""):
            jar[c["name"]] = c["value"]
    return jar


def unit_by(code, index):
    for u in PLAN[code]["units"]:
        if u["index"].rstrip(".") == str(index):
            return u
    return None


def main():
    pairs = sys.argv[1:]
    jar = cookie_jar()
    sess = requests.Session()
    sess.headers.update(HDR)
    sess.cookies.update(jar)
    summary = []
    for pair in pairs:
        code, index = pair.split(":")
        u = unit_by(code, index)
        if not u:
            print("!! not found", pair)
            continue
        cwid = u["cwid"]
        key = "%su%s" % (code, index)
        outdir = BASE / "slides" / key
        jy_url = (_host() + "course_ware/course_ware_jy_view.aspx?course_ware_id=%s&can_exam=1") % cwid
        try:
            r = sess.get(jy_url, timeout=25)
        except Exception as e:
            print("!! %s jy fetch failed: %r" % (key, e))
            continue
        body = r.text
        m = re.search(r"jiangyi/([0-9A-Za-z_\-]{6,40})/jypic", body)
        if not m:
            print("!! %s no uploadid (status %s len %d)" % (key, r.status_code, len(body)))
            summary.append({"key": key, "cwid": cwid, "ok": False})
            continue
        uploadid = m.group(1)
        pages = re.findall(r"jypic/(\d+)\.JPG", body)
        maxpage = max([int(p) for p in pages], default=90)
        outdir.mkdir(parents=True, exist_ok=True)

        def fetch(n):
            url = _cdn() + "/jiangyi/%s/jypic/%d.JPG" % (uploadid, n)
            dst = outdir / ("%d.JPG" % n)
            if dst.exists() and dst.stat().st_size > 1000:
                return True
            try:
                rr = sess.get(url, timeout=20)
                if rr.status_code == 200 and len(rr.content) > 1000:
                    dst.write_bytes(rr.content)
                    return True
            except Exception:
                pass
            return False

        got = 0
        with ThreadPoolExecutor(max_workers=6) as ex:
            for ok in ex.map(fetch, range(1, maxpage + 1)):
                if ok:
                    got += 1
        print("== %s %s uploadid=%s pages=%d/%d" % (key, u["title"][:26], uploadid, got, maxpage))
        summary.append({"key": key, "cwid": cwid, "uploadid": uploadid, "pages": got, "ok": got > 0})
    (BASE / "slides_summary_http.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
