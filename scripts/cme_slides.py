# -*- coding: utf-8 -*-
"""下载指定单元的讲义幻灯片。

用法: python cme_slides.py c3:6 c3:7 c2:1 ...
- 通过浏览器(当前端口) fetch jy_view 页拿到 uploadid
- 从 CDN 并发下载 jypic/{n}.JPG 到 ab/slides/{key}/
"""
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from config import (data_dir as _data_dir, host as _host, origin as _origin, site as _site, site_key as _site_key, cdn_base as _cdn, user as _user, password as _pwd, alive_check as _alive_check, alive_marker as _alive_marker, courses as _courses, course_list as _course_list)  # noqa: E402

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cme_cdp as C  # noqa

BASE = _data_dir()
PLAN = json.loads((BASE / "units_plan.json").read_text(encoding="utf-8"))
COURSE_BY_CODE = {"c1": "c1", "c2": "c2", "c3": "c3"}


def unit_by(code, index):
    for u in PLAN[code]["units"]:
        if u["index"].rstrip(".") == str(index):
            return u
    return None


def get_uploadid(c, cwid):
    r = C.evaluate(c, r"""(async () => {
      const r = await fetch('/course_ware/course_ware_jy_view.aspx?course_ware_id=%s&can_exam=1&r=' + Math.random(), {credentials:'include'});
      const t = await r.text();
      return {status: r.status, len: t.length, body: t};
    })()""" % cwid, await_promise=True)
    body = r.get("body") or ""
    (BASE / "jy").mkdir(exist_ok=True)
    (BASE / "jy" / ("%s.html" % cwid)).write_text(body, encoding="utf-8")
    m = re.search(r"jiangyi/([0-9A-Za-z_\-]{6,40})/jypic", body)
    uploadid = m.group(1) if m else None
    # 页数线索
    pages = re.findall(r"jypic/(\d+)\.JPG", body)
    maxpage = max([int(p) for p in pages], default=None)
    return uploadid, maxpage, r.get("status"), len(body)


def download_slides(uploadid, outdir, maxpage=None):
    outdir.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0", "Referer": _host()})

    def fetch(n):
        url = _cdn() + "/jiangyi/%s/jypic/%d.JPG" % (uploadid, n)
        dst = outdir / ("%d.JPG" % n)
        if dst.exists() and dst.stat().st_size > 1000:
            return n, True, dst.stat().st_size, "cached"
        try:
            r = session.get(url, timeout=20)
            if r.status_code == 200 and len(r.content) > 1000:
                dst.write_bytes(r.content)
                return n, True, len(r.content), "ok"
            return n, False, 0, "status=%s len=%d" % (r.status_code, len(r.content))
        except Exception as e:
            return n, False, 0, repr(e)

    limit = maxpage if maxpage else 90
    got = 0
    fails_in_row = 0
    n = 1
    results = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        # 分批推进（先并行拉 24 页，遇到连续失败就停）
        while n <= limit:
            batch = list(range(n, min(n + 24, limit + 1)))
            for num, ok, size, note in ex.map(fetch, batch):
                results.append((num, ok, size, note))
                if ok:
                    got += 1
                    fails_in_row = 0
                else:
                    fails_in_row += 1
            # 批量里如果有失败，可能就是到尾了（除非中间缺失）
            n += 24
            if fails_in_row >= len(batch):
                break
    return got, results


def main():
    pairs = sys.argv[1:]
    c = C.page_cdp()
    summary = []
    try:
        for pair in pairs:
            code, index = pair.split(":")
            u = unit_by(code, index)
            if not u:
                print("!! not found", pair)
                continue
            cwid = u["cwid"]
            key = "%su%s" % (code, index)
            uploadid, maxpage, status, blen = get_uploadid(c, cwid)
            print("== %s [%s] %s -> uploadid=%s maxpage=%s (status=%s len=%s)" % (
                key, cwid, u["title"][:30], uploadid, maxpage, status, blen))
            if not uploadid:
                summary.append({"key": key, "cwid": cwid, "ok": False})
                continue
            outdir = BASE / "slides" / key
            got, results = download_slides(uploadid, outdir, maxpage)
            okcount = sum(1 for r in results if r[1])
            print("   downloaded %d pages -> %s" % (okcount, outdir))
            summary.append({"key": key, "cwid": cwid, "uploadid": uploadid, "pages": okcount, "ok": True})
    finally:
        c.close()
    print(json.dumps(summary, ensure_ascii=False))
    (BASE / "slides_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
