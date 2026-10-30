# Update Claude Code on the VM

Read this file when its row in SKILL.md applies. `vmssh`, `vmcp`, `SKILL_DIR`, the rules and the numbered Steps (1 to 6) are defined in SKILL.md. Section numbers refer to [`docs/claude-code-vm-setup-spec.md`](../../../docs/claude-code-vm-setup-spec.md).

## Update Claude Code: restart the servers onto the new version

The nightly updater (the systemd timer in guide section 5.3) replaces the file on disk only. Each
Remote Control server keeps the version it started with until it restarts. So "the update is held"
usually means nobody restarted the servers. The fix is a gated restart of each unit on the SAME
login, on the owner's go. Skip Steps 1-3 of SKILL.md.

**What counts as the owner's go here.** A request to update Claude Code on the VM is **not** a go to
restart. A same-login restart stops each session's process and its background jobs (guide section
10.3), and the turn check in step 5 cannot see background jobs. So before you ask for a go, list what
the restart will stop on each unit (step 3), for every unit on the box, not only your own. The
owner's go must name the units, for example "go: restart claude-remote-control-1 and
claude-remote-control-2". Restart only the units it names; a go that names none covers none. Pushing
work (step 0) still needs its own go. Record the owner's exact words in your ops notes, not "owner's
go", so the record shows which units were approved.

**Restart from an admin SSH shell, not from a session on that account.** A session cannot safely
restart the unit it runs under: on the VM, the turn check always finds the calling session
mid-turn. Make one cheap call first (`vmssh true`). If your tunnel reports a sign-in error, ask the
owner to renew it in a terminal. They finish any browser step or prompt themselves; an agent never
types a password. Check the session inventory (Step 4 of SKILL.md) for a VM session already doing this update.
A restart of the unit it runs under cuts its turn: wait until it ends its turn (the step 5 check).
If the wait runs long, ask the owner again before the restart.

0. **Get the work online first.** Before you install (step 2) or restart anything, make sure every
   account's unpushed work is pushed (guide section 10.4, step 1). The
   [`machine-move`](../../machine-move/SKILL.md) skill in SYNC mode does it, but it works on ONE
   Linux account at a time, not on the whole box (each account has its own home, repositories and Git
   login, guide section 9.2). Run it once per account, as that account: from the admin shell, every
   command of the skill goes through `sudo -n -iu claude-N`. Start each account with its dry run
   (its Step 1, read-only) and show the owner what it would push and wip-commit. Run it for real
   only on the owner's go: it pushes branches that are ahead and wip-commits idle dirty worktrees. A
   live session's uncommitted edits stay on disk only. If any account still has work that is not on
   origin, stop and report it; do not install or restart.
1. **Measure.** Run `vm-status.sh`: it prints `binary=OLD-VERSION` for each unit whose running server
   is older than the file on disk. The skill does not ship it. It is the script in guide section
   10.1. Save it from the guide to a local file named `vm-status.sh`. Make the private `vm-ops`
   folder in the admin's home if it is not there yet (`vmssh 'mkdir -p -m 700 vm-ops'`, as in Step 4
   of SKILL.md), copy the file with `vmcp vm-status.sh`, and run `vmssh 'bash vm-ops/vm-status.sh'`.
   It needs passwordless sudo, or `binary` reads `unknown`.
   Get the installed version (`vmssh '/usr/bin/claude --version'`) and the latest one (npm install:
   `vmssh 'npm view @anthropic-ai/claude-code version'`; apt install:
   `vmssh 'apt-cache policy claude-code'`). Check every account for a **shadow copy**:
   `vmssh "sudo -n -iu <account> bash -lc 'command -v claude'"` should print the system path. A
   `~/.local/bin/claude` comes from a non-sudo `npm i -g` with a per-account npm prefix, and the
   nightly timer never updates it.
2. **Install the newest version first** (on approval), so the restarts land on it:
   `vmssh 'sudo -n systemctl start claude-code-update.service && /usr/bin/claude --version'`. Stop if
   the updater fails, and check that the installed version now equals the latest from step 1. If it
   does not, the restarts would land on the old version while the drift check reads current.
3. **List what each restart will stop, then ask for the go.** Run the session inventory (Step 4 of
   SKILL.md). It covers every account at once; keep its output in the private folder that step
   makes. For each unit that would restart, the unit your own session runs under included, work out
   what the restart stops. `tree_procs` is a session's process plus every child it started
   (background shells, test runs, dev servers), and `tree_rss_mb` is their memory. Summarise the file
   per account:
   ```bash
   python3 - "$OUT_DIR/sessions.jsonl" <<'PY'
   import collections, json, sys
   by = collections.defaultdict(list)
   for line in open(sys.argv[1]):
       row = json.loads(line)
       by[row["user"]].append(row)
   for user, rows in sorted(by.items()):
       print(user, "sessions", len(rows), "procs", sum(r["tree_procs"] for r in rows),
             "rss_mb", sum(r["tree_rss_mb"] for r in rows))
       for r in rows:
           if r["tree_procs"] > 1:
               print("  children:", r["tree_procs"] - 1, "rss_mb", r["tree_rss_mb"],
                     "title", r.get("title"), "cwd", r.get("cwd"))
   PY
   ```
   Give the owner, per unit: the session count, the process total and the memory total, and each
   session that has children, by title and `cwd`: the restart kills those children, and the turn
   check will not warn you. Flag the sessions waiting on the owner's "go". A same-login restart keeps
   their threads, and each comes back when it is messaged, but its processes do not. The inventory
   lists every session of an account, including a terminal session in tmux or one started by cron,
   which run outside the unit and do not stop. `vmssh 'cat /proc/<pid>/cgroup'` shows a session's
   unit. If you do not check, say the list is an upper bound. Then ask for the go: one numbered
   decision per unit, each with a recommendation, and a "go" line that names the units. Restart
   nothing on a reply that names none.
4. **Record the baseline** for every unit with the snippet in guide section 9.3 (step 2): `MainPID`,
   `NRestarts` and the inner server PID. For each `OLD-VERSION` unit, check that the saved login is
   the expected account: `vmssh 'sudo -n -iu <account> claude auth status --text'`.
5. **Restart one unit at a time, only the units the go names, idle accounts first.** Right before
   each one, check the turn state of the account's main transcripts with `scripts/turn_check.py`, not
   the file times. Copy it to the private `vm-ops` folder as in Step 4 of SKILL.md (stop if the copy
   fails; always pass `-I`):
   ```bash
   vmcp "${SKILL_DIR}/scripts/turn_check.py"
   vmssh "sudo -n python3 -I vm-ops/turn_check.py <account>"
   ```
   It prints one line for the account: `IDLE`, `BUSY` or `UNKNOWN`. A `BUSY` account also gets one
   line per mid-turn session (session id, project folder, and the type and `stop_reason` of its last
   entry; never transcript text). `UNKNOWN` means it could not tell, and `detail=` says why (a missing
   or unreadable folder, a half-written line, a `/proc` read that did not finish, no such account).
   Treat `UNKNOWN` like `BUSY`; a half-written line is often a write in progress, so you may run it
   once more. Only `IDLE`, exit code 0, allows the restart. The exit code is 0 for all `IDLE`, 1 if
   any account is `BUSY`, 3 if any is `UNKNOWN`, 2 for a usage error. What it checks:
   - The last `user` or `assistant` entry of a transcript must be an `assistant` entry with
     `stop_reason` `end_turn` or `stop_sequence`. Anything else is a turn in progress.
   - It does not judge by age alone. A turn waiting on a long build or test writes nothing for a
     long time. It checks every main transcript written in the last 20 minutes (`--window-min`
     changes this; do not lower it), plus any older one whose session id a live process of that
     account still references (in `/proc/<pid>/cmdline`, or an open `/proc/<pid>/fd` path such as
     `/tmp/claude-<uid>/<project>/<session id>/`). An old unfinished transcript with no live process
     is a dead session and is skipped. If `/proc` cannot be read fully (a permission error, not a
     process that just exited), the account is `UNKNOWN`.
   - It skips subagent transcripts (`agent-*.jsonl`, anything under `subagents/`, `isSidechain`
     entries). They rarely end on `end_turn`, and a parent waiting on a subagent already ends on
     `tool_use`. Counting them flags idle files as busy.
   - It fails closed: an unreadable folder, a missing projects folder or a half-written line is
     `UNKNOWN`, never `IDLE`.
   - It does not use "written in the last 3 minutes": that false-alarms on an account whose daemon
     re-spawns idle sessions (each re-spawn writes a `system` entry).

   A unit with a session mid-turn waits: a restart cuts a running turn. Order per unit: run
   `vm-status.sh` again and confirm the unit is still `OLD-VERSION`, read the saved login, re-run the
   inventory (Step 4 of SKILL.md) and compare this unit's sessions with the list the owner saw (a new
   session, or a new child process, means ask again and name what changed), then run the turn check
   LAST. Put the check and the restart in ONE command, so the restart runs only if the check exits 0:
   ```bash
   vmssh "sudo -n python3 -I vm-ops/turn_check.py <account> && sudo -n systemctl restart <unit>"
   ```
   Stop at the first failure. A turn can still start in the seconds between the check and the
   restart; such a turn stops and needs one message to continue.
6. **Verify.** `vm-status.sh` (step 1) shows `binary=current` for every unit, each unit kept its environment
   ID (`bridge-pointer.json`, guide section 6 Step 10), and the other units' `MainPID`, `NRestarts`
   and inner PID did not change. Each unit shows `Capacity: 0/<N>` until a session is messaged; that
   is normal after a restart.
7. **Remove shadow copies** (on approval). First check that no process runs the copy
   (`readlink /proc/<pid>/exe`) and that no cron, settings file or unit names it by path. Then, as
   that user, `npm uninstall -g @anthropic-ai/claude-code`. If it fails `ENOTEMPTY`, a stale
   `.claude-code-<random>` staging folder sits beside it: check no process uses it, remove it, and
   run the uninstall again. Install Claude Code only with `sudo -n npm install -g` (or the apt
   package). **The copies come back** while processes still run an old binary: Claude Code's in-app
   auto-updater sees a newer version and runs `npm install --global`, which the per-account prefix
   sends to `~/.local`. The root fix is to turn the in-app CLI updater off, because the nightly
   timer already updates the system copy. **Never set `DISABLE_AUTOUPDATER=1` alone:** it also turns
   off background plugin updates (`DISABLE_UPDATES` and `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC`
   do the same), so the accounts stop getting plugin fixes. Set both in each account's
   `~/.claude/settings.json` `env`: `"DISABLE_AUTOUPDATER": "1"` and `"FORCE_AUTOUPDATE_PLUGINS":
   "1"` (guide section 8). Then check `claude doctor` shows auto-updates disabled by env and that a
   plugin update still lands. A non-official marketplace updates only when its own auto-update is
   on. It is a settings change: get the owner's approval.
8. **Record** the versions, the order, the units the owner named, and anything skipped in your ops
   notes. Then delete the private folder that holds the session inventory (`rm -r "$OUT_DIR"`).

