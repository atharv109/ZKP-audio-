#!/usr/bin/env python
"""eval/final/compute_rates.py -- RESULTS_FINAL.md section 1.

Pooled + per-attack spoof-accept / bona-fide-reject rates on the FULL LA eval
score set at a given threshold, computed from an existing scores CSV
(file,label,prediction,score,correct) joined to the OFFICIAL CM eval protocol
(utt -> label + attack tag). No rescoring.

Convention (matches eval/u3/u3_metrics.py, the pipeline's metric code):
  score higher = more bonafide; spoof ACCEPT = score >= thr;
  bona-fide REJECT = score < thr.
Strict-inequality variants (> accept, <= reject) are also printed for audit.
"""
import argparse, csv, os, sys, collections

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scores", required=True)
    ap.add_argument("--protocol", required=True)
    ap.add_argument("--threshold", required=True, type=float)
    ap.add_argument("--json-out", default=None)
    a = ap.parse_args()
    thr = a.threshold

    proto = {}   # utt -> (label, attack)
    with open(a.protocol) as f:
        for line in f:
            p = line.split()
            if len(p) == 5 and p[4] in ("bonafide", "spoof"):
                proto[p[1]] = (p[4], p[3])

    rows, seen, mism, extra = 0, set(), 0, []
    scores = {}
    with open(a.scores, newline="") as f:
        for row in csv.DictReader(f):
            rows += 1
            utt = os.path.splitext(os.path.basename(row["file"].strip()))[0]
            if utt in seen:
                sys.exit(f"FATAL: duplicate utterance {utt}")
            seen.add(utt)
            scores[utt] = float(row["score"])
            if utt not in proto:
                extra.append(utt)
            elif row["label"].strip() != proto[utt][0]:
                mism += 1

    n_bona = sum(1 for u in proto if proto[u][0] == "bonafide")
    n_spoof = len(proto) - n_bona
    missing = [u for u in proto if u not in scores]

    sa_ge = sa_gt = fr_lt = fr_le = 0
    per = collections.defaultdict(lambda: [0, 0])  # attack -> [accepts, total]
    for u, (lab, atk) in proto.items():
        s = scores[u]
        if lab == "spoof":
            if s >= thr: sa_ge += 1
            if s > thr:  sa_gt += 1
            per[atk][0] += 1 if s >= thr else 0
            per[atk][1] += 1
        else:
            if s < thr: fr_lt += 1
            if s <= thr: fr_le += 1

    def pc(n, d): return f"{n} / {d} ({100.0*n/d:.2f}%)" if d else "n/a"

    print(f"scores rows={rows} unique={len(seen)} protocol={len(proto)} "
          f"(bona={n_bona} spoof={n_spoof}) missing={len(missing)} extra={len(extra)} "
          f"label_mismatches={mism}")
    print(f"threshold = {thr!r}")
    print(f"POOLED spoof-accept  (score >= thr): {pc(sa_ge, n_spoof)}")
    print(f"POOLED spoof-accept  (score >  thr): {pc(sa_gt, n_spoof)}")
    print(f"POOLED bona-reject   (score <  thr): {pc(fr_lt, n_bona)}")
    print(f"POOLED bona-reject   (score <= thr): {pc(fr_le, n_bona)}")
    print("per-attack spoof-accept (score >= thr):")
    for atk in sorted(per):
        acc, tot = per[atk]
        print(f"  {atk}: {pc(acc, tot)}")
    if a.json_out:
        import json
        out = {"threshold": thr, "scores": os.path.abspath(a.scores),
               "protocol": os.path.abspath(a.protocol),
               "rows": rows, "label_mismatches": mism,
               "missing": len(missing), "extra": len(extra),
               "pooled": {"spoof_accept_ge": [sa_ge, n_spoof],
                          "spoof_accept_gt": [sa_gt, n_spoof],
                          "bona_reject_lt": [fr_lt, n_bona],
                          "bona_reject_le": [fr_le, n_bona]},
               "per_attack": {k: v for k, v in sorted(per.items())}}
        json.dump(out, open(a.json_out, "w"), indent=1)

if __name__ == "__main__":
    sys.exit(main())
