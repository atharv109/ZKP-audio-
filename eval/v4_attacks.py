#!/usr/bin/env python
"""eval/v4_attacks.py -- re-run the attack matrix against the v4 pipeline (Part B).

Issues records via scripts/issue_capture_record_v4.js, proofs via the HOLDER
(scripts/provenance_cli_v4.js -- it holds the handoff) and fabricated proofs via
direct snarkjs fullProve (attacker role, no handoff), then verifies with
scripts/verify_fully_v4.js (+ --now / --expect-nonce / strict policies).

Phases (resumable, append-only to eval/results_v4.csv):
  p0   enroll seed-42 genuine x10 + a1sub spoof x10 (refusal counts = gate)
  p1   honest holder proofs (aligned wide policy)
  p2   A1: substitute file + ORIGINAL proof + record -> REJECT
  p3   A4: fabricated in-rule metadata + own salt -> REJECT (C mismatch)
  p4   A4': TRUE metadata + own salt -> REJECT (C mismatch)
  p5   A5: tampered detector fields in the record -> REJECT (canonical)
  p6   A6: within-window replay ACCEPT; fresh-nonce REJECT; expired REJECT
  p7   down: wide-policy proof vs strict verifier policy -> REJECT
  p8   A2: 50 seed-43 bona fide enrolled clean; 7 transforms x holder+verify
  p9   A3: 450 splices; 10-splice re-enrollment path (refused/enrolled counts)
"""
import csv, json, os, statistics, subprocess, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from content_common import (REPO, EVAL, Stop, ram_gate, run_cmd, sha256_file,
                            measure)

ATT = os.path.join(REPO, "outputs", "v4", "eval_v4_att")
CSV_OUT = os.path.join(EVAL, "..", "..", "eval", "results_v4.csv")
CSV_OUT = os.path.join(REPO, "eval", "results_v4.csv")
STATE = os.path.join(EVAL, "v4_att_state.json")
MAN42 = os.path.join(EVAL, "sample_manifest.csv")
MAN43 = os.path.join(EVAL, "sample_manifest_content.csv")
ISSUER = os.path.join(REPO, "scripts", "issue_capture_record_v4.js")
HOLDER = os.path.join(REPO, "scripts", "provenance_cli_v4.js")
FV = os.path.join(REPO, "scripts", "verify_fully_v4.js")
KEY = "<HOME>/zkp-demo-issuer-keys/issuer_private.pem"
WEIGHTS = "<HOME>/external/aasist/models/weights/AASIST-L.pth"
AREPO = "<HOME>/external/aasist"
CONF = "<HOME>/external/aasist/config/AASIST-L.conf"
META = os.path.join(REPO, "inputs", "demo_metadata_v4.json")
TMP = os.path.join(os.environ.get("TEMP", "/tmp"), "v4att")
os.makedirs(TMP, exist_ok=True)

WIDE = {"device_ids": [1024, 2048, 4096], "timestamp_range": [1780279200, 1780865999],
        "gps_lat_range": [407400, 408400], "gps_long_range": [778000, 779200],
        "sensor_min": 70}
STRICT = {"device_ids": [1024, 1024, 4096], "timestamp_range": [1780279200, 1780295999],
          "gps_lat_range": [408400, 408400], "gps_long_range": [778600, 778600],
          "sensor_min": 77}
POL_DIR = os.path.join(ATT, "policies")
ENROLL_META = os.path.join(REPO, "inputs", "demo_metadata_v4.json")

FIELDS = ["file_id", "label", "attack_id", "system", "command", "exit_code",
          "verdict", "reason", "runtime_ms", "peak_node_mb", "peak_python_mb",
          "pipeline_version"]

def write_header():
    if not os.path.exists(CSV_OUT):
        with open(CSV_OUT, "w", newline="") as f:
            csv.writer(f).writerow(FIELDS)

def add(rows_done, **kw):
    key = (kw.get("attack_id"), kw.get("system"), kw.get("file_id"), kw.get("label"))
    if key in rows_done:
        return False
    kw.setdefault("runtime_ms", kw.get("ms", ""))
    kw.setdefault("peak_node_mb", kw.get("pn", ""))
    kw.setdefault("peak_python_mb", kw.get("pp", ""))
    with open(CSV_OUT, "a", newline="") as f:
        csv.writer(f).writerow([kw.get(k, "") for k in FIELDS])
    rows_done.add(key)
    print(f"  [row] {kw.get('attack_id')}/{kw.get('system')} {kw.get('file_id')} -> "
          f"{kw.get('verdict')} ({kw.get('runtime_ms','')} ms)", flush=True)
    return True

def load_rows():
    done = set()
    if os.path.exists(CSV_OUT):
        with open(CSV_OUT) as f:
            for r in csv.DictReader(f):
                done.add((r["attack_id"], r["system"], r["file_id"], r["label"]))
    return done

def load_state():
    if os.path.exists(STATE):
        with open(STATE) as f:
            return json.load(f)
    return {}

def save_state(st):
    with open(STATE, "w") as f:
        json.dump(st, f, indent=2, sort_keys=True)
        f.write("\n")

def fv_args(audio, proof, pub, rec, extra=None):
    a = ["node", FV, audio, proof, pub, rec, "--policy-file",
         os.path.join(POL_DIR, "wide.json")]
    if extra:
        a += extra
    return a

def parse_fv(out, code, tag):
    line = [l for l in out.splitlines() if l.startswith("RESULT : FULL-VERIFY")]
    if not line or code not in (0, 1):
        raise Stop(f"{tag}: unparseable FV output (exit {code}):\n{out[-400:]}")
    reason = line[-1].split("\u2014", 1)[1].strip() if "\u2014" in line[-1] else ""
    return ("ACCEPT" if code == 0 else "REJECT"), (reason or "FV outcome")

def enroll(rec_path, hand_path, audio, tag, allow_spoof=False):
    """v4 issuer. Returns (status, {fields...} | None). Refusal is EXPECTED for spoof."""
    if os.path.exists(rec_path):
        with open(rec_path) as f:
            return 0, json.load(f)
    ram_gate(f"v4 enroll {tag}")
    a = ["node", ISSUER, audio, rec_path, "--metadata", META,
         "--issuer-key", KEY, "--handoff", hand_path, "--expires-hours", "24",
         "--weights", WEIGHTS, "--aasist-repo", AREPO, "--config", CONF]
    if allow_spoof:
        a.append("--allow-spoof-enrollment")
    r = run_cmd(a, f"enroll-{tag}", need_exit=None)
    if r["exit"] != 0:
        return r["exit"], {"stderr": r["stderr"][-300:], "stdout": r["stdout"][-200:]}
    return 0, json.load(open(rec_path, encoding="utf-8"))

def holder_prove(audio, outdir, hand_path, pol_name, nonce=None, need=0, tag=""):
    pol = os.path.join(POL_DIR, pol_name + ".json")
    a = ["node", HOLDER, audio, outdir, "--handoff", hand_path, "--policy", pol]
    if nonce is not None:
        a += ["--nonce", str(nonce)]
    return run_cmd(a, f"prove-{tag}-{pol_name}", need_exit=need)

def prove_fabricated(meta, salt, limbs_hi, limbs_lo, pol_name, nonce, tag):
    """Direct snarkjs fullProve (attacker role, no handoff) -> {dir}."""
    pol = json.load(open(os.path.join(POL_DIR, pol_name + ".json")))
    inp = { "device_id": str(meta["device_id"]), "timestamp": str(meta["timestamp"]),
            "sensor_score": str(meta["sensor_score"]), "gps_lat": str(meta["gps_lat"]),
            "gps_long": str(meta["gps_long"]), "salt": str(salt),
            "media_hash_hi": limbs_hi, "media_hash_lo": limbs_lo,
            "valid_claim": "1", "session_nonce": str(nonce or 0),
            "allowed_device_0": str(pol["device_ids"][0]),
            "allowed_device_1": str(pol["device_ids"][1]),
            "allowed_device_2": str(pol["device_ids"][2]),
            "timestamp_min": str(pol["timestamp_range"][0]),
            "timestamp_max": str(pol["timestamp_range"][1]),
            "gps_lat_min": str(pol["gps_lat_range"][0]),
            "gps_lat_max": str(pol["gps_lat_range"][1]),
            "gps_long_min": str(pol["gps_long_range"][0]),
            "gps_long_max": str(pol["gps_long_range"][1]),
            "sensor_min": str(pol["sensor_min"]) }
    dirpath = os.path.join(ATT, "fab", f"{tag}")
    os.makedirs(dirpath, exist_ok=True)
    script = os.path.join(dirpath, "_prove.js")
    with open(script, "w") as f:
        f.write("const snarkjs=require('snarkjs'),fs=require('fs'),path=require('path');\n")
        f.write("const inp=" + json.dumps(inp) + ";\n")
        f.write(f"const dir={json.dumps(dirpath)};\n")
        f.write("(async()=>{try{const r=await snarkjs.groth16.fullProve(inp,"
                f"{json.dumps(os.path.join(REPO, 'outputs', 'v4', 'provenance_v4_js', 'provenance_v4.wasm'))},"
                f"{json.dumps(os.path.join(REPO, 'outputs', 'v4', 'circuit_v4.zkey'))});\n"
                "fs.writeFileSync(path.join(dir,'proof.json'),JSON.stringify(r.proof));\n"
                "fs.writeFileSync(path.join(dir,'public.json'),JSON.stringify(r.publicSignals));\n"
                "console.log('PROVE_OK');process.exit(0);}catch(e){console.error('PROVE_FAIL:'+(e.message||e).substring(0, 90));process.exit(1);}})();\n")
    r = run_cmd(["node", script], f"prove-{tag}", need_exit=None)
    if r["exit"] != 0:
        return None, r["stderr"]
    return dirpath, None

def load_manifests():
    m42 = list(csv.DictReader(open(MAN42)))
    m43 = list(csv.DictReader(open(MAN43)))
    return m42, m43


def limbs_of(path):
    import hashlib as _h
    h = _h.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    d = h.hexdigest()
    return str(int(d[:32], 16)), str(int(d[32:], 16))

def main():
    phases = sys.argv[1] if len(sys.argv) > 1 else "all"
    t0 = time.perf_counter()
    write_header()
    rows_done = load_rows()
    st = load_state()
    os.makedirs(POL_DIR, exist_ok=True)
    os.makedirs(TMP, exist_ok=True)
    for name, pol in (("wide", WIDE), ("strict", STRICT)):
        with open(os.path.join(POL_DIR, name + ".json"), "w") as f:
            json.dump(pol, f, indent=2)
    m42, m43 = load_manifests()
    bona42 = [r for r in m42 if r["label"] == "bonafide"]
    spoof42 = [r for r in m42 if r["label"] == "spoof"]
    subs = [r for r in m43 if r["label"] == "a1sub"]  # seed-44 substitutes live in the content manifest
    bona43 = [r for r in m43 if r["label"] == "bonafide"]
    costs = {"enroll_ms": [], "hold_ms": [], "fv_ms": []}

    # ── p0: enroll seed-42 genuine + a1sub spoof (gate counts) ───────────────
    if phases in ("p0", "all"):
        print("[p0] v4 enrollments (refusals expected for near-threshold/spoof)")
        st.setdefault("enroll", {})
        for r in bona42 + subs:
            fid = r["file_id"]
            if st["enroll"].get(fid) in ("enrolled", "refused"):
                continue
            rec = os.path.join(ATT, "enroll42", fid, "record.json")
            hand = os.path.join(TMP, f"hand_{fid}.json")
            code, info = enroll(rec, hand, r["flac_path"], f"42-{fid}")
            if code == 0:
                st["enroll"][fid] = "enrolled"
                costs["enroll_ms"].append(None)  # timing comes from run_cmds already logged
            else:
                st["enroll"][fid] = "refused"
                print(f"  [p0] {fid}: REFUSED ({(info.get('stderr') or '').strip().splitlines()[-1][:90]})")
            save_state(st)
        n_ok = sum(1 for v in st["enroll"].values() if v == "enrolled")
        print(f"[p0] enrolled={n_ok} refused={10 - n_ok}")
        print("[p0] done")

    enrolled42 = [r for r in bona42 if st.get("enroll", {}).get(r["file_id"]) == "enrolled"]
    rec_of = {r["file_id"]: os.path.join(ATT, "enroll42", r["file_id"], "record.json")
              for r in enrolled42}
    hand_of = {r["file_id"]: os.path.join(TMP, f"hand_{r['file_id']}.json")
               for r in enrolled42}
    subs_of = {r["file_id"]: r["flac_path"] for r in subs}

    def run_holder_measure(fid, od, hand, pol, nonce=None):
        # measure via run_cmd so we also capture peak memory; returns (ms, None)
        a = ["node", HOLDER, next(r["flac_path"] for r in bona42 if r["file_id"] == fid),
             od, "--handoff", hand, "--policy", os.path.join(POL_DIR, pol + ".json")]
        if nonce is not None: a += ["--nonce", str(nonce)]
        r = run_cmd(a, f"hold-{fid}", need_exit=0)
        return r["ms"], None
    globals()["run_holder_measure"] = run_holder_measure

    # ── p1: honest holder proofs (aligned wide policy) ────────────────────────
    if phases in ("p1", "all"):
        for r in enrolled42:
            fid = r["file_id"]
            od = os.path.join(ATT, "honest_proofs", fid)
            if st.get("honest_proof", {}).get(fid): continue
            ram_gate(f"prove {fid}")
            t = run_holder_measure(fid, od, hand_of[fid], "wide")
            if t is None:
                raise Stop(f"holder prove failed for {fid}")
            st.setdefault("honest_proof", {})[fid] = {"dir": od, "ms": t[0], "stages": t[1]}
            costs["hold_ms"].append(t[0])
            save_state(st)
        print("[p1] honest proofs done")


    # ── p2: A1 substitution (substitute file + ORIGINAL proof + record) ───────
    if phases in ("p2", "all"):
        for i, r in enumerate(bona42):
            fid = r["file_id"]
            sub = subs[i]["file_id"]
            if (fid, "A1", "S1", f"sub={sub}") not in rows_done and st.get("honest_proof", {}).get(fid):
                proof = os.path.join(st["honest_proof"][fid]["dir"], "proof.json")
                pub = os.path.join(st["honest_proof"][fid]["dir"], "public.json")
                a = fv_args(subs_of[sub], proof, pub, rec_of[fid])
                rr = run_cmd(a, f"A1-{fid}", need_exit=None)
                v, reason = parse_fv(rr["out"], rr["exit"], f"A1/{fid}")
                add(rows_done, file_id=fid, label=f"sub={sub}", attack_id="A1", system="S1",
                    command="verify_fully_v4 <substitute> <original proof/public> <original record>",
                    exit_code=rr["exit"], verdict=v, reason=reason, ms=rr["ms"],
                    pn=rr["peak_node_mb"], pp=rr["peak_python_mb"], pv="v4")
                add(rows_done, file_id=fid, label=f"sub={sub}", attack_id="A1", system="S2",
                    command="same run, Part A' outcome", exit_code=rr["exit"], verdict=v,
                    reason="Part A': " + reason, ms=rr["ms"], pn=rr["peak_node_mb"],
                    pp=rr["peak_python_mb"], pv="v4")
        print("[p2] A1 done")

    # ── p3/p4: A4 + A4' fabricated proofs ─────────────────────────────────────
    if phases in ("p3", "all"):
        for r in enrolled42:
            fid = r["file_id"]
            meta2 = {"device_id": 4096, "timestamp": 1780800000, "sensor_score": 99,
                     "gps_lat": 408399, "gps_long": 779199}
            hi, lo = limbs_of(r["flac_path"])
            d, err = prove_fabricated(meta2, "999000999000999", hi, lo, "wide", 0, f"A4-{fid}")
            if d is None:
                raise Stop(f"A4 prove failed for {fid}: {err[-200:]}")
            a = fv_args(r["flac_path"], os.path.join(d, "proof.json"),
                        os.path.join(d, "public.json"), rec_of[fid])
            rr = run_cmd(a, f"A4-{fid}", need_exit=None)
            v, reason = parse_fv(rr["out"], rr["exit"], f"A4/{fid}")
            add(rows_done, file_id=fid, label="fabricated-meta+salt", attack_id="A4", system="S1",
                command="holder->verify_fully_v4 (fabricated proof vs original record)",
                exit_code=rr["exit"], verdict=v, reason=reason, ms=rr["ms"],
                pn=rr["peak_node_mb"], pp=rr["peak_python_mb"], pv="v4")
        print("[p3] A4 done")
    if phases in ("p4", "all"):
        for r in enrolled42:
            fid = r["file_id"]
            meta_t = json.load(open(META))
            hi, lo = limbs_of(r["flac_path"])
            d, err = prove_fabricated(meta_t, "42424242424242424242424242",
                                      hi, lo, "wide", 0, f"A4p-{fid}")
            if d is None: raise Stop(f"A4' prove failed {fid}: {err[-200:]}")
            a = fv_args(r["flac_path"], os.path.join(d, "proof.json"),
                        os.path.join(d, "public.json"), rec_of[fid])
            rr = run_cmd(a, f"A4p-{fid}", need_exit=None)
            v, reason = parse_fv(rr["out"], rr["exit"], f"A4p/{fid}")
            add(rows_done, file_id=fid, label="true-meta+own-salt", attack_id="A4p", system="S1",
                command="attacker proves with TRUE metadata but OWN salt vs original record",
                exit_code=rr["exit"], verdict=v, reason=reason, ms=rr["ms"],
                pn=rr["peak_node_mb"], pp=rr["peak_python_mb"], pv="v4")
        print("[p4] A4' done")
    # ── p5: A5 tampered detector fields in the record ─────────────────────────
    if phases in ("p5", "all"):
        for r in enrolled42:
            fid = r["file_id"]
            rec2 = json.load(open(rec_of[fid]))
            rec2["det_decision"] = "spoof" if rec2["det_decision"] != "spoof" else "bonafide"
            rp2 = os.path.join(ATT, "a5", f"{fid}.json")
            os.makedirs(os.path.dirname(rp2), exist_ok=True)
            json.dump(rec2, open(rp2, "w"), indent=2)
            proof = os.path.join(st["honest_proof"][fid]["dir"], "proof.json")
            pub = os.path.join(st["honest_proof"][fid]["dir"], "public.json")
            rr = run_cmd(fv_args(r["flac_path"], proof, pub, rp2), f"A5-{fid}", need_exit=None)
            v, reason = parse_fv(rr["out"], rr["exit"], f"A5/{fid}")
            add(rows_done, file_id=fid, label="det_decision flip", attack_id="A5", system="S1",
                command="verify_fully_v4 with tampered det_decision (signature kept)",
                exit_code=rr["exit"], verdict=v, reason=reason, ms=rr["ms"],
                pn=rr["peak_node_mb"], pp=rr["peak_python_mb"], pv="v4")
        print("[p5] A5 done")

    # ── p6: A6 replay semantics ────────────────────────────────────────────────
    if phases in ("p6", "all"):
        for r in enrolled42:
            fid = r["file_id"]
            proof = os.path.join(st["honest_proof"][fid]["dir"], "proof.json")
            pub = os.path.join(st["honest_proof"][fid]["dir"], "public.json")
            # (a) within-window replay, no nonce expectation -> ACCEPT (residual)
            ra = run_cmd(fv_args(r["flac_path"], proof, pub, rec_of[fid]), f"A6a-{fid}", need_exit=None)
            va, ra_ = parse_fv(ra["out"], ra["exit"], f"A6a/{fid}")
            add(rows_done, file_id=fid, label="replay-within-window", attack_id="A6", system="S1",
                command="verify_fully_v4 (same record+file, second context)",
                exit_code=ra["exit"], verdict=va, reason=ra_ + " [residual per FIX_DESIGN]",
                ms=ra["ms"], pn=ra["peak_node_mb"], pp=ra["peak_python_mb"], pv="v4")
            # (b) fresh nonce expectation -> REJECT
            rb = run_cmd(fv_args(r["flac_path"], proof, pub, rec_of[fid],
                       ["--expect-nonce", "42"]), f"A6b-{fid}", need_exit=None)
            vb, rb_ = parse_fv(rb["out"], rb["exit"], f"A6b/{fid}")
            add(rows_done, file_id=fid, label="replay+fresh-nonce", attack_id="A6", system="S1",
                command="verify_fully_v4 --expect-nonce 42",
                exit_code=rb["exit"], verdict=vb, reason=rb_, ms=rb["ms"],
                pn=rb["peak_node_mb"], pp=rb["peak_python_mb"], pv="v4")
            # (c) after expiry -> REJECT
            recObj = json.load(open(rec_of[fid]))
            later = time.strftime("%Y-%m-%dT%H:%M:%S.000Z",
                                  time.gmtime(time.mktime(time.strptime(
                                      recObj["expires_at_utc"][:19], "%Y-%m-%dT%H:%M:%S")) + 3600))
            rc = run_cmd(fv_args(r["flac_path"], proof, pub, rec_of[fid],
                       ["--now", later]), f"A6c-{fid}", need_exit=None)
            vc, rc_ = parse_fv(rc["out"], rc["exit"], f"A6c/{fid}")
            add(rows_done, file_id=fid, label="after-expiry", attack_id="A6", system="S1",
                command="verify_fully_v4 --now (expires+1h)",
                exit_code=rc["exit"], verdict=vc, reason=rc_, ms=rc["ms"],
                pn=rc["peak_node_mb"], pp=rc["peak_python_mb"], pv="v4")
        print("[p6] A6 done")

    # ── p7: policy downgrade (wide proof vs strict verifier policy) ───────────
    if phases in ("p7", "all"):
        for r in enrolled42:
            fid = r["file_id"]
            proof = os.path.join(st["honest_proof"][fid]["dir"], "proof.json")
            pub = os.path.join(st["honest_proof"][fid]["dir"], "public.json")
            rr = run_cmd(fv_args(r["flac_path"], proof, pub, rec_of[fid],
                       ["--policy-file", os.path.join(POL_DIR, "strict.json")]),
                       f"DOWNGRADE-{fid}", need_exit=None)
            v, reason = parse_fv(rr["out"], rr["exit"], f"DOWNGRADE/{fid}")
            add(rows_done, file_id=fid, label="wide-proof vs strict-verifier", attack_id="DOWN",
                system="S1", command="verify_fully_v4 --policy-file strict.json",
                exit_code=rr["exit"], verdict=v, reason=reason, ms=rr["ms"],
                pn=rr["peak_node_mb"], pp=rr["peak_python_mb"], pv="v4")
        print("[p7] downgrade done")

    # p8: A2 content -- enroll 50 clean, 7 transforms per file via holder+verify
    if phases in ("p8", "all"):
        print("[p8] A2 on v4")
        st.setdefault("enroll43", {})
        troot = os.path.join(REPO, "outputs", "v3", "eval_content", "transforms", "a2")
        CONDS = ["mp3_64k", "mp3_32k", "opus_32k", "resample_8k_rt",
                 "noise_20db", "noise_10db", "reverb_rt60_0.3s"]
        for r43 in bona43:
            fid = r43["file_id"]
            if st["enroll43"].get(fid) in ("enrolled", "refused"): continue
            rec = os.path.join(ATT, "enroll43", fid, "record.json")
            hand = os.path.join(TMP, f"hand43_{fid}.json")
            code, info = enroll(rec, hand, r43["flac_path"], f"43-{fid}")
            st["enroll43"][fid] = "enrolled" if code == 0 else "refused"
            save_state(st)
        enr43 = [r for r in bona43 if st["enroll43"].get(r["file_id"]) == "enrolled"]
        print(f"[p8] seed-43 clean enrolled={len(enr43)} refused={50 - len(enr43)}")
        for r43 in enr43:
            fid = r43["file_id"]
            if not st.get("honest_proof43", {}).get(fid):
                od = os.path.join(ATT, "honest43", fid)
                ram_gate(f"A2 clean prove {fid}")
                hh = run_cmd(["node", HOLDER, r43["flac_path"], od,
                              "--handoff", os.path.join(TMP, f"hand43_{fid}.json"),
                              "--policy", os.path.join(POL_DIR, "wide.json")],
                             f"hold43-{fid}", need_exit=0)
                st.setdefault("honest_proof43", {})[fid] = {"dir": od, "ms": hh["ms"]}
                save_state(st)
            rec = os.path.join(ATT, "enroll43", fid, "record.json")
            hand = os.path.join(TMP, f"hand43_{fid}.json")
            for c in CONDS:
                key = ("A2", "S1", f"{fid}@{c}", "holder-proof vs clean record")
                if key in rows_done: continue
                tpath = os.path.join(troot, c, fid, "transform.flac")
                od = os.path.join(ATT, "a2_proofs", c, fid)
                if not os.path.exists(os.path.join(od, "proof.json")):
                    ram_gate(f"A2 prove {c}/{fid}")
                    rrr = run_cmd(["node", HOLDER, tpath, od, "--handoff", hand,
                                   "--policy", os.path.join(POL_DIR, "wide.json")],
                                  f"A2-hold-{c}-{fid}", need_exit=None)
                    if rrr["exit"] != 0:
                        add(rows_done, file_id=f"{fid}@{c}", label=c, attack_id="A2",
                            system="S1", command="holder refused (pre-prove guard)",
                            exit_code=rrr["exit"], verdict="REJECT",
                            reason=(rrr["stderr"] or "").strip().splitlines()[-1][:160]
                            if (rrr["stderr"] or "").strip() else "holder refusal",
                            ms=rrr["ms"], pn=rrr["peak_node_mb"],
                            pp=rrr["peak_python_mb"], pv="v4")
                        continue
                rr = run_cmd(fv_args(tpath, os.path.join(od, "proof.json"),
                                     os.path.join(od, "public.json"), rec),
                             f"A2-{c}-{fid}", need_exit=None)
                v, reason = parse_fv(rr["out"], rr["exit"], f"A2/{c}/{fid}")
                add(rows_done, file_id=f"{fid}@{c}", label=c, attack_id="A2", system="S1",
                    command="holder-prove(transform) -> verify_fully_v4 vs clean record",
                    exit_code=rr["exit"], verdict=v, reason=reason, ms=rr["ms"],
                    pn=rr["peak_node_mb"], pp=rr["peak_python_mb"], pv="v4")
        scores = json.load(open(os.path.join(EVAL, "content_scores.json")))
        thr = 1.7635419737
        for r43 in bona43:
            for c in CONDS:
                sc = scores[os.path.join(troot, c, r43["file_id"], "transform.flac")]
                add(rows_done, file_id=f"{r43['file_id']}@{c}", label="frozen-AASISTL",
                    attack_id="A2", system="S4", command="frozen scores (no rescore)",
                    exit_code="", verdict="bonafide" if sc >= thr else "spoof",
                    reason=f"score={sc:.6f} @thr={thr}", pv="v4")
        print("[p8] A2 done")

    # p9: A3 content -- 450 splices (holder proves under clean handoff)
    if phases in ("p9", "all"):
        print("[p9] A3 on v4")
        sroot = os.path.join(REPO, "outputs", "v3", "eval_content", "transforms", "a3")
        FRACS = ["0.1", "0.25", "0.5"]
        POSITIONS = ["start", "middle", "end"]
        scores = json.load(open(os.path.join(EVAL, "content_scores.json")))
        thr = 1.7635419737
        for r43 in bona43:
            fid = r43["file_id"]
            if st.get("enroll43", {}).get(fid) != "enrolled": continue
            rec = os.path.join(ATT, "enroll43", fid, "record.json")
            hand = os.path.join(TMP, f"hand43_{fid}.json")
            for frac in FRACS:
                for pos in POSITIONS:
                    sp = os.path.join(sroot, frac, pos, fid, "splice.flac")
                    key = ("A3", "S1", f"{fid}@{frac}_{pos}", "holder-proof vs clean record")
                    if key in rows_done: continue
                    od = os.path.join(ATT, "a3_proofs", frac, pos, fid)
                    if not os.path.exists(os.path.join(od, "proof.json")):
                        ram_gate(f"A3 prove {frac}/{pos}/{fid}")
                        run_cmd(["node", HOLDER, sp, od, "--handoff", hand,
                                 "--policy", os.path.join(POL_DIR, "wide.json")],
                                f"A3-hold-{frac}-{pos}-{fid}", need_exit=None)
                    rr = run_cmd(fv_args(sp, os.path.join(od, "proof.json"),
                                         os.path.join(od, "public.json"), rec),
                                 f"A3-{frac}-{pos}-{fid}", need_exit=None)
                    v, reason = parse_fv(rr["out"], rr["exit"], f"A3/{frac}/{pos}/{fid}")
                    sc = scores[sp]
                    add(rows_done, file_id=f"{fid}@{frac}_{pos}", label=f"{frac}_{pos}",
                        attack_id="A3", system="S1",
                        command="holder-prove(splice) then verify_fully_v4 vs clean record",
                        exit_code=rr["exit"], verdict=v,
                        reason=reason + f" [frozen splice score {sc:.6f}]", ms=rr["ms"],
                        pn=rr["peak_node_mb"], pp=rr["peak_python_mb"], pv="v4")
                    add(rows_done, file_id=f"{fid}@{frac}_{pos}", label=f"{frac}_{pos}",
                        attack_id="A3", system="S4", command="frozen splice score (no rescore)",
                        exit_code="", verdict="spoof" if sc < thr else "bonafide",
                        reason=f"score={sc:.6f} @thr={thr}", pv="v4")
        print("[p9] A3 splices done")
    # p9b: A3re re-enrollment residual (10 splices)
    if phases in ("p9", "all"):
        FRACS = ["0.1", "0.25", "0.5"]
        POSITIONS = ["start", "middle", "end"]
        sroot = os.path.join(REPO, "outputs", "v3", "eval_content", "transforms", "a3")
        re10 = [(bona43[0]["file_id"], f, p) for f in FRACS for p in POSITIONS] +                [(bona43[1]["file_id"], "0.5", "middle")]
        n_ref, n_enr = 0, 0
        for fid, frac, pos in re10:
            sp = os.path.join(sroot, frac, pos, fid, "splice.flac")
            key = ("A3re", "S1", f"{fid}@{frac}_{pos}", "re-enrollment path")
            if key in rows_done: continue
            rec = os.path.join(ATT, "a3_reenroll", frac, pos, fid, "record.json")
            hand = os.path.join(TMP, f"handre_{fid}_{frac}_{pos}.json")
            code, info = enroll(rec, hand, sp, f"re-{fid}-{frac}-{pos}")
            if code != 0:
                n_ref += 1
                msg = (info.get("stderr") or "").strip().splitlines()[-1][:160] if (info.get("stderr") or "").strip() else "refused"
                add(rows_done, file_id=f"{fid}@{frac}_{pos}", label=f"{frac}_{pos}",
                    attack_id="A3re", system="S1",
                    command="issue_capture_record_v4 over the splice",
                    exit_code=code, verdict="REJECT (enrollment gate)", reason=msg, pv="v4")
                continue
            n_enr += 1
            ram_gate(f"A3re prove {fid}-{frac}-{pos}")
            pr = os.path.join(ATT, "a3_reenroll", frac, pos, fid, "proofs")
            run_cmd(["node", HOLDER, sp, pr, "--handoff", hand,
                     "--policy", os.path.join(POL_DIR, "wide.json")],
                    f"A3re-hold-{fid}-{frac}-{pos}", need_exit=None)
            rr = run_cmd(fv_args(sp, os.path.join(pr, "proof.json"),
                                 os.path.join(pr, "public.json"), rec,
                                 ["--allow-flagged"]), f"A3re-{fid}-{frac}-{pos}",
                         need_exit=None)
            v, reason = parse_fv(rr["out"], rr["exit"], f"A3re/{fid}")
            add(rows_done, file_id=f"{fid}@{frac}_{pos}", label=f"{frac}_{pos}",
                attack_id="A3re", system="S1",
                command="full v4 pipeline over the splice (own record+proof)",
                exit_code=rr["exit"], verdict=v, reason=reason, ms=rr["ms"],
                pn=rr["peak_node_mb"], pp=rr["peak_python_mb"], pv="v4")
        print(f"[p9] re-enrollment: enrolled={n_enr} refused={n_ref} (A3 residual)")
        print("[p9] A3 done")
    print(f"[done {phases}] {time.perf_counter() - t0:.1f}s")
    return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except Stop as e:
        print(f"\nSTOPPED -- {e}", file=sys.stderr)
        sys.exit(2)
