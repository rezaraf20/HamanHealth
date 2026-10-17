#!/usr/bin/env bash
# Install the debug APK on a connected phone and show its log output.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ADB="$HOME/Library/Android/sdk/platform-tools/adb"
APK="$ROOT/android/app/build/outputs/apk/debug/app-debug.apk"

[ -f "$APK" ] || { echo "No APK. Run ./tools/build.sh first."; exit 1; }

if [ -z "$("$ADB" devices | sed '1d' | grep -w device || true)" ]; then
  cat <<MSG
No authorised device found.

  1. On the phone: Settings > About phone > tap "Build number" 7 times
  2. Settings > System > Developer options > enable "USB debugging"
  3. Connect by USB and accept the "Allow USB debugging?" prompt

Then re-run this script.  Current adb state:
MSG
  "$ADB" devices -l
  exit 1
fi

echo "==> Installing"
"$ADB" install -r "$APK"
echo "==> Launching"
"$ADB" shell monkey -p com.haman.sleep -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1
echo
echo "Streaming logs (Ctrl-C to stop):"
"$ADB" logcat -c
"$ADB" logcat MonitoringService:V AudioCapture:V YamnetClassifier:V AndroidRuntime:E '*:S'
