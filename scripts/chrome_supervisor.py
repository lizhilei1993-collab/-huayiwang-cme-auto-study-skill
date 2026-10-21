# -*- coding: utf-8 -*-
"""CME Chrome 守护：保持指定端口的专属 Chrome 实例存活（计划任务运行，独立于会话进程树）。

用法: python chrome_supervisor.py [--port 9222] [--tag chromeA]
- 单实例锁（按 tag）防止重复守护
- 每 20s 检查 CDP 端口；挂了自动重启 Chrome（同一 profile，cookie 保留）
- 心跳文件供外部诊断
"""
import argparse
import msvcrt
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from config import (data_dir as _data_dir, host as _host, origin as _origin, site as _site, site_key as _site_key, cdn_base as _cdn, user as _user, password as _pwd, alive_check as _alive_check, alive_marker as _alive_marker, courses as _courses, course_list as _course_list)  # noqa: E402

BASE = _data_dir()
CHROME = os.environ.get("CHROME_PATH", r"C:/Program Files/Google/Chrome/Application/chrome.exe")

_lock_fd = None


def note(tag, msg):
    line = "[%s] [%s] %s" % (datetime.now().strftime("%m-%d %H:%M:%S"), tag, msg)
    try:
        BASE.mkdir(parents=True, exist_ok=True)
        with open(BASE / ("chrome_supervisor.log"), "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def acquire_lock(lock_file):
    global _lock_fd
    try:
        fd = open(lock_file, "a+")
        fd.seek(0)
        try:
            msvcrt.locking(fd.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            fd.close()
            return False
        _lock_fd = fd
        fd.seek(0)
        fd.truncate()
        fd.write(str(os.getpid()))
        fd.flush()
        return True
    except OSError:
        return False


def port_ok(port):
    try:
        req = urllib.request.urlopen("http://127.0.0.1:%d/json/version" % port, timeout=3)
        return req.status == 200
    except Exception:
        return False


def launch(port, profile, tag):
    args = [
        CHROME,
        "--remote-debugging-port=%d" % port,
        "--remote-allow-origins=*",
        "--user-data-dir=%s" % str(BASE / profile),
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-timer-throttling",
        "--disable-backgrounding-occluded-windows",
        "--disable-renderer-backgrounding",
        "--disable-features=CalculateNativeWinOcclusion",
        "--autoplay-policy=no-user-gesture-required",
        "--window-size=1280,900",
        "about:blank",
    ]
    flags = 0x00000008 | 0x00000200 | 0x08000000  # DETACHED | NEW_GROUP | NO_WINDOW
    p = subprocess.Popen(args, creationflags=flags, close_fds=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    note(tag, "launched chrome pid=%d port=%d" % (p.pid, port))
    return p.pid


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9222)
    ap.add_argument("--tag", default="chromeA")
    a = ap.parse_args()
    tag = a.tag
    port = a.port
    profile = tag
    lock_file = BASE / ("%s.lock" % tag)
    heartbeat = BASE / ("%s.heartbeat" % tag)

    if not acquire_lock(lock_file):
        note(tag, "已有守护在运行，退出")
        return 0
    note(tag, "supervisor start pid=%d port=%d" % (os.getpid(), port))
    while True:
        try:
            heartbeat.write_text(datetime.now().strftime("%Y-%m-%d %H:%M:%S"), encoding="utf-8")
        except OSError:
            pass
        if not port_ok(port):
            note(tag, "CDP 端口 %d 无响应 -> 拉起 Chrome" % port)
            try:
                launch(port, profile, tag)
            except Exception as e:
                note(tag, "launch failed: %r" % e)
            for _ in range(12):
                time.sleep(5)
                if port_ok(port):
                    note(tag, "chrome 已就绪 (%d)" % port)
                    break
            else:
                note(tag, "chrome 60s 内未就绪")
        time.sleep(20)


if __name__ == "__main__":
    sys.exit(main())
