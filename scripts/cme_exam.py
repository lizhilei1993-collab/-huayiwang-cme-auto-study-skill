# -*- coding: utf-8 -*-
"""考试工具：提取题目 / 作答 / 查看结果。

用法:
  python cme_exam.py dump <cwid>              提取题目 -> ab/exams/<cwid>.json
  python cme_exam.py answer <cwid> B,C,A,D,E  按选项字母作答并提交
  python cme_exam.py check <cwid>             查看当前勾选状态
  python cme_exam.py result                   读取结果页信息
"""
import json
import sys
import time
from pathlib import Path
from config import (data_dir as _data_dir, host as _host, origin as _origin, site as _site, site_key as _site_key, cdn_base as _cdn, user as _user, password as _pwd, alive_check as _alive_check, alive_marker as _alive_marker, courses as _courses, course_list as _course_list)  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cme_cdp as C  # noqa

BASE = _data_dir()
EXAM_DIR = BASE / "exams"
EXAM_DIR.mkdir(parents=True, exist_ok=True)

DUMP_JS = r"""(() => {
  const tables = [...document.querySelectorAll('table.tablestyle')];
  const out = [];
  tables.forEach((t, qi) => {
    const q = t.querySelector('label.q_name');
    const qid = q ? q.getAttribute('data-qid') : null;
    const opts = [...t.querySelectorAll('input[type=radio]')].map((r, oi) => {
      const lab = r.closest('label');
      let txt = lab ? lab.innerText.trim() : '';
      txt = txt.replace(/\s+/g, ' ');
      return {oi, value: r.value, name: r.name, text: txt.slice(0, 300), checked: r.checked};
    });
    out.push({qi, qid, text: q ? q.innerText.trim().replace(/\s+/g, ' ') : '', opts});
  });
  return out;
})()"""

CHECK_JS = r"""(() => {
  const tables = [...document.querySelectorAll('table.tablestyle')];
  return tables.map((t, qi) => {
    const sel = t.querySelector('input[type=radio]:checked');
    return {qi, selected: sel ? sel.value : null};
  });
})()"""


def cmd_dump(cwid):
    c = C.page_cdp()
    try:
        qs = C.evaluate(c, DUMP_JS)
        (EXAM_DIR / ("%s.json" % cwid)).write_text(json.dumps(qs, ensure_ascii=False, indent=1), encoding="utf-8")
        for q in qs:
            print("Q%d [%s] %s" % (q["qi"] + 1, q["qid"][:8] if q["qid"] else "?", q["text"]))
            for o in q["opts"]:
                print("   %s" % o["text"])
        print("saved ->", EXAM_DIR / ("%s.json" % cwid))
    finally:
        c.close()
    return 0


def cmd_check(cwid):
    c = C.page_cdp()
    try:
        print(json.dumps(C.evaluate(c, CHECK_JS), ensure_ascii=False))
    finally:
        c.close()
    return 0


def cmd_answer(cwid, letters):
    letters = [x.strip().upper() for x in letters.split(",") if x.strip()]
    c = C.page_cdp()
    try:
        qs = C.evaluate(c, DUMP_JS)
        if len(qs) != len(letters):
            print("!! question count %d != answer count %d" % (len(qs), len(letters)))
            return 2
        for qi, (q, letter) in enumerate(zip(qs, letters)):
            idx = ord(letter) - ord("A")
            if idx < 0 or idx >= len(q["opts"]):
                print("!! invalid letter %s for Q%d" % (letter, qi + 1))
                return 2
            # 点击选项 label 中心（可信点击）
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
                print("!! cannot locate Q%d option %s" % (qi + 1, letter))
                return 2
            x, y = float(info["x"]), float(info["y"])
            c.send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})
            time.sleep(0.05)
            c.send("Input.dispatchMouseEvent", {"type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1})
            time.sleep(0.05)
            c.send("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": 1})
            time.sleep(0.4)
            print("Q%d -> %s" % (qi + 1, letter))

        # 校验勾选
        chk = C.evaluate(c, CHECK_JS)
        selected = [x["selected"] for x in chk]
        expect = [qs[i]["opts"][ord(l) - ord("A")]["value"] for i, l in enumerate(letters)]
        if selected != expect:
            print("!! selection mismatch: got %s expected %s" % (selected, expect))
            return 3
        print("all selections verified")

        # 提交
        C.evaluate(c, "window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(1)
        C.click_nth_visible(c, "#btn_submit", 0)
        print("submitted")
        time.sleep(4)
        res = C.evaluate(c, "({url: location.href, title: document.title})")
        print("after submit:", json.dumps(res, ensure_ascii=False))
    finally:
        c.close()
    return 0


def cmd_result():
    c = C.page_cdp()
    try:
        info = C.evaluate(c, r"""(() => {
          const out = {url: location.href, title: document.title};
          const txt = document.body.innerText.replace(/\s+/g,' ');
          out.score = (txt.match(/得分[:：]?\s*\d+/) || [])[0] || null;
          out.pass = /通过|合格/.test(txt);
          out.fail = /未通过|不合格/.test(txt);
          out.snippet = txt.slice(0, 400);
          return out;
        })()""")
        print(json.dumps(info, ensure_ascii=False))
    finally:
        c.close()
    return 0


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "dump":
        sys.exit(cmd_dump(sys.argv[2]))
    elif cmd == "answer":
        sys.exit(cmd_answer(sys.argv[2], sys.argv[3]))
    elif cmd == "check":
        sys.exit(cmd_check(sys.argv[2]))
    elif cmd == "result":
        sys.exit(cmd_result())
    print("unknown", cmd)
    sys.exit(1)
