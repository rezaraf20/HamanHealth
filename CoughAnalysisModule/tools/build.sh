#!/usr/bin/env bash
# Build the debug APK and run the domain test suite.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export JAVA_HOME="$(echo "$HOME"/Library/Java/JavaVirtualMachines/jdk-21*/Contents/Home)"
export PATH="$JAVA_HOME/bin:$PATH"
cd "$ROOT/android"
./gradlew :core-domain:test :app:assembleDebug "$@"
echo
echo "APK: $ROOT/android/app/build/outputs/apk/debug/app-debug.apk"
ls -lh app/build/outputs/apk/debug/app-debug.apk | awk '{print "Size:", $5}'
