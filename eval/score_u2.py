#!/usr/bin/env python
"""eval/score_u2.py -- u2 transform-corpus scoring (frozen AASIST-L).
Batched <=32/fresh run_inference.py process; RAM-gated; resumable
(cache eval/u2_scores.json)."""
import csv, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from content_common import REPO, EVAL, RUN_INFERENCE, WEIGHTS, AASIST_REPO, CONFIG, run_cmd, ram_gate

MAN = os.path.join(REPO, "eval", "sample_manifest_u2.csv")
ROOT = os.path.join(REPO, "outputs", "v3", "eval_content", "u2")
CACHE = os.path.join(EVAL, "u2_scores.json")
BATCH = 32
CONDS = ["mp3_64k", "mp3_32k", "opus_32k", "resample_8k_rt",
         "noise_20db", "noise_10db", "reverb_rt60_0.3s"]
FRACS = ["0.1", "0.25", "0.5"]
POSITIONS = ["start", "middle", "end"]

def main():
    score_map = {}
    with open(MAN) as f:
        for r in csv.DictReader(f):
            fid, lab = r["file_id"], r["label"]
            for c in CONDS:
                score_map[os.path.join(ROOT, "a2", c, fid, "transform.flac")] = (fid, lab, c)
            if lab == "bonafide":
                for frac in FRACS:
                    for pos in POSITIONS:
                        score_map[os.path.join(ROOT, "a3", frac, pos, fid, "splice.flac")] = (fid, lab, frac + "_" + pos)
    cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
    todo = [p for p in score_map if p not in cache and os.path.isfile(p)]
    missingfiles = sum(1 for p in score_map if not os.path.isfile(p))
    print(f"to_score={len(todo)} total={len(score_map)} not_yet_created={missingfiles}", flush=True)
    if missingfiles:
        print("STOP: transform corpus incomplete; run transform_u2.py first.", file=sys.stderr)
        return 1
    for b, chunk in enumerate([todo[i:i+BATCH] for i in range(0, len(todo), BATCH)]):
        ram_gate(f"u2 batch {b}")
        lp = os.path.join(EVAL, "_u2_batch.csv")
        with open(lp, "w", newline="") as f:
            w = csv.writer(f); w.writerow(["file", "label"])
            for x in chunk: w.writerow([x, "unknown"])
        outp = os.path.join(EVAL, "_u2_batch_out.csv")
        r = run_cmd([sys.executable, RUN_INFERENCE, "--backend", "aasist",
                     "--weights", WEIGHTS, "--aasist-repo", AASIST_REPO,
                     "--config", CONFIG, "--labels", lp, "--out", outp,
                     "--threshold", "0.0"], f"u2-b{b}", need_exit=0, timeout=600)
        with open(outp) as f:
            for row in csv.DictReader(f):
                cache[row["file"]] = float(row["score"])
        json.dump(cache, open(CACHE, "w"), indent=0, sort_keys=True)
        os.remove(lp)
        if b % 20 == 0:
            print(f"  batch {b}: scored={len(cache)} ({r['ms']} ms py_peak {r['peak_python_mb']})", flush=True)
    print(f"DONE scored={len(cache)}/{len(score_map)}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
