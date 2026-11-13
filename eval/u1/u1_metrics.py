#!/usr/bin/env python
"""eval/u1/u1_metrics.py -- step-5 metrics from eval/u1/u1_scores.json.

Per condition (laundered / clean) x label: FAR/FRR at both operating points
(dev -0.9449426, eval 1.7635419737), pooled AUC, pooled EER, 95% bootstrap
CIs (10,000 resamples), plus paired clean-vs-laundered score shift per clip.
Writes eval/u1/u1_metrics.json.
"""
import json
import os
import sys

import numpy as np

U1 = os.path.dirname(os.path.abspath(__file__))
DEV = -0.9449426
EVAL_T = 1.7635419737


def main():
    segdir = sys.argv[1] if len(sys.argv) > 1 else "C1_segments"
    cache_name = sys.argv[2] if len(sys.argv) > 2 else "u1_scores.json"
    out_name = sys.argv[3] if len(sys.argv) > 3 else "u1_metrics.json"
    cache = json.load(open(os.path.join(U1, cache_name)))
    man = json.load(open(os.path.join(U1, "track_manifest.json")))
    rows = []
    for c in man["clips"]:
        seg = os.path.join(U1, segdir,
                           f"{c['order']:03d}_{c['kind']}_{c['file_id']}.wav")
        lau = cache.get(seg)
        cln = cache.get(c["src"])
        if lau is None or cln is None:
            continue
        rows.append({"file_id": c["file_id"], "kind": c["kind"],
                     "attack_id": c.get("attack_id", ""), "laundered": lau,
                     "clean": cln})
    if len(rows) < 100:
        print("STOP: incomplete cache (%d/100 clips)" % len(rows))
        return 1
    s_l = np.array([r["laundered"] for r in rows if r["kind"] == "spoof"])
    s_b = np.array([r["laundered"] for r in rows if r["kind"] == "bonafide"])
    c_l = np.array([r["clean"] for r in rows if r["kind"] == "spoof"])
    c_b = np.array([r["clean"] for r in rows if r["kind"] == "bonafide"])

    def far(arr, thr):
        return float((arr >= thr).mean()), int((arr >= thr).sum()), len(arr)

    def frr(arr, thr):
        return float((arr < thr).mean()), int((arr < thr).sum()), len(arr)

    def auc_ee(sa, sb):
        # pooled AUC via rank comparison; EER via bisection over thresholds
        x = np.concatenate([sa, sb])
        y = np.concatenate([np.ones(len(sa)), np.zeros(len(sb))])
        order = np.argsort(np.argsort(x))
        n1, n0 = len(sa), len(sb)
        auc = (order[:n1].sum() - n1 * (n1 - 1) / 2) * 1.0 / (n1 * n0)
        best = (0.5, None)
        for t in np.unique(x):
            far_m = float((sa >= t).mean())
            frr_m = float((sb < t).mean())
            if abs(far_m - frr_m) < best[0]:
                best = (abs(far_m - frr_m), t)
        t = best[1] if best[1] is not None else float(np.median(x))
        far_m = float((sa >= t).mean())
        frr_m = float((sb < t).mean())
        return float(auc), (float((far_m + frr_m) / 2), float(t))

    def boot_ci(sa, thr, n=10000, gt=True):
        rng = np.random.default_rng(44)
        xs = [float((sa[rng.integers(0, len(sa), len(sa))] >= thr).mean())
              if gt else
              float((sa[rng.integers(0, len(sa), len(sa))] < thr).mean())
              for _ in range(n)]
        lo, hi = np.percentile(xs, [2.5, 97.5])
        return [float(lo), float(hi)]

    out = {"thresholds": {"dev": DEV, "eval": EVAL_T}}
    for cond, sa, sb in [("clean", c_l, c_b), ("laundered", s_l, s_b)]:
        d = {}
        d["far_dev"] = far(sa, DEV)
        d["far_eval"] = far(sa, EVAL_T)
        d["frr_dev"] = frr(sb, DEV)
        d["frr_eval"] = frr(sb, EVAL_T)
        d["auc"], d["eer"] = auc_ee(sa, sb)
        d["far_dev_ci95"] = boot_ci(sa, DEV)
        d["frr_dev_ci95"] = boot_ci(sb, DEV, gt=False)
        out[cond] = d
    # paired per-clip shift
    sh = [r["laundered"] - r["clean"] for r in rows]
    out["paired_shift"] = {
        "median": float(np.median(sh)), "mean": float(np.mean(sh)),
        "q10": float(np.percentile(sh, 10)), "q90": float(np.percentile(sh, 90))}
    out["per_clip"] = rows
    json.dump(out, open(os.path.join(U1, out_name), "w"), indent=1)
    print(json.dumps({k: out[k] for k in ("clean", "laundered", "paired_shift")},
                     indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
