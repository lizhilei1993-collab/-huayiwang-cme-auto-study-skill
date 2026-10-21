#!/bin/bash
# agent-browser 视频守护脚本 v2：仅使用原生（可信）点击
# 用法: bash ab_watch2.sh <logfile> <max_cycles>
export AGENT_BROWSER_EXECUTABLE_PATH="${CHROME_PATH:-C:/Program Files/Google/Chrome/Application/chrome.exe}"
LOG="$1"
MAX="${2:-200}"
: > "$LOG"
for i in $(seq 1 "$MAX"); do
  TS=$(date +%H:%M:%S)
  STATE=$(agent-browser eval "(() => {
    const alert = [...document.querySelectorAll('.layui-layer')].find(e => e.offsetParent && (e.innerText||'').includes('异常插件'));
    if (alert) return 'ALERT';
    const sign = document.querySelector('.btn_sign');
    if (sign && sign.offsetParent) return 'SIGN';
    const v = document.querySelector('video');
    if (!v) return 'NOVIDEO';
    if (v.ended) return 'ENDED:t=' + Math.round(v.currentTime) + ',d=' + Math.round(v.duration);
    if (v.paused) return 'PAUSED:t=' + Math.round(v.currentTime) + ',d=' + Math.round(v.duration);
    return 'PLAYING:t=' + Math.round(v.currentTime) + ',d=' + Math.round(v.duration);
  })()" 2>&1 | tr -d '"')
  echo "[$TS] $STATE" >> "$LOG"
  case "$STATE" in
    ALERT*) echo "[$TS] !!! ANTI-CHEAT ALERT PRESENT !!!" >> "$LOG"; break ;;
    SIGN*) agent-browser click ".btn_sign" >> "$LOG" 2>&1; echo "[$TS] signed (native click)" >> "$LOG" ;;
    PAUSED*) agent-browser click "button.pv-playpause" >> "$LOG" 2>&1; echo "[$TS] resumed play (native click)" >> "$LOG" ;;
    ENDED*) echo "[$TS] VIDEO_ENDED" >> "$LOG"; break ;;
  esac
  sleep 10
done
echo "[$(date +%H:%M:%S)] WATCHER_EXIT" >> "$LOG"
