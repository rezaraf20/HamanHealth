#!/usr/bin/env bash
# Recreate the Android toolchain on a fresh macOS machine, without sudo.
#
# Homebrew is deliberately not used: installing it needs sudo, and everything here
# fits under $HOME. Android Studio goes to /Applications, which admin users can write
# to directly.
set -euo pipefail

JDK_DIR="$HOME/Library/Java/JavaVirtualMachines"
SDK="$HOME/Library/Android/sdk"
DL="$(mktemp -d)"
trap 'rm -rf "$DL"' EXIT

echo "==> JDKs (17 for the Gradle toolchain, 21 to run Gradle itself)"
mkdir -p "$JDK_DIR"
for v in 17 21; do
  if ! ls -d "$JDK_DIR"/jdk-"$v"* >/dev/null 2>&1; then
    echo "    downloading Temurin $v ..."
    curl -fsSL -o "$DL/jdk$v.tar.gz" \
      "https://api.adoptium.net/v3/binary/latest/$v/ga/mac/aarch64/jdk/hotspot/normal/eclipse"
    tar -xzf "$DL/jdk$v.tar.gz" -C "$JDK_DIR"
  else
    echo "    JDK $v already present"
  fi
done

echo "==> Android SDK command-line tools"
if [ ! -x "$SDK/cmdline-tools/latest/bin/sdkmanager" ]; then
  mkdir -p "$SDK/cmdline-tools"
  curl -fsSL -o "$DL/cmdline-tools.zip" \
    "https://dl.google.com/android/repository/commandlinetools-mac-13114758_latest.zip"
  unzip -q "$DL/cmdline-tools.zip" -d "$DL/cmdx"
  mv "$DL/cmdx/cmdline-tools" "$SDK/cmdline-tools/latest"
else
  echo "    already present"
fi

export JAVA_HOME="$(echo "$JDK_DIR"/jdk-21*/Contents/Home)"
export PATH="$JAVA_HOME/bin:$PATH"

echo "==> SDK packages (licenses, platform 37.2, build-tools, platform-tools)"
yes 2>/dev/null | "$SDK/cmdline-tools/latest/bin/sdkmanager" --sdk_root="$SDK" --licenses >/dev/null
"$SDK/cmdline-tools/latest/bin/sdkmanager" --sdk_root="$SDK" \
  "platform-tools" "platforms;android-37.2" "build-tools;37.0.0" >/dev/null
echo "    done"

echo "==> Writing android/local.properties and toolchain paths"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
echo "sdk.dir=$SDK" > "$ROOT/android/local.properties"
J17="$(echo "$JDK_DIR"/jdk-17*/Contents/Home)"
J21="$(echo "$JDK_DIR"/jdk-21*/Contents/Home)"
python3 - "$ROOT/android/gradle.properties" "$J17" "$J21" <<'PY'
import sys, pathlib
path, j17, j21 = pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3]
lines = [l for l in path.read_text().splitlines()
         if not l.startswith("org.gradle.java.installations.paths")]
lines.append(f"org.gradle.java.installations.paths={j17},{j21}")
path.write_text("\n".join(lines) + "\n")
PY

cat <<MSG

Toolchain ready.

  JDKs        $JDK_DIR
  Android SDK $SDK
  adb         $SDK/platform-tools/adb

Android Studio is optional (the build works entirely from the CLI). To install it:
  open https://developer.android.com/studio  and drag it to /Applications.

Next:  ./tools/build.sh        build the debug APK
       ./tools/install.sh      install it on a connected phone
MSG
