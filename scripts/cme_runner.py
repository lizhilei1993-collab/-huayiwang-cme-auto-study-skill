# -*- coding: utf-8 -*-
"""CME 队列守护：按顺序自动把未完成的课件视频一集接一集播完。

用法:
  python cme_runner.py [queue.json]
队列文件: {"items":[{"cid":"...","cwid":"...","title":"...","secs":3574}, ...]}

行为:
  - 顺次导航到每个课件的播放页并监控
  - SIGN 签到弹窗 -> 可信点击
  - PAUSED -> 恢复播放；连续失败 -> 重载页面
  - NOVIDEO -> 导航回课件页（必要时恢复 cookie）
  - CDP 断线自动重连（Chrome 被守护重启时不中断）
  - 每 5 分钟用 HTTP 拉一次课程页，判断当前单元是否已 待考试/已完成 -> 切换到下一单元
  - 每 3 分钟备份 cookie
  - 检测到登录页 -> 先重放 cookie；仍无效 -> 调 cme_login 纯 HTTP 自动登录并注入浏览器
  - 状态写入 runner_status.json（外部可读进度）
"""
import json
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from config import (data_dir as _data_dir, host as _host, origin as _origin, site as _site, site_key as _site_key, cdn_base as _cdn, user as _user, password as _pwd, alive_check as _alive_check, alive_marker as _alive_marker, courses as _courses, course_list as _course_list)  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cme_cdp as C  # noqa

BASE = _data_dir()
COOKIE_BK = BASE / "cookies_latest.json"
STATUS = BASE / "runner_status.json"
QUEUE_DEFAULT = BASE / "queue.json"
LOGFILE = BASE / "runner.log"
HOST = _host()
RELOGIN_COOLDOWN = 300          # 两次自动登录最小间隔（秒）
_last_relogin = [0.0]


def cdp_cookies(raw):
    """清洗 cookie 为 CDP 可接受格式（expires 必须是正数 double，session cookie 需省略）"""
    out = []
    for c in raw or []:
        name = c.get("name")
        if not name:
            continue
        item = {"name": str(name),
                "value": str(c.get("value") if c.get("value") is not None else "")}
        dom = c.get("domain")
        if dom:
            item["domain"] = str(dom)
            item["path"] = str(c.get("path") or "/")
        else:
            item["url"] = _origin() + str(c.get("path") or "/")
        try:
            exp = float(c.get("expires"))
            if exp > 0:
                item["expires"] = exp
        except Exception:
            pass
        out.append(item)
    return out


def inject_cookies(cookies):
    b = C.browser_cdp()
    try:
        b.send("Storage.setCookies", {"cookies": cdp_cookies(cookies)})
    finally:
        b.close()


def auto_relogin():
    """纯 HTTP 自动登录 -> 写 cookie 备份 -> 注入浏览器。带冷却，失败返回 False"""
    now = time.time()
    if now - _last_relogin[0] < RELOGIN_COOLDOWN:
        log("AUTO-LOGIN skipped (冷却中，剩 %ds)" % int(RELOGIN_COOLDOWN - (now - _last_relogin[0])))
        return False
    _last_relogin[0] = now
    log("AUTO-LOGIN start")
    try:
        import cme_login as L
        s = L.do_login_http()
        if not s:
            log("AUTO-LOGIN failed (登录接口未成功)")
            return False
        if not L.alive(s):
            log("AUTO-LOGIN 登录返回成功但会话仍无效")
            return False
        n = L.dump_cookies(s)
        log("AUTO-LOGIN ok, %d cookies 已保存" % n)
        inject_cookies(json.loads(COOKIE_BK.read_text(encoding="utf-8")))
        log("AUTO-LOGIN cookies 已注入浏览器")
        return True
    except BaseException as e:
        log("AUTO-LOGIN error: %r" % e)
        return False

STATE_JS = r"""(() => {
  const visible = el => !!(el && el.offsetParent !== null && el.getClientRects().length);
  const alert = [...document.querySelectorAll('.layui-layer')].find(e => visible(e) && (e.innerText||'').includes('异常插件'));
  const sign = document.querySelector('.btn_sign');
  const v = document.querySelector('video');
  const out = {url: location.href.slice(0, 140)};
  out.vis = document.visibilityState;
  out.alert = !!alert;
  if (alert) out.alertText = (alert.innerText||'').trim().slice(0, 140);
  out.sign = visible(sign);
  if (!v) { out.novideo = true; }
  else {
    out.t = Math.round(v.currentTime); out.d = Math.round(v.duration||0);
    out.paused = v.paused; out.ended = v.ended; out.ready = v.readyState;
  }
  return out;
})()"""

# 签到弹层顽固不消失时：隐藏遮罩层 + 恢复播放。
# 10-19 实测：弹层出现后点 .btn_sign 不报错但也不消失，视频时间戳直接冻结
# （2263 秒卡了 3.5 小时），是当天效率从 100% 掉到 6% 的根因。
SIGN_KILL_JS = r"""(() => {
  let killed = 0;
  const bs = document.querySelector('.btn_sign');
  let node = bs;
  for (let i = 0; i < 6 && node; i++) {
    if (node.className && String(node.className).indexOf('layui-layer') >= 0) {
      node.style.display = 'none'; killed++;
      try { node.remove(); } catch (e) {}
      break;
    }
    node = node.parentElement;
  }
  if (bs) { try { bs.style.display = 'none'; } catch (e) {} }
  const v = document.querySelector('video');
  if (v && v.paused) { try { v.play(); } catch (e) {} }
  return JSON.stringify({killed: killed, hasBtn: !!bs, paused: v ? v.paused : null});
})()"""


def log(msg):
    line = "[%s] %s" % (datetime.now().strftime("%m-%d %H:%M:%S"), msg)
    try:
        with open(LOGFILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def write_status(d):
    d["ts"] = datetime.now().strftime("%m-%d %H:%M:%S")
    try:
        STATUS.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass


def course_state(cids):
    """HTTP 拉课程页，返回 {cwid: state}"""
    try:
        import requests
        from bs4 import BeautifulSoup
        raw = json.loads(COOKIE_BK.read_text(encoding="utf-8"))
        items = raw if isinstance(raw, list) else raw.get("cookies", [])
        s = requests.Session()
        s.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                        "AppleWebKit/537.36 Chrome/141.0 Safari/537.36"})
        for c in items:
            if _site_key() in (c.get("domain") or ""):
                s.cookies.set(c["name"], c["value"], domain=_site())
        states = {}
        for cid in cids:
            r = s.get(HOST + "pages/course.aspx?cid=" + cid, timeout=30)
            r.encoding = "utf-8"
            soup = BeautifulSoup(r.text, "html.parser")
            for d in soup.select("div.cw-progress-row"):
                states[d.get("data-cwrid")] = d.get("data-studystate")
        return states
    except Exception as e:
        log("course_state failed: %r" % e)
        return {}


def unit_gone(url):
    """开播前预检：课件若已下线，页面会返回 '课件不存在或已下线'。
    命中则跳过该单元，避免在空页面上无限重载空转（2026-10-17 实测踩坑）。"""
    try:
        import requests
        raw = json.loads(COOKIE_BK.read_text(encoding="utf-8"))
        items = raw if isinstance(raw, list) else raw.get("cookies", [])
        s = requests.Session()
        s.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                        "AppleWebKit/537.36 Chrome/141.0 Safari/537.36"})
        for c in items:
            if _site_key() in (c.get("domain") or ""):
                s.cookies.set(c["name"], c["value"], domain=_site())
        r = s.get(url, timeout=25)
        r.encoding = "utf-8"
        if "课件不存在" in r.text or "已下线" in r.text:
            return True
        if len(r.text.strip()) < 200 and "<video" not in r.text.lower():
            log("preflight 可疑(短响应 %d 字节)" % len(r.text))
        return False
    except Exception as e:
        log("preflight failed: %r" % e)
        return False


def main():
    qf = Path(sys.argv[1]) if len(sys.argv) > 1 else QUEUE_DEFAULT
    q = json.loads(qf.read_text(encoding="utf-8"))
    items = q["items"]
    cids = []
    for it in items:
        if it["cid"] not in cids:
            cids.append(it["cid"])
    log("RUNNER_START items=%d" % len(items))

    holder = {"c": C.page_cdp()}
    fails = {"eval": 0, "nav": 0}

    def get_state():
        while True:
            try:
                st = C.evaluate(holder["c"], STATE_JS)
                fails["eval"] = 0
                return st
            except Exception as e:
                fails["eval"] += 1
                log("eval fail(%d): %r" % (fails["eval"], e))
                if fails["eval"] >= 3:
                    try:
                        holder["c"].close()
                    except Exception:
                        pass
                    time.sleep(3)
                    try:
                        holder["c"] = C.page_cdp()
                        log("CDP reconnected")
                        fails["eval"] = 0
                    except Exception as e2:
                        log("CDP reconnect failed: %r" % e2)
                        time.sleep(15)
                else:
                    time.sleep(5)

    def do(js, what="js"):
        while True:
            try:
                return C.evaluate(holder["c"], js)
            except Exception as e:
                log("%s failed: %r" % (what, e))
                time.sleep(5)

    def nav(url):
        do("location.href=%s" % json.dumps(url), "nav")
        # 关键：无窗口启动的 Chrome 会把页面判为 hidden，Chrome 会挂起媒体加载，
        # 导致 MSE 已建立但永不请求分片（readyState 恒为 0）。必须把页面提到前台。
        try:
            holder["c"].send("Page.bringToFront", {}, timeout=8)
        except BaseException as e:
            log("bringToFront fail: %r" % e)

    def click_sel(sel, n=0):
        try:
            C.click_nth_visible(holder["c"], sel, n)
            return True
        except BaseException as e:  # SystemExit 也要接住，否则整个进程会退出
            log("click %s failed: %r" % (sel, e))
            return False

    pause_fails = 0
    novideo_count = 0
    last_cookie = time.time()
    last_check = 0

    try:
        for idx, it in enumerate(items):
            cwid = it["cwid"]
            url = (HOST + "course_ware/"
                   "course_ware_polyv.aspx?ff=0&ft=0&cwid=%s&t=0" % cwid)
            log("=== UNIT %d/%d %s (%ss) cwid=%s" % (idx + 1, len(items),
                                                     it.get("title", "")[:30],
                                                     it.get("secs"), cwid))
            write_status({"phase": "unit", "index": idx + 1, "total": len(items),
                          "title": it.get("title"), "cwid": cwid})

            if not it.get("secs"):
                log("skip (secs=0, 无视频)")
                continue

            if unit_gone(url):
                log("!! 课件不存在或已下线 -> SKIP（不占用队列时间）")
                continue

            # 已完成/待考试的单元直接跳过（便于重启后安全重跑整条队列）
            try:
                s0 = course_state(cids).get(cwid)
                if s0 in ("待考试", "已完成"):
                    log("already %s -> skip" % s0)
                    continue
                log("pre-state = %s" % s0)
            except Exception as e:
                log("pre-state check failed: %r" % e)

            nav(url)
            time.sleep(22)

            novideo_count = 0
            novideo_total = 0
            pause_fails = 0
            stuck = 0
            sign_clicks = 0
            sign_total = 0
            last_t = 0
            last_t_time = time.time()
            stall = 0
            started = time.time()
            done = False

            while not done:
                st = get_state()
                st["phase"] = "playing"
                st["index"] = idx + 1
                st["total"] = len(items)
                st["title"] = it.get("title")
                write_status(st)

                if st.get("vis") and st.get("vis") != "visible":
                    log("page hidden(%s) -> bringToFront" % st.get("vis"))
                    try:
                        holder["c"].send("Page.bringToFront", {}, timeout=8)
                    except BaseException:
                        pass
                    time.sleep(2)
                    continue

                if "login.aspx" in (st.get("url") or ""):
                    log("落在登录页 -> 尝试恢复会话")
                    nav(url)
                    time.sleep(12)
                    st_l = get_state()
                    if "login.aspx" in (st_l.get("url") or ""):
                        if auto_relogin():
                            nav(url)
                            time.sleep(16)
                            log("重登录后 -> %s" % (get_state().get("url") or "")[:80])
                        else:
                            time.sleep(30)
                    continue

                if st.get("url") and cwid not in st["url"] and "polyv" in st["url"]:
                    log("URL drift -> %s ; renavigate" % st["url"][:90])
                    nav(url)
                    time.sleep(12)
                    continue

                if st.get("novideo"):
                    novideo_count += 1
                    novideo_total += 1
                    log("NOVIDEO(%d/%d) url=%s" % (novideo_count, novideo_total, st.get("url")))
                    if novideo_total >= 45:
                        log("!! 持续取不到 video 元素（%d 次）-> 放弃本单元，转下一集" % novideo_total)
                        write_status({"phase": "skip-novideo", "index": idx + 1,
                                      "title": it.get("title"), "cwid": cwid})
                        done = True
                        break
                    if novideo_count >= 6:
                        novideo_count = 0
                        log("recovery: renavigate")
                        nav(url)
                        time.sleep(14)
                        try:
                            st2 = get_state()
                            if "login.aspx" in (st2.get("url") or ""):
                                log("on login page -> restore cookies")
                                cookies = json.loads(COOKIE_BK.read_text(encoding="utf-8"))
                                inject_cookies(cookies)
                                nav(url)
                                time.sleep(14)
                                st3 = get_state()
                                if "login.aspx" in (st3.get("url") or ""):
                                    log("cookie 重放无效 -> 触发自动登录")
                                    if auto_relogin():
                                        nav(url)
                                        time.sleep(16)
                                        st4 = get_state()
                                        log("登录后页面 -> %s" % (st4.get("url") or "")[:80])
                        except BaseException as e:
                            log("cookie restore path failed: %r" % e)
                    time.sleep(10)
                    continue
                novideo_count = 0

                if st.get("alert"):
                    log("!!! ANTI-CHEAT ALERT: %s" % st.get("alertText"))
                    write_status({"phase": "blocked", "alert": st.get("alertText"),
                                  "index": idx + 1, "title": it.get("title")})
                    do("document.querySelectorAll('.layui-layer-close,.layui-layer-btn').forEach(function(e){e.click();})",
                       "close-alert")
                    time.sleep(20)
                    continue

                if st.get("sign"):
                    sign_total += 1
                    if sign_clicks < 2:
                        sign_clicks += 1
                        log("SIGN(%d/2) -> trusted click" % sign_clicks)
                        click_sel(".btn_sign", 0)
                        time.sleep(2)
                        if not get_state().get("sign"):
                            log("SIGN dismissed by click")
                            sign_clicks = 0
                            sign_total = 0
                        continue
                    if sign_clicks < 6:
                        sign_clicks += 1
                        log("SIGN 未消失(%d) -> 隐藏遮罩并强制播放" % sign_clicks)
                        try:
                            rs = C.evaluate(holder["c"], SIGN_KILL_JS)
                            log("hide-sign -> %s" % str(rs)[:120])
                        except BaseException as e:
                            log("hide-sign failed: %r" % e)
                        time.sleep(2)
                        # 不 continue：继续走主流程，由进度看门狗兜底
                    else:
                        log("SIGN 顽固 -> 重载页面")
                        sign_clicks = 0
                        nav(url + "&r=" + str(int(time.time())))
                        time.sleep(22)
                        continue
                else:
                    sign_clicks = 0
                    sign_total = 0

                if st.get("ended"):
                    log("VIDEO_ENDED t=%s d=%s" % (st.get("t"), st.get("d")))
                    done = True
                    break

                if st.get("paused"):
                    if not st.get("d"):
                        # 播放器还在加载/未就绪：多次无效则强制重载（带随机参数破缓存）
                        stuck += 1
                        log("loading (t=%s d=%s ready=%s) stuck=%d" % (st.get("t"), st.get("d"),
                                                                       st.get("ready"), stuck))
                        if stuck >= 6:
                            log("loading stuck -> force reload")
                            nav(url + "&r=" + str(int(time.time())))
                            time.sleep(25)
                            stuck = 0
                        time.sleep(10)
                        continue
                    stuck = 0
                    pause_fails += 1
                    log("PAUSED t=%s/%s (fail %d)" % (st.get("t"), st.get("d"), pause_fails))
                    if click_sel("button.pv-playpause", 0):
                        time.sleep(2)
                        st2 = get_state()
                        if st2.get("paused"):
                            try:
                                C.trusted_click(holder["c"], "video")
                            except BaseException:
                                pass
                            time.sleep(2)
                            st3 = get_state()
                            if st3.get("paused") and pause_fails >= 3:
                                log("recovery: reload page")
                                nav(url)
                                time.sleep(16)
                                pause_fails = 0
                            elif not st3.get("paused"):
                                pause_fails = 0
                        else:
                            pause_fails = 0
                else:
                    pause_fails = 0
                    if int(time.time()) % 60 < 12:
                        log("PLAYING t=%s/%s" % (st.get("t"), st.get("d")))

                # 进度看门狗：只要时间戳不再前进（缓冲、遮罩、静默冻结都算），
                # 超过 90 秒就强制重载。服务端记录进度，重载后从断点续播。
                # 10-19 下午的教训：只有状态判断不够，t 冻结时状态一切"正常"。
                t_now = st.get("t") or 0
                if abs(t_now - last_t) >= 2:
                    last_t = t_now
                    last_t_time = time.time()
                    if sign_total > 0 and not st.get("sign"):
                        sign_total = 0
                elif st.get("d") and not st.get("ended"):
                    if time.time() - last_t_time > 90:
                        stall += 1
                        log("t 停滞 %ds (t=%s/%s) stall=%d -> 强制重载" % (
                            int(time.time() - last_t_time), t_now, st.get("d"), stall))
                        nav(url + "&r=" + str(int(time.time())))
                        time.sleep(22)
                        last_t = 0
                        last_t_time = time.time()
                        sign_clicks = 0
                        if stall >= 8:
                            log("!! 连续停滞 8 次仍无进展 -> 放弃本单元转下一集")
                            write_status({"phase": "skip-stall", "index": idx + 1,
                                          "title": it.get("title"), "cwid": cwid})
                            done = True
                            break
                        continue

                if time.time() - last_check > 300:
                    last_check = time.time()
                    states = course_state(cids)
                    s = states.get(cwid)
                    if s:
                        log("unit state = %s" % s)
                        if s in ("待考试", "已完成"):
                            log("UNIT UNLOCKED (%s) -> next" % s)
                            done = True
                            break
                    else:
                        log("state not found for cwid")
                    if st.get("t") and it.get("secs") and st["t"] >= it["secs"] - 3:
                        log("position reached duration -> next")
                        done = True
                        break

                if time.time() - started > (it.get("secs") or 3600) + 3600:
                    log("timeout waiting unit (t=%s/%s 已耗 %.0fmin) -> next"
                        % (st.get("t"), st.get("d"), (time.time() - started) / 60))
                    done = True
                    break

                if time.time() - last_cookie > 180:
                    try:
                        cookies = None
                        try:
                            b = C.browser_cdp()
                            try:
                                r = b.send("Storage.getCookies")
                                cookies = r.get("cookies", [])
                            finally:
                                b.close()
                        except Exception:
                            pass
                        if cookies:
                            COOKIE_BK.write_text(json.dumps(cookies, ensure_ascii=False, indent=1),
                                                 encoding="utf-8")
                            log("cookie backup (%d)" % len(cookies))
                    except Exception as e:
                        log("cookie backup failed: %r" % e)
                    last_cookie = time.time()

                time.sleep(10)

        log("QUEUE_EXHAUSTED")
        write_status({"phase": "exhausted"})
    except BaseException:
        log("FATAL\n" + traceback.format_exc())
        write_status({"phase": "fatal"})
    finally:
        try:
            holder["c"].close()
        except Exception:
            pass
        log("RUNNER_EXIT")


if __name__ == "__main__":
    main()
