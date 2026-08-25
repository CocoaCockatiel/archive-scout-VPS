#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

rm -rf build dist release
export MACOSX_DEPLOYMENT_TARGET="12.0"

python -m PyInstaller \
  --noconfirm --clean --windowed \
  --name "Archive Scout" \
  --icon assets/archivescout.icns \
  --add-data "assets/archivescout.png:assets" \
  --target-arch universal2 \
  --collect-all truststore --collect-all urllib3 --collect-all httpx --collect-all httpcore --collect-all dotenv \
  run_app.py

python -m PyInstaller \
  --noconfirm --clean --console --onefile \
  --name "ArchiveScoutCLI" \
  --target-arch universal2 \
  --collect-all truststore --collect-all urllib3 --collect-all httpx --collect-all httpcore --collect-all dotenv \
  run_cli.py

APP="dist/Archive Scout.app"
CLI="dist/ArchiveScoutCLI"
PACKAGE="release/ArchiveScout-macOS-Universal"
ZIP="release/ArchiveScout-macOS-Universal.zip"
TEMP_ROOT="${RUNNER_TEMP:-${TMPDIR:-/tmp}}"
VERIFY_ROOT="$(mktemp -d "$TEMP_ROOT/archive-scout-macos-verify.XXXXXX")"
EXTRACTED_APP="$VERIFY_ROOT/ArchiveScout-macOS-Universal/Archive Scout.app"
EXTRACTED_CLI="$VERIFY_ROOT/ArchiveScout-macOS-Universal/ArchiveScoutCLI"

cleanup() { rm -rf "$VERIFY_ROOT"; }
trap cleanup EXIT

python scripts/verify_macos_bundle.py "$APP"
codesign --force --deep --sign - "$APP"
codesign --force --sign - "$CLI"
codesign --verify --deep --strict --verbose=2 "$APP"
codesign --verify --strict --verbose=2 "$CLI"

STARTUP_LOG="$HOME/Library/Logs/Archive Scout/startup-error.log"
rm -f "$STARTUP_LOG"
ARCHIVE_SCOUT_STARTUP_PROBE=1 "$APP/Contents/MacOS/Archive Scout"
if [[ -s "$STARTUP_LOG" ]]; then
  cat "$STARTUP_LOG" >&2
  exit 1
fi
"$CLI" --help >/dev/null

mkdir -p "$PACKAGE"
rm -rf "$PACKAGE" "$ZIP" "$ZIP.sha256"
mkdir -p "$PACKAGE"
ditto "$APP" "$PACKAGE/Archive Scout.app"
cp "$CLI" "$PACKAGE/ArchiveScoutCLI"
cp README.md "$PACKAGE/README.md"

ditto -c -k --sequesterRsrc --keepParent "$PACKAGE" "$ZIP"
ditto -x -k "$ZIP" "$VERIFY_ROOT"
python scripts/verify_macos_bundle.py "$EXTRACTED_APP"
codesign --verify --deep --strict --verbose=2 "$EXTRACTED_APP"
codesign --verify --strict --verbose=2 "$EXTRACTED_CLI"
"$EXTRACTED_CLI" --help >/dev/null

(
  cd release
  shasum -a 256 ArchiveScout-macOS-Universal.zip > ArchiveScout-macOS-Universal.zip.sha256
)
trap - EXIT
rm -rf "$VERIFY_ROOT"
