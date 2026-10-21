# -*- coding: utf-8 -*-
"""CME 视频守护 v3（CDP 版）：监控播放、处理签到/暂停、定期备份 cookie。

用法: python cme_watch.py <logfile> <max_cycles> [cwid]
- 每 10s 轮询状态
- SIGN -> CDP 可信点击 .btn_sign
- PAUSED -> 点击播放按钮恢复；连续失败 3 次 -> 重新导航并续播
- ALERT/NOVIDEO -> 记录并退出（需人工介入）
- ENDED -> 记录 VIDEO_ENDED 并退出（由编排层决定下一步）
- 每 3 分钟导出 cookie 备份
"""
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from config import (data_dir as _data_dir, host as _host, origin as _origin, site as _site, site_key as _site_key, cdn_base as _cdn, user as _user, password as _pwd, alive_check as _alive_check, alive_marker as _alive_marker, courses as _courses, course_list as _course_list)  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cme_cdp as C  # noqa

BASE = _data_dir()
COOKIE_BK = BASE / "cookies_latest.json"
STATUS = BASE / "watch_status.json"

STATE_JS = r"""(() => {
  const visible = el => !!(el && el.offsetParent !== null && el.getClientRects().length);
  const alert = [...document.querySelectorAll('.layui-layer')].find(e => visible(e) && (e.innerText||'').includes('异常插件'));
  const sign = document.querySelector('.btn_sign');
  const v = document.querySelector('video');
  const out = {url: location.href.slice(0,120)};
  out.alert = !!alert;
  if (alert) out.alertText = (alert.innerText||'').trim().slice(0,120);
  out.sign = visible(sign);
  if (!v) { out.novideo = true; }
  else {
    out.t = Math.round(v.currentTime); out.d = Math.round(v.duration||0);
    out.paused = v.paused; out.ended = v.ended; out.ready = v.readyState;
  }
  return out;
})()"""


def log(msg, path):
    line = "[%s] %s" % (datetime.now().strftime("%H:%M:%S"), msg)
    with open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def main():
    logfile = Path(sys.argv[1])
    max_cycles = int(sys.argv[2]) if len(sys.argv) > 2 else 20000
    cwid = sys.argv[3] if len(sys.argv) > 3 else ""
    url = (_host() + "course_ware/course_ware_polyv.aspx?ff=0&ft=0&cwid=%s&t=0") % cwid

    c = C.page_cdp()
    pause_fails = 0
    novideo_count = 0
    last_cookie = time.time()
    log("WATCHER_START cwid=%s" % cwid, logfile)

    def recover(reason):
        """尝试恢复：先导航回课件页；若仍是登录页则恢复 cookie 再试。"""
        log("recovery(%s): navigate back" % reason, logfile)
        try:
            C.evaluate(c, "location.href=%s" % json.dumps(url))
        except Exception as e:
            log("recovery nav failed: %r" % e, logfile)
        time.sleep(12)
        try:
            st = C.evaluate(c, STATE_JS)
        except Exception as e:
            log("recovery check failed: %r" % e, logfile)
            return False
        if st.get("novideo") and "login.aspx" in (st.get("url") or ""):
            log("recovery: on login page -> restore cookies", logfile)
            try:
                cookies = json.loads(COOKIE_BK.read_text(encoding="utf-8"))
                b = C.browser_cdp()
                try:
                    b.send("Network.setCookies", {"cookies": cookies})
                finally:
                    b.close()
                C.evaluate(c, "location.href=%s" % json.dumps(url))
                time.sleep(12)
                st = C.evaluate(c, STATE_JS)
            except Exception as e:
                log("cookie restore failed: %r" % e, logfile)
                return False
        ok = not st.get("novideo")
        log("recovery result: %s" % ("OK" if ok else "FAILED"), logfile)
        return ok

    try:
        for i in range(max_cycles):
            try:
                st = C.evaluate(c, STATE_JS)
            except Exception as e:
                log("eval-error: %r" % e, logfile)
                time.sleep(10)
                continue

            st["ts"] = datetime.now().strftime("%H:%M:%S")
            try:
                STATUS.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
            except OSError:
                pass

            if st.get("novideo"):
                novideo_count += 1
                log("NOVIDEO(%d) url=%s" % (novideo_count, st.get("url")), logfile)
                if novideo_count >= 3:
                    if recover("novideo"):
                        novideo_count = 0
                        continue
                    log("NOVIDEO recovery failed -> exit", logfile)
                    break
                time.sleep(10)
                continue
            else:
                novideo_count = 0
            if st.get("alert"):
                log("!!! ANTI-CHEAT ALERT: %s" % st.get("alertText"), logfile)
                break
            if st.get("sign"):
                log("SIGN detected -> native click", logfile)
                try:
                    C.click_nth_visible(c, ".btn_sign", 0)
                except Exception as e:
                    log("sign click failed: %r" % e, logfile)
                time.sleep(2)
                continue
            if st.get("ended"):
                log("VIDEO_ENDED t=%s d=%s" % (st.get("t"), st.get("d")), logfile)
                break
            if st.get("paused"):
                pause_fails += 1
                log("PAUSED t=%s d=%s (fail %d)" % (st.get("t"), st.get("d"), pause_fails), logfile)
                try:
                    C.click_nth_visible(c, "button.pv-playpause", 0)
                    time.sleep(2)
                    st2 = C.evaluate(c, STATE_JS)
                    if st2.get("paused"):
                        # 再试一次：点击视频中部
                        C.trusted_click(c, "video")
                        time.sleep(2)
                        st3 = C.evaluate(c, STATE_JS)
                        if st3.get("paused"):
                            log("still paused after clicks", logfile)
                            if pause_fails >= 3:
                                log("recovery: reload page", logfile)
                                C.evaluate(c, "location.href=%s" % json.dumps(url))
                                time.sleep(15)
                                pause_fails = 0
                        else:
                            pause_fails = 0
                    else:
                        pause_fails = 0
                except Exception as e:
                    log("pause recovery failed: %r" % e, logfile)
            else:
                pause_fails = 0
                log("PLAYING t=%s d=%s" % (st.get("t"), st.get("d")), logfile)

            if time.time() - last_cookie > 180:
                try:
                    cookies = None
                    try:
                        import cme_cdp as CC
                        b = CC.browser_cdp()
                        try:
                            r = b.send("Storage.getCookies")
                            cookies = r.get("cookies", [])
                        finally:
                            b.close()
                    except Exception:
                        cookies = None
                    if cookies:
                        COOKIE_BK.write_text(json.dumps(cookies, ensure_ascii=False, indent=1), encoding="utf-8")
                        log("cookie backup (%d)" % len(cookies), logfile)
                except Exception as e:
                    log("cookie backup failed: %r" % e, logfile)
                last_cookie = time.time()

            time.sleep(10)
    finally:
        c.close()
        log("WATCHER_EXIT", logfile)


if __name__ == "__main__":
    main()
