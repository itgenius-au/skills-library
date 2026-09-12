#!/usr/bin/env bash
# bq-timeout.sh - source this for run_with_timeout, a hard wall-clock cap around a bq call.
#
# Why: bq has no client-side timeout, so a bq call can wedge in a dead-socket read forever.
# The vault's scheduled jobs run under a NON-OVERLAPPING scheduler (macOS launchd
# StartInterval / Linux systemd timer / cron), so one hung run blocks every later run until a
# human kills it. Capping each bq call means a wedged call dies and the next scheduled run
# starts clean.
#
# run_with_timeout SECS CMD... - run CMD with a hard cap. Returns CMD's exit code, or 124 on
# timeout (matching coreutils timeout). Prefers coreutils timeout(1)/gtimeout(1) when present
# (Linux has it); else a portable bash fallback that kills the whole process SUBTREE - bq spawns
# nested python children, so killing only the top process orphans them still holding the socket.
#
# Sourced by the hooks, the heartbeat, and the sync scripts. tests/test_bq_timeout.sh guards it.

_kill_tree() {
  # Post-order: recurse into children FIRST (while the parent still lives and pgrep can see them),
  # kill the parent LAST. Killing the parent first reparents its children to launchd/init, after
  # which `pgrep -P <dead pid>` finds nothing and they survive holding the socket. Use the
  # for-word-list form, never `kids=$(pgrep ...)`: pgrep exits 1 at every leaf, which trips set -e
  # inside a sync script's command-substitution call site.
  local _pid="$1" _kid
  for _kid in $(pgrep -P "$_pid" 2>/dev/null || true); do
    _kill_tree "$_kid"
  done
  kill -KILL "$_pid" 2>/dev/null || true
}

_run_with_timeout_fallback() {
  local _secs="$1"; shift
  "$@" &
  local _pid=$! _waited=0 _rc=0
  # Synchronous poll, NOT a detached "sleep N; kill" watcher (which can fire on a reused PID).
  while kill -0 "$_pid" 2>/dev/null; do
    if [ "$_waited" -ge "$_secs" ]; then
      echo "run_with_timeout: '$1' exceeded ${_secs}s - killed" >&2
      _kill_tree "$_pid"
      wait "$_pid" 2>/dev/null || true
      return 124
    fi
    sleep 1
    _waited=$((_waited + 1))   # never ((_waited++)): returns 1 when _waited is 0 and trips set -e
  done
  wait "$_pid" || _rc=$?       # guard: a bare wait would abort under set -e before _rc is captured
  return "$_rc"
}

run_with_timeout() {
  local _secs="$1"; shift
  local _rc=0 _bin=""
  if command -v timeout >/dev/null 2>&1; then
    _bin=timeout
  elif command -v gtimeout >/dev/null 2>&1; then
    _bin=gtimeout
  fi
  if [ -n "$_bin" ]; then
    "$_bin" -k 5 "$_secs" "$@" || _rc=$?
    # Log on the coreutils path too (124 = timed out), so a wedge is visible in the log
    # whichever branch ran - not only the bash fallback below.
    if [ "$_rc" -eq 124 ]; then
      echo "run_with_timeout: '$1' exceeded ${_secs}s - killed" >&2
    fi
    return "$_rc"
  fi
  _run_with_timeout_fallback "$_secs" "$@"
}
