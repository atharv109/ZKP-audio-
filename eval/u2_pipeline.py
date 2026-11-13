#!/usr/bin/env python
"""eval/u2_pipeline.py -- n=200 measurement phases (run AFTER the dev threshold exists
for the detector-gated phases).

  pS   : score the u2 transform corpus (threshold-independent raw scores)
  pE   : enroll 200 genuine via the v4 issuer at DET_THRESHOLD (casualty count)
  pA2  : A2 crypto: 7 conditions x enrolled files (holder prove + verify) + S4 rows
  pA3  : A3 crypto: 9 cells x enrolled files + S4 rows
  pA3re: 50 splices stratified over 9 cells -> issuer refusals + FULL-VERIFY
  CSV: eval/results_u2.csv (append-only, deduped). State: eval/u2_state.json.
Usage: python eval/u2_pipeline.py pS|pE|pA2|pA3|pA3re|all
"""
import csv, json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from content_common import REPO, EVAL, Stop, ram_gate, run_cmd

CSV_OUT = os.environ.get("U2_CSV_OUT", os.path.join(EVAL, "results_u2.csv"))
STATE = os.path.join(EVAL, "u2_state.json")
MAN = os.path.join(REPO, "eval", "sample_manifest_u2.csv")
ROOT = os.path.join(REPO, "outputs", "v3", "eval_content", "u2")
ATT = os.path.join(REPO, "outputs", "v4", "u2_att")
ISSUER = os.path.join(REPO, "scripts", "issue_capture_record_v4.js")
HOLDER = os.path.join(REPO, "scripts", "provenance_cli_v4.js")
FV = os.path.join(REPO, "scripts", "verify_fully_v4.js")
KEY = "<HOME>/zkp-demo-issuer-keys/issuer_private.pem"
POL = os.path.join(REPO, "outputs", "v4", "eval_v4_att", "policies", "wide_v2.json")
TMP = os.path.join(os.environ.get("TEMP", "/tmp"), "u2att")
os.makedirs(TMP, exist_ok=True)
os.makedirs(ATT, exist_ok=True)

FIELDS = ["file_id", "label", "attack_id", "system", "command", "exit_code",
          "verdict", "reason", "runtime_ms", "peak_node_mb", "peak_python_mb",
          "pipeline_version"]

def rows_load():
    import time
    done = set()
    for attempt in range(4):
        try:
            with open(CSV_OUT) as f:
                head = f.readline()
                f.seek(0)
                if not head.startswith("file_id"):
                    raise ValueError("stale headerless copy")
                for r in csv.DictReader(f):
                    try:
                        done.add((r["attack_id"], r["system"], r["file_id"], r["label"]))
                    except KeyError as ke:
                        import sys as _s
                        print("DEBUG row keys:", list(r.keys())[:6], "line:", _s.maxsize if False else r, file=_s.stderr)
                        raise
            return done
        except Exception:
            if attempt == 3:
                raise
            time.sleep(3)
    return done

def add(done, **kw):
    key = (kw.get("attack_id"), kw.get("system"), kw.get("file_id"), kw.get("label"))
    if key in done: return False
    done.add(key)
    kw.setdefault("runtime_ms", kw.get("ms", ""))
    kw.setdefault("peak_node_mb", kw.get("pn", ""))
    kw.setdefault("peak_python_mb", kw.get("pp", ""))
    kw.setdefault("pipeline_version", "v4")
    with open(CSV_OUT, "a", newline="") as f:
        csv.writer(f).writerow([kw.get(k, "") for k in FIELDS])
    print(f"  [row] {kw.get('attack_id')}/{kw.get('system')} {kw.get('file_id')} -> {kw.get('verdict')}", flush=True)
    return True

def state_load():
    return json.load(open(STATE)) if os.path.exists(STATE) else {}
def state_save(st):
    json.dump(st, open(STATE, "w"), indent=2, sort_keys=True)

def manifest():
    with open(MAN) as f:
        return list(csv.DictReader(f))

def scores_load():
    return json.load(open(os.path.join(EVAL, "u2_scores.json")))

def pS(done):
    r = run_cmd([sys.executable, os.path.join(EVAL, "score_u2.py")], "u2-score", need_exit=0, timeout=3600)
    print(f"[pS] u2 scoring done ({r['ms']} ms)")

def pE(done, st):
    thr = os.environ.get("DET_THRESHOLD")
    print(f"[pE] enrolling 200 genuine at DET_THRESHOLD={thr}")
    bona = [r for r in manifest() if r["label"] == "bonafide"]
    st.setdefault("enroll", {})
    for r in bona:
        fid = r["file_id"]
        if st["enroll"].get(fid) in ("enrolled", "refused"): continue
        ram_gate(f"u2 enroll {fid}")
        rec = os.path.join(ATT, "enroll", fid, "record.json")
        hand = os.path.join(TMP, f"hand_{fid}.json")
        a = ["node", ISSUER, r["flac_path"], rec,
             "--metadata", os.path.join(REPO, "inputs", "demo_metadata_v4.json"),
             "--issuer-key", KEY, "--handoff", hand, "--expires-hours", "24",
             "--weights", "<HOME>/external/aasist/models/weights/AASIST-L.pth",
             "--aasist-repo", "<HOME>/external/aasist",
             "--config", "<HOME>/external/aasist/config/AASIST-L.conf"]
        rr = run_cmd(a, f"u2enr-{fid}", need_exit=None)
        st["enroll"][fid] = "enrolled" if rr["exit"] == 0 else "refused"
        state_save(st)
    n_ok = sum(1 for v in st["enroll"].values() if v == "enrolled")
    print(f"[pE] enrolled={n_ok} refused={200 - n_ok}")

def pA2_pA3(done, st, which):
    scores = scores_load()
    thr = os.environ.get("DET_THRESHOLD", "1.7635419737")
    bona = [r for r in manifest() if r["label"] == "bonafide" and
            st.get("enroll", {}).get(r["file_id"]) == "enrolled"]
    CONDS = ["mp3_64k", "mp3_32k", "opus_32k", "resample_8k_rt",
             "noise_20db", "noise_10db", "reverb_rt60_0.3s"]
    FRACS = ["0.1", "0.25", "0.5"]
    POSITIONS = ["start", "middle", "end"]
    cells = (["a2", c, "a2", c] for c in CONDS) if which == "A2" else \
            ((["a3", f, pos, f"{f}_{pos}"] for f in FRACS for pos in POSITIONS))
    for kind, key, _, cell in cells:
        attack = which
        for r in bona:
            fid = r["file_id"]
            path = os.path.join(ROOT, kind, key, fid,
                                "splice.flac" if kind == "a3" else "transform.flac")
            tkey = (attack, "S1", f"{fid}@{cell}", "crypto-vs-clean-record")
            if tkey in done: continue
            rec = os.path.join(ATT, "enroll", fid, "record.json")
            hand = os.path.join(TMP, f"hand_{fid}.json")
            od = os.path.join(ATT, "proofs", attack, cell, fid)
            if not os.path.exists(os.path.join(od, "proof.json")):
                ram_gate(f"{attack} prove {cell}/{fid}")
                rp = run_cmd(["node", HOLDER, path, od, "--handoff", hand,
                              "--policy", POL], f"u2hold-{attack}-{cell}-{fid}", need_exit=None)
                if rp["exit"] != 0:
                    add(done, file_id=f"{fid}@{cell}", label=cell, attack_id=attack,
                        system="S1", command="holder refusal", exit_code=rp["exit"],
                        verdict="REJECT", reason=(rp["stderr"] or "").strip()[-160:],
                        ms=rp["ms"], pn=rp["peak_node_mb"], pp=rp["peak_python_mb"])
                    continue
            rr = run_cmd(["node", FV, path, os.path.join(od, "proof.json"),
                          os.path.join(od, "public.json"), rec, "--policy-file", POL],
                         f"u2fv-{attack}-{cell}-{fid}", need_exit=None)
            line = [l for l in (rr["out"] or "").splitlines() if l.startswith("RESULT :")]
            reason = ((line[-1].split("\u2014") + [""])[1].strip() if line else "")[:120]
            sc = scores.get(path)
            add(done, file_id=f"{fid}@{cell}", label=cell, attack_id=attack, system="S1",
                command="holder-prove -> verify_fully_v4 vs clean record",
                exit_code=rr["exit"], verdict="ACCEPT" if rr["exit"] == 0 else "REJECT",
                reason=reason, ms=rr["ms"], pn=rr["peak_node_mb"], pp=rr["peak_python_mb"])
            if sc is not None:
                add(done, file_id=f"{fid}@{cell}", label="u2-score", attack_id=attack,
                    system="S4", command="AASIST-L (u2 run)",
                    exit_code="", verdict="bonafide" if sc >= float(thr) else "spoof",
                    reason=f"score={sc:.6f} @thr={thr}")
        # per-cell aggregate S4 rows are derived in the report script
    print(f"[p{which}] done")

def pA3re(done, st):
    scores = scores_load()
    thr = os.environ.get("DET_THRESHOLD", "1.7635419737")
    bona = [r for r in manifest() if r["label"] == "bonafide" and
            st.get("enroll", {}).get(r["file_id"]) == "enrolled"]
    FRACS = ["0.1", "0.25", "0.5"]
    POSITIONS = ["start", "middle", "end"]
    # 50 splices stratified: round-robin over the 9 cells across 50 enrolled files
    picks = []
    for i in range(50):
        r = bona[i % len(bona)]
        cell_idx = i % 9
        picks.append((r, FRACS[cell_idx // 3], POSITIONS[cell_idx % 3], cell_idx))
    n_ok, n_ref = 0, 0
    for r, frac, pos, _ in picks:
        fid = r["file_id"]
        sp = os.path.join(ROOT, "a3", frac, pos, fid, "splice.flac")
        cell = f"{frac}_{pos}"
        key = ("A3re", "S1", f"{fid}@{cell}", "reenroll-at-devthreshold")
        if key in done: continue
        rec = os.path.join(ATT, "a3re", cell, fid, "record.json")
        hand = os.path.join(TMP, f"handre_{fid}_{cell.replace('.', '')}.json")
        now_iso = None
        ram_gate(f"A3re enroll {fid}")
        a = ["node", ISSUER, sp, rec,
             "--metadata", os.path.join(REPO, "inputs", "demo_metadata_v4.json"),
             "--issuer-key", KEY, "--handoff", hand, "--expires-hours", "24",
             "--weights", "<HOME>/external/aasist/models/weights/AASIST-L.pth",
             "--aasist-repo", "<HOME>/external/aasist",
             "--config", "<HOME>/external/aasist/config/AASIST-L.conf"]
        enroll_r = run_cmd(a, f"u2a3re-{fid}-{cell}", need_exit=None)
        if enroll_r["exit"] != 0:
            n_ref += 1
            add(done, file_id=f"{fid}@{cell}", label=cell, attack_id="A3re", system="S1",
                command="issue_capture_record_v4 over the splice",
                exit_code=enroll_r["exit"], verdict="REFUSED-AT-ENROLLMENT",
                reason=(enroll_r["stderr"] or "").strip().splitlines()[-1][:150])
            continue
        n_ok += 1
        od = os.path.join(ATT, "a3re", cell, fid, "proofs")
        run_cmd(["node", HOLDER, sp, od, "--handoff", hand, "--policy", POL],
                f"u2a3re-hold-{fid}-{cell}", need_exit=0)
        recObj = json.load(open(rec))
        rr = run_cmd(["node", FV, sp, os.path.join(od, "proof.json"),
                      os.path.join(od, "public.json"), rec, "--policy-file", POL,
                      "--now", recObj["issued_at_utc"]],
                     f"u2a3re-fv-{fid}-{cell}", need_exit=None)
        line = [l for l in (rr["out"] or "").splitlines() if l.startswith("RESULT :")]
        reason = ((line[-1].split("\u2014") + [""])[1].strip() if line else "")[:120]
        add(done, file_id=f"{fid}@{cell}", label=cell, attack_id="A3re", system="S1",
            command="full v4 pipeline over the splice (own record+proof)",
            exit_code=rr["exit"], verdict="ACCEPT" if rr["exit"] == 0 else "REJECT",
            reason=reason, ms=rr["ms"], pn=rr["peak_node_mb"], pp=rr["peak_python_mb"])
    print(f"[pA3re] enrolled-and-accepted={n_ok} refused={n_ref} (of 50)")

def main():
    phase = sys.argv[1] if len(sys.argv) > 1 else "all"
    done = rows_load()
    st = state_load()
    if phase in ("pS", "all"): pS(done)
    if phase in ("pE", "all"): pE(done, st)
    if phase in ("pA2", "all"): pA2_pA3(done, st, "A2")
    if phase in ("pA3", "all"): pA2_pA3(done, st, "A3")
    if phase in ("pA3re", "all"): pA3re(done, st)
    print(f"[done {phase}]")
    return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except Stop as e:
        print(f"STOPPED -- {e}", file=sys.stderr)
        sys.exit(2)
