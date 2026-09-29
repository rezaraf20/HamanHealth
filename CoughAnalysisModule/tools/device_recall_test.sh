#!/usr/bin/env bash
# Controlled recall test on a USB-connected phone.
#
# Plays 12 held-out real coughs (loud, then quiet) from this Mac's speaker while the app
# monitors, then scores which ones the phone logged. Optionally forces a microphone route.
# Also pulls the raw audio the phone captured so it can be replayed offline:
#   .venv/bin/python ml/analyze_capture.py results/device/<label>.pcm --dir ml/artifacts/playback
#
# Usage:  ./tools/device_recall_test.sh <label> [ROUTE]      e.g.  a31 CAMCORDER@16k
# Needs:  a debug build installed, mic permission granted, phone next to the Mac speaker.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ADB=$HOME/Library/Android/sdk/platform-tools/adb
PB="$ROOT/ml/artifacts/playback"
OUT="$ROOT/results/device"; mkdir -p "$OUT"
LABEL=${1:?label required}; ROUTE=${2:-}

[ -f "$PB/playback_loud.wav" ] || "$ROOT/.venv/bin/python" "$ROOT/ml/make_playback.py"

prefs() {  # rewrite the app's prefs with an optional forced route
  $ADB shell am force-stop com.haman.sleep
  local route_xml=""; [ -n "$1" ] && route_xml="    <string name=\"audio_route\">$1</string>"
  printf "<?xml version='1.0' encoding='utf-8' standalone='yes' ?>\n<map>\n%s\n</map>\n" "$route_xml" \
    | $ADB shell "run-as com.haman.sleep sh -c 'cat > shared_prefs/haman.xml'"
}

tap() {  # tap the first on-screen element with this exact text, retrying while the UI settles
  for _ in 1 2 3 4 5 6; do
    $ADB shell uiautomator dump /sdcard/ui.xml >/dev/null 2>&1
    $ADB pull /sdcard/ui.xml "$OUT/.ui.xml" >/dev/null 2>&1
    local c; c=$(python3 - "$OUT/.ui.xml" "$1" <<'PY'
import re, sys
t = open(sys.argv[1]).read()
m = re.search(r'text="%s"[^>]*?bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"' % re.escape(sys.argv[2]), t)
print(f"{(int(m[1])+int(m[3]))//2} {(int(m[2])+int(m[4]))//2}" if m else "")
PY
)
    [ -n "$c" ] && { $ADB shell input tap $c; return 0; }
    sleep 2
  done
  echo "could not find '$1' on screen (is the phone unlocked?)"; exit 1
}

[ -n "$ROUTE" ] && prefs "$ROUTE"
$ADB shell run-as com.haman.sleep touch files/debug_raw
$ADB shell input keyevent KEYCODE_WAKEUP; $ADB shell svc power stayon usb
$ADB shell am start -n com.haman.sleep/.MainActivity >/dev/null 2>&1; sleep 3
tap "Start monitoring"
echo "[$LABEL] monitoring; letting the noise floor settle (20 s)"; sleep 20

VOL=$(osascript -e "output volume of (get volume settings)")
osascript -e "set volume output volume 50"
: > "$OUT/$LABEL.offsets"
for lvl in loud quiet; do
  echo "$lvl $($ADB shell date +%s%3N | tr -d '\r')" >> "$OUT/$LABEL.offsets"
  echo "[$LABEL] playing $lvl"; afplay "$PB/playback_$lvl.wav"
done
osascript -e "set volume output volume $VOL"
sleep 5; tap "Stop monitoring"; sleep 5
$ADB shell svc power stayon false
[ -n "$ROUTE" ] && prefs ""

for f in haman.db haman.db-wal haman.db-shm; do
  $ADB shell "run-as com.haman.sleep cat databases/$f" > "$OUT/$LABEL.${f/haman./}" 2>/dev/null
done
mv "$OUT/$LABEL.db-wal" "$OUT/$LABEL.dbwal" 2>/dev/null; mv "$OUT/$LABEL.db-shm" "$OUT/$LABEL.dbshm" 2>/dev/null
python3 - "$OUT" "$LABEL" "$PB" <<'PY'
import sqlite3, json, os, sys, shutil
out, label, pb = sys.argv[1:4]
db = f"{out}/{label}.db"
for a, b in (("dbwal", "-wal"), ("dbshm", "-shm")):
    if os.path.exists(f"{out}/{label}.{a}"): shutil.move(f"{out}/{label}.{a}", db + b)
c = sqlite3.connect(db)
sid, src, t0 = c.execute("select id, audioSource, startedAt from sessions order by id desc limit 1").fetchone()
ev = c.execute("select cls, startedAtMs, endedAtMs from events where sessionId=?", (sid,)).fetchall()
print(f"\n[{label}] session {sid}, route {src}, {len(ev)} events")
for line in open(f"{out}/{label}.offsets"):
    lvl, tp = line.split(); tp = int(tp)
    marks = json.load(open(f"{pb}/playback_{lvl}.json"))
    hit = sum(any(e[0] == "COUGH" and e[2] >= tp + m["start_s"]*1000 - 2500 and e[1] <= tp + m["end_s"]*1000 + 2500
                  for e in ev) for m in marks)
    print(f"  {lvl:6} coughs detected {hit}/{len(marks)}")
print(f"raw capture: {out}/{label}.pcm   (session {sid})")
open(f"{out}/{label}.sid", "w").write(str(sid))
PY
SID=$(cat "$OUT/$LABEL.sid")
$ADB shell "run-as com.haman.sleep cat files/debug/$SID.pcm" > "$OUT/$LABEL.pcm"
