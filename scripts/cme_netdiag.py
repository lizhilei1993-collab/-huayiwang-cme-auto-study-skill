# -*- coding: utf-8 -*-
"""诊断课件页播放器取流失败：抓 Network 事件 + 控制台错误。
用法: python cme_netdiag.py [秒数] [端口]
"""
import json
import sys
import time
from collections import Counter

sys.path.insert(0, ".")
import cme_cdp as C

DUR = int(sys.argv[1]) if len(sys.argv) > 1 else 35
PORT = sys.argv[2] if len(sys.argv) > 2 else "9222"
import os
os.environ["CME_CDP_PORT"] = PORT
import importlib
importlib.reload(C)


def main():
    t = C.pick_target()
    cdp = C.CDP(t["webSocketDebuggerUrl"], timeout=20)
    cdp.send("Page.enable")
    cdp.send("Network.enable")
    try:
        cdp.send("Log.enable")
    except Exception:
        pass
    try:
        cdp.send("Runtime.enable")
    except Exception:
        pass

    print("reload ...", flush=True)
    cdp.send("Page.reload", {"ignoreCache": False})

    reqs = {}
    fails = []
    logs = []
    resp_types = Counter()
    end = time.time() + DUR
    while time.time() < end:
        cdp.ws.settimeout(1.0)
        try:
            raw = cdp.ws.recv()
        except Exception:
            continue
        if not raw:
            continue
        try:
            m = json.loads(raw)
        except ValueError:
            continue
        meth = m.get("method")
        if meth == "Page.javascriptDialogOpening":
            cdp.mid += 1
            cdp.ws.send(json.dumps({"id": cdp.mid, "method": "Page.handleJavaScriptDialog",
                                    "params": {"accept": True}}))
            continue
        if meth == "Network.responseReceived":
            p = m["params"]
            r = p.get("response", {})
            url = r.get("url", "")
            reqs[p.get("requestId")] = {"url": url, "status": r.get("status"),
                                        "type": p.get("type"), "mime": r.get("mimeType")}
            resp_types[p.get("type")] += 1
        elif meth == "Network.loadingFailed":
            p = m["params"]
            info = reqs.get(p.get("requestId"), {})
            fails.append({"url": info.get("url", "?"), "err": p.get("errorText"),
                          "type": p.get("type"), "blocked": p.get("blockedReason")})
        elif meth == "Log.entryAdded":
            e = m["params"].get("entry", {})
            if e.get("level") in ("error", "warning"):
                logs.append("[%s] %s %s" % (e.get("level"), e.get("source"), (e.get("text") or "")[:180]))
        elif meth == "Runtime.consoleAPICalled":
            p = m["params"]
            if p.get("type") in ("error", "warning"):
                txt = " ".join(str(a.get("value", a.get("description", "")))[:120]
                               for a in p.get("args", []))
                logs.append("[console.%s] %s" % (p.get("type"), txt[:200]))

    print("\n=== response by type ===")
    for k, v in resp_types.most_common():
        print("  %-12s %d" % (k, v))

    print("\n=== media/stream requests ===")
    keys = ("m3u8", ".ts", ".m4s", ".mp4", "playsafe", "getPlaySafe", "polyv")
    hit = [v for v in reqs.values() if any(k in (v["url"] or "").lower() for k in keys)]
    for v in hit[:30]:
        print("  %s %-6s %-8s %s" % (v["status"], v["type"], (v["mime"] or "")[:28], v["url"][:110]))
    if not hit:
        print("  (none)")

    print("\n=== loadingFailed (%d) ===" % len(fails))
    for f in fails[:20]:
        print("  %-20s %-8s %s" % (f["err"], f["type"], (f["url"] or "")[:100]))

    print("\n=== HTTP >=400 ===")
    bad = [v for v in reqs.values() if (v["status"] or 0) >= 400]
    for v in bad[:25]:
        print("  %s %-8s %s" % (v["status"], v["type"], (v["url"] or "")[:110]))
    if not bad:
        print("  (none)")

    print("\n=== XHR/Fetch endpoints ===")
    for v in reqs.values():
        if v["type"] in ("XHR", "Fetch"):
            print("  %s %-6s %s" % (v["status"], v["type"], (v["url"] or "")[:110]))

    print("\n=== console/log errors ===")
    for L in logs[:20]:
        print("  " + L)
    if not logs:
        print("  (none)")

    cdp.close()


if __name__ == "__main__":
    main()
