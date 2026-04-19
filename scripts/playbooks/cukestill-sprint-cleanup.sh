#!/usr/bin/env bash
set -euo pipefail

repo="$HOME/mygit/cukestill"
agi="AGI-019"
sprints_arg=""
dry_run=false
json_output=false
force=false

deleted=()
planned_deletes=()
skipped=()
log_file=""

usage() {
  cat <<'EOF'
Usage: cukestill-sprint-cleanup.sh [options]

Safely deletes stale Gran Maestro sprint branches after verifying that each
branch tree matches the corresponding squash commit on master.

Options:
  --repo <path>      Target git repository (default: ~/mygit/cukestill)
  --agi <AGI-ID>    Agile ID (default: AGI-019)
  --sprints <range> Sprint range/list, e.g. 3-20 or 3,5,7. If omitted,
                    sprint numbers are detected from local branches.
  --dry-run         Report planned deletes without deleting branches.
  --json            Emit final summary as JSON.
  --force           Allow dirty primary worktree when switching back to master.
  --help            Show this help.
EOF
}

die() {
  local message="Error: $*"
  echo "$message" >&2
  if [[ -n "$log_file" ]]; then
    printf '%s\n' "$message" >> "$log_file"
  fi
  exit 1
}

log_info() {
  if [[ -n "$log_file" ]]; then
    printf '%s\n' "$*" | tee -a "$log_file" >&2
  else
    echo "$*" >&2
  fi
}

expand_path() {
  case "$1" in
    "~")
      printf '%s\n' "$HOME"
      ;;
    "~/"*)
      printf '%s/%s\n' "$HOME" "${1#~/}"
      ;;
    *)
      printf '%s\n' "$1"
      ;;
  esac
}

json_escape() {
  local value="$1"
  value=${value//\\/\\\\}
  value=${value//\"/\\\"}
  value=${value//$'\n'/\\n}
  value=${value//$'\r'/\\r}
  value=${value//$'\t'/\\t}
  printf '%s' "$value"
}

json_string_array() {
  local first=true
  local item
  printf '['
  for item in "$@"; do
    if [[ "$first" == true ]]; then
      first=false
    else
      printf ','
    fi
    printf '"%s"' "$(json_escape "$item")"
  done
  printf ']'
}

json_skipped_array() {
  local first=true
  local entry branch reason
  printf '['
  for entry in "$@"; do
    branch=${entry%%|*}
    reason=${entry#*|}
    if [[ "$first" == true ]]; then
      first=false
    else
      printf ','
    fi
    printf '{"branch":"%s","reason":"%s"}' "$(json_escape "$branch")" "$(json_escape "$reason")"
  done
  printf ']'
}

append_unique_number() {
  local candidate="$1"
  local existing
  if [[ "${#sprints[@]}" -gt 0 ]]; then
    for existing in "${sprints[@]}"; do
      if [[ "$existing" == "$candidate" ]]; then
        return 0
      fi
    done
  fi
  sprints+=("$candidate")
}

parse_sprints() {
  local input="$1"
  local token start end n
  IFS=',' read -r -a sprint_tokens <<< "$input"
  for token in "${sprint_tokens[@]}"; do
    if [[ "$token" =~ ^[0-9]+$ ]]; then
      append_unique_number "$token"
    elif [[ "$token" =~ ^([0-9]+)-([0-9]+)$ ]]; then
      start="${BASH_REMATCH[1]}"
      end="${BASH_REMATCH[2]}"
      if (( start > end )); then
        die "invalid sprint range: $token"
      fi
      for ((n = start; n <= end; n++)); do
        append_unique_number "$n"
      done
    else
      die "invalid --sprints value: $token"
    fi
  done
}

git_capture() {
  git -C "$repo" "$@"
}

branch_list() {
  local pattern="$1"
  git_capture branch --list "$pattern" --format='%(refname:short)'
}

collect_matching_branches() {
  local pattern="$1"
  local output line
  output=$(branch_list "$pattern")
  while IFS= read -r line; do
    if [[ -n "$line" ]]; then
      printf '%s\n' "$line"
    fi
  done <<< "$output"
}

find_squash_commit_for_sprint() {
  local sprint="$1"
  local grep_pattern
  grep_pattern="\\[$agi Sprint $sprint\\] squash-merged"
  git_capture log master --grep "$grep_pattern" -n 1 --format=%H
}

find_matching_squash_commit_for_branch_tree() {
  local branch="$1"
  local branch_tree commits commit commit_tree
  branch_tree=$(git_capture rev-parse "${branch}^{tree}")
  commits=$(git_capture log master --grep "\\[$agi Sprint [0-9][0-9]*\\] squash-merged" --format=%H)
  if [[ -z "$commits" ]]; then
    return 2
  fi
  while IFS= read -r commit; do
    if [[ -z "$commit" ]]; then
      continue
    fi
    commit_tree=$(git_capture rev-parse "${commit}^{tree}")
    if [[ "$branch_tree" == "$commit_tree" ]]; then
      printf '%s\n' "$commit"
      return 0
    fi
  done <<< "$commits"
  return 1
}

skip_branch() {
  local branch="$1"
  local reason="$2"
  skipped+=("$branch|$reason")
  log_info "skip: $branch ($reason)"
}

delete_or_plan_branch() {
  local branch="$1"
  local delete_output
  if [[ "$dry_run" == true ]]; then
    planned_deletes+=("$branch")
    log_info "dry-run: would delete $branch"
  else
    if delete_output=$(git_capture branch -D "$branch" 2>&1); then
      if [[ -n "$delete_output" ]]; then
        log_info "$delete_output"
      fi
    else
      die "git branch -D failed for $branch: $delete_output"
    fi
    deleted+=("$branch")
    log_info "deleted: $branch"
  fi
}

process_sprint_branch() {
  local sprint="$1"
  local branch="$2"
  local squash_commit branch_tree squash_tree
  squash_commit=$(find_squash_commit_for_sprint "$sprint")
  if [[ -z "$squash_commit" ]]; then
    die "missing squash commit for $branch ([${agi} Sprint ${sprint}] squash-merged)"
  fi

  branch_tree=$(git_capture rev-parse "${branch}^{tree}")
  squash_tree=$(git_capture rev-parse "${squash_commit}^{tree}")
  if [[ "$branch_tree" != "$squash_tree" ]]; then
    skip_branch "$branch" "tree_mismatch"
    return 0
  fi

  delete_or_plan_branch "$branch"
}

process_integration_branch() {
  local branch="$1"
  local matching_commit match_status
  if matching_commit=$(find_matching_squash_commit_for_branch_tree "$branch"); then
    if [[ -n "$matching_commit" ]]; then
      delete_or_plan_branch "$branch"
      return 0
    fi
  else
    match_status=$?
    if [[ "$match_status" -eq 2 ]]; then
      die "missing squash commits on master for $agi integration branch verification"
    fi
  fi
  skip_branch "$branch" "tree_mismatch"
}

detect_sprints() {
  local branches branch suffix sprint
  branches=$(branch_list "gran-maestro/${agi}/sprint-[0-9]*")
  while IFS= read -r branch; do
    if [[ -z "$branch" ]]; then
      continue
    fi
    suffix=${branch#gran-maestro/${agi}/sprint-}
    sprint=${suffix%%[^0-9]*}
    if [[ -n "$sprint" ]]; then
      append_unique_number "$sprint"
    fi
  done <<< "$branches"
}

collect_remaining() {
  local patterns=(
    "gran-maestro/${agi}/sprint-*"
    "gran-maestro-${agi}-sprint-integration/REQ-*"
    "${agi}/sprint-integration"
    "gran-maestro/${agi}/sprint-integration"
  )
  local pattern branches line
  remaining=()
  for pattern in "${patterns[@]}"; do
    branches=$(branch_list "$pattern")
    while IFS= read -r line; do
      if [[ -n "$line" ]]; then
        remaining+=("$line")
      fi
    done <<< "$branches"
  done
}

print_summary() {
  local summary deleted_json skipped_json planned_json remaining_json
  collect_remaining
  if [[ "$json_output" == true ]]; then
    if [[ "${#deleted[@]}" -gt 0 ]]; then
      deleted_json=$(json_string_array "${deleted[@]}")
    else
      deleted_json="[]"
    fi
    if [[ "${#skipped[@]}" -gt 0 ]]; then
      skipped_json=$(json_skipped_array "${skipped[@]}")
    else
      skipped_json="[]"
    fi
    if [[ "${#planned_deletes[@]}" -gt 0 ]]; then
      planned_json=$(json_string_array "${planned_deletes[@]}")
    else
      planned_json="[]"
    fi
    if [[ "${#remaining[@]}" -gt 0 ]]; then
      remaining_json=$(json_string_array "${remaining[@]}")
    else
      remaining_json="[]"
    fi
    summary=$(printf '{"repo":"%s","agi":"%s","deleted":%s,"skipped":%s,"planned_deletes":%s,"remaining":%s,"dry_run":%s}' \
      "$(json_escape "$repo")" \
      "$(json_escape "$agi")" \
      "$deleted_json" \
      "$skipped_json" \
      "$planned_json" \
      "$remaining_json" \
      "$dry_run")
    printf '%s\n' "$summary"
    if [[ -n "$log_file" ]]; then
      printf '%s\n' "$summary" >> "$log_file"
    fi
  else
    summary=$(printf 'Deleted: %d\nSkipped: %d\nRemaining sprint branches: %d\n' \
      "${#deleted[@]}" \
      "${#skipped[@]}" \
      "${#remaining[@]}")
    if [[ "${#planned_deletes[@]}" -gt 0 ]]; then
      summary+=$(printf 'Planned deletes: %d\n' "${#planned_deletes[@]}")
    fi
    printf '%s' "$summary"
    if [[ -n "$log_file" ]]; then
      printf '%s' "$summary" >> "$log_file"
    fi
  fi
}

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --repo)
      [[ "$#" -ge 2 ]] || die "--repo requires a value"
      repo=$(expand_path "$2")
      shift 2
      ;;
    --agi)
      [[ "$#" -ge 2 ]] || die "--agi requires a value"
      agi="$2"
      shift 2
      ;;
    --sprints)
      [[ "$#" -ge 2 ]] || die "--sprints requires a value"
      sprints_arg="$2"
      shift 2
      ;;
    --dry-run)
      dry_run=true
      shift
      ;;
    --json)
      json_output=true
      shift
      ;;
    --force)
      force=true
      shift
      ;;
    --help)
      usage
      exit 0
      ;;
    *)
      die "unknown option: $1"
      ;;
  esac
done

repo=$(expand_path "$repo")

git_capture rev-parse --git-dir >/dev/null

current_branch=$(git_capture rev-parse --abbrev-ref HEAD)
if [[ "$current_branch" != "master" ]]; then
  primary_status=$(git_capture status --porcelain)
  if [[ -n "$primary_status" && "$force" != true ]]; then
    die "uncommitted changes in primary worktree; commit/stash them or rerun with --force"
  fi
  git_capture checkout master >/dev/null
fi

log_dir="$repo/.gran-maestro/agile/$agi"
mkdir -p "$log_dir"
timestamp=$(date +%Y%m%dT%H%M%S)
log_file="$log_dir/cleanup-playbook-$timestamp.log"

log_info "repo: $repo"
log_info "agi: $agi"
log_info "dry_run: $dry_run"

sprints=()
if [[ -n "$sprints_arg" ]]; then
  parse_sprints "$sprints_arg"
else
  detect_sprints
fi

if [[ "${#sprints[@]}" -gt 0 ]]; then
  for sprint in "${sprints[@]}"; do
    sprint_branches=$(collect_matching_branches "gran-maestro/${agi}/sprint-${sprint}*")
    while IFS= read -r branch; do
      if [[ -n "$branch" ]]; then
        process_sprint_branch "$sprint" "$branch"
      fi
    done <<< "$sprint_branches"
  done
fi

integration_patterns=(
  "gran-maestro-${agi}-sprint-integration/REQ-*"
  "${agi}/sprint-integration"
  "gran-maestro/${agi}/sprint-integration"
)
for pattern in "${integration_patterns[@]}"; do
  integration_branches=$(collect_matching_branches "$pattern")
  while IFS= read -r branch; do
    if [[ -n "$branch" ]]; then
      process_integration_branch "$branch"
    fi
  done <<< "$integration_branches"
done

git_capture worktree prune
print_summary
