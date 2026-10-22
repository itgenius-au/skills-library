#!/usr/bin/env bash

set -u

usage() {
  printf 'Usage: discover-targets.sh [--root DIR] [--names]\n' >&2
}

json_escape() {
  LC_ALL=C tr '\001-\010\013\014\016-\037' '?' |
  awk '
    BEGIN { ORS = "" }
    {
      gsub(/\\/, "\\\\")
      gsub(/"/, "\\\"")
      gsub(/\t/, "\\t")
      gsub(/\r/, "\\r")
      if (NR > 1) {
        printf "\\n"
      }
      printf "%s", $0
    }
  '
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
      *Run:\ \`* | *Test:\ \`* | *Lint:\ \`* | *Typecheck:\ \`* | *Build:\ \`* | *Deploy:\ \`* | *Format:\ \`*)
        printf '%s\n' "$line"
        return 0
        ;;
    esac
  done < "$file"
  return 1
}

null_or_json_string() {
  value=$1
  if [ -z "$value" ]; then
    printf 'null'
  else
    escaped=$(printf '%s' "$value" | json_escape)
    printf '"%s"' "$escaped"
  fi
}

config_dir=${REPO_HEALTH_SWEEP_CONFIG_DIR:-$HOME/.claude}
config_file="$config_dir/repo-health-sweep.config.json"
root=
names_only=0

while [ "$#" -gt 0 ]; do
  case "$1" in
    --root)
      if [ "$#" -lt 2 ]; then
        usage
        exit 2
      fi
      root=$2
      shift 2
      ;;
    --names)
      names_only=1
      shift
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      usage
      exit 2
      ;;
  esac
done

if [ -z "$root" ]; then
  root=$(python3 - "$config_file" <<'PY'
import json
import sys

try:
    with open(sys.argv[1], encoding="utf-8") as config:
        value = json.load(config)["root"]
    if isinstance(value, str):
        print(value)
except (OSError, ValueError, KeyError, TypeError):
    pass
PY
)
fi

if [ -z "$root" ]; then
  printf 'discover-targets.sh: set "root" in the config file or pass --root (tried %s)\n' "$config_file" >&2
  exit 2
fi

if [ ! -d "$root" ]; then
  printf 'discover-targets.sh: root is not a directory: %s\n' "$root" >&2
  exit 2
fi

root=$(CDPATH='' cd -- "$root" && pwd)
items=

for repo_dir in "$root"/* "$root"/*/*; do
  [ -d "$repo_dir" ] || continue

  case "$repo_dir" in
    */node_modules | */node_modules/*) continue ;;
  esac

  [ -d "$repo_dir/.git" ] || [ -f "$repo_dir/.git" ] || continue

  claude_file="$repo_dir/.claude/CLAUDE.md"
  [ -f "$claude_file" ] || continue
  grep -Eq '^Health sweep: skip - .+' "$claude_file" && continue

  gate_line=$(find_gate_line "$claude_file")
  [ -n "$gate_line" ] || continue

  test_cmd=$(extract_cmd "$gate_line" "Test")
  lint_cmd=$(extract_cmd "$gate_line" "Lint")
  typecheck_cmd=$(extract_cmd "$gate_line" "Typecheck")

  if [ -z "$test_cmd" ] && [ -z "$lint_cmd" ] && [ -z "$typecheck_cmd" ]; then
    continue
  fi

  name=${repo_dir##*/}
  if [ "$names_only" -eq 1 ]; then
    item=$name
  else
    repo_json=$(printf '%s' "$name" | json_escape)
    path_json=$(printf '%s' "$repo_dir" | json_escape)
    test_json=$(null_or_json_string "$test_cmd")
    lint_json=$(null_or_json_string "$lint_cmd")
    typecheck_json=$(null_or_json_string "$typecheck_cmd")
    item=$(printf '{"repo":"%s","path":"%s","gates":{"test":%s,"lint":%s,"typecheck":%s}}' \
      "$repo_json" "$path_json" "$test_json" "$lint_json" "$typecheck_json")
  fi

  items=$(printf '%s\n%s\t%s' "$items" "$name" "$item")
done

sorted_items=$(printf '%s\n' "$items" | sed '/^$/d' | sort)

if [ "$names_only" -eq 1 ]; then
  if [ -n "$sorted_items" ]; then
    printf '%s\n' "$sorted_items" | while IFS="$(printf '\t')" read -r _ item; do
      [ -n "$item" ] || continue
      printf '%s\n' "$item"
    done
  fi
  exit 0
fi

printf '['
if [ -n "$sorted_items" ]; then
  first=1
  printf '%s\n' "$sorted_items" | while IFS="$(printf '\t')" read -r _ item; do
    [ -n "$item" ] || continue
    if [ "$first" -eq 1 ]; then
      first=0
    else
      printf ','
    fi
    printf '%s' "$item"
  done
fi
printf ']\n'
