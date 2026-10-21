# -*- coding: utf-8 -*-
"""纯 HTTP 抓取平台页面原文（复用 cookies_latest.json）。
用法: python cme_grab.py <path_or_url> [outfile]
    python cme_grab.py pages/exam_result.aspx?cwid=xxx out.html
"""
import json
import os
import sys
import re

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
AB = os.path.normpath(os.path.join(HERE, "..", "ab"))
CK = os.path.join(AB, "cookies_latest.json")
HOST = _host()


def cookie_jar():
    raw = json.load(open(CK, "rb"))
    items = raw if isinstance(raw, list) else raw.get("cookies", [])
    jar = {}
    for c in items:
        dom = c.get("domain", "")
        if _site_key() in dom:
            jar[c.get("name")] = c.get("value")
    return jar


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    path = sys.argv[1]
    url = path if path.startswith("http") else HOST + path.lstrip("/")
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
        "Referer": HOST + "pages/cme.aspx",
    })
    for k, v in cookie_jar().items():
        s.cookies.set(k, v, domain=_site())
    r = s.get(url, timeout=30)
    r.encoding = r.apparent_encoding or "utf-8"
    print("[GET]", r.status_code, len(r.text), "chars")
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(AB, "grab.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(r.text)
    print("[SAVED]", out)


if __name__ == "__main__":
    main()
