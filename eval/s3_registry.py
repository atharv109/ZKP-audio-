#!/usr/bin/env python
"""eval/s3_registry.py -- S3 Minnah-style local hash registry (simulated, no chain).

Registry JSON schema (eval/s3_registry.json):
    { "<file_sha256_hex>": {"metadata": {...}, "issued_at": "<ISO-8601 UTC>"} }

ACCEPT iff the presented file's sha256 hex is an enrolled key. Nothing else
is stored or checked (no detector score, no signature, no context).

Usage:
    python eval/s3_registry.py enroll <sha256hex> <metadata_json_or_inline>
    python eval/s3_registry.py lookup <sha256hex>
Prints exactly one line: "ACCEPT ..." or "REJECT ..." to stdout.
"""
import json
import os
import sys
from datetime import datetime, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REG = os.path.join(REPO, "eval", "s3_registry.json")


def load() -> dict:
    if os.path.exists(REG):
        with open(REG) as f:
            return json.load(f)
    return {}


def save(reg: dict) -> None:
    with open(REG, "w") as f:
        json.dump(reg, f, indent=2, sort_keys=True)
        f.write("\n")


def main() -> int:
    args = sys.argv[1:]
    if len(args) < 2 or args[0] not in ("enroll", "lookup"):
        print("usage: s3_registry.py enroll <sha256> <metadata_json> | lookup <sha256>",
              file=sys.stderr)
        return 2
    mode, sha = args[0], args[1].lower()
    if not (len(sha) == 64 and all(c in "0123456789abcdef" for c in sha)):
        print("REJECT malformed sha256")
        return 2
    reg = load()
    if mode == "lookup":
        if sha in reg:
            e = reg[sha]
            print(f"ACCEPT enrolled (issued_at={e['issued_at']})")
            return 0
        print("REJECT hash not enrolled")
        return 1
    # enroll: refuses duplicate keys (fresh-registry discipline)
    meta = json.loads(args[2]) if len(args) > 2 else {}
    if sha in reg:
        print("STOP registry already has this sha; refusing duplicate enrollment",
              file=sys.stderr)
        return 1
    reg[sha] = {"metadata": meta,
                "issued_at": datetime.now(timezone.utc).isoformat()}
    save(reg)
    print(f"ENROLLED {sha[:12]}...")
    return 0


if __name__ == "__main__":
    sys.exit(main())