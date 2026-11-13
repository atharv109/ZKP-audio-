#!/usr/bin/env python
"""eval/a1_supplement.py -- supplementary A1 measurement with an UNENROLLED substitute.

The main run's A1 substitute (LA_E_9394669) was itself enrolled, so its S3
cell read ACCEPT (the registry is blind BETWEEN enrolled files -- itself a
finding). This script measures A1 exactly as THREAT_MODEL hypothesized: an
unenrolled substitute file (LA_E_1000147.flac, outside the 20-sample
registry) with its own fresh proof, checked against the original record of
LA_E_1250691. This prove run also serves as the torch memory probe the main
run missed (its sampler did not track the python3.12.exe process name).

Appends rows to eval/results_binding.csv (append-only; nothing overwritten)
and a 'memprobe' entry to eval/run_costs.json.

Usage: python -I eval/a1_supplement.py
"""
import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run_binding_eval import (CSV_OUT, COSTS, OUTROOT, DEMO_WF, ISSUE,
                              VERIFY_FULLY, ISSUER_KEY, ENROLL_META, WEIGHTS,
                              AASIST_REPO, CONFIG, Stop, ram_gate, run_cmd,
                              parse_fv, s3, sha256_file)

SUB_FLAC = r"ASVspoof2019_LA_eval\flac\LA_E_1000147.flac"
ORIG_X = "LA_E_1250691"  # original enrolled genuine file (its record is used)
FIELDS = ["file_id", "label", "attack_id", "system", "command", "exit_code",
          "verdict", "reason", "runtime_ms", "peak_node_mb", "peak_python_mb"]


def fmt_cmd(argv):
    return "node scripts/verify_fully.js " + " ".join(
        os.path.basename(a) for a in argv[1:])


def main() -> int:
    ram_gate("A1 supplement prove")
    run_dir = os.path.join(OUTROOT, "A1sup", "run_1000147")
    if os.path.exists(run_dir):
        raise Stop(f"refusing existing run dir {run_dir}")
    r = run_cmd(["node", DEMO_WF, SUB_FLAC, ENROLL_META, run_dir,
                 "--weights", WEIGHTS, "--aasist-repo", AASIST_REPO,
                 "--config", CONFIG], "A1sup-prove", need_exit=0)
    proof = os.path.join(run_dir, "proof.json")
    pub = os.path.join(run_dir, "public.json")
    record = os.path.join(run_dir, "record.json")
    run_cmd(["node", ISSUE, SUB_FLAC, record, "--issuer-key", ISSUER_KEY],
            "A1sup-issue", need_exit=0)
    sha = sha256_file(SUB_FLAC)

    orig_record = os.path.join(OUTROOT, "enroll", "genuine", ORIG_X, "record.json")

    argv = ["node", VERIFY_FULLY, SUB_FLAC, proof, pub, orig_record]
    r2 = run_cmd(argv, "A1sup-verify", need_exit=None)
    pv = parse_fv(r2["stdout"], r2["exit"], f"A1sup/{ORIG_X}")

    rows = [
        dict(file_id="LA_E_1000147", label="spoof(A17)", attack_id="A1", system="S1",
             command=fmt_cmd(argv), exit_code=r2["exit"], verdict=pv["verdict"],
             reason=pv["reason"] + " [supplementary: UNENROLLED substitute vs original record]",
             ms=r2["ms"], pn=r2["peak_node_mb"], pp=r2["peak_python_mb"]),
        dict(file_id="LA_E_1000147", label="spoof(A17)", attack_id="A1", system="S2",
             command=fmt_cmd(argv) + "  [Part B outcome of the same run]",
             exit_code=r2["exit"], verdict=pv["verdict"],
             reason="Part B: " + pv["reason"] + " [supplementary: UNENROLLED substitute]",
             ms=r2["ms"], pn=r2["peak_node_mb"], pp=r2["peak_python_mb"]),
    ]
    v, msg = s3("lookup", sha)
    rows.append(dict(file_id="LA_E_1000147", label="spoof(A17)", attack_id="A1",
                     system="S3", command=f"python eval/s3_registry.py lookup {sha[:16]}...",
                     exit_code="", verdict=v, reason=msg + " [supplementary: unenrolled substitute]"))

    with open(COSTS, encoding="utf-8") as f:
        costs = json.load(f)
    costs.setdefault("memprobe", []).append({
        "file_id": "LA_E_1000147", "kind": "demo_workflow prove run (warm cache)",
        "ms_total": r["ms"], "peak_node_mb": r["peak_node_mb"],
        "peak_python_mb": r["peak_python_mb"]})
    with open(COSTS, "w", encoding="utf-8") as f:
        json.dump(costs, f, indent=2)
        f.write("\n")

    with open(CSV_OUT, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        for row in rows:
            w.writerow(row)
            print(f"  [row] {row['attack_id']}/{row['system']} {row['file_id']} -> "
                  f"{row['verdict']} ({row['ms'] or ''} ms)")
    print(f"A1 supplement done: S3={v}; prove-run peak python={r['peak_python_mb']} MB, "
          f"node={r['peak_node_mb']} MB")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Stop as e:
        print(f"\nSTOPPED -- unexpected error:\n{e}", file=sys.stderr)
        sys.exit(2)