#!/usr/bin/env python
"""eval/score_dev.py -- full ASVspoof 2019 LA dev scoring (frozen AASIST-L).

Batched (<=32 files per fresh run_inference.py process), RAM-gated, resumable
(cache: eval/dev_scores.json). Labels from the OFFICIAL CM dev protocol.
Also writes eval/dev_labels.csv (file,label) for later thresholding.
"""
import csv, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from content_common import REPO, EVAL, RUN_INFERENCE, WEIGHTS, AASIST_REPO, CONFIG, run_cmd, ram_gate

PROTOCOL = r"ASVspoof2019_LA_cm_protocols\ASVspoof2019.LA.cm.dev.trl.txt"
FLAC_DIR = r"ASVspoof2019_LA_dev\flac"
CACHE = os.path.join(EVAL, "dev_scores.json")
BATCH = 32

def main():
    protocol, missing = {}, []
    with open(PROTOCOL) as f:
        for line in f:
            parts = line.split()
            if len(parts) == 5 and parts[4] in ("bonafide", "spoof"):
                protocol[parts[1]] = parts[4]
    p = 0
    cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
    todo = []
    for utt, lab in sorted(protocol.items()):
        f = os.path.join(FLAC_DIR, utt + ".flac")
        if not os.path.isfile(f):
            missing.append(utt); continue
        if utt not in cache:
            todo.append(f)
    with open(os.path.join(EVAL, "dev_labels.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        for utt, lab in sorted(protocol.items()):
            w.writerow([utt, lab])
    p = 1
    print(f"protocol={len(protocol)} on-disk={len(protocol) - len(missing)} "
          f"missing={len(missing)} to_score={len(todo)}", flush=True)
    if missing:
        print(f"first missing: {missing[:3]}", file=sys.stderr)
    for b, chunk in enumerate([todo[i:i+BATCH] for i in range(0, len(todo), BATCH)]):
        ram_gate(f"dev batch {b}")
        lp = os.path.join(EVAL, "_dev_batch.csv")
        with open(lp, "w", newline="") as f:
            w = csv.writer(f); w.writerow(["file", "label"])
            for x in chunk: w.writerow([x, "unknown"])
        outp = os.path.join(EVAL, "_dev_batch_out.csv")
        r = run_cmd([sys.executable, RUN_INFERENCE, "--backend", "aasist",
                     "--weights", WEIGHTS, "--aasist-repo", AASIST_REPO,
                     "--config", CONFIG, "--labels", lp, "--out", outp,
                     "--threshold", "0.0"], f"dev-b{b}", need_exit=0, timeout=600)
        with open(outp) as f:
            for row in csv.DictReader(f):
                cache[os.path.splitext(os.path.basename(row["file"]))[0]] = float(row["score"])
        json.dump(cache, open(CACHE, "w"), indent=0, sort_keys=True)
        os.remove(lp)
        if b % 25 == 0:
            print(f"  batch {b}: scored_total={len(cache)} ({r['ms']} ms)", flush=True)
    print(f"DONE: scored={len(cache)}/{len(protocol)}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
