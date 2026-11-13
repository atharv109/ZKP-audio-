#!/usr/bin/env python
"""eval/content_eval.py -- content-attack orchestrator (A1 cleanup, A2, A3).

Phases (resumable, append-only; stops on ANY unexpected error):
  p0  A1 cleanup: 10 unenrolled substitutes, 1:1 vs genuine records
  p1c enroll 50 clean bona fide (proof + record + S3)
  p1d A2 crypto: 50 bona fide x 7 conditions
  p2c A3 crypto: 450 splices (+ 10 re-enrollments)
  p4  S4 aggregate metric rows
Usage: python eval/content_eval.py p0|p1c|p1d|p2c|p4|all
"""
import csv, importlib.util, json, os, statistics, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from content_common import (REPO, EVAL, DEMO_WF, ISSUE, VERIFY_FULLY, ISSUER_KEY,
                            ENROLL_META, WEIGHTS, AASIST_REPO, CONFIG,
                            THRESHOLD, THRESHOLD_DEFAULT, Stop, ram_gate,
                            run_cmd, parse_fv, s3, sha256_file,
                            ContentRows, CSV_FIELDS)

ROOT = os.path.join(REPO, "outputs", "v3", "eval_content")
CSV_OUT = os.path.join(EVAL, "results_content.csv")
COSTS = os.path.join(EVAL, "content_run_costs.json")
MERGED = os.path.join(REPO, "final_outputs", "minnah_comparison",
                      "dataset_acquisition", "merged_scores.csv")

def load_merged_scores():
    sc = {}
    with open(MERGED, newline="") as f:
        for row in csv.DictReader(f):
            sc[os.path.splitext(os.path.basename(row["file"]))[0]] = float(row["score"])
    return sc

def load_manifest():
    with open(os.path.join(EVAL, "sample_manifest_content.csv")) as f:
        return list(csv.DictReader(f))

COST_LOG = []

def ensure_prove_dir(run_dir, flac, tag):
    """Get a verified demo_workflow run dir (fresh; crashed attempts set aside)."""
    man = os.path.join(run_dir, "demo_result.json")
    try:
        with open(man) as f:
            m = json.load(f)
        if m.get("verdict", "").startswith("VERIFIED") \
           and os.path.isfile(os.path.join(run_dir, "proof.json")) \
           and os.path.isfile(os.path.join(run_dir, "public.json")):
            with open(os.path.join(run_dir, "demo_result.json")) as f:
                stages = {s["stage"]: s["ms"] for s in json.load(f)["stages"]}
            return {"run_dir": run_dir, "resumed": True,
                    "stages": stages, "ms": sum(stages.values())}
    except (OSError, json.JSONDecodeError):
        pass
    if os.path.exists(run_dir):
        stamp = time.strftime("%Y%m%d-%H%M%S")
        os.rename(run_dir, run_dir + f"_crashed_{stamp}")
    ram_gate(f"prove {tag}")
    r = run_cmd([ "node", DEMO_WF, flac, ENROLL_META, run_dir,
                  "--weights", WEIGHTS, "--aasist-repo", AASIST_REPO,
                  "--config", CONFIG], f"prove-{tag}", need_exit=0)
    with open(os.path.join(run_dir, "demo_result.json")) as f:
        stages = {s["stage"]: s["ms"] for s in json.load(f)["stages"]}
    COST_LOG.append({"tag": tag,
                     "run_dir": run_dir, "ms_total": r["ms"], "stages": stages,
                     "peak_python_mb": r["peak_python_mb"],
                     "peak_node_mb": r["peak_node_mb"]})
    return {"run_dir": run_dir, "resumed": False, "stages": stages, "ms": r["ms"],
            "peak_python_mb": r["peak_python_mb"], "peak_node_mb": r["peak_node_mb"]}

def phase0(rows, manifest, merged):
    """A1 cleanup: 10 unenrolled substitutes x 10 genuine records (1:1)."""
    bona = [r for r in manifest if r["label"] == "bonafide"]
    subs = [r for r in manifest if r["label"] == "a1sub"]
    print(f"[p0] A1 cleanup: {len(subs)} unenrolled substitutes")
    for i, sub in enumerate(subs):
        sub_dir = os.path.join(ROOT, "a1sub_proofs", sub["file_id"])
        pr = ensure_prove_dir(sub_dir, sub["flac_path"], f"a1sub-{i}")
        rec = os.path.join(ROOT, "enroll", bona[i]["file_id"], "record.json")
        fid = sub["file_id"]
        done_any = any(k[0] == "S1" and k[1] == fid and k[2] == "A1" for k in rows.done)
        tag = "A1c" if done_any else "A1"
        if not done_any:
            print(f"  [p0] skip {fid} (fresh state, not the correction pass)")
            continue
        print(f"  [p0] re-measuring {fid} as {tag} (supersedes earlier attempt)")
        argv = ["node", VERIFY_FULLY, sub["flac_path"],
                os.path.join(sub_dir, "proof.json"),
                os.path.join(sub_dir, "public.json"), rec]
        r = run_cmd(argv, f"A1-{fid}", need_exit=None)
        pv = parse_fv(r["stdout"], r["exit"], f"A1/{fid}")
        cmd = "node scripts/verify_fully.js <substitute.flac> <substitute proof/public> " \
              f"<record of {bona[i]['file_id']}>"
        rows.add(file_id=fid, label=f"a1sub-vs-{bona[i]['file_id']}", attack_id=tag,
                 system="S1", command=cmd, exit_code=r["exit"], verdict=pv["verdict"],
                 reason=pv["reason"], runtime_ms=r["ms"], peak_node_mb=r["peak_node_mb"],
                 peak_python_mb=r["peak_python_mb"])
        rows.add(file_id=fid, label=f"a1sub-vs-{bona[i]['file_id']}", attack_id=tag,
                 system="S2", command=cmd + " [Part B, same run]",
                 exit_code=r["exit"], verdict=pv["verdict"],
                 reason="Part B: " + pv["reason"], runtime_ms=r["ms"],
                 peak_node_mb=r["peak_node_mb"], peak_python_mb=r["peak_python_mb"])
        v, msg = s3("lookup", sha256_file(sub["flac_path"]))
        rows.add(file_id=fid, label="a1sub", attack_id=tag, system="S3",
                 command="python eval/s3_registry.py lookup <substitute sha>",
                 exit_code="", verdict=v, reason=msg)
        sc = float(sub["s4_score"])
        rows.add(file_id=fid, label="a1sub", attack_id=tag, system="S4",
                 command="read merged_scores.csv (frozen score)",
                 exit_code="", verdict="bonafide" if sc >= THRESHOLD else "spoof",
                 reason=f"score={sc}: "
                        f"{'bonafide' if sc >= THRESHOLD else 'spoof'}@{THRESHOLD}")
    print("[p0] done")

def phase1c(rows, manifest):
    """Enroll 50 clean bona fide: prove + issuer record + S3."""
    bona = [r for r in manifest if r["label"] == "bonafide"]
    print(f"[p1c] enrolling {len(bona)} clean bona fide files")
    for i, b in enumerate(bona):
        run_dir = os.path.join(ROOT, "enroll", b["file_id"])
        pr = ensure_prove_dir(run_dir, b["flac_path"], f"enroll-{b['file_id']}")
        rec = os.path.join(run_dir, "record.json")
        if not os.path.exists(rec):
            r = run_cmd(["node", ISSUE, b["flac_path"], rec,
                         "--issuer-key", ISSUER_KEY], f"issue-{b['file_id']}")
        v, msg = s3("enroll", sha256_file(b["flac_path"]), {"file_id": b["file_id"]})
        print(f"  [enroll] {b['file_id']}: "
              + ("resumed" if pr["resumed"] else f"fresh ({pr['ms']} ms)")
              + f", S3 {msg}", flush=True)
    print("[p1c] done")

def verify_against_clean_record(rows, attack_id, label, fid, transformed_path,
                                proof_dir, clean_record, clean_score, tag):
    """Transformed/spliced file + its own fresh proof vs the CLEAN record."""
    if ("S1", fid, attack_id, label) in rows.done:   # resume: cell already measured
        return None
    argv = ["node", VERIFY_FULLY, transformed_path,
            os.path.join(proof_dir, "proof.json"),
            os.path.join(proof_dir, "public.json"), clean_record]
    r = run_cmd(argv, f"{attack_id}-{tag}", need_exit=None)
    pv = parse_fv(r["stdout"], r["exit"], f"{attack_id}/{tag}")
    cmd = f"node scripts/verify_fully.js <{os.path.basename(transformed_path)}> " \
          "<its own proof/public> <clean original record>"
    rows.add(file_id=fid, label=label, attack_id=attack_id, system="S1",
             command=cmd, exit_code=r["exit"], verdict=pv["verdict"],
             reason=pv["reason"], runtime_ms=r["ms"],
             peak_node_mb=r["peak_node_mb"], peak_python_mb=r["peak_python_mb"])
    rows.add(file_id=fid, label=label, attack_id=attack_id, system="S2",
             command=cmd + " [Part B, same run]", exit_code=r["exit"],
             verdict=pv["verdict"], reason="Part B: " + pv["reason"],
             runtime_ms=r["ms"], peak_node_mb=r["peak_node_mb"],
             peak_python_mb=r["peak_python_mb"])
    v, msg = s3("lookup", sha256_file(transformed_path))
    rows.add(file_id=fid, label=label, attack_id=attack_id, system="S3",
             command="python eval/s3_registry.py lookup <transformed sha>",
             exit_code="", verdict=v, reason=msg)
    return pv["verdict"]

def s4_row(rows, fid, label, attack_id, score):
    verdict = "bonafide" if score >= THRESHOLD else "spoof"
    rows.add(file_id=fid, label=label, attack_id=attack_id, system="S4",
             command="AASIST-L score (content run, eval/score_content.py)",
             exit_code="", verdict=verdict,
             reason=f"score={score:.6f}: "
                    f"{'bonafide' if score >= THRESHOLD else 'spoof'}@{THRESHOLD}")
    return verdict

def phase1d(rows, manifest, scores):
    """A2: 50 bona fide x 7 conditions."""
    bona = [r for r in manifest if r["label"] == "bonafide"]
    CONDITIONS = ["mp3_64k", "mp3_32k", "opus_32k", "resample_8k_rt",
                  "noise_20db", "noise_10db", "reverb_rt60_0.3s"]
    print("[p1d] A2 crypto verification")
    for b in bona:
        rec = os.path.join(ROOT, "enroll", b["file_id"], "record.json")
        for c in CONDITIONS:
            tdir = os.path.join(ROOT, "transforms", "a2", c, b["file_id"])
            tpath = os.path.join(tdir, "transform.flac")
            fid = f"{b['file_id']}@{c}"
            pd = os.path.join(ROOT, "proofs", "a2", c, b["file_id"])
            ensure_prove_dir(pd, tpath, f"a2-{c}-{b['file_id']}")
            verify_against_clean_record(rows, "A2", c, fid, tpath, pd, rec,
                                        float(b["s4_score"]), f"{c}-{b['file_id']}")
            s4_row(rows, fid, c, "A2", scores[tpath])
    print("[p1d] done")

def phase2c(rows, manifest, scores):
    """A3: 450 splices + 10 re-enrollments."""
    bona = [r for r in manifest if r["label"] == "bonafide"]
    FRACS = ["0.1", "0.25", "0.5"]
    POSITIONS = ["start", "middle", "end"]
    print("[p2c] A3 crypto verification")
    n_re = 0
    for b in bona:
        rec = os.path.join(ROOT, "enroll", b["file_id"], "record.json")
        for frac in FRACS:
            for pos in POSITIONS:
                tdir = os.path.join(ROOT, "transforms", "a3", frac, pos, b["file_id"])
                tpath = os.path.join(tdir, "splice.flac")
                fid = f"{b['file_id']}@{frac}_{pos}"
                pd = os.path.join(ROOT, "proofs", "a3", frac, pos, b["file_id"])
                ensure_prove_dir(pd, tpath, f"a3-{frac}_{pos}-{b['file_id']}")
                verify_against_clean_record(rows, "A3", f"{frac}_{pos}", fid,
                                            tpath, pd, rec, float(b["s4_score"]),
                                            f"{frac}_{pos}-{b['file_id']}")
                s4_row(rows, fid, f"{frac}_{pos}", "A3", scores[tpath])
                # re-enrollment for the first 10 splices (deterministic subset:
                # file #1's 9 variants + file #2's 0.5/middle)
                if (b is bona[0] or (b is bona[1] and frac == "0.5" and pos == "middle")) and n_re < 10:
                    re_dir = os.path.join(ROOT, "reenroll", frac, pos, b["file_id"])
                    pr = ensure_prove_dir(re_dir, tpath,
                                          f"a3re-{frac}_{pos}-{b['file_id']}")
                    rer = os.path.join(re_dir, "record.json")
                    if not os.path.exists(rer):
                        rr = run_cmd(["node", ISSUE, tpath, rer,
                                      "--issuer-key", ISSUER_KEY],
                                     f"a3re-issue-{frac}_{pos}-{b['file_id']}")
                    v, msg = s3("enroll", sha256_file(tpath),
                                {"file_id": fid, "kind": "splice re-enrollment"})
                    vr = run_cmd(["node", VERIFY_FULLY, tpath,
                                  os.path.join(re_dir, "proof.json"),
                                  os.path.join(re_dir, "public.json"), rer],
                                 f"a3re-verify-{frac}_{pos}-{b['file_id']}",
                                 need_exit=None)
                    pvr = parse_fv(vr["stdout"], vr["exit"], f"A3re/{fid}")
                    rows.add(file_id=fid, label=f"{frac}_{pos}", attack_id="A3re",
                             system="S1", command="node scripts/verify_fully.js "
                             "<splice.flac> <its fresh proof/public> <its OWN new record>",
                             exit_code=vr["exit"], verdict=pvr["verdict"],
                             reason=pvr["reason"] + " [re-enrolled splice]",
                             runtime_ms=vr["ms"], peak_node_mb=vr["peak_node_mb"],
                             peak_python_mb=vr["peak_python_mb"])
                    v3, msg3 = s3("lookup", sha256_file(tpath))
                    rows.add(file_id=fid, label=f"{frac}_{pos}", attack_id="A3re",
                             system="S3", command="python eval/s3_registry.py lookup",
                             exit_code="", verdict=v3, reason=msg3)
                    n_re += 1
    print("[p2c] done")

def phase4(rows, manifest, scores):
    """S4 aggregate metric rows: A2 per condition, A3 per fraction x position."""
    import importlib.util as _ilu
    p = os.path.join(REPO, "final_outputs", "minnah_comparison",
                     "compute_full_eval_metrics.py")
    spec = _ilu.spec_from_file_location("cfm", p)
    cfm = _ilu.module_from_spec(spec)
    spec.loader.exec_module(cfm)

    bona = [r for r in manifest if r["label"] == "bonafide"]
    spoof = [r for r in manifest if r["label"] == "spoof"]
    CONDITIONS = ["mp3_64k", "mp3_32k", "opus_32k", "resample_8k_rt",
                  "noise_20db", "noise_10db", "reverb_rt60_0.3s"]
    # clean baseline on the SAME 100 files (frozen scores)
    bona_ids = [r["file_id"] for r in bona]
    spoof_ids = [r["file_id"] for r in spoof]
    merged_clean_b = [load_merged_scores()[i] for i in bona_ids]
    merged_clean_s = [load_merged_scores()[i] for i in spoof_ids]
    eer, thr = cfm.eer_interpolated(
        __import__("numpy").asarray(merged_clean_b),
        __import__("numpy").asarray(merged_clean_s))
    auc = cfm.auc_mann_whitney(__import__("numpy").asarray(merged_clean_b),
                               __import__("numpy").asarray(merged_clean_s))
    rows.add(file_id="*", label="clean_baseline", attack_id="A2", system="S4",
             command="frozen merged_scores.csv for the same 100 files",
             exit_code="", verdict=f"EER={eer:.6f}",
             reason=f"clean EER={eer*100:.4f}% AUC={auc:.6f} @thr={THRESHOLD} "
                    f"FRR={sum(1 for s in merged_clean_b if s < THRESHOLD)}/50 "
                    f"FAR={sum(1 for s in merged_clean_s if s >= THRESHOLD)}/50")
    for c in CONDITIONS:
        b = [scores[os.path.join(ROOT, "transforms", "a2", c, f, "transform.flac")]
             for f in bona_ids]
        s = [scores[os.path.join(ROOT, "transforms", "a2", c, f, "transform.flac")]
             for f in spoof_ids]
        eer, _ = cfm.eer_interpolated(__import__("numpy").asarray(b),
                                      __import__("numpy").asarray(s))
        aucv = cfm.auc_mann_whitney(__import__("numpy").asarray(b),
                                    __import__("numpy").asarray(s))
        frr = sum(1 for x in b if x < THRESHOLD)
        far = sum(1 for x in s if x >= THRESHOLD)
        rows.add(file_id="*", label=c, attack_id="A2", system="S4",
                 command="AASIST-L rescoring (content run)",
                 exit_code="", verdict=f"EER={eer:.6f}",
                 reason=f"EER={eer*100:.4f}% AUC={aucv:.6f} @thr FRR={frr}/50 "
                        f"FAR={far}/50 (n=100)")
    FRACS = ["0.1", "0.25", "0.5"]
    POSITIONS = ["start", "middle", "end"]
    for frac in FRACS:
        for pos in POSITIONS:
            det = 0
            for f in bona_ids:
                sc = scores[os.path.join(ROOT, "transforms", "a3", frac, pos,
                                         f, "splice.flac")]
                if sc < THRESHOLD:
                    det += 1
            rows.add(file_id="*", label=f"{frac}_{pos}", attack_id="A3", system="S4",
                     command="AASIST-L rescoring (content run)",
                     exit_code="", verdict=f"detection_rate={det}/50",
                     reason=f"spliced->spoof {det}/50 @thr={THRESHOLD} "
                            f"(frac={frac}, pos={pos})")
    print("[p4] metric rows done")

def main():
    phase = sys.argv[1] if len(sys.argv) > 1 else "all"
    t0 = time.perf_counter()
    rows = ContentRows(CSV_OUT)
    manifest = load_manifest()
    merged = load_merged_scores()
    scores = json.load(open(os.path.join(EVAL, "content_scores.json")))\
        if os.path.exists(os.path.join(EVAL, "content_scores.json")) else {}
    if phase in ("p0", "all"):
        phase0(rows, manifest, merged)
    if phase in ("p1c", "all"):
        phase1c(rows, manifest)
    if phase in ("p1d", "all"):
        if not scores:
            print("STOP: content_scores.json empty -- run scoring first "
                  "(python eval -c 'from score_content import ...' or the driver below)",
                  file=sys.stderr)
            return 1
        phase1d(rows, manifest, scores)
    if phase in ("p2c", "all"):
        phase2c(rows, manifest, scores)
    if phase in ("p4", "all"):
        phase4(rows, manifest, scores)
    with open(COSTS, "w") as f:
        json.dump({"started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                   "prove_runs": COST_LOG}, f, indent=2)
        f.write("\n")
    print(f"phase(s) {phase} done in {time.perf_counter()-t0:.1f}s")
    return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except Stop as e:
        print(f"\nSTOPPED -- unexpected error (per rules, not worked around):\n{e}",
              file=sys.stderr)
        sys.exit(2)
