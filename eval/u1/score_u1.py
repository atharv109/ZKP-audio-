#!/usr/bin/env python
"""eval/u1/score_u1.py -- U1 laundered-clip scoring (frozen AASIST-L).

Scores the 100 laundered clips (C1_segments, 16 kHz PCM_16) and the same 100
clips' clean originals (flac, per manifest), RAM-gated batches <=32 via
run_inference.py, cache eval/u1/u1_scores.json. Resumable.
"""
import csv
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from content_common import RAM_GATE_MB, ram_gate, run_cmd  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EVAL = os.path.join(REPO, "eval")
U1 = os.path.join(EVAL, "u1")
RUN_INFERENCE = os.path.join(REPO, "audio_benchmark", "run_inference.py")
WEIGHTS = r"<HOME>\external\aasist\models\weights\AASIST-L.pth"
AASIST_REPO = r"<HOME>\external\aasist"
CONFIG = r"<HOME>\external\aasist\config\AASIST-L.conf"
# (cache file chosen per argv in main)
BATCH = 32


def main():
    segdir = sys.argv[1] if len(sys.argv) > 1 else "C1_segments"
    cache_name = sys.argv[2] if len(sys.argv) > 2 else "u1_scores.json"
    man = json.load(open(os.path.join(U1, "track_manifest.json")))
    items = []
    for c in man["clips"]:
        seg = os.path.join(U1, segdir,
                           f"{c['order']:03d}_{c['kind']}_{c['file_id']}.wav")
        items.append((seg, "launder", c["kind"], c["file_id"]))
        items.append((c["src"], "clean", c["kind"], c["file_id"]))
    items = [(p, m, k, fid) for (p, m, k, fid) in items if os.path.isfile(p)]
    cache = json.load(open(os.path.join(U1, cache_name))) if os.path.exists(os.path.join(U1, cache_name)) else {}
    todo = [x for x in items if x[0] not in cache]
    print(f"to_score={len(todo)} cached={len(cache)}/{len(items)}", flush=True)
    for b, chunk in enumerate([todo[i:i + BATCH] for i in range(0, len(todo), BATCH)]):
        ram_gate(f"u1 score batch {b}")
        lp = os.path.join(EVAL, "_u1_batch.csv")
        with open(lp, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["file", "label"])
            for x in chunk:
                w.writerow([x[0], "unknown"])
        outp = os.path.join(EVAL, "_u1_batch_out.csv")
        r = run_cmd([sys.executable, RUN_INFERENCE, "--backend", "aasist",
                     "--weights", WEIGHTS, "--aasist-repo", AASIST_REPO,
                     "--config", CONFIG, "--labels", lp, "--out", outp,
                     "--threshold", "0.0"], f"u1-b{b}", need_exit=0, timeout=900)
        with open(outp) as f:
            for row in csv.DictReader(f):
                cache[row["file"]] = float(row["score"])
        json.dump(cache, open(os.path.join(U1, cache_name), "w"), indent=0, sort_keys=True)
        os.remove(lp)
        if b % 5 == 0:
            print(f"  batch {b}: scored={len(cache)} ({r['ms']} ms "
                  f"py_peak {r['peak_python_mb']}MB)", flush=True)
    print(f"DONE scored={len(cache)}/{len(items)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
