#!/usr/bin/env bash
set -euo pipefail

BASE_REF="${BASE_REF:-master}"
LOWER_BOUND=820
UPPER_BOUND=900

failures=0

pass() {
  printf '[PASS] %s\n' "$1"
}

fail() {
  printf '[FAIL] %s\n' "$1"
  failures=$((failures + 1))
}

if ! git rev-parse --verify --quiet "$BASE_REF" >/dev/null; then
  fail "Regression A: base ref '$BASE_REF' is not available"
  exit 1
fi

numstat="$(git diff --numstat "$BASE_REF" -- skills/accept/SKILL.md skills/recover/SKILL.md)"
if [[ -z "$numstat" ]]; then
  pass "Regression A: accept/recover skills have no diff against $BASE_REF"
else
  fail "Regression A: accept/recover skills changed against $BASE_REF"
  printf '%s\n' "$numstat"
fi

diff_output="$(git diff "$BASE_REF" -- skills/agile/SKILL.md)"
if [[ -z "$diff_output" ]]; then
  pass "Regression B: agile skill has no hunks against $BASE_REF"
else
  hunk_count=0
  bad_hunks=()

  while IFS= read -r line; do
    [[ "$line" == @@* ]] || continue
    hunk_count=$((hunk_count + 1))

    if [[ "$line" =~ ^@@[[:space:]]-([0-9]+)(,([0-9]+))?[[:space:]]\+([0-9]+)(,([0-9]+))?[[:space:]]@@ ]]; then
      old_start="${BASH_REMATCH[1]}"
      old_count="${BASH_REMATCH[3]:-1}"
      new_start="${BASH_REMATCH[4]}"
      new_count="${BASH_REMATCH[6]:-1}"

      old_end=$((old_start + old_count - 1))
      new_end=$((new_start + new_count - 1))

      if (( old_count == 0 )); then
        old_end="$old_start"
      fi
      if (( new_count == 0 )); then
        new_end="$new_start"
      fi

      if (( old_start < LOWER_BOUND || old_end > UPPER_BOUND || new_start < LOWER_BOUND || new_end > UPPER_BOUND )); then
        bad_hunks+=("$line (old ${old_start}-${old_end}, new ${new_start}-${new_end})")
      fi
    else
      bad_hunks+=("$line (unparseable hunk header)")
    fi
  done <<< "$diff_output"

  if (( hunk_count == 0 )); then
    pass "Regression B: agile skill has no hunk headers against $BASE_REF"
  elif (( ${#bad_hunks[@]} == 0 )); then
    pass "Regression B: all $hunk_count agile hunk range(s) are within lines ${LOWER_BOUND}-${UPPER_BOUND}"
  else
    fail "Regression B: agile hunk range outside lines ${LOWER_BOUND}-${UPPER_BOUND}"
    printf '  %s\n' "${bad_hunks[@]}"
  fi
fi

if (( failures > 0 )); then
  exit 1
fi
