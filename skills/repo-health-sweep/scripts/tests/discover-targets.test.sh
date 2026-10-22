#!/usr/bin/env bash

set -u

TEST_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
SUBJECT="$TEST_DIR/../discover-targets.sh"

failures=0

fail() {
  name=$1
  message=$2
  printf 'FAIL %s\n' "$name"
  printf '  %s\n' "$message"
  failures=$((failures + 1))
}

pass() {
  printf 'PASS %s\n' "$1"
}

write_claude() {
  repo_dir=$1
  content=$2
  mkdir -p "$repo_dir/.claude"
  printf '%s\n' "$content" > "$repo_dir/.claude/CLAUDE.md"
}

make_fake_root() {
  root=$1

  mkdir -p "$root/python-app/.git"
  write_claude "$root/python-app" "Gates: Run: \`python app.py\` | Test: \`pytest\` | Lint: \`ruff check .\` | Build: \`python -m build\`"

  mkdir -p "$root/node-app"
  printf 'gitdir: ../.git/modules/node-app\n' > "$root/node-app/.git"
  write_claude "$root/node-app" "Gates: Typecheck: \`npm run typecheck\` | Lint: \`npm run lint\` | Test: \`npm test\` | Deploy: \`npm run deploy\`"

  mkdir -p "$root/paused-app/.git"
  write_claude "$root/paused-app" "Gates: Test: \`pytest\` | Lint: \`ruff check .\`"
  printf '%s\n' 'Health sweep: skip - legacy exclusion fixture' >> "$root/paused-app/.claude/CLAUDE.md"

  mkdir -p "$root/embed-plugin/.git"
  write_claude "$root/embed-plugin" "Gates: Test: \`npm test\` | Typecheck: \`npm run typecheck\`"
  printf '%s\n' 'Health sweep: skip - legacy exclusion fixture' >> "$root/embed-plugin/.claude/CLAUDE.md"

  mkdir -p "$root/marketing-site/.git"
  write_claude "$root/marketing-site" "Gates: Test: \`npm test\`"
  printf '%s\n' 'Health sweep: skip - legacy exclusion fixture' >> "$root/marketing-site/.claude/CLAUDE.md"

  mkdir -p "$root/helper-site/.git"
  write_claude "$root/helper-site" "Gates: Lint: \`npm run lint\`"
  printf '%s\n' 'Health sweep: skip - legacy exclusion fixture' >> "$root/helper-site/.claude/CLAUDE.md"

  mkdir -p "$root/docs-only/.git"
  write_claude "$root/docs-only" 'No declared automation gates here.'

  mkdir -p "$root/plain-dir-no-git"
  write_claude "$root/plain-dir-no-git" "Gates: Test: \`false\`"

  mkdir -p "$root/no-claude/.git"
}

assert_eq() {
  name=$1
  expected=$2
  actual=$3

  if [ "$actual" = "$expected" ]; then
    pass "$name"
  else
    fail "$name" "expected <$expected>, got <$actual>"
  fi
}

make_full_repo() {
  repo_dir=$1
  mkdir -p "$repo_dir/.git"
  write_claude "$repo_dir" "Gates: Test: \`true\` | Lint: \`true\` | Typecheck: \`true\`"
}

new_case() {
  case_name=$1
  CASE_ROOT=$(mktemp -d "$tmp_base/$case_name.root.XXXXXX")
  CASE_CONFIG=$(mktemp -d "$tmp_base/$case_name.config.XXXXXX")
}

assert_names() {
  name=$1
  expected=$2
  config_dir=$3
  shift 3

  actual=$(REPO_HEALTH_SWEEP_CONFIG_DIR="$config_dir" bash "$SUBJECT" "$@" --names 2>&1)
  code=$?
  if [ "$code" -ne 0 ]; then
    fail "$name" "expected exit 0, got $code: $actual"
  else
    assert_eq "$name" "$expected" "$actual"
  fi
}

assert_root_error() {
  name=$1
  config_dir=$2

  actual=$(REPO_HEALTH_SWEEP_CONFIG_DIR="$config_dir" bash "$SUBJECT" --names 2>&1)
  code=$?
  valid=1
  [ "$code" -eq 2 ] || valid=0
  case "$actual" in
    *'in the config file or pass --root'*) ;;
    *) valid=0 ;;
  esac
  case "$actual" in
    *"$config_dir/repo-health-sweep.config.json"*) ;;
    *) valid=0 ;;
  esac
  case "$actual" in
    *Traceback*) valid=0 ;;
  esac

  if [ "$valid" -eq 1 ]; then
    pass "$name"
  else
    fail "$name" "expected exit 2 with root guidance, config path, and no traceback; got exit $code: $actual"
  fi
}

write_config_root() {
  config_dir=$1
  root=$2
  printf '{"root":"%s"}\n' "$root" > "$config_dir/repo-health-sweep.config.json"
}

tmp_base=$(mktemp -d "${TMPDIR:-/tmp}/discover-targets-tests.XXXXXX")
tmp_base=$(CDPATH='' cd -- "$tmp_base" && pwd)
trap 'rm -rf "$tmp_base"' EXIT HUP INT TERM

new_case legacy
tmp_root=$CASE_ROOT
tmp_config=$CASE_CONFIG

make_fake_root "$tmp_root"

json_output=$(REPO_HEALTH_SWEEP_CONFIG_DIR="$tmp_config" bash "$SUBJECT" --root "$tmp_root" 2>&1)
json_code=$?

if [ "$json_code" -ne 0 ]; then
  fail "discovers sweepable repos as JSON" "expected exit 0, got $json_code: $json_output"
else
  expected_json='[{"repo":"node-app","path":"'"$tmp_root"'/node-app","gates":{"test":"npm test","lint":"npm run lint","typecheck":"npm run typecheck"}},{"repo":"python-app","path":"'"$tmp_root"'/python-app","gates":{"test":"pytest","lint":"ruff check .","typecheck":null}}]'
  assert_eq "discovers sweepable repos as JSON" "$expected_json" "$json_output"
fi

names_output=$(REPO_HEALTH_SWEEP_CONFIG_DIR="$tmp_config" bash "$SUBJECT" --root "$tmp_root" --names 2>&1)
names_code=$?

if [ "$names_code" -ne 0 ]; then
  fail "lists included names only" "expected exit 0, got $names_code: $names_output"
else
  expected_names='node-app
python-app'
  assert_eq "lists included names only" "$expected_names" "$names_output"
fi

new_case depth-2
case_root=$CASE_ROOT
case_config=$CASE_CONFIG
make_full_repo "$case_root/group/app"
assert_names "(a) finds a repo at depth 2" "app" "$case_config" --root "$case_root"

new_case pruned-paths
case_root=$CASE_ROOT
case_config=$CASE_CONFIG
make_full_repo "$case_root/node_modules/pkg"
make_full_repo "$case_root/.hidden-repo"
assert_names "(b) skips node_modules and hidden repos" "" "$case_config" --root "$case_root"

new_case worktree
case_root=$CASE_ROOT
case_config=$CASE_CONFIG
make_full_repo "$case_root/repo"
make_full_repo "$case_root/repo/.claude/worktrees/wt"
assert_names "(b2) skips a repo's nested worktree" "repo" "$case_config" --root "$case_root"

new_case opt-out
case_root=$CASE_ROOT
case_config=$CASE_CONFIG
make_full_repo "$case_root/skip-me"
printf '%s\n' 'Health sweep: skip - paused' >> "$case_root/skip-me/.claude/CLAUDE.md"
make_full_repo "$case_root/near-miss"
printf '%s\n' 'Health sweep: skipping is not allowed' >> "$case_root/near-miss/.claude/CLAUDE.md"
make_full_repo "$case_root/bulleted"
printf '%s\n' '- Health sweep: skip - paused' >> "$case_root/bulleted/.claude/CLAUDE.md"
expected_names='bulleted
near-miss'
assert_names "(c) honors only the exact column-0 opt-out" "$expected_names" "$case_config" --root "$case_root"

new_case missing-config
case_root=$CASE_ROOT
case_config=$CASE_CONFIG
assert_root_error "(d) missing config exits 2 without traceback" "$case_config"

invalid_config=$(mktemp -d "$tmp_base/invalid-json.config.XXXXXX")
printf '%s\n' '{not json' > "$invalid_config/repo-health-sweep.config.json"
assert_root_error "(d) invalid JSON exits 2 without traceback" "$invalid_config"

missing_key_config=$(mktemp -d "$tmp_base/missing-key.config.XXXXXX")
printf '%s\n' '{"other":1}' > "$missing_key_config/repo-health-sweep.config.json"
assert_root_error "(d) missing config key exits 2 without traceback" "$missing_key_config"

new_case configured-root
case_root=$CASE_ROOT
case_config=$CASE_CONFIG
make_full_repo "$case_root/config-app"
write_config_root "$case_config" "$case_root"
assert_names "(e) uses root from config" "config-app" "$case_config"

new_case depth-3
case_root=$CASE_ROOT
case_config=$CASE_CONFIG
make_full_repo "$case_root/group/team/deep-app"
assert_names "(f) does not find a repo at depth 3" "" "$case_config" --root "$case_root"

new_case root-self
case_root=$CASE_ROOT
case_config=$CASE_CONFIG
make_full_repo "$case_root"
assert_names "(g) does not treat the root as a candidate" "" "$case_config" --root "$case_root"

new_case no-opt-out
case_root=$CASE_ROOT
case_config=$CASE_CONFIG
make_full_repo "$case_root/paused-app"
assert_names "(h) includes a repo with no opt-out" "paused-app" "$case_config" --root "$case_root"

new_case precedence-a
root_a=$CASE_ROOT
config_a=$CASE_CONFIG
make_full_repo "$root_a/a-repo"
new_case precedence-b
root_b=$CASE_ROOT
config_b=$CASE_CONFIG
make_full_repo "$root_b/b-repo"
write_config_root "$config_b" "$root_b"
assert_names "(i) --root takes precedence over configured root" "a-repo" "$config_b" --root "$root_a"

printf '%s\n' '{not json' > "$config_a/repo-health-sweep.config.json"
assert_names "(i) valid --root ignores invalid config JSON" "a-repo" "$config_a" --root "$root_a"

if [ "$failures" -ne 0 ]; then
  printf '%s test case(s) failed\n' "$failures"
  exit 1
fi

printf 'All discover-targets tests passed\n'
