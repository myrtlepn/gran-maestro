#!/usr/bin/env bash

GM_SHA256_BACKEND="${GM_SHA256_BACKEND:-}"

gm_sha256_backend() {
  if [ -n "$GM_SHA256_BACKEND" ]; then
    printf '%s\n' "$GM_SHA256_BACKEND"
    return 0
  fi

  if command -v sha256sum >/dev/null 2>&1; then
    GM_SHA256_BACKEND="sha256sum"
  elif command -v shasum >/dev/null 2>&1; then
    GM_SHA256_BACKEND="shasum"
  elif command -v openssl >/dev/null 2>&1; then
    GM_SHA256_BACKEND="openssl"
  else
    GM_SHA256_BACKEND="python"
  fi

  printf '%s\n' "$GM_SHA256_BACKEND"
}

gm_sha256_text() {
  case "$(gm_sha256_backend)" in
    sha256sum)
      sha256sum | awk '{print $1}'
      ;;
    shasum)
      shasum -a 256 | awk '{print $1}'
      ;;
    openssl)
      openssl dgst -sha256 | awk '{print $NF}'
      ;;
    *)
      python3 -c 'import hashlib, sys; print(hashlib.sha256(sys.stdin.buffer.read()).hexdigest())'
      ;;
  esac
}

gm_sha256_file() {
  local path="$1"

  case "$(gm_sha256_backend)" in
    sha256sum)
      sha256sum "$path" | awk '{print $1}'
      return
      ;;
    shasum)
      shasum -a 256 "$path" | awk '{print $1}'
      return
      ;;
    openssl)
      openssl dgst -sha256 "$path" | awk '{print $NF}'
      return
      ;;
  esac

  python3 - "$path" <<'PY'
import hashlib
import sys
from pathlib import Path

print(hashlib.sha256(Path(sys.argv[1]).read_bytes()).hexdigest())
PY
}
