#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  ./scripts/check-ai-context.sh [project-dir]

Checks:
  - required docs/ai_context files exist
  - context files are not too large
  - DECISIONS.jsonl and optional/FINDINGS.jsonl are valid JSONL
  - tracked files do not look like obvious secret/runtime files
  - tracked text files do not contain obvious secret markers

This script prints paths and line numbers only. It does not print secret values.
USAGE
}

target="."

for arg in "$@"; do
  case "$arg" in
    -h|--help)
      usage
      exit 0
      ;;
    *)
      target="$arg"
      ;;
  esac
done

project_dir="$(cd -- "$target" && pwd)"
context_dir="$project_dir/docs/ai_context"
status="ok"

warn() {
  printf 'WARN: %s\n' "$1"
  status="warn"
}

fail() {
  printf 'FAIL: %s\n' "$1"
  status="fail"
}

check_exists() {
  local rel="$1"
  if [[ ! -f "$project_dir/$rel" ]]; then
    fail "missing $rel"
  fi
}

check_size() {
  local rel="$1"
  local limit="$2"

  [[ -f "$project_dir/$rel" ]] || return 0

  local lines
  lines="$(wc -l < "$project_dir/$rel" | tr -d ' ')"
  if (( lines > limit )); then
    warn "$rel has $lines lines, suggested limit is $limit"
  fi
}

check_jsonl() {
  local rel="$1"

  [[ -f "$project_dir/$rel" ]] || return 0

  python3 - "$project_dir/$rel" "$rel" <<'PY'
import json
import sys

path, rel = sys.argv[1], sys.argv[2]
ok = True

with open(path, "r", encoding="utf-8") as fh:
    for line_no, line in enumerate(fh, 1):
        if not line.strip():
            continue
        try:
            json.loads(line)
        except json.JSONDecodeError as exc:
            print(f"FAIL: invalid JSONL in {rel}:{line_no}: {exc.msg}")
            ok = False

sys.exit(0 if ok else 1)
PY
}

printf '# ai-context check: %s\n\n' "$project_dir"

check_exists "AGENTS.md"
check_exists "docs/ai_context/PROJECT_MAP.md"
check_exists "docs/ai_context/DANGER_ZONES.md"
check_exists "docs/ai_context/VERIFICATION.md"

if [[ ! -d "$context_dir" ]]; then
  fail "missing docs/ai_context directory"
else
  check_size "docs/ai_context/PROJECT_MAP.md" 120
  check_size "docs/ai_context/DANGER_ZONES.md" 80
  check_size "docs/ai_context/VERIFICATION.md" 120
  check_size "docs/ai_context/CURRENT_GOAL.md" 80
  check_size "docs/ai_context/SESSION_SUMMARY.md" 150
  check_size "docs/ai_context/CONTEXT_HYGIENE.md" 120
fi

if ! check_jsonl "docs/ai_context/DECISIONS.jsonl"; then
  status="fail"
fi

if ! check_jsonl "docs/ai_context/optional/FINDINGS.jsonl"; then
  status="fail"
fi

if git -C "$project_dir" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  tracked_files="$(git -C "$project_dir" ls-files)"

  risky_path_re='(^|/)\.env($|\.(local|prod|production|staging|dev|development|test|secret|secrets)$)|\.pem$|\.p12$|\.sqlite$|\.db$|\.log$|(^|/)(logs|uploads|sessions|backups)/'

  if printf '%s\n' "$tracked_files" | grep -Eq "$risky_path_re"; then
    printf '%s\n' "$tracked_files" \
      | grep -E "$risky_path_re" \
      | while IFS= read -r rel; do
          warn "tracked sensitive/runtime-looking file: $rel"
        done
  fi

  secret_re='(sk-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9_]{20,}|xox[baprs]-[A-Za-z0-9-]{20,}|[0-9]{8,10}:[A-Za-z0-9_-]{35,}|BEGIN (RSA |OPENSSH |EC |DSA )?PRIVATE KEY|BOT_TOKEN[[:space:]]*=[[:space:]]*["'\'']?[0-9]{8,10}:[A-Za-z0-9_-]{20,}|API_KEY[[:space:]]*=[[:space:]]*["'\'']?[A-Za-z0-9_-]{24,})'

  while IFS= read -r rel; do
    case "$rel" in
      .env|.env.*|*.db|*.sqlite|*.log|*.pem|*.key|*.p12|*.png|*.jpg|*.jpeg|*.gif|*.pdf|*.zip)
        continue
        ;;
    esac

    file="$project_dir/$rel"
    [[ -f "$file" ]] || continue

    if grep -Iq . "$file" && grep -Ev 'SECRETS_OK_PLACEHOLDER' "$file" | grep -Eq "$secret_re"; then
      warn "possible secret marker in tracked text file: $rel"
    fi
  done <<< "$tracked_files"
else
  warn "target is not a git work tree; skipped tracked-file checks"
fi

printf '\nResult: %s\n' "$status"

if [[ "$status" == "fail" ]]; then
  exit 1
fi
