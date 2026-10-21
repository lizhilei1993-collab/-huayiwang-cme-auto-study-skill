# -*- coding: utf-8 -*-
"""纯 HTTP 考试解题器（不占浏览器，可快速重考）。

用法:
  python cme_http_exam.py get <cwid>                 拉取试卷 -> ab/http/<cwid>.json 并打印题面
  python cme_http_exam.py submit <cwid> [覆盖...]    按答案库作答并提交，打印结果
         覆盖格式: qid前缀=字母  例: 85844bfe=A
  python cme_http_exam.py try <cwid> <qid前缀> A,C,E  依次试若干字母，返回能通过/得分最高的一个
"""
import json
import os
import sys
import time
from pathlib import Path
from config import (data_dir as _data_dir, host as _host, origin as _origin, site as _site, site_key as _site_key, cdn_base as _cdn, user as _user, password as _pwd, alive_check as _alive_check, alive_marker as _alive_marker, courses as _courses, course_list as _course_list)  # noqa: E402

import requests
from bs4 import BeautifulSoup

BASE = _data_dir()
HTTPD = BASE / "http"
HTTPD.mkdir(parents=True, exist_ok=True)
KEYF = BASE / "answers.json"
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


def load_key():
    return json.loads(KEYF.read_text(encoding="utf-8")) if KEYF.exists() else {}


def save_key(k):
    KEYF.write_text(json.dumps(k, ensure_ascii=False, indent=1), encoding="utf-8")


def exam_url(cwid):
    return "%spages/exam.aspx?cwid=%s" % (HOST, cwid)


def parse_paper(html):
    soup = BeautifulSoup(html, "html.parser")
    vs = soup.find("input", {"name": "__VIEWSTATE"})
    vsg = soup.find("input", {"name": "__VIEWSTATEGENERATOR"})
    qs = []
    for t in soup.select("table.tablestyle"):
        q = t.select_one("label.q_name")
        if not q:
            continue
        opts = []
        for i, inp in enumerate(t.select("input[type=radio]")):
            lab = inp.find_parent("label")
            opts.append({
                "letter": chr(65 + i),
                "value": inp.get("value"),
                "text": (lab.get_text(" ", strip=True) if lab else "")[:300],
            })
        qs.append({
            "qid": q.get("data-qid"),
            "text": q.get_text(" ", strip=True),
            "opts": opts,
        })
    return {
        "viewstate": vs["value"] if vs else "",
        "vsg": vsg["value"] if vsg else "",
        "questions": qs,
        "captcha": ("txtCheckCode" in html),
    }


def fetch(s, cwid):
    r = s.get(exam_url(cwid), timeout=30)
    r.encoding = "utf-8"
    p = parse_paper(r.text)
    p["url"] = r.url
    return p


def http_status(s):
    r = s.get(HOST + "pages/studylist.aspx", timeout=30, allow_redirects=True)
    return "login" if "login.aspx" in r.url else "ok"


def submit(s, cwid, paper, pick):
    """pick: qid -> letter"""
    parts = []
    for q in paper["questions"]:
        L = pick.get(q["qid"])
        if not L:
            raise SystemExit("缺答案: %s | %s" % (q["qid"], q["text"][:40]))
        val = None
        for o in q["opts"]:
            if o["letter"] == L:
                val = o["value"]
        parts.append("%s|%s" % (q["qid"], val))
    data = {
        "__VIEWSTATE": paper["viewstate"],
        "__VIEWSTATEGENERATOR": paper["vsg"],
        "hd_result": ",".join(parts),
        "btn_submit.x": "10",
        "btn_submit.y": "10",
    }
    s.headers.update({
        "Origin": HOST.rstrip("/"),
        "Referer": exam_url(cwid),
        "Content-Type": "application/x-www-form-urlencoded",
        "Upgrade-Insecure-Requests": "1",
    })
    time.sleep(2)  # 模拟人间隔，避免触发"考试异常"
    r = s.post(exam_url(cwid), data=data, timeout=40, allow_redirects=True)
    r.encoding = "utf-8"
    return r


def parse_result(html):
    soup = BeautifulSoup(html, "html.parser")
    txt = soup.get_text(" ", strip=True)
    out = {"score": None, "fail": ("考试未通过" in txt), "pass": ("考试通过" in txt),
           "wrong": [], "captcha": ("检测到考试异常" in txt or "txtCheckCode" in html)}
    import re
    m = re.search(r"得分[:：]?\s*(\d+)", txt)
    if m:
        out["score"] = int(m.group(1))
    for i, li in enumerate(soup.select("li.state_cour_lis")):
        img = li.find("img")
        src = img.get("src", "") if img else ""
        ps = [(p.get("title") or p.get_text(" ", strip=True)) for p in li.find_all("p")]
        if "error_icon" in src:
            out["wrong"].append({"i": i + 1, "q": (ps[0] if ps else "")[:70]})
    return out


def cmd_get(cwid):
    s = session()
    p = fetch(s, cwid)
    (HTTPD / ("%s.json" % cwid)).write_text(
        json.dumps(p, ensure_ascii=False, indent=1), encoding="utf-8")
    for i, q in enumerate(p["questions"]):
        print("Q%d [%s] %s" % (i + 1, q["qid"][:8], q["text"][:80]))
        for o in q["opts"]:
            print("   %s %s" % (o["letter"], o["text"][:70]))
    print("saved ->", HTTPD / ("%s.json" % cwid))
    return 0


def build_pick(paper, overrides):
    key = load_key()
    pick = {}
    for q in paper["questions"]:
        qid = q["qid"]
        let = None
        for k, v in overrides.items():
            if qid.lower().startswith(k):
                let = v
        if let is None:
            let = key.get(qid)
        if let:
            pick[qid] = let
    return pick


def cmd_submit(cwid, overrides):
    s = session()
    p = fetch(s, cwid)
    pick = build_pick(p, overrides)
    print("== 作答 ==")
    for q in p["questions"]:
        print("  Q[%s] %s -> %s" % (q["qid"][:8], q["text"][:45], pick.get(q["qid"], "?")))
    r = submit(s, cwid, p, pick)
    res = parse_result(r.text)
    print("POST ->", r.status_code, r.url)
    print(json.dumps(res, ensure_ascii=False))
    (HTTPD / ("%s.result.html" % cwid)).write_text(r.text, encoding="utf-8")
    return 0


def cmd_try(cwid, qidpfx, letters):
    s = session()
    todo = [L.strip().upper() for L in letters.split(",") if L.strip()]
    best = {"score": -1, "letter": None}
    for L in todo:
        p = fetch(s, cwid)
        pick = build_pick(p, {qidpfx.lower(): L})
        r = submit(s, cwid, p, pick)
        res = parse_result(r.text)
        if res["captcha"]:
            print("!!! 触发验证码，需要人工过闸（试着改小批次）。已试: %s" % L)
            return 9
        nwrong = len(res["wrong"])
        print("try %s=%s -> 错题数=%s %s" % (qidpfx, L, nwrong,
                                           [w["i"] for w in res["wrong"]]))
        if nwrong == 0:
            print("*** 全对！%s = %s ***" % (qidpfx, L))
            key = load_key()
            for q in p["questions"]:
                if q["qid"].lower().startswith(qidpfx.lower()):
                    key[q["qid"]] = L
                    print("   已写入答案库:", q["qid"], "=", L)
            save_key(key)
            return 0
        if nwrong and (5 - nwrong) > best["score"]:
            best = {"score": 5 - nwrong, "letter": L}
        time.sleep(3)
    print("!! 未找到全对；最佳: %s (%d/5)" % (best["letter"], best["score"]))
    return 1


def gate(s, cid, cwid):
    r = s.get("%sashx/checkExamPay.ashx" % HOST, params={"courseId": cid, "cwid": cwid},
              timeout=30, headers={"X-Requested-With": "XMLHttpRequest",
                                   "Referer": "%scourse_ware/course_ware.aspx?cwid=%s" % (HOST, cwid)})
    try:
        return r.json()
    except Exception:
        return {"code": -1, "raw": r.text[:200]}


def cmd_gate(cid, cwid):
    s = session()
    print(json.dumps(gate(s, cid, cwid), ensure_ascii=False))
    return 0


def cmd_batch():
    """对 progress.json 中所有 待考试 单元：过闸 + 拉卷 + 报告可否直接作答。"""
    prog = json.loads((BASE / "progress.json").read_text(encoding="utf-8"))
    key = load_key()
    s = session()
    todo = [r for r in prog if r["state"] == "待考试"]
    print("待考试单元 %d 个" % len(todo))
    report = []
    for r in todo:
        cwid, cid = r["cwid"], r["cid"]
        g = gate(s, cid, cwid)
        p = fetch(s, cwid)
        (HTTPD / ("%s.json" % cwid)).write_text(
            json.dumps(p, ensure_ascii=False, indent=1), encoding="utf-8")
        known = [q for q in p["questions"] if key.get(q["qid"])]
        unknown = [q for q in p["questions"]
                   if not key.get(q["qid"])]
        print("-" * 66)
        print("[%s] %s" % (g.get("code"), r["title"][:40]))
        print("   cwid", cwid, "| 题数", len(p["questions"]), "| 已知", len(known), "| 未知", len(unknown))
        for q in p["questions"]:
            mark = "OK " if key.get(q["qid"]) else "?? "
            print("   %s [%s] %s" % (mark, q["qid"][:8], q["text"][:64]))
        if unknown:
            for q in unknown:
                print("      >>> 缺答案 %s" % q["qid"])
                for o in q["opts"]:
                    print("          %s %s" % (o["letter"], o["text"][:88]))
        report.append({"cwid": cwid, "cid": cid, "title": r["title"],
                       "gate": g.get("code"), "n": len(p["questions"]),
                       "unknown": [q["qid"] for q in unknown]})
    (BASE / "exam_batch.json").write_text(json.dumps(report, ensure_ascii=False, indent=1),
                                          encoding="utf-8")
    return 0


def cmd_showfile(path):
    html = Path(path).read_text(encoding="utf-8")
    p = parse_paper(html)
    print("captcha?" , p["captcha"], "| 题数", len(p["questions"]))
    for i, q in enumerate(p["questions"]):
        print("Q%d [%s] %s" % (i + 1, (q["qid"] or "?")[:8], q["text"][:80]))
        for o in q["opts"]:
            print("   %s %s" % (o["letter"], o["text"][:80]))
    return 0


def cmd_fromfile(cwid, path, overrides):
    html = Path(path).read_text(encoding="utf-8")
    p = parse_paper(html)
    if p["captcha"]:
        print("!! 该 HTML 是验证码页")
        return 2
    pick = build_pick(p, overrides)
    print("== 作答 ==")
    for q in p["questions"]:
        print("  Q[%s] %s -> %s" % (q["qid"][:8], q["text"][:45], pick.get(q["qid"], "?")))
    missing = [q["qid"] for q in p["questions"] if q["qid"] not in pick]
    if missing:
        print("!! 缺答案:", missing)
        for q in p["questions"]:
            if q["qid"] in missing:
                print("  题面:", q["text"][:120])
                for o in q["opts"]:
                    print("    %s %s" % (o["letter"], o["text"][:100]))
        return 2
    s = session()
    r = submit(s, cwid, p, pick)
    res = parse_result(r.text)
    print("POST ->", r.status_code, r.url)
    print(json.dumps(res, ensure_ascii=False))
    (HTTPD / ("%s.result.html" % cwid)).write_text(r.text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)
    c = sys.argv[1]
    if c == "batch":
        sys.exit(cmd_batch())
    if c == "showfile":
        sys.exit(cmd_showfile(sys.argv[2]))
    if c == "fromfile":
        _ov = {}
        for a in sys.argv[4:]:
            if "=" in a:
                k, v = a.split("=", 1)
                _ov[k.strip().lower()] = v.strip().upper()
        sys.exit(cmd_fromfile(sys.argv[2], sys.argv[3], _ov))
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(0)
    if c == "get":
        sys.exit(cmd_get(sys.argv[2]))
    if c == "gate":
        sys.exit(cmd_gate(sys.argv[2], sys.argv[3]))
    if c == "submit":
        ov = {}
        for a in sys.argv[3:]:
            if "=" in a:
                k, v = a.split("=", 1)
                ov[k.strip().lower()] = v.strip().upper()
        sys.exit(cmd_submit(sys.argv[2], ov))
    if c == "try":
        sys.exit(cmd_try(sys.argv[2], sys.argv[3], sys.argv[4]))
    print("unknown", c)
