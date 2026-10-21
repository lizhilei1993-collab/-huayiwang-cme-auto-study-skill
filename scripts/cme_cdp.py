# -*- coding: utf-8 -*-
"""CME CDP 工具箱：通过 Chrome DevTools Protocol 直连 9222 端口的专属 Chrome。

用法:
  python cme_cdp.py info                     当前页面 URL/标题
  python cme_cdp.py nav <url>                导航并等待加载
  python cme_cdp.py targets                  列出所有页面目标
  python cme_cdp.py state                    播放器/弹窗状态 JSON
  python cme_cdp.py eval <js>                执行 JS 返回结果
  python cme_cdp.py click <selector>         可信点击（CDP Input）
  python cme_cdp.py type <selector> <text>   可信键盘输入
  python cme_cdp.py screenshot <path>        整页截图
  python cme_cdp.py shot-el <sel> <path>     元素截图
  python cme_cdp.py seek <sec>               视频跳转
  python cme_cdp.py play / pause
  python cme_cdp.py cookies-out <path>       导出全部 cookie
  python cme_cdp.py cookies-in <path>        导入 cookie
  python cme_cdp.py newtab <url>             新标签页
  python cme_cdp.py closetab <index>         关闭标签页(0-based)
  python cme_cdp.py selecttab <index>
"""
import json
import os
import sys
import time
import urllib.request
import urllib.parse
import base64

import websocket

PORT = int(os.environ.get("CME_CDP_PORT", "9222"))
BASE = "http://127.0.0.1:%d" % PORT


def http_json(path):
    with urllib.request.urlopen(BASE + path, timeout=5) as r:
        return json.loads(r.read().decode("utf-8"))


def list_targets():
    return [t for t in http_json("/json/list") if t.get("type") == "page"]


def pick_target(url_filter=None):
    pages = list_targets()
    if not pages:
        raise SystemExit("no page targets")
    if url_filter:
        for t in pages:
            if url_filter in (t.get("url") or ""):
                return t
    for t in pages:
        u = t.get("url") or ""
        if _site_key() in u:
            return t
    return pages[0]


class CDP:
    def __init__(self, ws_url, timeout=15):
        self.ws = websocket.create_connection(ws_url, timeout=timeout,
                                              suppress_origin=True)
        self.mid = 0

    def send(self, method, params=None, timeout=15):
        self.mid += 1
        mid = self.mid
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        deadline = time.time() + timeout
        while time.time() < deadline:
            self.ws.settimeout(max(0.2, deadline - time.time()))
            try:
                raw = self.ws.recv()
            except websocket.WebSocketTimeoutException:
                continue
            if not raw:
                continue
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            if msg.get("method") == "Page.javascriptDialogOpening":
                # 自动接受（关闭）页面弹出的对话框，避免卡住 JS
                self.mid += 1
                self.ws.send(json.dumps({"id": self.mid, "method": "Page.handleJavaScriptDialog",
                                         "params": {"accept": True}}))
                continue
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError("%s -> %s" % (method, msg["error"]))
                return msg.get("result", {})
        raise TimeoutError(method)

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


def page_cdp(url_filter=None):
    t = pick_target(url_filter)
    cdp = CDP(t["webSocketDebuggerUrl"])
    try:
        cdp.send("Page.enable", {}, timeout=5)
    except Exception:
        pass
    try:
        cdp.send("Page.handleJavaScriptDialog", {"accept": True}, timeout=3)
    except Exception:
        pass
    return cdp


def browser_cdp():
    v = http_json("/json/version")
    return CDP(v["webSocketDebuggerUrl"])


def evaluate(cdp, expr, await_promise=False, timeout=15):
    params = {
        "expression": expr,
        "returnByValue": True,
        "awaitPromise": await_promise,
        "userGesture": True,
    }
    try:
        r = cdp.send("Runtime.evaluate", params, timeout=timeout)
    except TimeoutError:
        for _ in range(2):
            try:
                cdp.send("Page.handleJavaScriptDialog", {"accept": True}, timeout=3)
            except Exception:
                pass
        r = cdp.send("Runtime.evaluate", params, timeout=timeout)
    if r.get("exceptionDetails"):
        return {"__error__": str(r["exceptionDetails"].get("text")) + " " +
                str(r["exceptionDetails"].get("exception", {}).get("description", ""))}
    return r.get("result", {}).get("value")


def js_rect_center(sel):
    return """(() => {
      const el = document.querySelector(%s);
      if (!el) return null;
      el.scrollIntoView({block:'center', inline:'center'});
      const r = el.getBoundingClientRect();
      if (r.width === 0 && r.height === 0) return null;
      return {x: r.left + r.width/2, y: r.top + r.height/2, w: r.width, h: r.height};
    })()""" % json.dumps(sel)


def trusted_click(cdp, sel):
    info = evaluate(cdp, js_rect_center(sel))
    if not info or "__error__" in (info if isinstance(info, dict) else {}):
        raise SystemExit("element not found or not visible: %s -> %r" % (sel, info))
    x, y = float(info["x"]), float(info["y"])
    cdp.send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})
    time.sleep(0.05)
    cdp.send("Input.dispatchMouseEvent", {"type": "mousePressed", "x": x, "y": y,
                                          "button": "left", "clickCount": 1})
    time.sleep(0.05)
    cdp.send("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x, "y": y,
                                          "button": "left", "clickCount": 1})
    return info


def click_nth_visible(cdp, sel, n):
    info = evaluate(cdp, """(() => {
      const els = [...document.querySelectorAll(%s)].filter(e => {
        const r = e.getBoundingClientRect();
        return r.width > 0 && r.height > 0;
      });
      const el = els[%d];
      if (!el) return null;
      el.scrollIntoView({block:'center'});
      const r = el.getBoundingClientRect();
      return {x: r.left + r.width/2, y: r.top + r.height/2, w: r.width, h: r.height};
    })()""" % (json.dumps(sel), n))
    if not info:
        raise SystemExit("no visible match #%d for %s" % (n, sel))
    x, y = float(info["x"]), float(info["y"])
    cdp.send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})
    time.sleep(0.05)
    cdp.send("Input.dispatchMouseEvent", {"type": "mousePressed", "x": x, "y": y,
                                          "button": "left", "clickCount": 1})
    time.sleep(0.05)
    cdp.send("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x, "y": y,
                                          "button": "left", "clickCount": 1})
    return info


def type_text(cdp, sel, text):
    trusted_click(cdp, sel)
    time.sleep(0.2)
    for ch in text:
        cdp.send("Input.dispatchKeyEvent", {"type": "keyDown", "text": ch})
        cdp.send("Input.dispatchKeyEvent", {"type": "keyUp"})
        time.sleep(0.03)


STATE_JS = r"""(() => {
  const visible = el => !!(el && el.offsetParent !== null && el.getClientRects().length);
  const alert = [...document.querySelectorAll('.layui-layer')].find(e => visible(e) && (e.innerText||'').includes('异常插件'));
  const sign = document.querySelector('.btn_sign');
  const v = document.querySelector('video');
  const out = {url: location.href, title: document.title};
  const tips = [...document.querySelectorAll('.layer_tips')].find(e => visible(e));
  out.tips = tips ? (tips.innerText||'').trim().slice(0,200) : null;
  out.alert = !!alert;
  out.sign = visible(sign);
  if (v) {
    out.video = {t: Math.round(v.currentTime), d: Math.round(v.duration), paused: v.paused, ended: v.ended, ready: v.readyState};
  } else out.video = null;
  return out;
})()"""


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    cmd = sys.argv[1]
    args = sys.argv[2:]

    if cmd == "targets":
        for i, t in enumerate(list_targets()):
            print(i, "|", (t.get("title") or "")[:40], "|", (t.get("url") or "")[:100])
        return 0

    if cmd == "info":
        c = page_cdp()
        try:
            print(json.dumps(evaluate(c, "({url: location.href, title: document.title, ready: document.readyState})"), ensure_ascii=False))
        finally:
            c.close()
        return 0

    if cmd == "nav":
        url = args[0]
        c = page_cdp()
        try:
            c.send("Page.enable")
            c.send("Page.navigate", {"url": url})
            for _ in range(60):
                time.sleep(0.5)
                st = evaluate(c, "document.readyState")
                if st == "complete":
                    break
            time.sleep(1.0)
            print(json.dumps(evaluate(c, "({url: location.href, title: document.title})"), ensure_ascii=False))
        finally:
            c.close()
        return 0

    if cmd == "state":
        c = page_cdp()
        try:
            print(json.dumps(evaluate(c, STATE_JS), ensure_ascii=False))
        finally:
            c.close()
        return 0

    if cmd == "eval":
        c = page_cdp()
        try:
            r = evaluate(c, args[0], await_promise=True)
            print(json.dumps(r, ensure_ascii=False, default=str))
        finally:
            c.close()
        return 0

    if cmd == "html":
        c = page_cdp()
        try:
            html = evaluate(c, "document.documentElement.outerHTML", timeout=30)
            with open(args[0], "w", encoding="utf-8") as f:
                f.write(html or "")
            print("saved", args[0], len(html or ""), "chars")
        finally:
            c.close()
        return 0

    if cmd == "click":
        c = page_cdp()
        try:
            info = trusted_click(c, args[0])
            print("clicked", args[0], info)
        finally:
            c.close()
        return 0

    if cmd == "clickn":
        c = page_cdp()
        try:
            info = click_nth_visible(c, args[0], int(args[1]))
            print("clicked", args[0], "#", args[1], info)
        finally:
            c.close()
        return 0

    if cmd == "type":
        c = page_cdp()
        try:
            type_text(c, args[0], args[1])
            print("typed into", args[0])
        finally:
            c.close()
        return 0

    if cmd == "screenshot":
        c = page_cdp()
        try:
            r = c.send("Page.captureScreenshot", {"format": "png"})
            with open(args[0], "wb") as f:
                f.write(base64.b64decode(r["data"]))
            print("saved", args[0])
        finally:
            c.close()
        return 0

    if cmd == "shot-el":
        c = page_cdp()
        try:
            info = evaluate(c, """(() => {
              const el = document.querySelector(%s);
              if (!el) return null;
              el.scrollIntoView({block:'center'});
              const r = el.getBoundingClientRect();
              return {x: Math.max(0,Math.floor(r.left)), y: Math.max(0,Math.floor(r.top)), width: Math.ceil(r.width), height: Math.ceil(r.height), scale: 1};
            })()""" % json.dumps(args[0]))
            if not info:
                print("element not found")
                return 2
            r = c.send("Page.captureScreenshot", {"format": "png", "clip": dict(info, scale=3)})
            with open(args[1], "wb") as f:
                f.write(base64.b64decode(r["data"]))
            print("saved", args[1], info)
        finally:
            c.close()
        return 0

    if cmd == "seek":
        c = page_cdp()
        try:
            print(evaluate(c, "(() => { const v=document.querySelector('video'); if(!v) return 'novideo'; v.currentTime=%s; return v.currentTime; })()" % args[0]))
        finally:
            c.close()
        return 0

    if cmd in ("play", "pause"):
        c = page_cdp()
        try:
            if cmd == "play":
                print(evaluate(c, "(() => { const v=document.querySelector('video'); if(!v) return 'novideo'; v.play(); return 'played'; })()"))
            else:
                print(evaluate(c, "(() => { const v=document.querySelector('video'); if(!v) return 'novideo'; v.pause(); return 'paused'; })()"))
        finally:
            c.close()
        return 0

    if cmd == "cookies-out":
        cookies = None
        try:
            b = browser_cdp()
            try:
                r = b.send("Storage.getCookies")
                cookies = r.get("cookies", [])
            finally:
                b.close()
        except Exception:
            cookies = None
        if cookies is None:
            c = page_cdp()
            try:
                r = c.send("Network.getAllCookies")
                cookies = r.get("cookies", [])
            finally:
                c.close()
        with open(args[0], "w", encoding="utf-8") as f:
            json.dump(cookies, f, ensure_ascii=False, indent=1)
        print("saved %d cookies" % len(cookies))
        return 0

    if cmd == "cookies-in":
        with open(args[0], encoding="utf-8") as f:
            raw = json.load(f)
        cookies = []
        for c in raw:
            name, value = c.get("name"), c.get("value")
            if not name:
                continue
            item = {"name": str(name), "value": str(value if value is not None else "")}
            dom = c.get("domain")
            path = c.get("path") or "/"
            if dom:
                item["domain"] = str(dom)
                item["path"] = str(path)
            else:
                item["url"] = _origin() + str(path)
            exp = c.get("expires")
            try:
                expf = float(exp) if exp not in (None, "", 0, -1, "-1") else None
            except Exception:
                expf = None
            if expf and expf > 0:
                item["expires"] = expf
            cookies.append(item)
        ok = False
        try:
            b = browser_cdp()
            try:
                b.send("Storage.setCookies", {"cookies": cookies})
                ok = True
            finally:
                b.close()
        except Exception as e:
            print("Storage.setCookies failed: %r" % e)
        if not ok:
            c = page_cdp()
            try:
                c.send("Network.setCookies", {"cookies": cookies})
                ok = True
            finally:
                c.close()
        print("restored" if ok else "FAILED", len(cookies), "cookies")
        return 0

    if cmd == "newtab":
        url = args[0] if args else "about:blank"
        urllib.request.urlopen(BASE + "/json/new?" + urllib.parse.quote(url, safe=":/?=&"), timeout=5).read()
        time.sleep(1)
        for i, t in enumerate(list_targets()):
            print(i, "|", (t.get("url") or "")[:80])
        return 0

    if cmd == "closetab":
        pages = list_targets()
        idx = int(args[0])
        tid = pages[idx]["id"]
        urllib.request.urlopen(BASE + "/json/close/" + tid, timeout=5).read()
        print("closed", idx)
        return 0

    print("unknown command", cmd)
    return 1


if __name__ == "__main__":
    import urllib.parse  # noqa
    sys.exit(main())
