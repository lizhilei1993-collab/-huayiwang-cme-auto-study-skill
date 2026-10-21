# -*- coding: utf-8 -*-
"""验证码页处理（通用）。

用法:
  python cme_captcha.py fetch <页面相对路径> [图片输出路径]
      拉取页面 + 验证码图片，隐藏字段存 ab/captcha_state.json
      例: python cme_captcha.py fetch "pages/exam_code.aspx?cwid=xxx"
  python cme_captcha.py submit <验证码> [页面相对路径]
      提交验证码，打印结果
"""
import json
import os
import re
import sys
import urllib.parse
from pathlib import Path
from config import (data_dir as _data_dir, host as _host, origin as _origin, site as _site, site_key as _site_key, cdn_base as _cdn, user as _user, password as _pwd, alive_check as _alive_check, alive_marker as _alive_marker, courses as _courses, course_list as _course_list)  # noqa: E402

import requests
from bs4 import BeautifulSoup

BASE = _data_dir()
STATE = BASE / "captcha_state.json"
CK = BASE / "cookies_latest.json"
HOST = _host()


def session():
    raw = json.load(open(CK, "rb"))
    items = raw if isinstance(raw, list) else raw.get("cookies", [])
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
        "Referer": HOST + "pages/cme.aspx",
    })
    for c in items:
        if _site_key() in (c.get("domain") or ""):
            s.cookies.set(c["name"], c["value"], domain=_site())
    return s


def cmd_fetch(rel, imgout=None):
    s = session()
    url = rel if rel.startswith("http") else HOST + rel.lstrip("/")
    r = s.get(url, timeout=30)
    r.encoding = "utf-8"
    soup = BeautifulSoup(r.text, "html.parser")
    fields = {}
    for name in ("__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION",
                 "__EVENTTARGET", "__EVENTARGUMENT"):
        el = soup.find("input", {"name": name})
        if el is not None:
            fields[name] = el.get("value", "")
    # 表单 action
    form = soup.find("form")
    action = form.get("action") if form else rel
    # 验证码图片
    img = soup.select_one("img.yzm_img, img#imgCheckCode, img#yzm_img")
    src = img.get("src") if img else None
    out = imgout or str(BASE / "captcha.jpg")
    ok = False
    if src:
        iu = src if src.startswith("http") else HOST + src.lstrip("/")
        ir = s.get(iu, timeout=30)
        with open(out, "wb") as f:
            f.write(ir.content)
        ok = len(ir.content) > 500
    # 文本框名
    tb = soup.find("input", {"name": re.compile("CheckCode|imgCode|code", re.I)})
    STATE.write_text(json.dumps({
        "action": action, "page_url": url, "fields": fields,
        "textbox": tb.get("name") if tb else None,
        "img": out, "img_ok": ok,
        "cookies": {c.name: c.value for c in s.cookies},
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print("page:", r.status_code, len(r.text), "| action:", action)
    print("textbox:", tb.get("name") if tb else None, "| img:", out, "ok=", ok)
    print("state ->", STATE)
    return 0


def cmd_submit(code, rel=None):
    st = json.loads(STATE.read_text(encoding="utf-8"))
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
    })
    for k, v in st["cookies"].items():
        s.cookies.set(k, v, domain=_site())
    action = rel or st["action"]
    if action.startswith("http"):
        url = action
    else:
        url = urllib.parse.urljoin(st.get("page_url", HOST), action)
    data = dict(st["fields"])
    if st.get("textbox"):
        data[st["textbox"]] = code
    data["btnYes"] = "提交"
    r = s.post(url, data=data, timeout=40, allow_redirects=True)
    r.encoding = "utf-8"
    (BASE / "captcha_submit.html").write_text(r.text, encoding="utf-8")
    soup = BeautifulSoup(r.text, "html.parser")
    txt = soup.get_text(" ", strip=True)
    print("POST ->", r.status_code, r.url)
    print("snippet:", txt[:400])
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(0)
    if sys.argv[1] == "fetch":
        sys.exit(cmd_fetch(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None))
    if sys.argv[1] == "submit":
        sys.exit(cmd_submit(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None))
    print("unknown")
