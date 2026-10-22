#!/usr/bin/env bash

set -u

usage() {
  printf 'Usage: run-gates.sh <repo-dir>\n' >&2
}

json_escape() {
  # Replace every control byte (0x00-0x1F) with a space so no raw control
  # character can reach the JSON (a cold npm/uv run emits ANSI and
  # carriage-return progress bytes), then escape backslash and quote. The tail
  # is a diagnostic field, so exact whitespace is not worth a JSON-validity risk.
  LC_ALL=C tr '\000-\037' ' ' | LC_ALL=C sed -e 's/\\/\\\\/g' -e 's/"/\\"/g'
}

extract_cmd() {
  line=$1
  label=$2
  printf '%s\n' "$line" | sed -n "s/.*$label:[[:space:]]*\`\\([^\`]*\\)\`.*/\\1/p"
}

find_gate_line() {
  file=$1
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
      *Test:\ \`* | *Lint:\ \`* | *Typecheck:\ \`*)
        printf '%s\n' "$line"
        return 0
        ;;
    esac
  done < "$file"
  return 1
}

emit_skip() {
  repo_json=$(printf '%s' "$repo_dir" | json_escape)
  printf '{"repo":"%s","gates":{},"overall":"skip"}\n' "$repo_json"
}

run_gate() {
  name=$1
  cmd=$2

  output=$(
    cd "$repo_dir" 2>&1 && bash -c "$cmd" 2>&1
  )
  code=$?
  tail_output=$(printf '%s\n' "$output" | tail -n 20)

  if [ "$code" -eq 0 ]; then
    status=pass
  else
    status=fail
  fi

  cmd_json=$(printf '%s' "$cmd" | json_escape)
  tail_json=$(printf '%s' "$tail_output" | json_escape)
  printf '"%s":{"cmd":"%s","status":"%s","code":%s,"tail":"%s"}' \
    "$name" "$cmd_json" "$status" "$code" "$tail_json"
}

if [ "$#" -ne 1 ]; then
  usage
  exit 2
fi

repo_dir=$1
claude_file="$repo_dir/.claude/CLAUDE.md"

if [ ! -f "$claude_file" ]; then
  emit_skip
  exit 0
fi

gate_line=$(find_gate_line "$claude_file")
if [ -z "$gate_line" ]; then
  emit_skip
  exit 0
fi

test_cmd=$(extract_cmd "$gate_line" "Test")
lint_cmd=$(extract_cmd "$gate_line" "Lint")
typecheck_cmd=$(extract_cmd "$gate_line" "Typecheck")

if [ -z "$test_cmd" ] && [ -z "$lint_cmd" ] && [ -z "$typecheck_cmd" ]; then
  emit_skip
  exit 0
fi

overall=pass
gates_json=

if [ -n "$test_cmd" ]; then
  gates_json=$(run_gate "test" "$test_cmd")
  case "$gates_json" in
    *'"status":"fail"'*) overall=fail ;;
  esac
fi

if [ -n "$lint_cmd" ]; then
  gate_json=$(run_gate "lint" "$lint_cmd")
  case "$gate_json" in
    *'"status":"fail"'*) overall=fail ;;
  esac
  if [ -n "$gates_json" ]; then
    gates_json="$gates_json,$gate_json"
  else
    gates_json=$gate_json
  fi
fi

if [ -n "$typecheck_cmd" ]; then
  gate_json=$(run_gate "typecheck" "$typecheck_cmd")
  case "$gate_json" in
    *'"status":"fail"'*) overall=fail ;;
  esac
  if [ -n "$gates_json" ]; then
    gates_json="$gates_json,$gate_json"
  else
    gates_json=$gate_json
  fi
fi

repo_json=$(printf '%s' "$repo_dir" | json_escape)
printf '{"repo":"%s","gates":{%s},"overall":"%s"}\n' "$repo_json" "$gates_json" "$overall"
