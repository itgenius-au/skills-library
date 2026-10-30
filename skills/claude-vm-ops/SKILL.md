---
name: claude-vm-ops
description: 'Operate and safely fix a Linux VM that runs Claude Code Remote Control servers, laid out as in docs/claude-code-vm-setup-spec.md (one systemd unit and one Linux user per Claude account). Covers a slow or hung VM, high load, a full disk, a lost or expiring Claude sign-in, and servers left on an old Claude Code version. Read-only until the owner approves a change. Use when the VM or one account is slow, the disk is full, Claude Code needs updating on the VM, or claude.ai says an account must sign in again. Triggers on: claude vm ops, vm triage, claude vm slow, vm not responding, vm hung, cpu maxed on the vm, high load on the claude vm, runaway processes on the vm, remote control sessions sluggish, clean up the vm, needs to sign in again, claude vm login expired, remote control sign in again, sign-in expiring, token expiry check, no space left on device, grow the vm disk, update claude on the vm, claude update held, restart remote control onto the new version.'
---

# Claude VM Ops

A Claude Code VM runs one or more Remote Control accounts. Each account is one systemd service,
`claude-remote-control-N.service`, under its own Linux user, with its own cgroup memory limits
(`MemoryHigh` soft throttle, `MemoryMax` hard cap, `OOMPolicy=continue`). When the box "runs out of
CPU", the cause is often **one account over its `MemoryHigh`**, not CPU work: the kernel keeps
evicting that account's program files, it re-reads them from disk, the disk runs at its limit,
and the CPUs sit in iowait. Box-wide memory can still look fine.

This skill assumes the layout in the guide
[`docs/claude-code-vm-setup-spec.md`](../../docs/claude-code-vm-setup-spec.md): Linux users
`claude-1`, `claude-2`, units `claude-remote-control-1`, `claude-remote-control-2`, server names
`VM-1`, `VM-2`, and a separate admin user with sudo. Section numbers below point into that guide.
If your names differ, change them in every command. Evidence labels follow the guide: **[docs]**,
**[ran]**, **[seen]**, **[not run]**.

## Rules

- **Measure before you act.** Never kill, stop, or change a limit on a guess.
- **Read-only until the owner says go.** The owner is the person responsible for the VM. Present
  findings and numbered decisions, each with a recommendation. Every kill, `claude stop`, and
  `set-property` needs an explicit approval.
- **Never stop or message a live session to "check on it".** Sessions can run with
  `bypassPermissions` or `auto` and nobody watching. A wake also delivers any message queued in the
  thread (guide section 11), and one of them may be a "yes" to a money or access action. Read the
  transcript instead (Step 4).
- **Never restart a Remote Control service** to fix slowness (guide section 10.4). A long outage
  releases its environment and orphans every attached session. The one exception is a deliberate,
  gated, same-login restart onto a new Claude Code version, on the owner's go that names the
  units (see `references/update.md`).
- **A negative result needs a positive control.** "0 matches" from a filter is not a finding until
  the same filter matches a known live process.

## Setup

Always connect as the admin user, then `sudo -iu <account>` if you need to act as an account. Never
connect as the account itself. Reach the VM through your private tunnel (guide section 3). Put a
`timeout` on every SSH call: a thrashing box can hang the session.

```bash
VM=<vm-host-name-or-ip>; ADMIN=<admin-user>
vmssh() { timeout 170 ssh "${ADMIN}@${VM}" "$*"; }
vmcp()  { scp -q "$@" "${ADMIN}@${VM}:vm-ops/"; }   # copy local files into vm-ops in the admin's home
```

Every later command uses only `vmssh` and `vmcp`, except the ones labelled as worked examples. If
your tunnel needs another command, change these two helpers and nothing else.

**Prerequisite: the admin user needs passwordless sudo** (guide sections 3 and 10.1). Most commands
below run `sudo -n`, which fails at once instead of waiting for a password. Check it before Step 1:

```bash
vmssh 'sudo -n true' && echo "sudo ok"
```

If it prints `sudo: a password is required` or any other error, stop. Do not type or guess a password,
and do not connect as an account to get around it. Only the Step 1 snapshot works without root. Tell
the owner that the admin user has no passwordless sudo and ask them to grant it, or to run the root
steps themselves. Carry on only when `sudo -n true` passes.

**Worked example only: Google Cloud with no public SSH, through IAP.** Replace the two helpers with:

```bash
PROJECT=<gcp-project>; ZONE=<zone>
vmssh() { timeout 170 gcloud compute ssh "${ADMIN}@${VM}" --project "$PROJECT" --zone "$ZONE" \
  --tunnel-through-iap --command "$*"; }
vmcp()  { gcloud compute scp "$@" "${ADMIN}@${VM}:vm-ops/" --project "$PROJECT" --zone "$ZONE" \
  --tunnel-through-iap; }
```

On Google Cloud, never run `gcloud compute ssh <account>@...`: without OS Login it gives that
account passwordless sudo (guide section 16).

On macOS there is no `timeout` (and often no `gtimeout`), so `vmssh` fails with "command not
found". Drop it from the helper and set the Bash tool's own timeout (about 170 s) on each call.

## Step 1: Snapshot the box

```bash
vmssh 'uptime; nproc; free -h; echo "D-state: $(ps -eo stat= | grep -c ^D)";
  cat /proc/pressure/cpu /proc/pressure/memory /proc/pressure/io | grep some; vmstat 5 3'
```

Read it:

| Signal | Means |
|---|---|
| Load far above vCPU count, many procs in `D`, `vmstat` `wa` high, `bi` near the disk max, `id` 0 | Disk thrash. Go to Step 2. |
| `us` high, `wa` near 0, many runnable (`r`), few `D` | Real CPU load. Go to Step 3. |
| Swap full, box `available` memory near 0 | Box-wide memory pressure: all accounts suffer. Steps 2 and 5. |

## Step 2: Find the throttled account

```bash
vmssh 'for c in /sys/fs/cgroup/system.slice/claude-remote-control*.service; do
  s=$(basename "$c"); h1=$(grep ^high "$c/memory.events" | cut -d" " -f2); sleep 15
  h2=$(grep ^high "$c/memory.events" | cut -d" " -f2)
  echo "$s mem=$(( $(cat "$c/memory.current")/1048576 ))MB high=$(( $(cat "$c/memory.high")/1048576 ))MB throttle_15s=$((h2-h1)) mem_psi=$(head -1 "$c/memory.pressure" | cut -d" " -f2) io_psi=$(head -1 "$c/io.pressure" | cut -d" " -f2)"
done'
```

An account whose throttle counter climbs by thousands in 15 s, with memory near its `high` and its
own pressure high while the others read 0, is the cause. A CPU cap will not fix it.

## Step 3: Look for rogue processes

Run each check and report what it finds, sized in MB and CPU:

```bash
vmssh 'echo "== orphaned codex sandboxes ==";
  ps -eo pid=,ppid=,user=,etimes=,pcpu=,rss=,args= | awk "\$(2)==1 && \$(7)==\"codex-linux-sandbox\"";
  echo "== user-account orphans (PPID 1) ==";
  ps -eo pid=,ppid=,uid=,user=,etime=,pcpu=,rss=,args= | awk "\$(2)==1 && \$(3)>=1000" |
    grep -v -E "systemd --user|bash -c while|daemon run|bg-pty-host|remote-control --name|sd-pam|dbus-daemon|codex-linux-sandbox" | cut -c1-200;
  echo "== big non-session processes (>800 MB) ==";
  ps -eo pid=,user=,etime=,pcpu=,rss=,comm=,args= | awk "\$(5)>819200 && \$(6) !~ /^claude/" | cut -c1-200;
  echo "== hung tests (>3 h, <1% CPU) ==";
  ps -eo pid=,ppid=,user=,etimes=,pcpu=,rss=,args= | awk "\$(4)>10800 && \$(5)<1 && /pytest|python -B -|python -c/" | cut -c1-200;
  echo "== dev servers listening ==";
  sudo -n ss -ltnp | grep -E "node|vite|npm|python" | grep -v 127.0.0.53'
```

Known leaks:
- **Orphaned `codex-linux-sandbox` trees** (PPID 1, 0% CPU) pile up while parallel Codex review runs
  (guide section 13). Their `comm` is `codex` and their `/proc/<pid>/cmdline` contains newlines:
  match on `args`, never on `comm` or on a `cut` of the cmdline.
- **Detached test harnesses** (a `pytest` with PPID 1 from a session scratch folder, no timeout).
- **Orphaned `vite preview` and other dev servers** left by a finished session.

Positive control before reporting "none": run the same filter without its age or CPU condition and
confirm it matches something live.

## Step 4: Inventory the sessions (read-only)

Copy `scripts/vm_sessions.py` into a private `vm-ops` folder in the admin's home on the VM, and run it
as root from there. Never run a root script from `/tmp` or `/var/tmp`: any account can create the
file name there first, the copy then fails, and root would run that account's file. **Stop if the
copy fails.** Always pass `-I`, so Python does not import a module from the script's folder or the
current folder.

The output holds session text: titles, first and last messages. Send it to a private folder on your
own machine, outside any repository, never to the current folder. `mktemp -d` makes the folder with
mode 700.

```bash
vmssh 'mkdir -p -m 700 vm-ops'
vmcp "${SKILL_DIR}/scripts/vm_sessions.py"
OUT_DIR=$(mktemp -d "${TMPDIR:-/tmp}/vm-sessions.XXXXXX"); echo "$OUT_DIR"
vmssh "sudo -n python3 -I vm-ops/vm_sessions.py" > "$OUT_DIR/sessions.jsonl"
```

Read `$OUT_DIR/sessions.jsonl` (if your shell forgets variables between commands, set `OUT_DIR` again
to the folder the first command printed). **Delete the folder when you are done** (`rm -r "$OUT_DIR"`).
Do not paste its text into a ticket, a commit or a chat. The script replaces token-like strings with
`[REDACTED]` (the same patterns as `scan_casualties.py`, so long path-like strings go too), but
whatever else a session said stays in the file. `python3 vm_sessions.py --help` prints usage and
does not run the inventory.

(`SKILL_DIR` is this skill's base directory, printed when the skill loads.) The script finds a
session process by its binary name, `claude.exe`, which is what the npm install in guide section 5.2
(Option B) produces. Check yours with `vmssh 'ps -eo pid,comm,args | grep "[c]laude"'`. If the
session processes carry another name, run it as `sudo -n env CLAUDE_SESSION_BIN=<name> python3 -I ...`.
The apt install (Option A) was not run when this skill was written. **[not run]**

It maps each session process to its transcript through the `/proc/<pid>/fd` links of the form
`/tmp/claude-<uid>/<project-slug>/<session-uuid>/`, then reads the title, first ask, last exchange,
idle time and tree size. Group by account. Flag sessions that are waiting on the owner's "go" so no
decision is lost. Do not use `claude agents --json` for this: it can delete registry files while it
lists (guide section 11).

## Step 5: Present decisions, then act only on approval

Offer numbered decisions, each with a recommendation, and a "go" line. Typical ones:

1. **Kill named rogue processes** (Step 3). List exact PIDs, owner, age, CPU and RSS.
2. **Give the throttled account headroom** (Step 2), live and reverting at reboot:
   ```bash
   vmssh 'sudo -n systemctl set-property --runtime claude-remote-control-N.service MemoryHigh=<new>G MemoryMax=<new>G'
   ```
   The sum of every account's `MemoryMax`, plus 3 GB for the system, must fit in RAM, unless you
   chose to overcommit on purpose (guide section 9.4). A busy review run fills any headroom it
   gets, so this buys time; limiting parallel reviews is the durable fix. Revert with the old
   values the same way.
3. **Stop idle sessions** only if the owner picks them from the Step 4 list. First check each
   session's worktree for uncommitted or unpushed work.
4. **Resize the VM** if Step 1 shows real CPU load after memory is fixed (guide section 10.8).
   Fetch the live price from your provider's pricing page; never quote remembered rates.

Kill safely:
- Kill by **exact PID**. Never `pgrep -f <pattern>` inside an SSH `--command` string: it also
  matches the remote shell running the command and kills your own SSH session.
- Re-check each PID's identity (PPID, first arg, age, CPU) immediately before the kill, and put
  that same guard on **every** kill path, including a final `kill -KILL` loop for survivors.
- `SIGTERM`, wait 5 s, then `SIGKILL` only the survivors that still pass the guard.

## Step 6: Verify and record

- Re-run Steps 1 and 2. Report before and after: load, `D` count, throttle events, memory and I/O
  pressure, available RAM, `vmstat` `wa`.
- Confirm no Remote Control service restarted, for each unit:
  `vmssh 'systemctl show claude-remote-control-1 -p MainPID -p NRestarts'`.
- Record the incident in your own ops notes: what happened, the evidence, what changed (especially
  any `--runtime` limit, which resets at reboot), and open follow-ups.

## Branches (read the file when its row applies)

Each branch is its own task with its own steps. Do not run Steps 1 to 5 above for it, except the ones
its file tells you to reuse. The rules above still apply.

| When | Read now |
|---|---|
| claude.ai says an account "needs to sign in again", sessions fail with "OAuth session expired", or you are asked when each sign-in expires or to re-login before a wipe | `references/signin.md` |
| Claude Code needs updating on the VM, "the update is stuck", or the servers run an old version | `references/update.md` |
| "No space left on device", `df -h /` reads 100%, or you are asked to grow the disk | `references/disk.md` |

## Other gotchas

- `curl https://api.anthropic.com` from a VM without working IPv6 tries IPv6 first and reads about
  100 ms slow. Time it with `curl -4`.
- `virtio_balloon ... Out of puff!` in `dmesg` during pressure is a symptom, not a cause.
- A "memory above N%" alert on the VM does not fire when the pressure is inside one account's
  cgroup. Alert on swap, load, or PSI instead (guide section 10.9).
- **A session cannot restart the unit it runs under.** The turn check always finds the calling
  session mid-turn. `cat /proc/self/cgroup` shows which unit a session runs under. That unit needs
  the same gated restart (`references/update.md`, step 5, on the owner's go that names the unit), run
  from a shell that does not run under it, for example an admin SSH shell.
- **The turn check does not see background jobs.** A restart after a session's `end_turn` still
  stops that session's process and background shells (guide section 10.3). So an update request is
  not a go to restart: `references/update.md` (step 3) lists what each restart stops, for every unit,
  and asks for a go that names the units.
- **A stalled session blocks the turn check.** A session that hit a usage limit, with a task
  notification it never handled, keeps a `user` entry last while its process lives. The check then
  counts that account as busy on every run. Report it to the owner as a Step 5 decision (message it
  after the limit resets, or close it). Do not message or stop it yourself.
- **`claude update` run as an account is untested here; treat it as a user-level install.** The CLI's
  own updater runs a user-level `npm install --global`, and an account's npm prefix can sit in its
  home folder (check: `vmssh 'sudo -n -iu <account> npm config get prefix'`). Such an install makes a shadow
  copy (`references/update.md`, step 1). Use the updater unit (step 2) instead.

## Files

- `scripts/vm_sessions.py`: read-only inventory of live sessions (Step 4). Run as root. The output
  holds session text: keep it private and delete it.
- `scripts/turn_check.py`: read-only turn check per account (`references/update.md`, step 5): `IDLE`,
  `BUSY` or `UNKNOWN`. Run as root. It fails closed and never prints transcript text.
- `scripts/token_status.py`: read-only sign-in health per account: `OK`, `DUE`, `EXPIRED`, `WIPED`,
  `UNKNOWN`. It never prints a token.
- `scripts/scan_casualties.py`: read-only list of sessions that stopped on the sign-in error.
- `scripts/tests/`: pytest tests for all four. They need no VM and no login:
  `python3 -m pytest scripts/tests`.
- `references/signin.md`: sign-in lost, and sign-in due soon.
- `references/update.md`: update Claude Code and restart the servers onto it.
- `references/disk.md`: disk full, cleanup and online grow.
