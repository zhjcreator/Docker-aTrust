#!/bin/bash
# Start vnc-clip-bridge as a fully detached daemon.
# Usage: start-vcb.sh

set -e

pkill -9 -f vnc-clip-bridge 2>/dev/null || true
rm -f /tmp/vcb.log
sleep 0.5

LOG=/tmp/vcb.log
PIDFILE=/run/vcb.pid

# setsid -> new session, nohup -> ignore SIGHUP, & -> background
# redirect all FDs to avoid parent shell close breaking pipes
setsid env DISPLAY=:1 XAUTHORITY=/root/.Xauthority \
    nohup python3 /usr/local/bin/vnc-clip-bridge.py \
    > "$LOG" 2>&1 < /dev/null &

PID=$!
echo $PID > "$PIDFILE"

# Detach completely: wait for parent shell to be ready to exit
sleep 1
if ps -p $PID >/dev/null 2>&1; then
    echo "vcb started PID=$PID"
    exit 0
fi
echo "vcb failed to start; log:"
cat "$LOG"
exit 1