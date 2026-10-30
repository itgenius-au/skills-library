# Disk full

Read this file when its row in SKILL.md applies. `vmssh`, `vmcp`, `SKILL_DIR`, the rules and the numbered Steps (1 to 6) are defined in SKILL.md. Section numbers refer to [`docs/claude-code-vm-setup-spec.md`](../../../docs/claude-code-vm-setup-spec.md).

## Disk full: "No space left on device"

Writes fail and `df -h /` reads 100%. Skip Steps 1-5 of SKILL.md, except the Step 4 inventory that the
cleanup check below uses. On a busy VM the disk fills by gigabytes a day
(session scratch folders, package caches, old plugin versions, an uncapped syslog; guide section
4), so measure first, offer cleanup, and grow the disk only if cleanup is not enough.

1. **Measure.** Find what fills the disk, and the device behind `/`:
   ```bash
   vmssh 'df -h /; lsblk; sudo -n du -xh --max-depth=1 / 2>/dev/null | sort -rh | head -10;
     sudo -n du -xh --max-depth=2 /home /tmp 2>/dev/null | sort -rh | head -20;
     ls -la /var/log/syslog*; sudo -n journalctl --disk-usage'
   ```
   Compare with the last size and use% in your ops notes to get the growth rate. Also find the
   cloud disk that backs the VM and the time of its last snapshot, with your provider's console or
   CLI. Worked example, Google Cloud:
   ```bash
   gcloud compute instances describe "$VM" --project "$PROJECT" --zone "$ZONE" \
     --format='value(disks[0].source.basename())'
   gcloud compute snapshots list --project "$PROJECT" --sort-by=~creationTimestamp --limit 1 \
     --format='table(name,creationTimestamp,status)'
   ```
2. **Offer cleanup** as a sized list (guide section 10.7). Delete nothing without approval. These
   all rebuild themselves:
   - `~/.npm/_cacache`, `~/.npm/_npx`, `~/.cache/uv`, `~/.cache/pip`, for every account and root.
   - Session scratch folders `/tmp/claude-<uid>/<project>/<session>/` idle 3+ days
     (`find /tmp/claude-* -mindepth 2 -maxdepth 2 -type d -mtime +3`). Leave newer ones:
     long-running Remote Control sessions own them. **`-mtime` tests the folder's own modification
     time,** which changes only when an entry is added to it or removed from it, so a live session
     can own a folder that looks old. Before you delete any of them, cross-check each `<session>`
     name against the `uuid` values of the live sessions in the Step 4 inventory (SKILL.md), and keep
     every folder that a live session id names. Step 4 needs room to copy its script: if the copy
     fails on a full disk, free the caches in the first bullet, then run it.
   - Other top-level `/tmp` items idle 7+ days (uv caches, review sandbox copies).
   - Old plugin versions in `~/.claude/plugins/cache/<marketplace>/<plugin>/`. Keep the newest few
     and any version a live session loaded.
   - An uncapped `/var/log/syslog`: propose a logrotate `maxsize` (guide section 5.5).

   Never delete backups, worktrees, or transcripts under `~/.claude/projects`.
3. **Grow the disk** on approval. A disk cannot shrink back. First fetch the live per-GiB price for
   the disk type and region from your provider's pricing page and give the monthly increase.
   Confirm a snapshot from today exists in a ready state, or take one. Then resize the cloud disk
   with your provider's tool, and grow the partition and file system online, with no reboot:
   ```bash
   vmssh 'sudo -n growpart /dev/sda 1; sudo -n resize2fs /dev/sda1; df -h /'
   ```
   Check the device and partition with `lsblk` first: they are not always `sda` and `sda1`.
   `growpart` exits 1 with `NOCHANGE` when the partition already fills the disk. Worked example,
   Google Cloud, for the resize step (it needs `compute.disks.resize`):
   ```bash
   gcloud compute disks resize "$DISK" --size=<new>GB --zone "$ZONE" --project "$PROJECT" --quiet
   ```
   `DISK` is the name the first example command printed.
4. **Verify and record.** `df -h /` shows the new size. No Remote Control service restarted
   (`vmssh 'systemctl show claude-remote-control-1 -p MainPID -p NRestarts'` for each unit). Record the new
   size, the cost, the rollback snapshot, the growth rate, and any deferred cleanup in your ops
   notes.

