#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLUTTER_HOME="${FLUTTER_HOME:-$HOME/flutter}"
ANDROID_HOME="${ANDROID_HOME:-$HOME/Android/Sdk}"
SUDO=""
if [[ "$(id -u)" -ne 0 ]]; then SUDO="sudo"; fi

$SUDO apt-get update
$SUDO apt-get install -y curl git unzip xz-utils zip libglu1-mesa clang cmake ninja-build pkg-config libgtk-3-dev

if [[ ! -x "$FLUTTER_HOME/bin/flutter" ]]; then
  git clone --depth 1 --branch stable https://github.com/flutter/flutter.git "$FLUTTER_HOME"
fi
export PATH="$FLUTTER_HOME/bin:$PATH"
git config --global --add safe.directory "$FLUTTER_HOME"

if [[ ! -x "$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager" ]]; then
  archive="$(mktemp)"
  curl -fL "https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip" -o "$archive"
  mkdir -p "$ANDROID_HOME/cmdline-tools"
  temp_tools="$(mktemp -d)"
  unzip -q "$archive" -d "$temp_tools"
  mv "$temp_tools/cmdline-tools" "$ANDROID_HOME/cmdline-tools/latest"
  rm -rf "$archive" "$temp_tools"
fi
export ANDROID_HOME
export ANDROID_SDK_ROOT="$ANDROID_HOME"
export PATH="$ANDROID_HOME/cmdline-tools/latest/bin:$ANDROID_HOME/platform-tools:$PATH"
yes | sdkmanager --licenses >/dev/null || true
sdkmanager "platform-tools" "platforms;android-36" "build-tools;36.0.0"

cd "$ROOT"
# Generate/update the native Gradle wrapper while preserving lib/ and pubspec.yaml.
flutter create --platforms=android --org com.plsreloadtasker --project-name hbc_musik_client .
# ``flutter create`` generates its sample test again when it is absent. It
# references the template's MyApp class and must not be analyzed as part of HBC.
rm -f test/widget_test.dart
flutter config --no-analytics
flutter pub get
flutter analyze
flutter test
flutter build apk --release
printf '\nAPK: %s\n' "$ROOT/build/app/outputs/flutter-apk/app-release.apk"
