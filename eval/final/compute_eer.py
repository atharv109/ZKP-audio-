#!/usr/bin/env python
"""eval/final/compute_eer.py -- RESULTS_FINAL.md section 2.

Recompute pooled dev EER + dev-optimal threshold from an existing score cache
(utt -> score JSON) + labels CSV (utt,label). No rescoring.

Methods reported (all bona-fide-higher direction, FAR = (spoof >= t),
FRR = (bona < t) — the pipeline convention from eval/u3/u3_metrics.py):
  A. discrete point search: threshold minimizing |FAR - FRR| over the unique
     observed scores (identical to u3_metrics.eer_point)
  B. linear interpolation on the FAR/FRR step curves between the two adjacent
     thresholds bracketing the FAR=FRR crossing
  C. ROC-curve EER via scipy interp1d + brentq (classic interpolation)
"""
import argparse, csv, json, sys
import numpy as np

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scores", required=True)
    ap.add_argument("--labels", required=True)
    ap.add_argument("--json-out", default=None)
    a = ap.parse_args()

    cache = json.load(open(a.scores))
    labels = {}
    with open(a.labels, newline="") as f:
        for row in csv.reader(f):
            if row[0] == "file":
                continue
            labels[row[0]] = row[1]

    missing = [u for u in labels if u not in cache]
    if missing:
        print(f"WARNING: {len(missing)} labelled utterances absent from cache")
    sb = np.array([cache[u] for u, l in sorted(labels.items()) if l == "bonafide" and u in cache])
    sa = np.array([cache[u] for u, l in sorted(labels.items()) if l == "spoof" and u in cache])
    print(f"n_bonafide={len(sb)} n_spoof={len(sa)} total={len(sb)+len(sa)}")

    ts = np.unique(np.concatenate([sa, sb]))
    sa_s = np.sort(sa)
    sb_s = np.sort(sb)
    # far(t) = fraction of spoofs with score >= t ; frr(t) = fraction of bona with score < t
    far = (len(sa) - np.searchsorted(sa_s, ts, side="left")) / len(sa)
    frr = np.searchsorted(sb_s, ts, side="left") / len(sb)

    # ---- A. discrete point search (pipeline convention) ----
    gap = np.abs(far - frr)
    iA = int(np.argmin(gap))
    eerA = (far[iA] + frr[iA]) / 2
    thrA = float(ts[iA])

    # ---- B. linear interpolation between bracketing step points ----
    d = frr - far  # negative below crossing, positive above
    pos = np.nonzero(d > 0)[0]
    if len(pos) == 0 or pos[0] == 0:
        thrB, eerB = thrA, eerA
    else:
        j = int(pos[0])
        t0, t1 = ts[j - 1], ts[j]
        d0, d1 = d[j - 1], d[j]
        thrB = float(t0 + (t1 - t0) * (-d0) / (d1 - d0))
        farB = float(np.interp(thrB, ts, far))
        frrB = float(np.interp(thrB, ts, frr))
        eerB = (farB + frrB) / 2

    # ---- C. ROC interp1d + brentq EER ----
    eerC = None
    try:
        from scipy.interpolate import interp1d
        from scipy.optimize import brentq
        ff, fr = far[::-1], frr[::-1]          # far ascending
        keep = np.concatenate([[True], ff[1:] != ff[:-1]])
        g = interp1d(ff[keep], fr[keep])
        eerC = float(brentq(lambda x: float(g(x)) - x, 0.0, 1.0))
    except Exception as e:
        print(f"method C skipped: {e}")

    # ---- AUC: Mann-Whitney, ties = 0.5 (bona-higher) ----
    allv = np.concatenate([sb, sa])
    order = np.argsort(allv, kind="mergesort")
    sv = allv[order]
    uniq, inv, cnt = np.unique(sv, return_inverse=True, return_counts=True)
    cum = np.cumsum(cnt)
    avg_rank = (cum - cnt) + (cnt + 1) / 2.0    # mean of ascending ranks in each tie group
    ranks = np.empty(len(allv), dtype=float)
    ranks[order] = avg_rank[inv]
    r_b = ranks[:n0] if (n0 := len(sb)) else ranks[:len(sb)]
    u_b = r_b.sum() - n0 * (n0 + 1) / 2.0
    auc = u_b / (n0 * len(sa))

    print(f"A discrete-point : EER={eerA:.6%} threshold={thrA!r} (far={far[iA]:.6%} frr={frr[iA]:.6%})")
    print(f"B linear-interp  : EER={eerB:.6%} threshold={thrB!r}")
    if eerC is not None:
        print(f"C scipy ROC      : EER={eerC:.6%}")
    print(f"AUC (bona-higher, tie=0.5) = {auc:.6f}")

    if a.json_out:
        out = {"scores": a.scores, "labels": a.labels,
               "n_bonafide": int(n0), "n_spoof": int(len(sa)),
               "A_discrete": {"eer": float(eerA), "threshold": thrA,
                              "far": float(far[iA]), "frr": float(frr[iA])},
               "B_lininterp": {"eer": float(eerB), "threshold": thrB},
               "C_scipy_roc": {"eer": eerC},
               "auc_bona_higher": float(auc)}
        json.dump(out, open(a.json_out, "w"), indent=1)

if __name__ == "__main__":
    sys.exit(main())
