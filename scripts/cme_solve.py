# -*- coding: utf-8 -*-
"""按 qid 作答的考试解题器。

用法:
  python cme_solve.py solve <cwid> [覆盖]        按答案库作答并提交
        覆盖格式: qid前缀=字母   (可多个)
        例: python cme_solve.py solve <cwid> 85844bfe=B
  python cme_solve.py verdict                    读取结果页：分数 + 错题清单
  python cme_solve.py key <cwid>                 查看该 cwid 的答案库

答案库: ab/answers.json   {"<qid>": "A", ...}
"""
import json
import os
import sys
import time
from pathlib import Path
from config import (data_dir as _data_dir, host as _host, origin as _origin, site as _site, site_key as _site_key, cdn_base as _cdn, user as _user, password as _pwd, alive_check as _alive_check, alive_marker as _alive_marker, courses as _courses, course_list as _course_list)  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cme_cdp as C  # noqa

BASE = _data_dir()
KEYF = BASE / "answers.json"


def load_key():
    if KEYF.exists():
        return json.loads(KEYF.read_text(encoding="utf-8"))
    return {}


def save_key(k):
    KEYF.write_text(json.dumps(k, ensure_ascii=False, indent=1), encoding="utf-8")


DUMP_JS = r"""(() => {
  const tables = [...document.querySelectorAll('table.tablestyle')];
  return tables.map((t, qi) => {
    const q = t.querySelector('label.q_name');
    const qid = q ? q.getAttribute('data-qid') : null;
    const opts = [...t.querySelectorAll('input[type=radio]')].map((r, oi) => {
      const lab = r.closest('label');
      let txt = lab ? lab.innerText.trim() : '';
      txt = txt.replace(/\s+/g, ' ');
      return {oi, value: r.value, text: txt.slice(0, 300), checked: r.checked};
    });
    return {qi, qid, text: q ? q.innerText.trim().replace(/\s+/g, ' ') : '', opts};
  });
})()"""


def cmd_solve(cwid, overrides):
    ov = {}
    for s in overrides:
        if "=" in s:
            q, l = s.split("=", 1)
            ov[q.strip().lower()] = l.strip().upper()
    key = load_key()
    c = C.page_cdp()
    try:
        qs = C.evaluate(c, DUMP_JS)
        if not qs:
            print("!! 页面上没有题目（是否在考试页？）")
            return 2

        letters = []
        for q in qs:
            qid = q["qid"] or ""
            let = None
            for k, v in ov.items():
                if qid.lower().startswith(k):
                    let = v
            if let is None:
                let = key.get(qid)
            if not let:
                print("!! 缺答案 qid=%s  题面=%s" % (qid, q["text"][:50]))
                return 2
            letters.append(let)

        print("== 本次作答 ==")
        for q, L in zip(qs, letters):
            print("  Q%d [%s] -> %s | %s" % (q["qi"] + 1, (q["qid"] or "?")[:8], L, q["text"][:60]))

        # 逐题可信点击
        for qi, (q, letter) in enumerate(zip(qs, letters)):
            idx = ord(letter) - ord("A")
            if idx < 0 or idx >= len(q["opts"]):
                print("!! 字母越界 %s @Q%d" % (letter, qi + 1))
                return 2
            info = C.evaluate(c, """(() => {
              const t = [...document.querySelectorAll('table.tablestyle')][%d];
              if (!t) return null;
              const r = t.querySelectorAll('input[type=radio]')[%d];
              if (!r) return null;
              const lab = r.closest('label');
              if (!lab) return null;
              lab.scrollIntoView({block:'center'});
              const rect = lab.getBoundingClientRect();
              return {x: rect.left + rect.width/2, y: rect.top + Math.min(rect.height/2, 20)};
            })()""" % (qi, idx))
            if not info:
                print("!! 定位失败 Q%d %s" % (qi + 1, letter))
                return 2
            x, y = float(info["x"]), float(info["y"])
            c.send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})
            time.sleep(0.05)
            c.send("Input.dispatchMouseEvent", {"type": "mousePressed", "x": x, "y": y,
                                                "button": "left", "clickCount": 1})
            time.sleep(0.05)
            c.send("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x, "y": y,
                                                "button": "left", "clickCount": 1})
            time.sleep(0.35)

        chk = C.evaluate(c, """(() => [...document.querySelectorAll('table.tablestyle')].map(t => {
            const s = t.querySelector('input[type=radio]:checked');
            return s ? s.value : null; }))()""")
        expect = [qs[i]["opts"][ord(l) - ord("A")]["value"] for i, l in enumerate(letters)]
        if chk != expect:
            print("!! 勾选校验失败\n got=%s\n exp=%s" % (chk, expect))
            return 3
        print("  勾选校验 OK")

        C.evaluate(c, "window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(1)
        C.click_nth_visible(c, "#btn_submit", 0)
        print("  已提交")
        time.sleep(5)
        print("  跳转:", json.dumps(C.evaluate(c, "({url: location.href})"), ensure_ascii=False))
        return 0
    finally:
        c.close()


VERDICT_JS = r"""(() => {
  const txt = document.body.innerText.replace(/\s+/g, ' ');
  const out = {url: location.href};
  out.fail = /考试未通过|未通过/.test(txt);
  out.pass = /考试通过|已通过|恭喜/.test(txt);
  const m = txt.match(/得分[:：]?\s*(\d+)/);
  out.score = m ? m[1] : null;
  out.items = [...document.querySelectorAll('li.state_cour_lis')].map((li, i) => {
    const img = li.querySelector('img');
    const src = img ? img.getAttribute('src') : '';
    const ps = [...li.querySelectorAll('p')].map(p => (p.getAttribute('title') || p.innerText || '').trim());
    return {i: i + 1, wrong: /error_icon/.test(src), q: (ps[0] || '').slice(0, 60), mine: (ps[1] || '').slice(0, 80)};
  });
  return out;
})()"""


def cmd_verdict():
    c = C.page_cdp()
    try:
        v = C.evaluate(c, VERDICT_JS)
        print(json.dumps(v, ensure_ascii=False, indent=1))
        return 0
    finally:
        c.close()


def cmd_key(cwid):
    key = load_key()
    print(json.dumps(key, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)
    cmd = sys.argv[1]
    if cmd == "solve":
        sys.exit(cmd_solve(sys.argv[2], sys.argv[3:]))
    elif cmd == "verdict":
        sys.exit(cmd_verdict())
    elif cmd == "key":
        sys.exit(cmd_key(sys.argv[2]))
    print("unknown", cmd)
    sys.exit(1)
