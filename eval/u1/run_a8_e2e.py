#!/usr/bin/env python
"""eval/u1/run_a8_e2e.py -- A8 end-to-end (physical laundering) + crypto check.

Part 1: clean-spoof anchor enrollment (--allow-spoof-enrollment; the crypto
        check tests the record<->file binding, independent of the gate).
Part 2: A8 e2e on laundered spoofs: issuer (dev threshold, honest gate) ->
        count REFUSED vs SIGNED; signed -> holder proof + verify_fully_v4 vs
        its own record -> count FULL-VERIFY ACCEPT.
Part 3: crypto check on all 100 laundered clips: holder proves with the CLEAN
        handoff on laundered audio; verify_fully_v4 vs clean record -> REJECT
        expected. Bona fide clean records come from u2 enrollment.

Resumable via eval/u1/a8_state.json.
"""
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from content_common import REPO, run_cmd  # noqa: E402

U1 = os.path.join(REPO, "eval", "u1")
ATT = os.path.join(REPO, "outputs", "v4", "u1_att")
POL = os.path.join(REPO, "outputs", "v4", "eval_v4_att", "policies", "wide_v2.json")
META = os.path.join(REPO, "inputs", "demo_metadata_v4.json")
ISSUER = os.path.join(REPO, "scripts", "issue_capture_record.json".replace(".json", "_v4.js"))
HOLDER = os.path.join(REPO, "scripts", "provenance_cli_v4.js")
FV = os.path.join(REPO, "script".replace("t", "ts"), "verify_fully_v4.js")
KEY = r"<HOME>\zkp-demo-issuer-keys\issuer_private.pem"
TMPH = os.path.join(os.environ.get("TEMP", "/tmp"), "u1att")
DET_DEV = str(-0.9449426)
STATE = os.path.join(U1, "a8_state.json")
WEIGHTS = r"<HOME>\external\aasist\model".replace("model", "models\\weights\\AASIST-L.pth")
AASIST_REPO = r"<HOME>\external\aasist"
CONFIG = r"<HOME>\external\aasist\config\AASIST-L.conf"

os.makedirs(TMPH, exist_ok=True)
os.makedirs(ATT, exist_ok=True)


def model_args():
    return ["--weights", WEIGHTS, "--aasist-repo", AASIST_REPO, "--config", CONFIG]


def counts_new():
    return {"clean_enroll_ok": 0, "clean_enroll_refused": 0,
            "a8_refused": 0, "a8_signed": 0, "a8_prove_fail": 0,
            "a8_full_verify_accept": 0, "a8_verify_reject": 0,
            "crypto_reject": 0, "crypto_accept_BAD": 0, "crypto_holder_refuse": 0}


def seg_of(c):
    return os.path.join(U1, "C1_segments",
                        f"{c['order']:03d}_{c['kind']}_{c['file_id']}.wav")


def enroll_clean_spoofs(st, counts):
    """Anchor enrollment of clean spoof originals (crypto check) -- the
    --allow-spoof-enrollment flag bypasses the detector gate BY DESIGN here:
    the anchor record exists by hypothesis in the threat scenario."""
    for c in CLIPS:
        if c["kind"] != "spoof":
            continue
        fid = c["file_id"]
        if st.get("clean_enroll", {}).get(fid) == "enrolled":
            counts["clean_enroll_ok"] += 1
            continue
        rec = os.path.join(ATT, "clean_spoof_enroll", fid, "record.json")
        hand = os.path.join(TMPH, f"cleanspoof_{fid}.json")
        if not os.path.exists(rec):
            a = ["node", ISSUER, c["src"], rec, "--metadata", META,
                 "--issuer-key", KEY, "--handoff", hand, "--expires-hours", "24",
                 "--allow-spoof-enrollment"] + model_args()
            rr = run_cmd(a, f"u1clean-{fid}", need_exit=None, timeout=600)
            ok = (rr["exit"] == 0)
        else:
            ok = True
        st.setdefault("clean_enroll", {})[fid] = "enrolled" if ok else "refused"
        counts["clean_enroll_ok" if ok else "clean_enroll_refused"] += 1


def a8_e2e(st, counts):
    """Issuer (dev threshold, honest gate) on each laundered spoof ->
    REFUSED vs SIGNED; signed -> holder proof + verify vs own record."""
    for c in CLIPS:
        if c["kind"] != "spoof":
            continue
        fid = c["file_id"]
        e = st.setdefault("a8", {}).setdefault(fid, {})
        if e.get("stage") in ("refused", "full-verify-accept"):
            counts["a8_refused" if e["stage"] == "refused" else "a8_full_verify_accept"] += 1
            continue
        seg = seg_of(c)
        rec = os.path.join(ATT, "a8", fid, "record.json")
        hand = os.path.join(TMPH, f"hand_{fid}.json")
        if e.get("stage") != "signed":
            if os.path.exists(rec):
                os.remove(rec)
            a = ["node", ISSUER, seg, rec, "--metadata", META,
                 "--issuer-key", KEY, "--handoff", hand, "--expires-hours", "24"] + model_args()
            rr = run_cmd(a, f"a8issue-{fid}", need_exit=None, timeout=900)
            if rr["exit"] != 0:
                e["stage"] = "refused"
                e["reason"] = (rr["stderr"] or rr["out"] or "").strip()[-200:]
                counts["a8_refused"] += 1
                continue
            e["stage"] = "signed"
            counts["a8_signed"] += 1
        od = os.path.join(ATT, "a8_proofs", fid)
        if os.path.isdir(od):
            shutil.rmtree(od)   # holder refuses an existing outdir
        rr = run_cmd(["node", HOLDER, seg, od, "--handoff", hand, "--policy", POL],
                     f"a8holder-{fid}", need_exit=None, timeout=600)
        pf = os.path.join(od, "proof.json")
        pb = os.path.join(od, "public.json")
        if not (os.path.exists(pf) and os.path.exists(pb)):
            e["stage"] = "prove-fail"
            counts["a8_prove_fail"] += 1
            e["reason"] = (rr["stderr"] or "").strip()[-200:]
            continue
        now = json.load(open(rec))["issued_at_utc"]
        rv = run_cmd(["node", FV, seg, pf, pb, rec, "--policy-file", POL, "--now", now],
                     f"a8fv-{fid}", need_exit=None, timeout=600)
        if rv["exit"] == 0:
            e["stage"] = "full-verify-accept"
            counts["a8_full_verify_accept"] += 1
        else:
            e["stage"] = "verify-reject"
            e["reason"] = (rv["stderr"] or "").strip()[-200:]
            counts["a8_verify_reject"] += 1


def crypto_check(st, counts):
    """Holder proves on laundered audio with the CLEAN handoff; verify vs the
    clean record. Expected REJECT (record<->file hash binding)."""
    u2tmp = os.path.join(os.environ.get("TEMP", "/tmp"), "u2att")
    for c in CLIPS:
        fid = c["file_id"]
        e = st.setdefault("crypto", {}).setdefault(fid, {})
        if e.get("verdict") in ("REJECT", "ACCEPT", "HOLDER-REFUSE"):
            if e["verdict"] == "REJECT":
                counts["crypto_reject"] += 1
            elif e["verdict"] == "ACCEPT":
                counts["crypto_accept_BAD"] += 1
            else:
                counts["crypto_holder_refuse"] += 1
            continue
        if c["kind"] == "bonafide":
            crec = os.path.join(REPO, "outputs", "v4", "u2_att", "enroll", fid, "record.json")
            chand = os.path.join(u2tmp, f"found_{fid}.json" if False else f"hand_{fid}.json")
        else:
            crec = os.path.join(ATT, "clean_spoof_enroll", fid, "record.json")
            chand = os.path.join(TMPH, f"cleanspoof_{fid}.json")
        if not os.path.exists(crec):
            e["verdict"] = "NO-CLEAN-RECORD"
            counts["crypto_holder_refuse"] += 1
            continue
        od = os.path.join(ATT, "crypto_proofs", fid)
        pf = os.path.join(od, "proof.json")
        pb = os.path.join(od, "public.json")
        if not (os.path.exists(pf) and os.path.exists(pb)):
            rr = run_cmd(["node", HOLDER, seg_of(c), od, "--handoff", chand,
                          "--policy", POL], f"a8cr-{fid}", need_exit=None, timeout=600)
            if not (os.path.exists(pf) and os.path.exists(pb)):
                e["verdict"] = "HOLDER-REFUSE"
                e["reason"] = (rr["stderr"] or "").strip()[-200:]
                counts["crypto_holder_refuse"] += 1
                continue
        now = json.load(open(crec))["issued_at_utc"]
        rv = run_cmd(["node", FV, seg_of(c), pf, pb, crec, "--policy-file", POL,
                      "--now", now], f"a8crv-{fid}", need_exit=None,
                     timeout=600)
        e["verdict"] = "ACCEPT" if rv["exit"] == 0 else "REJECT"
        if rv["exit"] == 0:
            counts["crypto_accept_BAD"] += 1
        else:
            counts["crypto_reject"] += 1


def main():
    global CLIPS
    os.environ["DET_THRESHOLD"] = DET_DEV   # issuer spawns inheriting this
    man = json.load(open(os.path.join(U1, "track_manifest.json")))
    CLIPS = man["clips"]
    st = json.load(open(STATE)) if os.path.exists(STATE) else {}
    counts = counts_new()
    enroll_clean_spoofs(st, counts)
    a8_e2e(st, counts)
    crypto_check(st, counts)
    json.dump(st, open(STATE, "w"), indent=1)
    json.dump(counts, open(os.path.join(U1, "a8_counts.json"), "w"), indent=1)
    print(json.dumps(counts, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
