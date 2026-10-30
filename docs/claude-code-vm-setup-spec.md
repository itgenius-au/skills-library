# Claude Code on a VM: setup specification

This spec shows how to run Claude Code on an always-on Linux virtual machine and
drive it from your phone or a browser. It also shows how to run several Claude
accounts on one VM.

itGenius runs this setup every day. Our reference VM serves four Claude accounts.
The spec is provider-neutral: any Linux VM with systemd works. We built ours on
Google Cloud, so section 16 has the most detail for that provider.

This spec gives the layout we recommend for a new build. It is not an exact copy of the
reference VM: some values and safety choices differ.

**Last checked:** 2026-10-30, against Claude Code 2.1.314 on Ubuntu 24.04.

Claude Code changes fast. Before you rely on a command, check it against
`claude --help` and Anthropic's [Remote Control docs](https://code.claude.com/docs/en/remote-control).

**Evidence labels.** Claims that are not obvious carry one of these labels:

| Label | Meaning |
|---|---|
| **[docs]** | Anthropic's documentation says this. |
| **[ran]** | We ran this on the reference VM, and it worked. |
| **[seen]** | We observed this behavior. It is not documented, and it may change. |
| **[not run]** | We recommend this, but we have not run it. Test it first. |

## Contents

1. [What you get](#1-what-you-get)
2. [Architecture](#2-architecture)
3. [Decisions to make first](#3-decisions-to-make-first)
4. [VM specification](#4-vm-specification)
5. [Base OS setup](#5-base-os-setup)
6. [Set up one account](#6-set-up-one-account)
7. [The systemd unit](#7-the-systemd-unit)
8. [Account settings](#8-account-settings)
9. [Multiple accounts](#9-multiple-accounts)
10. [Daily operations](#10-daily-operations)
11. [Background sessions from scripts](#11-background-sessions-from-scripts)
12. [Security model](#12-security-model)
13. [Optional add-ons](#13-optional-add-ons)
14. [Troubleshooting](#14-troubleshooting)
15. [Definition of done](#15-definition-of-done)
16. [Provider notes](#16-provider-notes)

## 1. What you get

- Claude Code runs on the VM all the time. Work continues when your laptop is closed.
- You start, read and steer sessions from [claude.ai/code](https://claude.ai/code) or the
  Claude mobile app.
- systemd brings the server back after a crash, a network outage or a reboot.
- The VM needs no inbound ports for this. Claude Code makes outbound HTTPS calls only. **[docs]**
- Optional: several Claude accounts on one VM, each under its own Linux user.

**Limits to know before you start:**

- Remote Control needs a claude.ai subscription: Pro, Max, Team or Enterprise. API keys do
  not work. **[docs]**
- On Team and Enterprise, an Owner must turn on Remote Control in the
  [Claude Code admin settings](https://claude.ai/admin-settings/claude-code). **[docs]**
- It does not work through Amazon Bedrock, Google Cloud's Agent Platform, Microsoft Foundry
  or a custom `ANTHROPIC_BASE_URL`. **[docs]**
- Organizations with Zero Data Retention or the HIPAA configuration cannot use it. **[docs]**
- While Remote Control is connected, Anthropic stores the session transcript. Execution and
  files stay on your VM. **[docs]**
- If you or your organization turn on Trusted Devices, the VM must enroll through `/login`, and
  each viewing device must verify. A sign-in older than 18 hours needs a fresh check. **[docs]**

## 2. Architecture

```text
  Phone or browser (claude.ai/code, Claude mobile app)
        |
        |  HTTPS
        v
  Anthropic API and relay
        ^
        |  outbound HTTPS only, no inbound ports
        |
  +-----|-------------------------------------------------------+
  | VM  |                                                       |
  |   systemd                                                   |
  |    +- claude-remote-control-1.service   (User=claude-1)     |
  |    |    bash wrapper loop                                   |
  |    |      claude remote-control --name VM-1    <- server    |
  |    |        one worker process per session                  |
  |    |          tools, MCP servers, subagents                 |
  |    |                                                        |
  |    +- claude-remote-control-2.service   (User=claude-2)     |
  |         same shape, second Claude account                   |
  |                                                             |
  |   admin user: has sudo, used by a person, runs no server    |
  +-------------------------------------------------------------+
```

**Terms used in this spec:**

| Term | Meaning |
|---|---|
| **Server** | The `claude remote-control` process. One per account. |
| **Wrapper** | The bash `while true` loop that restarts the server. |
| **Environment** | The server's registration at Anthropic, with an ID that starts `env_`. It shows as a selectable computer in claude.ai/code. |
| **Session** | One conversation. Each live session is one worker process on the VM. |
| **Account** | One Claude login. On this VM, one Linux user holds one account. |

## 3. Decisions to make first

| Decision | Recommended | Other options | Advice |
|---|---|---|---|
| Accounts | One | Several, one Linux user each | Start with one. Add more with section 9. |
| Permission mode | `auto` | `bypassPermissions`, `acceptEdits`, `default`, `plan`, `dontAsk` | Read section 12 first. |
| Install method | Signed apt repository | System-wide npm, run as root | See section 5.2. |
| Who has sudo | Only the admin user | | Never give sudo to a user that runs a server. |
| Access to the VM | Private tunnel, no public SSH | Tailscale, WireGuard, bastion | Keep SSH off the public internet. |

## 4. VM specification

### Sizing

Anthropic's minimum is 4 GB RAM. **[docs]** That is a floor for one session, not a size
for an always-on server.

| Use | vCPU | RAM | Disk | Evidence |
|---|---|---|---|---|
| One account, a few sessions | 2 | 8 GB | 100 GB SSD | **[ran]** for CPU and RAM, on a standard disk. |
| Up to two accounts, normal load | 8 | 32 GB | 200 GB SSD | **[ran]** |
| Four accounts, two busy at once, 20+ sessions each | 16 | 64 GB | 400 GB SSD | **[ran]** Current reference VM. |

**Measured facts for sizing: [ran]**

- One session uses about 160 to 450 MB. Its MCP servers and helpers are extra.
- 2 GB RAM is not enough. Eight sessions on 2 GB filled swap and wedged the VM. No process
  was killed: the VM just stopped responding.
- Each MCP server runs as a process per session, so an unused one is costly. One browser
  MCP server used about 10 GB in total, and sessions called it once in a week.
- Use an SSD. A standard disk gave about 24 MiB/s. An SSD gave about 350 MB/s.
- The disk grows fast. With four busy accounts, we saw about 5 GB a day from session
  scratch folders, package caches, plugin versions and logs. Plan regular clean-ups, and
  alert on disk use (section 10.9).
- Each time the VM looked CPU-bound, the true cause was memory pressure inside one account
  (section 14).

### Cost

One more account on the same VM adds no VM cost. It adds one more Claude plan. Fetch your
provider's live prices when you size the VM.

If your use is bursty, stop the VM when you do not need it. A stopped VM usually bills for
its disk only. Everything persists on the disk. Treat a stop as a restart (section 10.4).

### Operating system

- Use Ubuntu 24.04 LTS, or another Linux with systemd and cgroup v2. **[ran]** on Ubuntu 24.04.
- Set the VM clock to UTC.
- Add swap. The reference VM has 2 GB. Do not treat swap as headroom: full swap is a
  warning sign, not a buffer.

### Network

- **Outbound:** HTTPS (port 443) to Anthropic's API. Add GitHub and your package mirrors.
- **Inbound:** nothing for Remote Control. **[docs]** Allow SSH only through your tunnel.
- **NAT gateway:** check the limit on source ports per VM. Many Claude processes connect
  to a few Anthropic IP addresses. A low limit causes a reconnect storm (section 14).
- **Several accounts on one IP address:** this works. Four accounts share one egress IP
  on the reference VM. **[ran]**

### Provider mapping

Only the Google Cloud column was run by us. The others are the usual equivalents.

| Need | Google Cloud | AWS | Azure | Any VPS |
|---|---|---|---|---|
| Private SSH | IAP tunnel | Session Manager | Bastion | Tailscale or WireGuard |
| Disk snapshots | Snapshot schedule | Data Lifecycle Manager | Azure Backup | Provider snapshots |
| Memory and swap metrics | Ops Agent | CloudWatch agent | Azure Monitor Agent | node_exporter or similar |
| VM identity | Attached service account | Instance profile | Managed identity | None |

## 5. Base OS setup

Run these steps as the admin user.

### 5.1 Packages

```bash
sudo apt-get -o DPkg::Lock::Timeout=600 update
sudo apt-get -o DPkg::Lock::Timeout=600 install -y git tmux jq curl gnupg ca-certificates python3 needrestart
```

Unattended upgrades hold the package lock just after first boot, so keep the timeout.
**[ran]**

Install the GitHub CLI (`gh`) from [its instructions](https://github.com/cli/cli#installation).

### 5.2 Install Claude Code

Every account must run one system-wide copy of Claude Code. A per-account copy goes stale
and causes version drift (section 10.5).

**Option A: signed apt repository (recommended for a new build).** Anthropic publishes this
repository. **[docs]** The package installs `/usr/bin/claude`, the same path the units in
this spec use. We confirmed that path from the package contents, but the reference VM does
not run this install. **[not run]**

```bash
sudo install -d -m 0755 /etc/apt/keyrings
sudo curl -fsSL https://downloads.claude.ai/keys/claude-code.asc \
  -o /etc/apt/keyrings/claude-code.asc
gpg --show-keys /etc/apt/keyrings/claude-code.asc
```

Check the fingerprint against
[Anthropic's setup page](https://code.claude.com/docs/en/setup#install-with-linux-package-managers).
Then add the repository and install:

```bash
echo "deb [signed-by=/etc/apt/keyrings/claude-code.asc] https://downloads.claude.ai/claude-code/apt/stable stable main" \
  | sudo tee /etc/apt/sources.list.d/claude-code.list
sudo apt update
sudo apt install claude-code
claude --version
command -v claude
```

If `command -v claude` prints a path other than `/usr/bin/claude`, use that path in the
unit and scripts. The `stable` channel is typically about a week behind `latest`. **[docs]** To follow
`latest`, use the `latest` repository line from Anthropic's page.

**Option B: system-wide npm (what the reference VM runs). [ran]**

This option needs Node.js 22 or later and npm. **[docs]** Ubuntu 24.04's own `nodejs` package
is older. Install Node.js from [nodejs.org](https://nodejs.org/en/download) or NodeSource
first. The reference VM uses NodeSource.

```bash
sudo npm install -g @anthropic-ai/claude-code
```

Anthropic's docs advise against `sudo npm install -g`. **[docs]** We use it because it gives
one root-owned copy that no account can change. Option A gives the same result without
that warning.

### 5.3 Nightly update of the file on disk

The update replaces the file on disk. Running servers keep their old version until you
restart them (section 10.5). This job never restarts a server.

`/usr/local/bin/update-claude-code.sh`, for Option A **[not run]**:

```bash
#!/bin/bash
set -euo pipefail
apt-get update -qq
apt-get install -y --only-upgrade claude-code
echo "$(date -Iseconds) Updated to $(/usr/bin/claude --version)" >> /var/log/claude-code-update.log
```

For Option B, use these lines instead. Anthropic prefers this `install` form to
`npm update -g`, which may not reach the newest release. **[docs]** The reference VM still
runs `npm update -g`.

```bash
#!/bin/bash
set -euo pipefail
npm install -g @anthropic-ai/claude-code@latest >> /var/log/claude-code-update.log 2>&1
echo "$(date -Iseconds) Updated to $(/usr/bin/claude --version)" >> /var/log/claude-code-update.log
```

`/etc/systemd/system/claude-code-update.service`:

```ini
[Unit]
Description=Update Claude Code CLI

[Service]
Type=oneshot
ExecStart=/usr/local/bin/update-claude-code.sh
```

`/etc/systemd/system/claude-code-update.timer`:

```ini
[Unit]
Description=Daily Claude Code update

[Timer]
OnCalendar=*-*-* 04:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

Turn it on:

```bash
sudo chmod 755 /usr/local/bin/update-claude-code.sh
sudo systemctl daemon-reload
sudo systemctl enable --now claude-code-update.timer
```

### 5.4 Stop OS upgrades from killing sessions

`needrestart` restarts services after a library upgrade. Under unattended upgrades it
restarts the Remote Control service with no warning. Every attached session stops, and the
log shows only a clean start. **[ran]**

**Exclude each server unit.** Create one file per unit.
`/etc/needrestart/conf.d/90-claude-remote-control-1.conf`:

```perl
# Exclude this Remote Control unit from needrestart auto-restart.
$nrconf{override_rc}{qr(^claude-remote-control-1\.service$)} = 0;
```

Check the syntax with `sudo perl -c` on the file. Then run `sudo needrestart -b -r l`,
which lists what it would restart and restarts nothing. Every other daemon still restarts
as normal. The trade: this unit can run on old libraries until you restart it on purpose.

**Run upgrades weekly, not daily.** `sudo systemctl edit apt-daily-upgrade.timer`:

```ini
[Timer]
OnCalendar=
OnCalendar=Sun *-*-* 06:00
RandomizedDelaySec=30m
Persistent=true
```

The empty `OnCalendar=` line is required. Without it, systemd adds the new schedule to the
daily one. Check with `systemctl show apt-daily-upgrade.timer -p TimersCalendar`: it must
show exactly one entry. The trade: a security patch can wait up to seven days.

### 5.5 Keep the logs under control

A busy server redraws its status many times a second. We measured about 1.1 million
journal lines a day from one account, and 2 to 3 GB a week in `/var/log/syslog`. **[ran]**

- The journal caps itself. Ubuntu's `/var/log/syslog` rotation has no size cap.
- Add `maxsize 1G` to the syslog block in `/etc/logrotate.d/rsyslog`. **[not run]**
- Never run a wide `journalctl` search on a busy VM. Use `-n 200`, or a window of a few
  seconds with `--since` and `--until`. Wide scans pushed a busy VM near its limit. **[ran]**

### 5.6 Snapshots and monitoring

- Turn on daily disk snapshots with your provider.
- Send memory, swap and disk metrics to your monitoring tool. Check that the agent is
  active, not only installed. With a disabled agent, a VM at 100% swap looks healthy. **[ran]**
- See section 10.9 for what to alert on.

## 6. Set up one account

This example builds `claude-1`, with server name `VM-1`. Replace the example values with
your own: `your-org/your-workspace`, `Your Name` and `you@example.com`.

**Step 1. Create the user.** As admin:

```bash
sudo useradd -m -s /bin/bash claude-1
sudo chmod 750 /home/claude-1
sudo loginctl enable-linger claude-1
sudo -l -U claude-1
id claude-1
```

`sudo -l -U` must say the user may not run sudo. `id` must show no `sudo`, `adm`, `docker` or
cloud agent group. Always reach the user with `sudo -iu claude-1` (see section 16 for why).

**Step 2. Set up GitHub and git.** As the new user (`sudo -iu claude-1`):

```bash
gh auth login --hostname github.com --git-protocol https --web
gh auth setup-git
git config --global user.name "Your Name"
git config --global user.email "you@example.com"
```

Use an email that is verified on your GitHub account, or your commits show as unlinked.
Without a git identity, `git commit` fails in every new worktree. **[ran]**

**Step 3. Clone a working repository.**

```bash
gh repo clone your-org/your-workspace ~/projects/workspace
```

Sessions start in this folder. Use a git repository, so sessions can use worktrees. Do not
use the home folder: Claude Code never saves trust for it. **[docs]**

**Step 4. Write the account settings.** Create `~/.claude/settings.json` and
`~/.claude/harness-path.sh` from section 8. Do this before the first `claude` run, so the
in-app updater is off from the start.

**Step 5. Trust the folder and sign in.** A person must do this. Stay as the new user:

```bash
cd ~/projects/workspace
claude
```

- Answer yes to the trust prompt. Without saved trust, the headless server exits with
  `Workspace not trusted`. **[docs]**
- If you plan to use `bypassPermissions`, start with
  `claude --permission-mode bypassPermissions` instead, and accept the warning.
- Type `/login`. Choose the Claude subscription option, not the API option.
- Open the printed URL on your laptop. Sign in. Copy the code back to the terminal.
- Type `/exit`.

`claude auth login --claudeai` does the same sign-in from the shell.

Never use `claude setup-token` or `CLAUDE_CODE_OAUTH_TOKEN` here. Those tokens cannot start
Remote Control. **[docs]**

**Step 6. Check the login.**

```bash
claude auth status --text
jq '.oauthAccount | {emailAddress, accountUuid, organizationType, organizationUuid}' ~/.claude.json
stat -c '%a %U' ~/.claude/.credentials.json
env | grep -E '^(ANTHROPIC_API_KEY|ANTHROPIC_BASE_URL|CLAUDE_CODE_OAUTH_TOKEN)=' | cut -d= -f1
```

- The email and organization must be the ones you expect.
- One email can belong to two organizations, for example a personal plan and a Team org.
  Only an organization whose seat includes Claude Code works. Pick that one at sign-in.
  **[ran]**
- The credentials file must be mode `600` and owned by the user.
- The last command must print nothing.

**Step 7. Pre-seed the first-run prompt.**

The first `claude remote-control` run for a user asks `Enable Remote Control? (y/n)`. Under
systemd nothing can answer. The process connects but never registers an environment, and the
journal goes quiet. It looks like a network fault. **[ran]** Set the flag first:

```bash
cp ~/.claude.json ~/.claude.json.bak-preseed
(umask 077; jq '.remoteDialogSeen = true' ~/.claude.json > ~/.claude.json.new)
mv ~/.claude.json.new ~/.claude.json
```

`remoteDialogSeen` is an internal key. **[seen]** If the unit still hangs, stop the unit and
answer the prompt once as the user:

```bash
cd ~/projects/workspace
printf 'y\n' | timeout 20 claude remote-control --name VM-1
```

**Step 8. Install the unit and the needrestart file.** As admin, create both files. Paste
the text from section 7 and section 5.4:

```bash
sudoedit /etc/systemd/system/claude-remote-control-1.service
sudoedit /etc/needrestart/conf.d/90-claude-remote-control-1.conf
sudo perl -c /etc/needrestart/conf.d/90-claude-remote-control-1.conf
sudo systemd-analyze verify /etc/systemd/system/claude-remote-control-1.service
sudo systemctl daemon-reload
```

**Step 9. Start the server.**

```bash
sudo systemctl enable --now claude-remote-control-1
```

**Step 10. Verify from the outside.**

```bash
systemctl status claude-remote-control-1 --no-pager
journalctl -u claude-remote-control-1 -n 40 --no-pager
sudo jq . /home/claude-1/.claude/projects/-home-claude-1-projects-workspace/bridge-pointer.json
```

`bridge-pointer.json` holds the environment ID and the server PID. The folder name is the
working directory with `/` and `.` replaced by `-`. **[seen]**

Then do the real test:

1. Open claude.ai/code, signed in as this account.
2. Start a new session. Pick your VM in the environment list, not the cloud default.
3. Send: "Run `id -un` and reply with only the output."
4. Accept only `claude-1` as the answer.

## 7. The systemd unit

`/etc/systemd/system/claude-remote-control-1.service`:

```ini
[Unit]
Description=Claude Code Remote Control (account claude-1 / VM-1)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=claude-1
Group=claude-1
WorkingDirectory=/home/claude-1/projects/workspace
ExecStart=/bin/bash -c 'while true; do /usr/bin/claude remote-control --name VM-1 --permission-mode auto --capacity 100 2>&1; echo "Session ended, restarting in 10s..."; sleep 10; done'
Restart=always
RestartSec=30
MemoryHigh=12G
MemoryMax=13G
OOMPolicy=continue
StandardOutput=journal
StandardError=journal
SyslogIdentifier=claude-remote-control-1

[Install]
WantedBy=multi-user.target
```

This is the unit shape the reference VM runs. Two values need your choice:

- `--permission-mode`. This template uses `auto` (section 12). We have not run `auto` as the
  server flag. **[not run]** If auto mode is not available to a session, Claude Code starts it
  in Manual mode instead. **[docs]**
- The memory limits. These values suit one account on a 16 GB VM. Section 9.4 gives other
  values.

**Why each line matters:**

| Line | Why |
|---|---|
| `After=` / `Wants=network-online.target` | The server needs the network at start. |
| `User=` | One Linux user holds one Claude login. The server reads that user's `~/.claude`. |
| `WorkingDirectory=` | Sessions start here, and this folder decides which `CLAUDE.md` loads. |
| `while true` wrapper | Claude Code exits on a long outage. **[docs]** The loop restarts it in 10 seconds. |
| `Restart=always` | A second layer, for when the wrapper itself dies. |
| `--name` | The title for sessions. The environment entry in claude.ai keeps its hostname-based name. Rename it in the claude.ai UI. **[seen]** |
| `--permission-mode` | The mode for sessions this server spawns. See section 12. |
| `--capacity` | Maximum concurrent sessions. The default is 32. **[docs]** It is a ceiling only. RAM runs out first. |
| `MemoryHigh=` | A soft limit. Above it, the kernel throttles the account. |
| `MemoryMax=` | A hard limit. Above it, the kernel kills a process inside this account. |
| `OOMPolicy=continue` | **Key line.** Without it, one killed test restarts the whole service and drops every session of that account. With it, only the runaway process dies. **[ran]** |
| `SyslogIdentifier=` | Keeps each account's log lines separate. |

**Session folders.** By default, all sessions share the working directory (`--spawn same-dir`).
Add `--spawn worktree` to give each session its own git worktree. **[docs]** Sessions that edit
the same files in one folder conflict. In a terminal, the first run can also ask
`Spawn mode for this project:`. Passing `--spawn` skips it. **[docs]**

**Why not tmux?** tmux needs a manual start after a reboot, and it does not restart a dead
server. Use tmux only if you want to watch the server's terminal. Do not run both for one
user and folder: the second server refuses to start.

**Do not set** `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` or `DISABLE_GROWTHBOOK` anywhere. Each
makes Remote Control unavailable. **[docs]**

## 8. Account settings

Each Linux user has its own settings. Apply them once per account. Replace `claude-1` with
the account's user. If the file already exists, merge these keys into it.

`~/.claude/settings.json`:

```json
{
  "env": {
    "BASH_ENV": "/home/claude-1/.claude/harness-path.sh",
    "DISABLE_AUTOUPDATER": "1",
    "FORCE_AUTOUPDATE_PLUGINS": "1",
    "CLAUDE_CODE_SUBAGENT_MODEL": "sonnet"
  },
  "permissions": {
    "defaultMode": "auto"
  },
  "cleanupPeriodDays": 1000,
  "agentPushNotifEnabled": true,
  "effortLevel": "high"
}
```

| Key | Why |
|---|---|
| `DISABLE_AUTOUPDATER` | Stops the in-app updater. The nightly timer owns updates. With an npm install and a per-user npm prefix, the in-app updater writes a stale copy to `~/.local`. **[ran]** |
| `FORCE_AUTOUPDATE_PLUGINS` | **Always set this with the line above.** `DISABLE_AUTOUPDATER` alone also stops plugin updates. **[docs]** A marketplace other than the official one also needs its own auto-update turned on. |
| `BASH_ENV` | Fixes "command not found" in tool calls. See below. |
| `permissions.defaultMode` | The mode for sessions the server does not spawn, such as `claude --bg` from cron. The unit's flag covers only sessions the server spawns. `auto` works only from this user-level file, not from a project's settings. **[docs]** |
| `CLAUDE_CODE_SUBAGENT_MODEL` | Optional. Runs subagents on a cheaper model. |
| `cleanupPeriodDays` | Claude Code deletes transcripts after 30 days by default. On a VM you want them longer. |
| `agentPushNotifEnabled` | Lets a session send a push to your phone. |
| `effortLevel` | Optional default effort. Pick your own. |

`skipDangerousModePermissionPrompt: true` also appears here if you accepted the
`bypassPermissions` warning in Step 5.

### The PATH fix

Tool calls run in a non-interactive, non-login shell. That shell skips `~/.profile`, and it
leaves `~/.bashrc` at the interactive guard. So `~/.local/bin` never reaches the PATH, and
editing rc files does not help. **[ran]**

Bash sources the file named by `BASH_ENV` for every non-interactive shell. So create
`~/.claude/harness-path.sh`:

```bash
# Append, never prepend, so a ~/.local copy cannot shadow /usr/bin/claude.
case ":$PATH:" in
  *":$HOME/.local/bin:"*) ;;
  *) export PATH="$PATH:$HOME/.local/bin" ;;
esac
```

stdio MCP servers do not go through that shell. Use absolute paths for their commands.

Settings load when a session starts, so the fix applies to the next session.

### Sharing configuration across accounts

Each Linux user has its own `~/.claude`, hooks, plugins, git identity and crontab. Keep your
shared files in a git repository, and run your setup script once as each user. A setup run
as one user does not reach the others. The public
[`machine-move`](../skills/machine-move/SKILL.md) skill covers repository sync and new-machine setup.

## 9. Multiple accounts

### 9.1 The model

**One Linux user holds one Claude account.** To serve two accounts at once, add a user and a
unit. **[ran]**

| Item | Account 1 | Account 2 |
|---|---|---|
| Linux user | `claude-1` | `claude-2` |
| Home | `/home/claude-1`, mode 750 | `/home/claude-2`, mode 750 |
| Claude login | `first@example.com` | `second@example.com` |
| systemd unit | `claude-remote-control-1.service` | `claude-remote-control-2.service` |
| Server name | `VM-1` | `VM-2` |
| Working folder | `/home/claude-1/projects/workspace` | `/home/claude-2/projects/workspace` |
| needrestart file | `90-claude-remote-control-1.conf` | `90-claude-remote-control-2.conf` |
| Environment ID | Its own | Its own |

Each account needs its own Claude plan and has its own usage limits. Check Anthropic's
current terms for your plan.

### 9.2 What is isolated and what is shared

| Isolated per account | Shared by all accounts |
|---|---|
| Claude login and usage limits | The `claude` binary |
| `~/.claude`, `~/.claude.json`, transcripts | CPU, RAM, disk, disk throughput |
| GitHub login and git identity | `/tmp`: any account can read a default-mode file there |
| Codex and other per-user CLI logins | The VM's cloud identity (section 12) |
| Crontab and systemd user timers | The egress IP address |
| Memory limits, through the cgroup | Kernel, OS packages, reboots |

A VM-wide reboot or memory crisis hits every account. Use a second VM if you need a real
failure boundary.

### 9.3 Add an account

Follow section 6 for the new user, with these additions.

1. **Pick a new login.** No two servers may share an account.
2. **Protect the running accounts.** Before you start, and after each step, record this for
   every existing unit. Change the first line for each unit. Stop if a value changes.

   ```bash
   unit=claude-remote-control-1
   main=$(systemctl show -p MainPID --value "$unit")
   inner=$(ps -o pid=,args= --ppid "$main" | grep -F 'claude remote-control' | awk '{print $1}')
   echo "$unit main=$main restarts=$(systemctl show -p NRestarts --value "$unit") inner=$inner"
   ```

   Watch the inner PID, not only `MainPID`. The wrapper can stay up while the server restarts.
   `daemon-reload` does not disturb running units. **[ran]**

3. **Compare logins by their account fields, not by environment ID.** Read `oauthAccount` in each
   account's `~/.claude.json`. `accountUuid` must differ between accounts, and
   `organizationUuid` must be the organization you expect for that account. Two personal plans
   have different organizations. Two seats in one Team org share one, and that is correct. An
   environment ID follows a local pointer file. It can survive an account switch, so it proves
   nothing about the account. **[ran]**
4. **Budget memory.** See section 9.4.
5. **Turn off the in-app updater** and add the plugin line (section 8).
6. **Log in every other CLI.** Codex, for example, stores its login per user. A new account
   starts logged out, and any tool that calls Codex fails there. **[ran]**
7. **Run your setup script as the new user,** so its hooks and guards exist. A bare user runs
   with no guards until you do. **[ran]**
8. **Check sudo again at the end.** See section 16 for how a cloud SSH tool can add it back.
   A running service keeps the groups it started with, until it restarts:
   `ps -o supgrp= -p <MainPID>`.

### 9.4 Memory budget

**Simple rule: the sum of every account's `MemoryMax`, plus 3 GB for the system, must fit in
RAM.** Use this rule unless you know your load.

| RAM | Accounts | `MemoryHigh` | `MemoryMax` | Evidence |
|---|---|---|---|---|
| 8 GB | 1 | 4500M | 5G | **[not run]** |
| 16 GB | 1 | 12G | 13G | **[not run]** |
| 32 GB | 2 | 13G | 14G | **[not run]** |
| 64 GB | 4 | 13G | 15G | **[not run]** |

**Overcommit, if you know your load.** The reference VM gives each of its four accounts
`MemoryLow=12G`, `MemoryHigh=44G` and `MemoryMax=48G` on 64 GB. **[ran]** The ceilings sum to more
than RAM on purpose. This suits a load where at most one account nears its ceiling, and a
second busy account stays near its protected 12 GB: 48 + 12 + 2 for the system is 62 GB. If
several accounts push past that, the kernel reclaims memory and all of them slow down.

**Rules from running it: [ran]**

- Keep `MemoryHigh` close to `MemoryMax`, about 90%. A limit of 11G high and 14G max made an
  account thrash long before it reached the ceiling.
- A contained runaway is still a problem. A stuck process held under its cap can fill swap
  and slow every other account. Kill it.
- `MemoryLow` needs `memory_recursiveprot` in the cgroup2 mount options. Check `/proc/mounts`.
- Sessions that cron starts run in cron's cgroup, not the account's unit. The unit limits do not
  cap them.

Change a limit live, with no restart:

```bash
sudo systemctl set-property claude-remote-control-1.service MemoryHigh=44G MemoryMax=48G
```

Add `--runtime` for a change that ends at reboot.

### 9.5 See each account's sessions

claude.ai/code and the mobile app show only the signed-in account and organization. There is
no combined view. **[ran]**

- Use one browser profile per account.
- If claude.ai shows an empty sidebar and "Claude Code isn't available on your account", you
  are on the wrong organization. Switch organization **before** you debug the VM. Direct
  session links fail the same way, so a healthy VM looks dead. **[ran]**
- In the new-session picker, choose your VM. The default is the cloud environment. **[ran]**

### 9.6 Change the account a server serves

**Never change only the saved login under a running server.** The server re-reads the
credentials file while it runs. It moved to the new account mid-run and dropped the old
account's sessions one at a time, each at its next token refresh. **[seen]** Use this order:

1. Move your work off the old account's sessions. Sessions do not follow you to the new
   account.
2. `sudo systemctl stop claude-remote-control-1`. Keep the stop under about 10 minutes.
3. Sign in as the new account, as that user. Check `claude auth status --text`.
4. `sudo systemctl start claude-remote-control-1`.
5. Check the new server is up, and that the other units did not change.

A restart on a **new** account starts clean. The old sessions stay readable in claude.ai under
the old account.

### 9.7 Remove an account

First, as that user, run `gh auth logout` and `claude auth logout`. Then, as admin:

```bash
sudo systemctl disable --now claude-remote-control-2
sudo systemctl reset-failed claude-remote-control-2
sudo mkdir -p /root/removed-account-2
sudo mv /etc/systemd/system/claude-remote-control-2.service /root/removed-account-2/
sudo mv /etc/needrestart/conf.d/90-claude-remote-control-2.conf /root/removed-account-2/
sudo systemctl daemon-reload
sudo loginctl disable-linger claude-2
sudo loginctl terminate-user claude-2
```

Delete the user only when you are sure you do not need the home folder.

### 9.8 An alternative: `CLAUDE_CONFIG_DIR`

`CLAUDE_CONFIG_DIR` points Claude Code at a different configuration folder. Anthropic
describes it as useful for running multiple accounts side by side. **[docs]** It fits a laptop.
We do not use it on the VM, because Linux users also isolate memory limits, files, crontabs and
other CLI logins. **[not run]** for a server.

## 10. Daily operations

### 10.1 Status

`vm-status.sh`, read-only. Run it as an admin user with passwordless sudo. Without that, the
`binary` field reads `unknown`.

```bash
#!/usr/bin/env bash
# One line per Remote Control unit. Changes nothing.
echo "installed: $(/usr/bin/claude --version | awk '{print $1}')"
units=$(systemctl list-units --all --type=service --no-legend --plain 'claude-remote-control*' | awk '{print $1}')
for unit in $units; do
  user=$(systemctl show -p User --value "$unit")
  main=$(systemctl show -p MainPID --value "$unit")
  restarts=$(systemctl show -p NRestarts --value "$unit")
  inner=$(ps -o pid=,args= --ppid "$main" 2>/dev/null | grep -F 'claude remote-control' | awk 'NR==1{print $1}')
  exe=$(sudo -n readlink "/proc/${inner:-0}/exe" 2>/dev/null)
  case "$exe" in
    "") binary=unknown ;;
    *" (deleted)") binary=OLD-VERSION ;;
    *) binary=current ;;
  esac
  echo "$unit user=$user main=$main restarts=$restarts server=${inner:-none} binary=$binary"
done
```

`OLD-VERSION` means the file on disk changed after the server started.

**Other checks:**

- Session count: `journalctl -u claude-remote-control-1 -n 200 --no-pager | grep -a Capacity | tail -1`
- Box health: `free -h; swapon --show; df -h /; uptime`
- Find the processes: `ps -eo pid,etime,args | grep '[c]laude'`

### 10.2 Reach the VM

- Connect as admin through your tunnel, then `sudo -iu claude-1`.
- To work in a terminal session on the same account, run `claude` from a folder. Terminal
  sessions and served sessions run side by side.
- Run terminal sessions inside `tmux`. A plain SSH drop kills the process. **[docs]**

### 10.3 What survives and what does not

| Event | Files and git | Transcript | The session's process | Background jobs |
|---|---|---|---|---|
| Phone or browser disconnects | Safe | Safe | Keeps running | Keep running |
| Network blip, under about 10 minutes | Safe | Safe | Reconnects | Keep running |
| Same-login fast restart | Safe | Safe | Stops. Returns when messaged. | Stop |
| Outage past about 10 minutes | Safe | Safe | Server exits | Stop |
| VM reboot | Safe, except `/tmp` | Safe | Stops | Stop |

**Habits that follow from this:**

- **Keep a plan file up to date in the repository.** Artifacts survive. Session memory may not.
  After any gap, tell the session to re-read its plan.
- **Commit often.** Push before any planned restart. A public example is the wip-commit hook in
  the [`session-dsp`](../skills/session-dsp/SKILL.md) skill.
- **Keep durable scratch out of `/tmp`.** Ubuntu empties `/tmp` at every boot on our VM. **[ran]**
- **Never rename a worktree folder.** Transcripts live under
  `~/.claude/projects/<path-slug>/`, keyed to the folder path. A rename orphans them. **[ran]**
- **Do not trust a running background server after a drop.** A child process dies with its
  session. Start it again.
- A session that crashes in server mode comes back when you send it a message. You do not
  need to restart the server. **[docs]**

### 10.4 Restart rules

**Do not restart a server to fix slowness.** Restart only for a version update or an account
change. Before every restart or VM stop:

1. Push all work, for every account.
2. Check that no session is mid-turn. For each recent transcript in `~/.claude/projects`, the
   last `user` or `assistant` entry must be an `assistant` entry with `stop_reason` of `end_turn`.
   Skip subagent transcripts. A file-age check gives false alarms. **[ran]**
3. Restart one unit at a time, idle accounts first.
4. After each restart, check that the other units did not change (section 9.3).

**What to expect: [ran]**

- A same-login restart in under a minute keeps the environment.
- The new server shows `Capacity: 0/100`. This is normal. Each session comes back when you send
  it one message.
- A running turn is cut, and background shells of a session stop.
- **A session cannot safely restart its own unit.** Run the restart from an admin SSH shell.

To stop a server, use `systemctl stop`. To restart one by hand, send `SIGINT` to the inner
server, not the wrapper. The wrapper starts it again in 10 seconds. `pgrep -f` matches both
processes, and the wrapper usually has the lower PID.

After `claude remote-control` stops, the same folder can bring sessions back for about four
hours. **[docs]**

### 10.5 Update Claude Code

The nightly timer changes the file on disk only. A running server keeps its start version.
So "the update is stuck" usually means nobody restarted the servers. **[ran]**

1. Run the updater: `sudo systemctl start claude-code-update.service`.
2. Check the version: `/usr/bin/claude --version`.
3. Check each account resolves the system copy: `sudo -iu claude-1 bash -lc 'command -v claude'`.
   A `~/.local/bin/claude` is a stale shadow copy. Check that no process runs it, then remove
   it as that user with `npm uninstall -g @anthropic-ai/claude-code`. If that fails with
   `ENOTEMPTY`, first remove the stale `.claude-code-<random>` staging folder beside it.
4. Run `vm-status.sh`.
5. Follow the restart rules (section 10.4) for each unit that shows `OLD-VERSION`.
6. Run `vm-status.sh` again.

**Do not run `npm i -g` as an account.** With a per-user npm prefix, it makes a shadow copy.
**[ran]** Treat `claude update` the same way. We have not tested it as an account.

### 10.6 Sign-in health

**This is the failure you will hit first on a long-running VM.**

[seen] A refresh token expires about four weeks after the login that created it (27 to 30 days
in our cases). Renewals do not extend it. About 8 hours later, the next access-token renewal
fails. Claude Code then empties `~/.claude/.credentials.json` and sets `expiresAt` to 0. Every
process on that account fails with `OAuth session expired and could not be refreshed`, and
claude.ai says the computer needs to sign in again.

A refused refresh can also empty the file with weeks left on the token. **[seen]** We have not
found the cause of those cases.

Two traps: **[ran]**

- `~/.claude.json` keeps the email after a wipe, so a fresh `claude` still looks signed in.
  Check the token fields.
- Sessions on the failed account stop in silence. Scheduled jobs that need Claude fail too.

`token-check.py`, read-only. Run it as root to check several accounts. It never prints a token.

```python
#!/usr/bin/env python3
"""Read-only sign-in check. Usage: token-check.py USER [USER ...]. Never prints a token."""
import json
import sys
import time
from datetime import datetime, timezone

DAY_MS = 86400000
DUE_DAYS = 3
now = int(time.time() * 1000)
status = 0


def utc(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


for user in sys.argv[1:]:
    try:
        with open(f"/home/{user}/.claude/.credentials.json", encoding="utf-8") as f:
            oauth = json.load(f)["claudeAiOauth"]
        access, refresh = oauth.get("accessToken"), oauth.get("refreshToken")
        expires, refresh_expires = oauth.get("expiresAt"), oauth.get("refreshTokenExpiresAt")
        if not access or not refresh or expires == 0:
            verdict, detail = "WIPED", "sign in again now"
        elif not refresh_expires:
            verdict, detail = "UNKNOWN", "no refresh expiry in the file"
        elif refresh_expires <= now:
            verdict, detail = "EXPIRED", f"refresh token ended {utc(refresh_expires)}"
        elif refresh_expires - now <= DUE_DAYS * DAY_MS:
            verdict, detail = "DUE", f"refresh token ends {utc(refresh_expires)}"
        else:
            verdict, detail = "OK", f"refresh token ends {utc(refresh_expires)}"
    except Exception as ex:
        verdict, detail = "UNKNOWN", type(ex).__name__
    print(f"{user} {verdict} {detail}")
    status = status or int(verdict != "OK")
sys.exit(status)
```

**Re-login, with no restart and no SSH for the person who signs in. [ran]** Use this only for
the SAME account. Run as admin, with the account's own email:

```bash
sudo -iu claude-1 tmux new -d -s relogin -x 400 -y 50 "claude auth login --claudeai --email you@example.com; sleep 1800"
sleep 8
sudo -iu claude-1 tmux capture-pane -p -J -t relogin
```

The wide pane keeps the URL on one line. Open the URL. Sign in and pick the right organization.
The page shows a one-time code. Enter it:

```bash
sudo -iu claude-1 tmux send-keys -t relogin -l '<code>'
sudo -iu claude-1 tmux send-keys -t relogin Enter
```

The pane prints `Login successful.` Then:

```bash
sudo -iu claude-1 claude auth status --text
sudo -iu claude-1 tmux kill-session -t relogin
systemctl show claude-remote-control-1 -p MainPID -p NRestarts
```

`MainPID` and `NRestarts` must not change. The running server picks up the new token. Sessions
that failed mid-turn do not retry: each one needs a new message.

**Prevent it.** Run the check daily from cron. Re-login any `DUE` account. In the one case we
tested, a re-login before the wipe kept every session running. **[seen]** Sign in to all accounts
on one day, so one reminder covers them all.

### 10.7 Disk

Measure first: `df -h /`, then `sudo du -xh --max-depth=2 /home /tmp | sort -rh | head -20`.

**These rebuild themselves, so you can clear them for every account.** We measured them, but
we have not run a full clean-up. **[not run]**

- `~/.npm/_cacache`, `~/.npm/_npx`, `~/.cache/uv`, `~/.cache/pip`
- Session scratch folders `/tmp/claude-<uid>/<project>/<session>/` idle for 3 or more days
- Other top-level `/tmp` items idle for 7 or more days
- Old plugin versions under `~/.claude/plugins/cache/`. Keep the newest few, and any version a
  live session loaded.

**Never delete** backups, worktrees or transcripts under `~/.claude/projects`.

To grow a disk online: resize it with your provider, then run `growpart` and `resize2fs`. No
reboot is needed, and servers keep running. **[ran]** A disk cannot shrink back. Take a snapshot
first.

### 10.8 Resize the VM

Stop to start took under two minutes, and every environment came back. **[ran]**

1. Check every account is quiet (section 10.4).
2. Pause cron jobs that start sessions. Back up the crontab to the home folder, not `/tmp`.
3. Set the new memory limits so they apply at boot.
4. Record each unit's environment ID.
5. Take the snapshot **while the VM runs**. A snapshot during the stop eats the time window.
6. Stop the VM, change the type, start the VM. Abort if any step fails.
7. Watch the serial console. SSH can take a few minutes.
8. Check each environment ID, then restore the crontab.

### 10.9 Monitoring and alerts

A "memory above N%" alert is not enough. Pressure inside one account's cgroup does not move it.
**[ran]** Alert on:

- **The line `giving up` in a server journal.** It means an environment is gone.
- Swap use, load and memory pressure (`/proc/pressure/memory`).
- Disk above 85%.
- Each account's sign-in status (section 10.6).

Confirm that each alert has a notification channel, and test it.

## 11. Background sessions from scripts

A script, cron job or timer can start a session that shows up on your phone.

```bash
cd ~/projects/workspace
claude --bg --remote-control "nightly-report" -n "nightly-report" "Write the nightly report" </dev/null
```

The working folder decides which `CLAUDE.md` and memory load. **[ran]**

- `--bg` alone is local. You will not see the session on your phone. `--remote-control` surfaces
  it. **[ran]**
- `-n` sets the title. Pass both. **[ran]**
- The session inherits the user's settings. It starts in `permissions.defaultMode`, unless you
  pass `--permission-mode`. **[ran]**
- **Close stdin.** The `claude` CLI appends piped stdin to the prompt. A heredoc around the command
  sends the rest of your script to the session. **[ran]**

**Inspect:**

```bash
claude agents --json
claude logs <id>
```

- `claude agents --json` can delete the registry files of dead sessions while it lists them, so
  it is not read-only. **[seen]** For a pure read, open `~/.claude/jobs/<id>/state.json`.
- The transcript is the reliable record: `~/.claude/projects/<slug>/<uuid>.jsonl`.
- `idle` does not mean finished. A session with a background task reads `idle` until that task
  ends. **[ran]**

**Stop or redirect:**

- To quiet a noisy session, send it a message. `claude stop <id>` also kills its subagents.

**Idle retirement. [seen]** The daemon retires an idle background session: after about 1 hour for
a plain `--bg` session, and about 8 hours for a `--remote-control` one. It then shows offline in
claude.ai, and a message from the web does not wake it. A session waiting for your decision
retires too. Pin a session in the `claude agents` view with Ctrl+T to keep it alive. A pinned idle
session costs no tokens and about 200 MB of memory.

**Resume:**

```bash
cd <original-session-folder>
claude --bg --resume <full-session-uuid> "<message>" </dev/null
```

- **Pass no other flags.** A background session keeps its saved options. Extra flags start a copy
  under a new ID, on a new thread. **[ran]**
- Use the local session UUID, not the `session_...` ID in the URL. **[ran]**
- `claude remote-control --session-id` is for a session on a server environment, not a `--bg`
  session. **[ran]**
- **A wake delivers queued messages.** If you typed into the thread while it was offline, the
  session acts on that text at once, in its permission mode. A queued "yes" can trigger the
  action it answered. Check the thread before you wake it. **[ran]**

**Schedule it:**

- **Cron:** set an explicit `PATH` line and use absolute interpreter paths. Cron's default PATH is
  short. Test the command first with `env -i HOME=<home> PATH=<path>`. **[ran]**
- **Cron table:** tag your lines with a comment, so you can remove only your own. Never pipe
  `crontab -l` directly into a filter and back: a failed read erases the table. **[ran]**
- **systemd oneshot unit:** set `KillMode=process`. The default kills all children when the unit
  exits, which kills every session it just started. **[ran]**
- **Check the sign-in before every spawn** (`claude auth status`), and fail with an alert. With a
  wiped login, each session prints `Login expired` and idles, while your job logs success. **[ran]**
- `systemctl --user` through `sudo -iu` needs `XDG_RUNTIME_DIR=/run/user/$(id -u)`. **[ran]**

## 12. Security model

**A VM session is a remote shell that holds your credentials.** Anyone who can message a session
can run commands on the VM. Protect the Claude account like a root login.

### Permission modes

| Mode | Behavior on a VM |
|---|---|
| `bypassPermissions` | Every tool call runs with no prompt. Bash, edits and deletes run unsupervised on an always-on VM. See the warning below. |
| `auto` | Background safety checks allow safe actions and gate risky ones. All plans can use it, with a supported model. **[docs]** After 3 blocks in a row, or 20 in a session, it pauses and prompts again, so a session can wait for you. **[docs]** Sessions started from the mobile app run in this mode anyway, whatever the server flag says. **[seen]** |
| `default` | Prompts for each risky action. Safest, but a stalled prompt stops unattended work. |

**Warning about `bypassPermissions`.** Anthropic says to use it only in isolated environments
without internet access, and that it offers no protection against prompt injection or unintended
actions. **[docs]** An always-on VM with network access and credentials is not that kind of
environment. Any web page, file or tool result a session reads can try to steer it. Choose this
mode only if you understand that risk, and limit what the VM can reach. Claude Code refuses to
start in this mode as root. **[docs]**

### Rules

1. **No sudo for any user that runs a server.** With sudo, one session can restart or read
   every other account. Check again at the end of each build.
2. **Home folders are mode 750.** Each account must not read another account's files.
3. **Never write a secret to `/tmp`.** Default `/tmp` files are world-readable, so on a shared VM
   any account reads them. A one-line redirect such as `get-secret > /tmp/x` does this. Use a
   variable, pipe straight to the consumer, or use `mktemp` (mode 600).
4. **Keep secrets in a secret manager,** and fetch them at run time. Do not keep `.env` files.
5. **Do not sign a person's cloud account in on the VM.** Unattended jobs and agents use service
   identities. A person's login also adds that person's full reach to every session.
6. **Keep the VM's identity narrow.** Grant elevated access on demand, by impersonation, with no
   key file. Alert on key creation.
7. **No sudo is not a cloud boundary.** Every Linux user can reach the metadata server, so every
   account can use the VM's attached identity. To block one user, as root:

   ```bash
   iptables -I OUTPUT -d 169.254.169.254 -p tcp --dport 80 -m owner --uid-owner <uid> -j REJECT
   ```

   Add it to a oneshot unit, so it returns after a reboot. Block port 80 only: on Google Cloud
   the same address also serves DNS. Then give that user its own identity.
8. **Delay is a security trade.** Weekly OS upgrades (section 5.4) mean a patch can wait seven days.
9. **Think before you wake a session.** See section 11.

### Guard hooks

A `PreToolUse` hook that returns `deny` works under `bypassPermissions`, in foreground and
background sessions. **[ran]** Use hooks for the few things that must never happen, for example a
push to your main branch.

- User-level hooks live in `~/.claude/settings.json`. A session can edit that file. To stop this,
  make the file root-owned and `chattr +i`.
- Immutable settings drop the `bypassPermissions` acceptance. Add
  `skipDangerousModePermissionPrompt: true` to the file before you lock it. **[seen]**
- File-based managed settings are ignored when the signed-in organization has server-managed
  settings. Claude Code uses one managed source. **[seen]**
- A hook is a seatbelt, not a sandbox. It sees the patterns you match, and nothing else.

## 13. Optional add-ons

**Other model CLIs (Codex, Gemini).** Install them system-wide, once. Each user needs its own
login. For Codex on a headless VM: `codex login --device-auth`, then approve in your browser.
**[ran]** The [`review-swarm`](../skills/review-swarm/SKILL.md) skill uses these CLIs.

- Put `timeout -k` around any review CLI call. A stuck one can hold a CPU core for hours. **[ran]**
- Codex sandboxes leave orphaned process trees during parallel runs. Clean them up. **[ran]**
- `codex exec` reads stdin. Give it `</dev/null` inside scripts. **[ran]**

**Codex sandbox on Ubuntu 24.04.** Every Codex sandbox tier fails with
`bwrap: setting up uid map: Permission denied`, because Ubuntu restricts unprivileged user
namespaces. **[ran]** Fix it with Ubuntu's own `bwrap-userns-restrict` AppArmor profile, on
`/usr/bin/bwrap`:

- Take the profile text from Ubuntu's `apparmor` source package, for your release.
- Load it with `sudo apparmor_parser -r /etc/apparmor.d/bwrap-userns-restrict`.
- Do not add a second profile for the same path.
- Do not turn off `kernel.apparmor_restrict_unprivileged_userns` for the whole machine.

**MCP servers.** Each server is at least one process per session. Install only what you use.

**Plugins and skills.** Install per account:

```text
/plugin marketplace add itgenius-au/skills-library
/plugin install skills-library@skills-library
```

Useful skills from this library for a VM: [`session-wrap`](../skills/session-wrap/SKILL.md),
[`session-dsp`](../skills/session-dsp/SKILL.md),
[`session-status-sweep`](../skills/session-status-sweep/SKILL.md),
[`repo-cleanup`](../skills/repo-cleanup/SKILL.md) and
[`dev-update-env`](../skills/dev-update-env/SKILL.md).

**Transcript capture.** Transcripts are plain JSONL files under `~/.claude/projects`. Hooks or a
timer can copy them to a data warehouse for audit and recall. Use a service identity for the
copy job.

**A dedicated agent user.** For a scheduled agent that must not reach your other accounts, add a
Linux user with no Remote Control unit. Give it its own Claude seat, its own service identity,
its own per-secret grants, and the metadata block from section 12. Mount any shared data
read-only, under a neutral path.

## 14. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Unit is active, no environment appears, journal is silent after the banner | `Enable Remote Control? (y/n)` is waiting | Section 6, Step 7 |
| `Workspace not trusted` | Folder was never trusted | Run `claude` in that folder once, as that user |
| `requires a full-scope login token` | `setup-token` or `CLAUDE_CODE_OAUTH_TOKEN` | Unset it. Use `/login`. |
| `requires a claude.ai subscription` | `ANTHROPIC_API_KEY` is set, or the sign-in is an API one | Unset it. Use `/login`. |
| `disabled by your organization's policy` | The org toggle is off | An Owner turns it on |
| Empty sidebar, "Claude Code isn't available on your account" | Wrong organization is active | Switch organization in claude.ai. Do not touch the VM. |
| "Needs to sign in again", `OAuth session expired` | Login was emptied | Section 10.6 |
| Sessions fail one by one, `Environment env_... not found`, server stays up | The saved login changed under a running server | Section 9.6 |
| `Server unreachable for 11 minutes, giving up.` | Network outage | The wrapper restarts it. The old environment is gone. See below. |
| Many reconnect lines, short dropouts | NAT source-port limit | Raise the limit. Section 16. |
| `Capacity: 0/100` after a restart | Normal | Send each session one message |
| Session shows offline, a web message does nothing | Idle retirement of a `--bg` session | Section 11, Resume |
| Service restarted, `NRestarts=0`, no error | `needrestart` during an OS upgrade | Check `/var/log/apt/history.log`. Section 5.4. |
| High load, processes in `D` state, free memory looks fine | One account is over `MemoryHigh`, and the kernel keeps evicting its files | Read `memory.events` in the unit's cgroup. Give it headroom, or stop the load. Do not add a CPU cap. |
| Swap full, load high, SSH times out | Box-wide memory starvation | Use the serial console. Keep every query cheap. Find and kill the largest process. |
| One account is slow, its service looks healthy | Another account is filling memory or swap | Check `free` and the other cgroups first |
| `command not found` for a tool that is installed | `~/.local/bin` is not on the tool shell's PATH | Section 8, the PATH fix |
| MCP server fails with `ENOENT` | The launcher has no login PATH | Use an absolute path |
| `Author identity unknown` | No global git identity | Section 6, Step 2 |
| `Environment env_... is already being served by another` | A server already runs in that folder | Use a different worktree folder, or stop the server. Never switch to an unrelated folder. |
| `bwrap: setting up uid map: Permission denied` | Ubuntu 24.04 AppArmor | Section 13 |
| `You've hit your org's monthly spend limit`, then a reset time | The plan's 5-hour limit was hit, and extra usage is off | Wait, or run fewer parallel sessions. Five parallel sessions used a Standard Team seat's window in about an hour. |
| "This session's environment was deleted" | The environment is gone | History stays readable. Start a new session with a hand-off note. |

**Recover after a long outage.** Do not restart the service: that orphans the live sessions too.
**[ran]** The environment cannot be revived. Sessions from it stay readable in claude.ai. For
about four hours after a server stops, you can reattach them one at a time: **[docs]**

```bash
tmux new -d -s reattach "cd <a trusted folder> && claude remote-control --session-id <id>"
```

- It is one-shot: it exits when that session ends. It is a recovery tool, not a durable setup.
- Run reattaches one at a time, and check the session name in the first reply. On an older CLI,
  the server ignored the ID we passed and handed back a different orphaned session. **[seen]**
- A reattached session stays idle until you send it one message.
- Stop a reattach by killing its tmux session, not by PID.
- Use it only when the environment is gone. On a live environment, send a message instead. A
  reattach there can take the session from its worker, and it cut that environment's session
  limit to 1 until the next restart. **[seen]**

**First moves on a sick VM:**

1. Read `free -m` first. Keep every later query cheap.
2. Read `vmstat 5 3`. High `wa` with high `bi` is disk thrash from memory pressure. High `us` is
   real CPU load.
3. Read `memory.events` and `memory.pressure` for each unit under
   `/sys/fs/cgroup/system.slice/`.
4. Kill by exact PID. `pkill -f` over SSH can match your own shell.
5. Never message or stop a session to check on it. Read its transcript.

## 15. Definition of done

**For every account:**

- [ ] The unit is active, with `NRestarts=0` and a stable inner PID.
- [ ] `claude auth status --text` shows the expected email and organization.
- [ ] `accountUuid` differs from every other account, and `organizationUuid` is the one you expect.
- [ ] `sudo -l -U <user>` says no sudo, and `id` shows no sudo-like group.
- [ ] The running server has no sudo group: `ps -o supgrp= -p <MainPID>`.
- [ ] You chose the permission mode on purpose, and you read section 12.
- [ ] Home is mode 750, and `.credentials.json` is mode 600.
- [ ] `git config --global user.email` is set.
- [ ] `settings.json` has both updater keys.
- [ ] `command -v claude` resolves to the system copy.
- [ ] A new session answers `id -un` with the right user.
- [ ] The token check says `OK`, and you recorded the expiry date.

**For the VM:**

- [ ] No public SSH. Remote Control works with no inbound ports.
- [ ] Each unit has a needrestart exclusion.
- [ ] `apt-daily-upgrade.timer` shows one weekly entry.
- [ ] The nightly update timer is active.
- [ ] Snapshots run, and you know how to restore one.
- [ ] Metrics flow, and each alert reaches a person.
- [ ] A reboot test passes: every server returns with no help.

## 16. Provider notes

### Google Cloud (run by us)

**Do not SSH in as the account user. [seen]** `gcloud compute ssh claude-1@<vm>` writes that
user's key to project metadata. With OS Login off, the guest agent then adds the user to the
`google-sudoers` group, with passwordless sudo. A mistyped user name gets the same treatment.
`gpasswd -d` does not stick while the key is there.

- Always use `gcloud compute ssh admin@<vm> --tunnel-through-iap`, then `sudo -iu claude-1`.
- Check the key list: read the `ssh-keys` item in `gcloud compute project-info describe`. Only
  your admin user may appear.
- To fix it, remove only that user's line from the `ssh-keys` value. The guest agent then removes
  the group. A running service keeps the group until its next restart.

**Other providers:** check whether your provider's agent manages SSH users and sudo groups.

**Cloud NAT. [ran]** The default of 64 ports per VM is too low. Claude processes connect to a few
Anthropic IP addresses, closed ports wait 120 seconds, and each dropped connection triggers another
reconnect. Turn on dynamic allocation and error logging:

```bash
gcloud compute routers nats update <nat> --router <router> --region <region> \
  --enable-logging --log-filter=ERRORS_ONLY
gcloud compute routers nats update <nat> --router <router> --region <region> \
  --enable-dynamic-port-allocation --min-ports-per-vm=64 --max-ports-per-vm=32768
```

Neither command restarts the server.

**Disks. [ran]**

- Grow online with `gcloud compute disks resize`, then `growpart` and `resize2fs`.
- A clone with `--source-disk` refuses a type change. To change type: stop the VM, snapshot the
  disk, create a new disk from the snapshot, swap the boot disk, start the VM.
- E2 machine types do not support Hyperdisk or Local SSD.

**Monitoring. [ran]** The service account needs `monitoring.metricWriter`, and any reader needs
`monitoring.viewer`. Without the viewer role, a chart can show blanks with no error.

**gcloud identity. [ran]**

- A person's `gcloud` login fails in a session with no terminal: `Reauthentication failed. cannot
  prompt during non-interactive execution`. Keep the default config on a service account.
- If a person must log in once, set `CLOUDSDK_CONFIG` to a separate folder, then revoke the
  login afterwards.
- A Claude `/login` and a `gcloud auth login` are unrelated. Neither one helps the other.
- `gcloud` lives in `/snap/bin` on Ubuntu. Add that to the `PATH` of cron jobs.

### Other providers

We have not run this setup on another provider. Sections 1 to 15 use Linux, systemd and Claude
Code, so they should carry over. Sections 5.4, 5.5 and 13 assume Ubuntu. Check these items first:

- Which identity the VM gets by default, and what it can reach.
- Whether a cloud agent manages users, SSH keys or sudo groups.
- The NAT gateway's limit on ports per VM.
- Whether a stop keeps the disk, and what it costs.
