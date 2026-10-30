# Sign-in lost, or due soon

Read this file when its row in SKILL.md applies. `vmssh`, `vmcp`, `SKILL_DIR`, the rules and the numbered Steps (1 to 6) are defined in SKILL.md. Section numbers refer to [`docs/claude-code-vm-setup-spec.md`](../../../docs/claude-code-vm-setup-spec.md).

## Sign-in lost: "Claude Code on your computer needs to sign in again"

claude.ai shows this when one account's OAuth token refresh is rejected. Claude Code then empties
that account's `~/.claude/.credentials.json`, and every process of that account fails with "OAuth
session expired and could not be refreshed". Skip Steps 1-5 of SKILL.md. Stay read-only, and never
print token values. Guide section 10.6 has the background.

**Likely cause. [seen], not proven.** A refresh token expires about 4 weeks after the login that
made it (27 to 30 days in our cases), and renewals do not extend it. About 8 hours after it
expires, the next access-token renewal fails and the wipe follows. So the wipe can be predicted
from `refreshTokenExpiresAt`, and prevented by a same-account re-login before it (see "Sign-in due soon"
below).

1. **Map the claude.ai computer tile to its Linux account.** Use the server name (`--name`, for
   example `VM-1`), the unit and the account table in guide section 9.1.
2. **Check the token fields, not the email.** `~/.claude.json` keeps `oauthAccount.emailAddress`
   after a wipe, so a fresh `claude` still looks signed in. Run `scripts/token_status.py` as root
   for this account and every other account on the box. It prints presence and expiry only, never a
   token value:
   ```bash
   vmssh 'mkdir -p -m 700 vm-ops'
   vmcp "${SKILL_DIR}/scripts/token_status.py"
   vmssh "sudo -n python3 -I vm-ops/token_status.py <account> <other accounts>"
   vmssh "sudo -n stat -c 'creds mtime: %y' /home/<account>/.claude/.credentials.json"
   ```
   Use the private `vm-ops` folder and `-I` for the reasons in Step 4 of SKILL.md, and stop if the copy fails.
   Run the `stat` as its own command, so the script's exit code stays visible. A session that runs
   on the VM runs as its own `claude-N` account, with no sudo, so it can check only its own account:
   `python3 -I "${SKILL_DIR}/scripts/token_status.py" <its own account>`. Other accounts' homes are
   closed to it (mode 750): checking them needs an admin shell, as in the commands above. One line
   per account:
   - `WIPED`: empty tokens or `expiresAt` 0. A failed refresh wiped the file, and the `mtime` is the
     wipe time. Fix it with step 5, after the owner's go.
   - `EXPIRED`: the refresh token has expired. The next renewal (within about 8 hours) will wipe the
     file. Offer a re-login now with step 5; it starts only on the owner's go.
   - `DUE`: the refresh token expires within 3 days (`--due-days` changes this). Offer a re-login
     now; it starts only on the owner's go.
   - `OK`: nothing to do. `UNKNOWN`: the file could not be read or judged; check it by hand.

   Exit code 0 = all `OK`, 1 = some account needs a re-login, 3 = some `UNKNOWN`, 2 = usage error.
3. **Find who saw the error first.** List the session transcripts that the account wrote within
   about 30 s of the wipe (`find /home/<account>/.claude/projects -newermt <wipe-30s> ! -newermt
   <wipe+15s>`). Grep them for `could not be refreshed`, and grep
   `/home/<account>/.claude/daemon.log` for `auth:` to see the daemon's refresh schedule. Some
   accounts have no `daemon.log`; then skip that grep and read the account's tile in claude.ai
   instead. If no transcript was written near the wipe, that fits the likely cause above: an idle
   account whose own renewal failed.
4. **Rule out local writers.** Anything else on the box that touches the credentials file, for
   example a monitor, a cron job or a copy script: compare its run times with the wipe time. Check
   `last <account>` for unexpected logins.
5. **Fix: re-login by link.** The owner does not need a terminal, but they must sign in, so **ask
   for their go before you start the login**. Use this only to log back in to the SAME account. To
   change the account, follow guide section 9.6 (stop, sign in, start). Do not restart the Remote
   Control service: the running server picks up the new token **[ran]**.
   - Record the baseline first: `vmssh 'systemctl show <unit> -p MainPID -p NRestarts'`. The last
     check compares against these values.
   - Start the login as that account in tmux. The wide pane keeps the URL on one line:
     ```bash
     vmssh 'sudo -n -iu <account> tmux new -d -s relogin -x 400 -y 50 "claude auth login --claudeai --email <account email>; sleep 1800"; sleep 8;
       sudo -n -iu <account> tmux capture-pane -p -J -t relogin'
     ```
   - Give the owner the `https://claude.com/cai/oauth/authorize?...` URL from the pane. They sign in
     as the account email and pick the organization whose seat includes Claude Code (guide section
     6, Step 6); a Team org without Claude Code shows "isn't available". The page then shows a
     one-time code.
   - The owner pastes the code into the pane (`sudo -iu <account> tmux attach -t relogin`), or gives
     it to you in chat. A code given in chat is the owner's go to enter it. Enter it at once; never
     print or store it anywhere else. The code works once, and only for the login process that waits
     in the pane, because that process holds the PKCE secret:
     ```bash
     vmssh "sudo -n -iu <account> tmux send-keys -t relogin -l '<code>'; sudo -n -iu <account> tmux send-keys -t relogin Enter"
     ```
     The pane prints `Login successful.` If the code was rejected or the pane timed out, kill the
     tmux session and start again; a new pane gives a new URL.
   - Check `sudo -n -iu <account> claude auth status --text`: logged in, with the expected email and
     organization. Then kill the tmux session, re-run check 2, and run the same `systemctl show`
     again. Both values must match the baseline. A changed value means the service restarted:
     report it, and check the sessions (Step 4 of SKILL.md).
   - **When the session runs as that account** (a session on the VM runs as its own `claude-N`
     account, with no sudo), drop `sudo -n -iu <account>` from every command above. Plain `tmux`,
     `claude auth status` and `systemctl show` work, for that one account only. Any other account
     needs an admin shell.
6. **Resume the casualties.** Sessions that failed mid-turn stop on the error and do not retry. Each
   needs one message. List them, read-only, with `scripts/scan_casualties.py` run as root. Copy it
   to the VM as in check 2, then:
   ```bash
   vmssh "sudo -n python3 -I vm-ops/scan_casualties.py --since '<start time>' <account>"
   ```
   A session on the VM has no sudo: it runs `python3 -I "${SKILL_DIR}/scripts/scan_casualties.py"`
   with the same arguments, for its own account only. Other accounts need an admin shell. For
   `<start time>`, use the wipe time minus 10 minutes: a session that failed on an earlier rewrite
   of the file has an older transcript. It takes an ISO time such as `2025-03-04T20:11:00Z`, or the
   `creds mtime` value from check 2 as printed; a time with no offset is read as UTC. The `SUMMARY`
   line shows the start time it used (`since=`): check it before you trust a short list.
   - `STOPPED <session id> ... ask="..."`: the session stopped on the error. `ask` is the start of
     the message that failed. Give the owner the list; the owner sends each one again. Never message
     a session yourself to test it.
   - `RECOVERED`: a normal assistant reply came after the last error. Nothing to do. (A later user
     message or notification with no reply still counts as `STOPPED`.)
   - `PARTIAL`: the transcript's last line was half-written (a write in progress). Run the scan once
     more; if it is still `PARTIAL`, read that transcript by hand.
   - `UNREADABLE`: a transcript or folder could not be read, or an entry it needs is malformed;
     check it by hand.

   It judges a session from all its transcript files together (a session that moved to another
   project folder has one file in each), so `project=` can list more than one folder. The `ask` text
   has token-like strings replaced with `[REDACTED]`. Exit code 3 = some `UNREADABLE` or `PARTIAL`,
   else 1 = some `STOPPED`, else 0.

   It matches only the API error entry Claude Code writes: an assistant entry with
   `isApiErrorMessage: true` and either `error: "authentication_failed"` or the text "OAuth session
   expired" / "could not be refreshed". It never matches assistant prose, tool output or pasted text
   that quotes the error. **Positive control:** if check 3's grep found a transcript with the error
   that the scan does not list, treat the scan as unproven and read that transcript by hand. Also
   check any scheduled job that starts Claude sessions on that account (cron, timers): during the
   gap each of its sessions prints `Login expired` and idles, while the job's own log reports
   success (guide section 11).
7. **Check every other account before you finish.** Run check 2 for all accounts, from an admin
   shell (a session on the VM sees only its own). Offer a re-login for any `EXPIRED` or `DUE`
   account now (see "Sign-in due soon" below), on the owner's go. Record each account's
   `refresh_expires` in your ops notes. Checking all accounts can find a second account whose
   refresh token has already expired, with its wipe still pending.

Use a narrow `journalctl --since/--until` window (guide section 5.5). A broad `--since -36h | grep`
on a Remote Control unit can run for minutes on a busy box.

## Sign-in due soon: re-login before the wipe

Use this to check when each account's sign-in will lapse, or to stop a wipe that is coming. It
prevents the outage that "Sign-in lost" repairs. Skip Steps 1-5 of SKILL.md.

1. **Read every account's expiry.** Run check 2 of "Sign-in lost" (`token_status.py`) for all
   accounts on the box, from an admin shell.
2. **Offer a re-login for each `EXPIRED` or `DUE` account now, and run it on the owner's go,** with
   step 5 of "Sign-in lost": same account, by link, no restart. That step ends with check 2: the
   account must read `OK`, with a new `refresh_expires` about 4 weeks out. Running processes appear to re-read the file before they
   renew **[seen]**; step 3 checks it. In the one case we tested, a re-login before the old access
   token ran out kept the account signed in and the service kept its PID.
3. **Check again after the old access token's expiry time** (the `access_expires` value read in step
   1): run `token_status.py` once more. The account must read `OK`, and `systemctl show` must match
   the baseline. A `WIPED` result means a process renewed with the old token: run step 5 once more, on
   the owner's go.
4. **Line the accounts up, if the owner agrees.** When several accounts fall due within a week of
   each other, offer to re-login them together, so their expiries stay together and one reminder
   covers them all. Each extra re-login is one more sign-in for the owner, so do it only on their go.
5. **Record.** Write each account's new `refresh_expires` in your ops notes, and tell the owner the
   earliest date.

