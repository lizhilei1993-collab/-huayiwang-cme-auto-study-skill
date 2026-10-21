# -*- coding: utf-8 -*-
"""平台登录（优先纯 HTTP + ddddocr 全自动；浏览器版保留为兜底）

用法:
  python cme_login.py                 # 自动登录（纯 HTTP），刷新 ab/cookies_latest.json
  python cme_login.py check           # 检查 ab/cookies_latest.json 是否仍有效
  python cme_login.py captcha         # [兜底] 浏览器打开登录页并导出放大验证码图
  python cme_login.py submit 72074    # [兜底] 浏览器填入账号密码验证码并提交

登录机制（实测）:
  POST /ashx/loginsso.ashx  (form serialize of #form1, loginType=1 为密码登录)
  验证码: GET /secure/CheckCode.aspx  (同 session)
"""
import json
import os
import re
import sys
import time
from pathlib import Path
from config import (data_dir as _data_dir, host as _host, origin as _origin, site as _site, site_key as _site_key, cdn_base as _cdn, user as _user, password as _pwd, alive_check as _alive_check, alive_marker as _alive_marker, courses as _courses, course_list as _course_list)  # noqa: E402

import requests
from bs4 import BeautifulSoup

HOST = _host()
LOGIN_PAGE = HOST + "secure/login.aspx"
SSO_POST = HOST + "ashx/loginsso.ashx"
CAPTCHA_URL = HOST + "secure/CheckCode.aspx"
COURSE_TEST = _alive_check()

USER = _user()
PWD = _pwd()
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")

AB = _data_dir()
CKF = AB / "cookies_latest.json"
SHOT = AB / "shots" / "captcha_live.png"

_ocr = None


def ocr():
    global _ocr
    if _ocr is None:
        import ddddocr
        _ocr = ddddocr.DdddOcr(show_ad=False)
    return _ocr


def new_session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
    })
    return s


def load_cookies_into(s, path=None):
    p = Path(path or CKF)
    if not p.exists():
        return 0
    try:
        ck = json.load(open(p, encoding="utf-8"))
    except Exception:
        return 0
    n = 0
    for c in ck:
        try:
            s.cookies.set(c["name"], c["value"], domain=c.get("domain"), path=c.get("path", "/"))
            n += 1
        except Exception:
            pass
    return n


def dump_cookies(s, path=None):
    p = Path(path or CKF)
    out = [{"name": c.name, "value": c.value, "domain": c.domain,
            "path": c.path, "expires": c.expires, "secure": c.secure} for c in s.cookies]
    with open(p, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    return len(out)


def alive(s=None):
    """会话有效性判定：course.aspx 返回带 data-cwrid 的课程页"""
    if s is None:
        s = new_session()
        load_cookies_into(s)
    try:
        r = s.get(COURSE_TEST, timeout=30)
        r.encoding = "utf-8"
        return _alive_marker() in r.text and "login.aspx" not in str(r.url)
    except Exception as e:
        print("alive check error:", e)
        return False


def fetch_captcha(s):
    """同 session 拉验证码并 OCR，返回 (bytes, text)"""
    r = s.get(CAPTCHA_URL, params={"r": str(time.time())}, timeout=30,
              headers={"Referer": LOGIN_PAGE,
                       "Accept": "image/avif,image/webp,image/*,*/*;q=0.8"})
    if r.status_code != 200 or len(r.content) < 200:
        return None, None
    txt = ocr().classification(r.content)
    return r.content, re.sub(r"[^0-9a-zA-Z]", "", txt or "")


def do_login_http(max_try=10):
    s = new_session()
    r = s.get(LOGIN_PAGE, timeout=30)
    r.encoding = "utf-8"
    sp = BeautifulSoup(r.text, "html.parser")

    def hv(name):
        el = sp.find("input", {"name": name})
        return (el.get("value") or "") if el else ""

    vs, vsg = hv("__VIEWSTATE"), hv("__VIEWSTATEGENERATOR")
    urls = hv("urls") or (HOST + "cme/index.html")
    print("login page ok | VIEWSTATE=%d urls=%s" % (len(vs), urls))

    for i in range(1, max_try + 1):
        img, code = fetch_captcha(s)
        if not img:
            print("  [%d] 验证码图片拉取失败" % i)
            time.sleep(2)
            continue
        if not code or len(code) < 3:
            print("  [%d] OCR 可疑: %r" % (i, code))
            time.sleep(1)
            continue
        # 实测正确的字段组合（2026-10-17 验证通过）：
        #   用户名 -> txt_user_name
        #   密码   -> txt_user_pwd（明文框，服务端读的是这个，不是 _real）
        #   协议   -> chec1（checkbox 的 name；agree1 只是 id）
        #   验证码 -> txt_img_code
        data = {
            "__VIEWSTATE": vs, "__VIEWSTATEGENERATOR": vsg,
            "flag": "", "loginType": "1", "urls": urls,
            "unitCode": "", "params": "", "timer": "", "sign": "",
            "txt_user_name": USER,
            "txt_user_pwd": PWD,
            "txt_user_pwd_real": PWD,
            "txt_img_code": code,
            "chec1": "on",
            "agree1": "on",
        }
        rr = s.post(SSO_POST, data=data, timeout=30, headers={
            "Referer": LOGIN_PAGE, "Origin": HOST.rstrip("/"),
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        })
        rr.encoding = "utf-8"
        try:
            js = rr.json()
        except Exception:
            print("  [%d] 非 JSON: %s" % (i, re.sub(r"\s+", " ", rr.text)[:150]))
            time.sleep(2)
            continue

        cv = js.get("code")
        if cv == 0:
            back = (js.get("body") or {}).get("loginReturnUrl") or urls
            print("  [%d] 登录成功 -> %s" % (i, str(back)[:90]))
            try:
                s.get(back, timeout=30)
                s.get(HOST + "cme/index.html", timeout=30)
            except Exception:
                pass
            return s
        print("  [%d] 失败 code=%s msg=%s (ocr=%r)" % (i, cv, js.get("msg"), code))
        time.sleep(1.2)
    return None


# ---------------- 浏览器兜底（沿用旧实现） ----------------

def _cdp():
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import cme_cdp as C
    return C


def do_captcha():
    C = _cdp()
    c = C.page_cdp()
    try:
        if "login.aspx" not in C.evaluate(c, "location.href"):
            C.evaluate(c, "location.href=%s" % json.dumps(LOGIN_PAGE))
            time.sleep(4)
        C.evaluate(c, "(() => { var d=document.getElementById('type_pwd'); if(d){ d.style.display=''; try{jQuery('#type_pwd').trigger('click');}catch(e){} } return 'ok'; })()")
        time.sleep(1.5)
        info = C.evaluate(c, """(() => {
          const el = document.querySelector('#yzm_img'); if (!el) return null;
          el.scrollIntoView({block:'center'});
          const r = el.getBoundingClientRect();
          return {x: Math.max(0,Math.floor(r.left)), y: Math.max(0,Math.floor(r.top)),
                  width: Math.ceil(r.width), height: Math.ceil(r.height)};
        })()""")
        if not info:
            print("NO CAPTCHA IMG")
            return 1
        r = c.send("Page.captureScreenshot", {"format": "png", "clip": dict(info, scale=4)})
        import base64
        SHOT.parent.mkdir(parents=True, exist_ok=True)
        SHOT.write_bytes(base64.b64decode(r["data"]))
        print("captcha saved:", SHOT)
        return 0
    finally:
        c.close()


def do_submit(code):
    C = _cdp()
    c = C.page_cdp()
    try:
        C.type_text(c, "#txt_user_name", USER)
        time.sleep(0.3)
        C.type_text(c, "#txt_user_pwd", PWD)
        time.sleep(0.3)
        C.type_text(c, "#txt_img_code", code)
        time.sleep(0.3)
        vals = C.evaluate(c, """(() => ({
          user: (document.getElementById('txt_user_name')||{}).value,
          pwdReal: (document.getElementById('txt_user_pwd_real')||{}).value,
          code: (document.getElementById('txt_img_code')||{}).value,
          agree: document.getElementById('agree1') ? document.getElementById('agree1').checked : null
        }))()""")
        print("filled:", json.dumps(vals, ensure_ascii=False))
        if not vals.get("agree"):
            C.trusted_click(c, "#agree1")
            time.sleep(0.3)
        C.click_nth_visible(c, "button.btn_login", 0)
        for _ in range(20):
            time.sleep(1)
            if "login.aspx" not in C.evaluate(c, "location.href"):
                break
        print("result:", json.dumps(C.evaluate(c, "({url: location.href, title: document.title})"), ensure_ascii=False))
        return 0
    finally:
        c.close()


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "login"
    if cmd == "captcha":
        return do_captcha()
    if cmd == "submit":
        return do_submit(sys.argv[2])
    if cmd == "check":
        ok = alive()
        print("session alive:", ok)
        return 0 if ok else 1

    if alive():
        print("cookie 仍有效，无需登录")
        return 0
    print("会话失效，开始纯 HTTP 自动登录 ...")
    s = do_login_http()
    if not s:
        print("FATAL 自动登录失败")
        return 2
    ok = alive(s)
    n = dump_cookies(s)
    print("校验:", "OK" if ok else "FAIL", "| 写入", n, "条 cookie ->", CKF)
    return 0 if ok else 3


if __name__ == "__main__":
    sys.exit(main())
