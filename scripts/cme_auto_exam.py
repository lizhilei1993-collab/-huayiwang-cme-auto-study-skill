# -*- coding: utf-8 -*-
"""考试全自动机：自动过验证码 -> 拉卷 -> 作答 -> 迭代收敛 -> 通过。

用法:
  python cme_auto_exam.py scan              列出所有单元的考试就绪度（只读，不发卷）
  python cme_auto_exam.py run [cwid...]     处理所有"待考试"单元（或指定 cwid）
  python cme_auto_exam.py one <cid> <cwid>  处理单个单元
  python cme_auto_exam.py probe <cid> <cwid> 打印某单元试卷内容

原理:
  1) 就绪判定：exam.aspx 对未看完视频的单元返回 '请先进行课件观看学习完成后
     再进行考试'；返回真实试卷/验证码页 = 可考。
  2) checkExamPay 过闸 -> GET exam.aspx；若返回验证码页则 ddddocr 自动识别并提交
  3) 解析试卷（qid + 选项）
  4) 作答：优先查 answers.json（按 qid）/ answers_text.json（按题面归一化）
  5) 提交，读结果页错题；错的题把选项字母向后顺延，重考，直至全对
  6) 仅在**确证通过**（结果页出现"考试通过"）时才写答案库，避免污染
"""
import json
import re
import sys
import time
import urllib.parse
from pathlib import Path
from config import (data_dir as _data_dir, host as _host, origin as _origin, site as _site, site_key as _site_key, cdn_base as _cdn, user as _user, password as _pwd, alive_check as _alive_check, alive_marker as _alive_marker, courses as _courses, course_list as _course_list)  # noqa: E402

import ddddocr
import requests
from bs4 import BeautifulSoup

BASE = _data_dir()
KEYF = BASE / "answers.json"
TEXTF = BASE / "answers_text.json"
CK = BASE / "cookies_latest.json"
HOST = _host()
LOGF = BASE / "auto_exam.log"

NOTREADY = "请先进行课件观看学习完成后再进行考试"
PAYFAIL = "付费状态查询失败"

_OCR = None


def ocr():
    global _OCR
    if _OCR is None:
        _OCR = ddddocr.DdddOcr(show_ad=False)
    return _OCR


def log(msg):
    line = time.strftime("[%m-%d %H:%M:%S] ") + msg
    try:
        with open(LOGF, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass
    print(line, flush=True)


_session_checked = [False]


def session():
    raw = json.loads(CK.read_text(encoding="utf-8"))
    items = raw if isinstance(raw, list) else raw.get("cookies", [])
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
        "Referer": HOST + "pages/cme.aspx",
        "Origin": HOST.rstrip("/"),
    })
    for c in items:
        if _site_key() in (c.get("domain") or ""):
            s.cookies.set(c["name"], c["value"], domain=_site())

    # 首次调用时校验会话；失效则自动登录（避免考试机在掉登录后空转）
    if not _session_checked[0]:
        _session_checked[0] = True
        try:
            r = s.get(_alive_check(), timeout=30)
            r.encoding = "utf-8"
            if "data-cwrid=" not in r.text:
                print("[session] cookie 已失效，尝试自动登录 ...")
                import cme_login as L
                ns = L.do_login_http()
                if ns is not None and L.alive(ns):
                    L.dump_cookies(ns)
                    ns.headers.update({
                        "Referer": HOST + "pages/cme.aspx",
                        "Origin": HOST.rstrip("/"),
                    })
                    s = ns
                    print("[session] 自动登录成功")
                else:
                    print("[session] 自动登录失败，后续请求可能全部无效")
        except BaseException as e:
            print("[session] alive check 异常: %r" % e)
    return s


def load_key():
    return json.loads(KEYF.read_text(encoding="utf-8")) if KEYF.exists() else {}


def save_key(k):
    KEYF.write_text(json.dumps(k, ensure_ascii=False, indent=1), encoding="utf-8")


def load_textkey():
    return json.loads(TEXTF.read_text(encoding="utf-8")) if TEXTF.exists() else {}


def save_textkey(k):
    TEXTF.write_text(json.dumps(k, ensure_ascii=False, indent=1), encoding="utf-8")


def norm(t):
    return re.sub(r"[\s\u3000]+", "", (t or "")).strip()


def gate(s, cid, cwid):
    r = s.get(HOST + "ashx/checkExamPay.ashx", params={"courseId": cid, "cwid": cwid},
              timeout=30, headers={"X-Requested-With": "XMLHttpRequest",
                                   "Referer": "%scourse_ware/course_ware.aspx?cwid=%s" % (HOST, cwid)})
    try:
        return r.json()
    except Exception:
        return {"code": -1, "raw": r.text[:120]}


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
            opts.append({"letter": chr(65 + i), "value": inp.get("value"),
                         "text": (lab.get_text(" ", strip=True) if lab else "")[:200]})
        qs.append({"qid": q.get("data-qid"), "text": q.get_text(" ", strip=True), "opts": opts})
    return {"viewstate": vs["value"] if vs else "", "vsg": vsg["value"] if vsg else "",
            "questions": qs, "captcha": ("txtCheckCode" in html)}


def exam_probe(s, cwid, tries=4):
    """只读探测考试入口。返回 (kind, text)：ready / captcha / notready / payfail / other

    注意：服务端『深圳平台付费状态查询失败』是**偶发**错误（同一单元重试即变成
    真实结果），必须重试；否则会误判。
    """
    last = ""
    for i in range(tries):
        r = s.get(HOST + "pages/exam.aspx?cwid=" + cwid, timeout=30)
        r.encoding = "utf-8"
        t = r.text
        last = t
        if PAYFAIL in t:
            time.sleep(1.5 + i)
            continue
        if NOTREADY in t:
            return "notready", t
        if "txtCheckCode" in t:
            return "captcha", t
        if parse_paper(t)["questions"]:
            return "ready", t
        return "other", t
    return "payfail", last


def solve_captcha(s, cwid, max_try=5):
    """完成验证码并返回考卷 HTML（失败返回 None）。"""
    url = HOST + "pages/exam_code.aspx?cwid=" + cwid
    for i in range(max_try):
        r = s.get(url, timeout=30)
        r.encoding = "utf-8"
        soup = BeautifulSoup(r.text, "html.parser")
        img = soup.select_one("img.yzm_img, img#imgCheckCode")
        if img is None:
            return r.text  # 已不是验证码页
        fields = {}
        for name in ("__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION",
                     "__EVENTTARGET", "__EVENTARGUMENT"):
            el = soup.find("input", {"name": name})
            if el is not None:
                fields[name] = el.get("value", "")
        src = urllib.parse.urljoin(url, img.get("src") or "")
        ir = s.get(src, timeout=30)
        code = ocr().classification(ir.content)
        code = re.sub(r"[^0-9A-Za-z]", "", code)
        form = soup.find("form")
        action = urllib.parse.urljoin(url, form.get("action") if form else url)
        data = dict(fields)
        data["txtCheckCode"] = code
        data["btnYes"] = "提交"
        rr = s.post(action, data=data, timeout=40, allow_redirects=True)
        rr.encoding = "utf-8"
        log("  captcha[%d] 识别=%s -> %s" % (i + 1, code, "通过" if "txtCheckCode" not in rr.text else "重试"))
        if "txtCheckCode" not in rr.text:
            return rr.text
        time.sleep(2)
    return None


def parse_result(html):
    soup = BeautifulSoup(html, "html.parser")
    txt = soup.get_text(" ", strip=True)
    out = {"fail": "考试未通过" in txt, "pass": "考试通过" in txt, "wrong": [],
           "captcha": "txtCheckCode" in html}
    m = re.search(r"得分[:：]?\s*(\d+)", txt)
    out["score"] = int(m.group(1)) if m else None
    m2 = re.search(r'test_score[:：]\s*"?(\d+)', html)
    if m2:
        out["score"] = int(m2.group(1))
    for i, li in enumerate(soup.select("li.state_cour_lis")):
        img = li.find("img")
        src = img.get("src", "") if img else ""
        ps = [(p.get("title") or p.get_text(" ", strip=True)) for p in li.find_all("p")]
        if "error_icon" in src:
            out["wrong"].append({"i": i + 1, "q": (ps[0] if ps else "")[:60]})
    return out


def submit_paper(s, cwid, paper, pick):
    parts = []
    for q in paper["questions"]:
        L = pick.get(q["qid"])
        val = next((o["value"] for o in q["opts"] if o["letter"] == L), None)
        parts.append("%s|%s" % (q["qid"], val))
    data = {"__VIEWSTATE": paper["viewstate"], "__VIEWSTATEGENERATOR": paper["vsg"],
            "hd_result": ",".join(parts), "btn_submit.x": "10", "btn_submit.y": "10"}
    s.headers.update({"Referer": HOST + "pages/exam.aspx?cwid=" + cwid,
                      "Content-Type": "application/x-www-form-urlencoded"})
    r = s.post(HOST + "pages/exam.aspx?cwid=" + cwid, data=data, timeout=40, allow_redirects=True)
    r.encoding = "utf-8"
    return r


def resolve_answers(paper, key, tkey):
    """返回 {qid: letter or None}"""
    out = {}
    for q in paper["questions"]:
        let = key.get(q["qid"])
        if not let:
            ent = tkey.get(norm(q["text"]))
            if isinstance(ent, dict):
                want = ent.get("opt", "")
                for o in q["opts"]:
                    if want and o["text"].startswith(want[:18]):
                        let = o["letter"]
                        break
                if not let:
                    let = ent.get("letter")
        out[q["qid"]] = let
    return out


def get_state(s, cid, cwid):
    r = s.get(HOST + "pages/course.aspx?cid=" + cid, timeout=30)
    r.encoding = "utf-8"
    soup = BeautifulSoup(r.text, "html.parser")
    for d in soup.select("div.cw-progress-row"):
        if d.get("data-cwrid") == cwid:
            return d.get("data-studystate")
    return None


def solve_one(s, cid, cwid, title="", max_attempts=10):
    log("== %s [%s]" % (title[:34], cwid[:8]))
    st = get_state(s, cid, cwid)
    if st == "已完成":
        log("   已完成，跳过")
        return True
    g = gate(s, cid, cwid)
    if g.get("code") != 0:
        log("   checkExamPay code=%s msg=%s" % (g.get("code"), str(g.get("msg"))[:60]))

    kind, html = exam_probe(s, cwid)
    log("   入口=%s" % kind)
    if kind == "notready":
        log("   !! 视频未看完，暂不可考")
        return False
    if kind in ("payfail", "other"):
        log("   !! 入口异常: %s" % re.sub(r"\s+", " ", html)[:110])
        return False
    if kind == "captcha":
        html = solve_captcha(s, cwid)
    if not html:
        log("   !! 验证码未通过")
        return False
    paper = parse_paper(html)
    if not paper["questions"]:
        log("   !! 未拿到题目")
        return False

    key = load_key()
    tkey = load_textkey()
    base = resolve_answers(paper, key, tkey)
    log("   题数=%d，答案库命中=%d" % (len(paper["questions"]),
                                      sum(1 for v in base.values() if v)))

    pick = {}
    for q in paper["questions"]:
        pick[q["qid"]] = base.get(q["qid"]) or "A"

    for attempt in range(max_attempts):
        r2 = submit_paper(s, cwid, paper, pick)
        res = parse_result(r2.text)
        if res["captcha"]:
            log("   触发验证码 -> 重新过闸")
            html = solve_captcha(s, cwid)
            if not html:
                return False
            paper = parse_paper(html)
            qidmap = {q["qid"]: q for q in paper["questions"]}
            pick = {qid: pick.get(qid, "A") for qid in qidmap}
            continue
        if res["pass"]:
            log("   *** 通过（第 %d 次提交，得分=%s）***" % (attempt + 1, res["score"]))
            for q in paper["questions"]:
                let = pick.get(q["qid"])
                if not let:
                    continue
                key[q["qid"]] = let
                opt = next((o["text"] for o in q["opts"] if o["letter"] == let), "")
                tkey[norm(q["text"])] = {"letter": let, "opt": opt[:60]}
            save_key(key)
            save_textkey(tkey)
            time.sleep(1)
            log("   新状态: %s" % get_state(s, cid, cwid))
            return True
        if not res["wrong"]:
            # 未通过但没解析到错题：结果页形态异常，别误判为通过，也别乱改答案
            log("   !! 第 %d 次提交：未通过但未解析到错题（score=%s），10s 后重试"
                % (attempt + 1, res["score"]))
            time.sleep(10)
            continue
        log("   第 %d 次提交：错 %d 题 %s (score=%s)" % (attempt + 1, len(res["wrong"]),
                                                      [w["i"] for w in res["wrong"]], res["score"]))
        for w in res["wrong"]:
            idx = w["i"] - 1
            if idx < 0 or idx >= len(paper["questions"]):
                continue
            q = paper["questions"][idx]
            cur = pick.get(q["qid"], "A")
            n = len(q["opts"])
            pos = ord(cur) - ord("A")
            pick[q["qid"]] = chr(ord("A") + (pos + 1) % n)
        time.sleep(4)
    log("   !! 达到最大尝试次数仍未通过")
    return False


def refresh(prog, s, cids):
    """拉真实状态 + 视频进度，回填 prog。返回 (就绪候选, 统计)。"""
    fresh = {}
    for cid in cids:
        try:
            rr = s.get(HOST + "pages/course.aspx?cid=" + cid, timeout=30)
            rr.encoding = "utf-8"
            sp = BeautifulSoup(rr.text, "html.parser")
            for d in sp.select("div.cw-progress-row"):
                fresh[d.get("data-cwrid")] = {
                    "state": d.get("data-studystate"),
                    "maxtime": int(d.get("data-maxtime") or 0),
                    "totaltime": int(d.get("data-totaltime") or 0),
                    "completed": d.get("data-completed"),
                }
        except Exception as e:
            log("!! 状态刷新失败 %s: %r" % (cid[:8], e))
    cands = []
    for r in prog:
        f = fresh.get(r["cwid"])
        if f:
            r["state"] = f["state"]
            r["maxtime"] = f["maxtime"]
            r["totaltime"] = f["totaltime"]
            r["completed"] = f["completed"]
        if r.get("state") == "已完成":
            continue
        mt, tt = r.get("maxtime") or 0, r.get("totaltime") or 0
        if tt > 0 and mt >= tt - 2:
            cands.append(r)          # 视频已看完、考试未过 -> 待考试
        elif tt == 0:
            cands.append(r)          # 无视频课件，直接试考试入口
    return cands, fresh


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    cmd = sys.argv[1]
    if cmd == "scan":
        s = session()
        prog = json.loads((BASE / "progress.json").read_text(encoding="utf-8"))
        cids = []
        for r in prog:
            if r["cid"] not in cids:
                cids.append(r["cid"])
        cands, _ = refresh(prog, s, cids)
        log("== SCAN 候选 %d / 全部 %d" % (len(cands), len(prog)))
        for r in prog:
            if r.get("state") == "已完成":
                continue
            kind, t = exam_probe(s, r["cwid"])
            print("  %-34s %-5s %s/%s  %s" % (r["title"][:32], r["state"],
                                              r.get("maxtime"), r.get("totaltime"), kind), flush=True)
            time.sleep(0.6)
        return
    if cmd == "probe":
        cid, cwid = sys.argv[2], sys.argv[3]
        s = session()
        log("== PROBE %s" % cwid[:8])
        log("   state=%s" % get_state(s, cid, cwid))
        log("   gate=%s" % gate(s, cid, cwid))
        kind, html = exam_probe(s, cwid)
        log("   入口=%s" % kind)
        if kind == "captcha":
            html = solve_captcha(s, cwid)
        if not html:
            return
        paper = parse_paper(html)
        log("   题数=%d" % len(paper["questions"]))
        key = load_key()
        for i, q in enumerate(paper["questions"]):
            hit = "已知:" + key[q["qid"]] if key.get(q["qid"]) else "未知"
            print("  Q%d [%s] %s  << %s" % (i + 1, q["qid"][:8], q["text"][:60], hit), flush=True)
            for o in q["opts"]:
                print("     %s %s" % (o["letter"], o["text"][:76]), flush=True)
        return
    if cmd == "one":
        cid, cwid = sys.argv[2], sys.argv[3]
        s = session()
        ok = solve_one(s, cid, cwid, sys.argv[4] if len(sys.argv) > 4 else cwid)
        sys.exit(0 if ok else 1)
    if cmd == "run":
        s = session()
        prog = json.loads((BASE / "progress.json").read_text(encoding="utf-8"))
        cids = []
        for r in prog:
            if r["cid"] not in cids:
                cids.append(r["cid"])
        cands, _ = refresh(prog, s, cids)
        (BASE / "progress.json").write_text(json.dumps(prog, ensure_ascii=False, indent=1),
                                            encoding="utf-8")

        if len(sys.argv) > 2:
            want = set(sys.argv[2:])
            todo = [r for r in prog if r["cwid"] in want]
        else:
            # 排除 totaltime=0 的空壳单元（平台已下架，如课程一「多重用药临床实操」，
            # 服务端返回「课件不存在或已下线」，永远不可学习/不可考）
            todo = [r for r in cands if int(r.get("totaltime") or 0) > 0]
        log("处理 %d 个待考试单元（全部 %d，已完成 %d，候选 %d）"
            % (len(todo), len(prog), sum(1 for r in prog if r.get("state") == "已完成"),
               len(cands)))
        for r in todo:
            try:
                solve_one(s, r["cid"], r["cwid"], r.get("title", ""))
            except Exception as e:
                log("!! 异常: %r" % e)
            time.sleep(6)
        return
    print("unknown", cmd)


if __name__ == "__main__":
    main()
