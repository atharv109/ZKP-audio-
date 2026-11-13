#!/usr/bin/env python
"""eval/run_content_all.py -- full driver: score A2+A3, then all eval phases."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from content_common import REPO, Stop
import content_eval
import score_content

def main():
    import csv
    m = list(csv.DictReader(open(os.path.join(REPO, "eval", "sample_manifest_content.csv"))))
    paths = []
    root = os.path.join(REPO, "outputs", "v3", "eval_content", "transforms")
    for r in m:
        if r["label"] == "a1sub":
            continue
        for d in ("a2",):
            pass
        # A2: 7 conditions per file
        for c in ["mp3_64k", "mp3_32k", "opus_32k", "resample_8k_rt",
                  "noise_20db", "noise_10db", "reverb_rt60_0.3s"]:
            paths.append(os.path.join(root, "a2", c, r["file_id"], "transform.flac"))
        if r["label"] == "bonafide":
            for frac in ["0.1", "0.25", "0.5"]:
                for pos in ["start", "middle", "end"]:
                    paths.append(os.path.join(root, "a3", frac, pos, r["file_id"], "splice.flac"))
    print(f"scoring {len(paths)} files (%d batches of 32)" % -(-len(paths) // 32))
    score_content.score(paths, "content")
    print("scoring done -> content_scores.json")
    content_eval.main()

if __name__ == "__main__":
    try:
        main()
    except Stop as e:
        print(f"STOPPED: {e}", file=sys.stderr)
        sys.exit(2)
