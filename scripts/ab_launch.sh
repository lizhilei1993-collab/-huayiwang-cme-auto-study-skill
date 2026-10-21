#!/bin/bash
# agent-browser launch runner: uses system Chrome, logs everything
# 可用环境变量覆盖: CME_DATA_DIR / CME_HOST / CHROME_PATH
D="${CME_DATA_DIR:-$(cd "$(dirname "$0")/.." && pwd)/ab}"
HOST_URL="${CME_HOST:-https://cme.example.com}"
CHROME="${CHROME_PATH:-C:/Program Files/Google/Chrome/Application/chrome.exe}"
mkdir -p "$D"
export AGENT_BROWSER_EXECUTABLE_PATH="$CHROME"

echo "[$(date +%H:%M:%S)] starting open..." > "$D/run.log"
agent-browser open "$HOST_URL/pages/cme.aspx" > "$D/open.log" 2>&1 &
OPEN_PID=$!
echo "[$(date +%H:%M:%S)] open pid=$OPEN_PID, waiting 25s..." >> "$D/run.log"
sleep 25
echo "[$(date +%H:%M:%S)] --- open.log ---" >> "$D/run.log"
cat "$D/open.log" >> "$D/run.log" 2>&1
echo "[$(date +%H:%M:%S)] --- get url ---" >> "$D/run.log"
agent-browser get url >> "$D/run.log" 2>&1 &
GPID=$!
sleep 10
echo "[$(date +%H:%M:%S)] done" >> "$D/run.log"
