#!/usr/bin/env bash
# Build the installable release APK and place it at the repository root.
#
# Release build, not debug: it is not debuggable, so `adb run-as` cannot copy the
# sleep log and audio clips off a phone, and the debug-only raw-audio dump is disabled.
# Bump versionCode/versionName in android/app/build.gradle.kts before each release.
set -euo pipefail
MODULE="$(cd "$(dirname "$0")/.." && pwd)"
REPO="$(cd "$MODULE/.." && pwd)"
export JAVA_HOME="$(echo "$HOME"/Library/Java/JavaVirtualMachines/jdk-21*/Contents/Home)"
export PATH="$JAVA_HOME/bin:$PATH"

cd "$MODULE/android"
./gradlew :core-domain:test :app:assembleRelease

VERSION=$(grep -m1 'versionName' app/build.gradle.kts | sed -E 's/.*"(.*)".*/\1/')
OUT="$REPO/HamanCough-v$VERSION.apk"
rm -f "$REPO"/HamanCough-v*.apk          # keep exactly one APK at the root
cp app/build/outputs/apk/release/app-release.apk "$OUT"
echo
echo "APK:     $OUT"
echo "Size:    $(du -h "$OUT" | cut -f1)"
echo "SHA-256: $(shasum -a 256 "$OUT" | cut -d' ' -f1)"
echo "Update the version and checksum in INSTALL.md at the repository root."
