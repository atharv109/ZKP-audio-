#!/usr/bin/env python
"""eval/score_content.py -- batched AASIST-L scoring via the UNCHANGED
audio_benchmark/run_inference.py (<=32 files per fresh Python process).

Scores cache: eval/content_scores.json {path: score} (append-only).
"""
import csv, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from content_common import (REPO, EVAL, RUN_INFERENCE, WEIGHTS, AASIST_REPO,
                            CONFIG, run_cmd, ram_gate)

CACHE = os.path.join(EVAL, "content_scores.json")
BATCH = 32

def load_cache():
    if os.path.exists(CACHE):
        with open(CACHE) as f:
            return json.load(f)
    return {}

def save_cache(c):
    with open(CACHE, "w") as f:
        json.dump(c, f, indent=0, sort_keys=True)

def score(paths, tag):
    """paths: list of absolute paths (labels 'unknown'); returns {path: score}."""
    cache = load_cache()
    todo = [p for p in paths if p not in cache]
    out = {}
    for b, chunk in enumerate([todo[i:i+BATCH] for i in range(0, len(todo), BATCH)]):
        ram_gate(f"score batch {b} ({tag})")
        lp = os.path.join(EVAL, f"_batch_{tag}_{b}.csv")
        with open(lp, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["file", "label"])
            for p in chunk:
                w.writerow([p, "unknown"])
        outp = os.path.join(EVAL, f"_batch_{tag}_{b}_out.csv")
        r = run_cmd([sys_exec := "python", RUN_INFERENCE, "--backend", "aasist",
                     "--weights", WEIGHTS, "--aasist-repo", AASIST_REPO,
                     "--config", CONFIG, "--labels", lp, "--out", outp,
                     "--threshold", "0.0"], f"score-{tag}-b{b}")
        scores = {}
        with open(outp) as f:
            for row in csv.DictReader(f):
                scores[row["file"]] = float(row["score"])
        missing = [p for p in chunk if p not in scores]
        if missing:
            raise RuntimeError(f"scoring missing {len(missing)} files, "
                               f"first: {missing[0]}")
        cache.update(scores)
        save_cache(cache)
        os.remove(lp)
        print(f"  [score {tag}] batch {b}: {len(chunk)} files "
              f"({r['ms']} ms, py peak {r['peak_python_mb']} MB)", flush=True)
    out.update({p: cache[p] for p in paths})
    return out
