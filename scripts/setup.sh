#!/usr/bin/env bash
# One-time setup check for the Video-Edits system. Safe to re-run.
set -u
cd "$(dirname "$0")/.."

ok()   { printf '  \033[32m✓\033[0m %s\n' "$1"; }
bad()  { printf '  \033[31m✗\033[0m %s\n' "$1"; MISSING=1; }
MISSING=0

echo "1. Tools"
command -v ffmpeg  >/dev/null && ok "FFmpeg $(ffmpeg -version | head -1 | awk '{print $3}')" \
  || bad "FFmpeg missing — macOS: brew install ffmpeg | Windows: winget install Gyan.FFmpeg | Linux: sudo apt install ffmpeg"
command -v python3 >/dev/null && ok "Python $(python3 -c 'import sys;print(sys.version.split()[0])')" \
  || bad "Python 3 missing — https://www.python.org/downloads/"
if command -v node >/dev/null; then
  major=$(node -p 'process.versions.node.split(".")[0]')
  [ "$major" -ge 22 ] && ok "Node $(node -v)" || bad "Node $(node -v) is too old — HyperFrames needs 22+ (https://nodejs.org)"
else
  bad "Node.js missing — HyperFrames needs Node 22+ (https://nodejs.org)"
fi
command -v claude >/dev/null && ok "Claude Code CLI" || echo "  - Claude Code CLI not found (optional; needed for connectors in the terminal)"

echo "2. HyperFrames"
if command -v npx >/dev/null; then
  (cd motion && npx --yes hyperframes@0.8.163 lint >/dev/null 2>&1) && ok "motion/ project lints clean" \
    || echo "  - run 'cd motion && npx hyperframes lint' to see issues"
fi

echo "3. Connectors"
[ -f .env ] && . ./.env
[ -n "${EPIDEMIC_SOUND_API_KEY:-}" ] && ok "EPIDEMIC_SOUND_API_KEY is set" \
  || echo "  - EPIDEMIC_SOUND_API_KEY not set (copy .env.example to .env and paste your key)"
echo "  - Tella authenticates in the browser the first time Claude Code uses it (/mcp → tella → Authenticate)"

echo
[ "$MISSING" = 0 ] && echo "Ready. Next: README step 4." || echo "Install the items marked ✗, then re-run scripts/setup.sh."
exit "$MISSING"
