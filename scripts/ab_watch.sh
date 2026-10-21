#!/bin/bash
# agent-browser 视频守护脚本：处理签到弹窗、保持播放、记录状态
# 用法: bash ab_watch.sh <logfile> <max_cycles>
export AGENT_BROWSER_EXECUTABLE_PATH="${CHROME_PATH:-C:/Program Files/Google/Chrome/Application/chrome.exe}"
LOG="$1"
MAX="${2:-100}"
: > "$LOG"
for i in $(seq 1 "$MAX"); do
  TS=$(date +%H:%M:%S)
  OUT=$(agent-browser eval "(() => {
    const v = document.querySelector('video');
    if (!v) return 'NO_VIDEO';
    const r = {t: Math.round(v.currentTime), d: Math.round(v.duration), paused: v.paused, ended: v.ended, acts: []};
    let handled = false;
    const sign = document.querySelector('.btn_sign');
    if (sign && sign.offsetParent) { sign.click(); r.acts.push('SIGN'); handled = true; }
    if (!handled && !r.ended && v.paused) {
      const pb = document.querySelector('button.pv-playpause');
      if (pb) { pb.click(); r.acts.push('PLAY'); handled = true; }
    }
    const pops = [...document.querySelectorAll('.pv-question, .pv-quiz, .quiz-wrap, .question-wrap, .layui-layer, .card_question')].filter(e => e.offsetParent).map(e => (e.className||'').toString().slice(0,50));
    if (pops.length) r.pops = pops;
    return JSON.stringify(r);
  })()" 2>&1)
  echo "[$TS] $OUT" >> "$LOG"
  if echo "$OUT" | grep -q '"ended":true'; then
    echo "[$TS] VIDEO_ENDED" >> "$LOG"
    break
  fi
  sleep 10
done
echo "[$(date +%H:%M:%S)] WATCHER_EXIT" >> "$LOG"
