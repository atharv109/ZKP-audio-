#!/usr/bin/env python
"""eval/append_supplement_rows.py -- recover the A1-supplement CSV rows.

The a1_supplement pipeline runs all succeeded (artifacts on disk in
outputs/v3/eval_binding/A1sup/run_1000147 + memprobe in run_costs.json), but
the row dicts used wrong keys ('ms'/'pn'/'pp') and the CSV append failed.
This script reads the existing artifacts and appends the 3 rows correctly.
Append-only; overwrite refused.
"""
import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run_binding_eval import CSV_OUT, OUTROOT  # noqa


def main() -> int:
    run_dir = os.path.join(OUTROOT, "A1sup", "run_1000147")
    with open(os.path.join(run_dir, "record.json")) as f:
        rec = json.load(f)
    with open(os.path.join(run_dir, "demo_result.json")) as f:
        man = json.load(f)
    verify_log = sorted(os.listdir(os.path.join(OUTROOT, "logs")))
    a_logs = [l for l in verify_log if l.startswith("A1sup-verify.")]
    with open(os.path.join(OUTROOT, "logs", a_logs[-1])) as f:
        out = f.read()
    import re
    m = re.search(r"RESULT : FULL-VERIFY (ACCEPT|REJECT) — ([^\n]+)", out)
    verdict = m.group(1).upper() if m and m.group(1) == "ACCEPT" else "REJECT"
    reason = m.group(2).strip() if m else "unparseable"
    exit_code = 0 if verdict == "ACCEPT" else 1
    sha = rec["file_sha256"]
    rows = [
        {"file_id": "LA_E_1000147", "label": "spoof(A17)", "attack_id": "A1", "system": "S1",
         "command": "node scripts/verify_fully.js LA_E_1000147.flac run_1000147/proof.json run_1000147/public.json genuine/../LA_E_1250691/record.json [A1sup]",
         "exit_code": exit_code, "verdict": verdict, "reason": reason + " [supplementary: UNENROLLED substitute vs original record]"},
        {"file_id": "LA_E_1000147", "label": "spoof(A17)", "attack_id": "A1", "system": "S2",
         "command": "same run as S1 row", "exit_code": exit_code, "verdict": verdict,
         "reason": "Part B: " + reason + " [supplementary: UNENROLLED substitute]"},
    ]
    # S3 lookup
    import subprocess
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from run_binding_eval import s3
    v, msg = s3("lookup", sha)
    rows.append({"file_id": "LA_E_1000147", "label": "spoof(A17)", "attack_id": "A1",
                 "system": "S3", "command": f"python eval/s3_registry.py lookup {sha[:16]}...",
                 "exit_code": "", "verdict": v, "reason": msg + " [supplementary: unenrolled substitute]"})
    with open(CSV_OUT, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["file_id", "label", "attack_id", "system",
                                          "command", "exit_code", "verdict", "reason",
                                          "runtime_ms", "peak_node_mb", "peak_python_mb"])
        for r in rows:
            w.writerow(r)
            print(f"  [row] {r['attack_id']}/{r['system']} {r['file_id']} -> {r['verdict']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())