#!/usr/bin/env python3
"""Read-only check of Claude Code login health for accounts on a shared VM.

Usage: token_status.py [--home-root DIR] [--due-days N] [--now-ms MS] ACCOUNT [ACCOUNT ...]

Reads <home-root>/<account>/.claude/.credentials.json for each account and prints one
verdict line per account (OK, DUE, EXPIRED, WIPED or UNKNOWN) plus a SUMMARY line.
A failed refresh "wipes" the file (empty tokens, expiresAt 0); refresh tokens die about
4 weeks after login, so DUE/EXPIRED warns before that happens. DUE means the refresh token
expires within --due-days days (default 3).

It never writes anything and never prints token values, file contents or JSON fragments.
It fails closed: any parse problem is UNKNOWN, never OK.

Exit codes: 3 if any UNKNOWN; else 1 if any WIPED, EXPIRED or DUE; else 0; 2 = usage error.
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

DAY_MS = 86400000
VERDICTS = ("OK", "DUE", "EXPIRED", "WIPED", "UNKNOWN")


def nonneg_int(value):
    try:
        n = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not an integer: {value!r}")
    if n < 0:
        raise argparse.ArgumentTypeError("must be >= 0")
    return n


def valid_account(name):
    return bool(name) and "/" not in name and name not in (".", "..")


def fmt_ms(ms):
    """Format a ms epoch as UTC text, or 'none' when missing, 0 or unparseable."""
    if not isinstance(ms, int) or isinstance(ms, bool) or ms <= 0:
        return "none"
    try:
        return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    except (OverflowError, OSError, ValueError):
        return "none"


def in_range(ms):
    """True when a positive ms epoch converts to a datetime (a microseconds value does not)."""
    try:
        datetime.fromtimestamp(ms / 1000, timezone.utc)
        return True
    except (OverflowError, OSError, ValueError):
        return False


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def has_token(v):
    return isinstance(v, str) and v != ""


def assess(path, now_ms, due_days):
    """Return (verdict, access_yes, refresh_yes, access_expires, refresh_expires, detail)."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return "UNKNOWN", False, False, None, None, "file_missing"
    except Exception as ex:  # class name only: the message could quote file content
        return "UNKNOWN", False, False, None, None, type(ex).__name__
    if not isinstance(data, dict):
        return "UNKNOWN", False, False, None, None, "top_level_not_object"
    oauth = data.get("claudeAiOauth")
    if not isinstance(oauth, dict):
        return "UNKNOWN", False, False, None, None, "claudeAiOauth_missing_or_not_object"

    access, refresh = oauth.get("accessToken"), oauth.get("refreshToken")
    exp, rexp = oauth.get("expiresAt"), oauth.get("refreshTokenExpiresAt")
    a_yes, r_yes = has_token(access), has_token(refresh)

    def out(verdict, detail):
        return verdict, a_yes, r_yes, exp, rexp, detail

    for key, v in (("expiresAt", exp), ("refreshTokenExpiresAt", rexp)):
        if key in oauth and (not is_int(v) or v < 0):
            return out("UNKNOWN", f"{key}_not_nonneg_int")
    # An absurdly large value would otherwise compare as "far future" and read as OK.
    if any(oauth.get(k) and not in_range(oauth[k]) for k in ("expiresAt", "refreshTokenExpiresAt")):
        return out("UNKNOWN", "expiry_out_of_range")
    # A token field of the wrong type is not "empty", so do not call it wiped.
    for key in ("accessToken", "refreshToken"):
        if key in oauth and not isinstance(oauth[key], str):
            return out("UNKNOWN", f"{key}_not_string")

    if not a_yes or not r_yes or ("expiresAt" in oauth and exp == 0):
        return out("WIPED", "tokens_empty_or_expiresAt_zero")
    # Tokens present but no expiresAt at all: an unfamiliar shape, not a wipe.
    if "expiresAt" not in oauth:
        return out("UNKNOWN", "expiresAt_missing")
    if not rexp:
        return out("UNKNOWN", "refreshTokenExpiresAt_missing_or_zero")
    left = rexp - now_ms
    if left <= 0:
        return out("EXPIRED", "refresh_token_expired")
    if left <= due_days * DAY_MS:
        return out("DUE", f"refresh_expires_in_{left // 3600000}h")
    return out("OK", "ok")


def main():
    p = argparse.ArgumentParser(description="Read-only Claude login health check.")
    p.add_argument("--home-root", default="/home")
    p.add_argument("--due-days", type=nonneg_int, default=3,
                   help="DUE when the refresh token expires within this many days (default 3)")
    p.add_argument("--now-ms", type=nonneg_int, default=None)
    p.add_argument("accounts", metavar="ACCOUNT", nargs="+")
    args = p.parse_args()
    for acct in args.accounts:
        if not valid_account(acct):
            p.error(f"invalid account name: {acct!r}")
    now_ms = args.now_ms if args.now_ms is not None else int(time.time() * 1000)

    counts = dict.fromkeys(VERDICTS, 0)
    for acct in args.accounts:
        path = os.path.join(args.home_root, acct, ".claude", ".credentials.json")
        verdict, a_yes, r_yes, exp, rexp, detail = assess(path, now_ms, args.due_days)
        counts[verdict] += 1
        print(f"{acct} {verdict} access={'yes' if a_yes else 'no'} refresh={'yes' if r_yes else 'no'} "
              f"access_expires={fmt_ms(exp)} refresh_expires={fmt_ms(rexp)} detail={detail}")
    print("SUMMARY " + " ".join(f"{k.lower()}={counts[k]}" for k in VERDICTS if k != "UNKNOWN")
          + f" unknown={counts['UNKNOWN']}")

    if counts["UNKNOWN"]:
        return 3
    if counts["WIPED"] or counts["EXPIRED"] or counts["DUE"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
