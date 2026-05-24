#!/usr/bin/env bash
# Check and notify version updates for gran-maestro.

set -u

CACHE_DIR="${HOME}/.claude/plugins/cache/gran-maestro/mst"
LAST_VERSION_FILE="${HOME}/.claude/mst-last-version"
LINE="━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

normalize_version() {
  printf "%s" "${1#v}"
}

find_versions() {
  if ! command -v python3 >/dev/null 2>&1; then
    # fallback: grep only
    find "$CACHE_DIR" -mindepth 1 -maxdepth 1 -type d -exec basename {} \; \
      | grep -E "^v?[0-9]+\.[0-9]+\.[0-9]+$" \
      | sed "s/^v//"
    return 0
  fi

  find "$CACHE_DIR" -mindepth 1 -maxdepth 1 -type d -exec basename {} \; \
    | python3 -c "import re,sys
for line in sys.stdin:
    s = line.strip()
    if re.fullmatch(r'v?[0-9]+\\.[0-9]+\\.[0-9]+', s):
      print(s[1:] if s.startswith('v') else s)"
}

if [ ! -d "$CACHE_DIR" ]; then
  exit 0
fi

LATEST_RAW=$(find_versions | sort -t. -k1,1n -k2,2n -k3,3n | tail -n 1 || true)
if [ -z "${LATEST_RAW:-}" ]; then
  exit 0
fi

if [ -d "$CACHE_DIR/$LATEST_RAW" ]; then
  CURRENT_DIR="$CACHE_DIR/$LATEST_RAW"
elif [ -d "$CACHE_DIR/v$LATEST_RAW" ]; then
  CURRENT_DIR="$CACHE_DIR/v$LATEST_RAW"
else
  exit 0
fi

CURRENT_VERSION="v$LATEST_RAW"
LAST_VERSION=""

if [ -f "$LAST_VERSION_FILE" ]; then
  LAST_VERSION="$(tr -d '[:space:]' < "$LAST_VERSION_FILE")"
fi

CURRENT_NORM="$(normalize_version "$CURRENT_VERSION")"
LAST_NORM="$(normalize_version "$LAST_VERSION")"

if [ "$LAST_NORM" = "$CURRENT_NORM" ]; then
  exit 0
fi

if [ -f "$CURRENT_DIR/CHANGELOG.md" ]; then
  CHANGELOG_SECTION="$(awk -v current="${CURRENT_NORM}" '
    $0 ~ ("^## \\[" current "\\]") { found=1; next }
    found && substr($0, 1, 3) == "## " { exit }
    found && NF { print }
  ' "$CURRENT_DIR/CHANGELOG.md" | head -n 10)"
else
  CHANGELOG_SECTION=""
fi

if [ -z "$LAST_VERSION" ]; then
  {
    printf "%s\n" "$LINE"
    printf "  Gran Maestro 업데이트: %s 설치됨\n" "$CURRENT_VERSION"
  } >&2
else
  DISPLAY_LAST="v$(normalize_version "$LAST_VERSION")"
  {
    printf "%s\n" "$LINE"
    printf "  Gran Maestro 업데이트: %s → %s\n\n" "$DISPLAY_LAST" "$CURRENT_VERSION"
    if [ -n "$CHANGELOG_SECTION" ]; then
      while IFS= read -r line; do
        printf "  %s\n" "$line"
      done <<< "$CHANGELOG_SECTION" >&2
    fi
  } >&2
fi

printf "%s\n" "$LINE" >&2
printf "%s\n" "$CURRENT_VERSION" > "$LAST_VERSION_FILE"
exit 0
