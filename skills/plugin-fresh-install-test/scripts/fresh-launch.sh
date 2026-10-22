#!/usr/bin/env bash
# Launch an INTERACTIVE Claude Code session with a brand-new config dir, to see what a
# teammate on a fresh machine gets from a plugin.
#
# Optional containment: --stub <cmd> (repeatable) puts a logging stub for <cmd> first on PATH.
# The stub appends its arguments to <out>/stub-<cmd>.log and exits 0, so a guard test that
# slips through runs nothing real. With no --stub, nothing is stubbed.
#
# Usage: fresh-launch.sh <repo-dir> [--out <dir>] [--no-synced <plugin>] [--stub <cmd>]...
#   --out        where to keep the config dir + stub logs (default: a new mktemp dir)
#   --no-synced  seed settings with {"enabledPlugins":{"<plugin>@synced":false}} BEFORE the
#                first launch, so a plugin turned on for your own claude.ai account cannot
#                mask the route you are testing (for example the repo's .claude/settings.json)
#   --stub       command to replace with a logging no-op (for example: gcloud, kubectl, terraform)
set -u
REPO="" OUT="" NOSYNC="" STUBS=""
while [ $# -gt 0 ]; do
  case "$1" in
    --out) OUT="$2"; shift 2 ;;
    --no-synced) NOSYNC="$2"; shift 2 ;;
    --stub) STUBS="$STUBS $2"; shift 2 ;;
    -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
    *) REPO="$1"; shift ;;
  esac
done
[ -n "$REPO" ] && [ -d "$REPO" ] || { echo "usage: fresh-launch.sh <repo-dir> [--out <dir>] [--no-synced <plugin>] [--stub <cmd>]..." >&2; exit 2; }
[ -n "$OUT" ] || OUT=$(mktemp -d "${TMPDIR:-/tmp}/fresh-install.XXXXXX")
[ -e "$OUT/config" ] && { echo "refusing: $OUT/config already exists (use a new --out)" >&2; exit 2; }
mkdir -p "$OUT/config" "$OUT/stubbin"
if [ -n "$NOSYNC" ]; then
  printf '{"enabledPlugins":{"%s@synced":false}}\n' "$NOSYNC" > "$OUT/config/settings.json"
fi
for cmd in $STUBS; do
  case "$cmd" in */*|"") echo "refusing: --stub takes a bare command name, got '$cmd'" >&2; exit 2 ;; esac
  : > "$OUT/stub-$cmd.log"
  cat > "$OUT/stubbin/$cmd" <<STUB
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "$OUT/stub-$cmd.log"
exit 0
STUB
  chmod +x "$OUT/stubbin/$cmd"
done
if [ -n "$NOSYNC" ]; then echo "Fresh config: $OUT/config   (synced $NOSYNC: OFF)"
else echo "Fresh config: $OUT/config   (synced plugins: left on)"; fi
echo "Repo: $REPO"
[ -n "$STUBS" ] && echo "Stubbed commands (logged, never run):$STUBS"
echo "In the session: sign in, trust the folder, accept plugin/marketplace prompts, run the probe, /exit."
echo "Then: verify-transcript.sh $OUT   and   probe.sh $OUT <repo-dir> --plugin <name>   (second session)"
cd "$REPO" || exit 1
export CLAUDE_CONFIG_DIR="$OUT/config" PATH="$OUT/stubbin:$PATH"
# A stubbed gcloud must not read your real gcloud credentials either.
case " $STUBS " in *" gcloud "*) mkdir -p "$OUT/empty-gcloud-config"; export CLOUDSDK_CONFIG="$OUT/empty-gcloud-config" ;; esac
exec claude
