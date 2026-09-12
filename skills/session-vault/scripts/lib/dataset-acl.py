#!/usr/bin/env python3
"""Add a dataset-scoped WRITER (BigQuery dataEditor) access entry for a service account.

Reads a `bq show --format=prettyjson <dataset>` resource on stdin, adds a WRITER entry for the
given SA email if not already present (idempotent), and writes the updated resource to stdout for
`bq update --source`. Used by setup-vault.sh to grant dataset-scoped dataEditor instead of a
project-level IAM binding. Stdlib only.
"""

import json
import sys


def main():
    if len(sys.argv) != 2:
        print("usage: dataset-acl.py <sa-email>  (dataset JSON on stdin)", file=sys.stderr)
        return 2
    sa = sys.argv[1]
    d = json.load(sys.stdin)
    access = d.get("access", [])
    if not any(e.get("role") == "WRITER" and e.get("userByEmail") == sa for e in access):
        access.append({"role": "WRITER", "userByEmail": sa})
        d["access"] = access
    json.dump(d, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
