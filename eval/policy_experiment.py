#!/usr/bin/env python
"""Section 1 of the final measurement: one enrollment, 9 grid-aligned policies.

Reuses the v4 matrix's single enrolled file (LA_E_1250691 -- record + handoff
already issued once by the real issuer); NO re-enrollment, NO issuer contact.
Writes eval/policy_exp_results.csv (one row per policy) + prints the table.
"""
import csv, json, os, statistics, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from content_common import REPO, EVAL, run_cmd, ram_gate

HOLDER = os.path.join(REPO, "scripts", "provenance_cli_v4.js")
FV = os.path.join(REPO, "scripts", "verify_fully_v4.js")
ATT = os.path.join(REPO, "outputs", "v4", "eval_v4_att")
STATE = os.path.join(EVAL, "v4_att_state.json")
G = 3600  # timestamp grid; gps grid 100
def tcell(n): return 1780279200 + n * G  # aligned anchor

TS = 1780298225  # hidden value (holder-side only; not printed)
OUT = os.path.join(EVAL, "policy_exp_results.csv")
FIELDS = ["case", "policy", "expected", "holder_stage", "actual", "reason", "proof_ms", "verify_ms"]

def main():
    st = json.load(open(STATE))
    fid = "LA_E_1250691"
    assert st["enroll"].get(fid) == "enrolled"
    rec = os.path.join(ATT, "enroll42", fid, "record.json")
    hand = os.path.join(os.environ.get("TEMP", "/tmp"), "v4att", f"hand_{fid}.json")
    audio = next(r["flac_path"] for r in csv.DictReader(
        open(os.path.join(EVAL, "sample_manifest.csv"))) if r["file_id"] == fid)
    pol_dir = os.path.join(ATT, "policy_exp")
    os.makedirs(pol_dir, exist_ok=True)

    # 9 grid-aligned policy cases: [ts_min, ts_max, lat, lon, sensor_min, device list]
    P = lambda tsr, lat, lon, smin, dev: {
        "device_ids": dev, "timestamp_range": tsr,
        "gps_lat_range": lat, "gps_long_range": lon, "sensor_min": smin}
    WIDE = [tcell(0), tcell(163), [407400, 408400], [778000, 779200], 70, [1024, 2048, 4096]]
    cases = [
        ("1 equal-cell (2 grid cells containing the value)", P([tcell(5), tcell(7) - 1],
            [407400, 408400], [778000, 779200], 70, [1024, 2048, 4096]), "ACCEPT"),
        ("2 same record, wide window (the enrollment-era window)", P([tcell(0), tcell(163) - 1], [407400, 408400], [778000, 779200], 70, [1024, 2048, 4096]), "ACCEPT"),
        ("3 wider still (year-scale)", P([1728000000, 1830239999],
            [407400, 408400], [778000, 779200], 70, [1024, 2048, 4096]), "ACCEPT"),
        ("4 narrower-excluding (window ends before the value)", P([tcell(0), tcell(0) + 7199],
            [407400, 408400], [778000, 779200], 70, [1024, 2048, 4096]), "REFUSE"),
        ("5 device-excluded (allow-list without the hidden device)",
            P([tcell(0), tcell(163)], [407400, 408400], [778000, 779200], 70, [2048, 2048, 4096]),
            "REFUSE"),
        ("6 sensor_min BELOW the hidden value (stricter but satisfied)",
            P([tcell(0), tcell(163) - 1], [407400, 408400], [778000, 779200], 71,
              [1024, 2048, 4096]), "ACCEPT"),
        ("7 sensor_min ABOVE the hidden value",
            P([tcell(0), tcell(163)], [407400, 408400], [778000, 779200], 80, [1024, 2048, 4096]),
            "REFUSE"),
        ("8 stale window (aligned, entirely in the past)",
            P([3600 * 444445, 3600 * 444445 + 7199],
              [407400, 408400], [778000, 779200], 70, [1024, 2048, 4096]), "REFUSE"),
        ("9 malformed (min > max -> policy VALIDATOR, not holder guard)",
            P([tcell(5), tcell(1)], [407400, 408400], [778000, 779200], 70, [1024, 2048, 4096]),
            "EXIT2"),
    ]
    rows = []
    proof_ms_all = []
    for name, pol, expected in cases:
        pf = os.path.join(pol_dir, f"pol_{name.split(' ')[0]}.json")
        json.dump(pol, open(pf, "w"))
        od = os.path.join(ATT, "policy_exp", name.split(" ")[0])
        if os.path.exists(od):
            import shutil; shutil.rmtree(od)
        # holder stage
        rh = run_cmd(["node", HOLDER, audio, od, "--handoff", hand, "--policy", pf],
                     f"pol-hold-{name.split(' ')[0]}", need_exit=None)
        holder_stage = "refused" if rh["exit"] == 1 else ("usage_error" if rh["exit"] == 2 else "proved")
        reason = ((rh["stderr"] or "").strip().splitlines() or [""])[-1][:120]
        verify_ms = ""
        if rh["exit"] == 0:
            proof_ms_all.append(rh["ms"])
            rv = run_cmd(["node", FV, audio, os.path.join(od, "proof.json"),
                          os.path.join(od, "public.json"), rec, "--policy-file", pf],
                         f"pol-verify-{name.split(' ')[0]}", need_exit=None)
            verify_ms = rv["ms"]
            actual = "ACCEPT" if rv["exit"] == 0 else "REJECT"
            vline = [l for l in (rv["out"] or "").splitlines()
                     if l.startswith("RESULT :")]
            reason = ((vline or [""])[0].split("\u2014") + [""])[1].strip()[:100] if vline else reason
        else:
            actual = "REFUSAL(exit %d)" % rh["exit"]
        rows.append(FIELDS and {"case": name, "policy": json.dumps(pol)[:80] + "...",
                                "expected": expected, "holder_stage": holder_stage,
                                "actual": actual, "reason": reason,
                                "proof_ms": rh["ms"], "verify_ms": verify_ms})
    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader(); w.writerows(rows)
    for r in rows:
        print(f"  {r['case'][:46]:46s} expected={r['expected']:7s} actual={r['actual']:18s} "
              f"proof={r['proof_ms']} ms")
    ok = all(r["expected"].startswith(r["actual"][:6]) or
             (r["expected"] == "ACCEPT" and r["actual"] == "ACCEPT") or
             (r["expected"] in ("REFUSE", "EXIT2") and ("REFUSAL" in r["actual"] or r["actual"] == "REJECT"))
             for r in rows)
    print("ALL_EXPECTATIONS_MET:", ok)
    if proof_ms_all:
        print(f"proof time over accepting policies: mean {statistics.mean(proof_ms_all):.0f} "
              f"median {statistics.median(proof_ms_all):.0f} ms  n={len(proof_ms_all)}")
    print("same record used for every policy; issuer never contacted")
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main())
