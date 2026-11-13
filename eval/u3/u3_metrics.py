#!/usr/bin/env python
"""eval/u3/u3_metrics.py -- per-detector metrics for RESULTS_U3.md.
Reads eval/u3/u3_scores_<D>_<mode>.json caches; per experiment computes
FAR/FRR at the detector's OWN dev-EER threshold + pooled AUC/EER + 95%
bootstrap CIs, and the A3 inside/beyond-window breakdown.
Writes eval/u3/u3_metrics_<D>.json."""
import json, os, sys
import numpy as np

U3 = os.path.dirname(os.path.abspath(__file__))
from score_u3 import CONDS, FRACS, POSITIONS, U2ROOT, EVAL, CACHE_DIR  # noqa: E402
LA_EVAL_FLAC = r"ASVspoof2019_LA_eval\flac"
SEED = 44


def _cache_path(det, mode):
    p = os.path.join(CACHE_DIR, f"u3_scores_{det}_{mode}.json")
    if not os.path.exists(p):
        alt = os.path.join(U3, f"u3_scores_{det}_{mode}.json")
        if os.path.exists(alt):
            p = alt
    return p


def dev_cache(det):
    return json.load(open(_cache_path(det, "dev")))


def eer_point(sa, sb):
    """bona=sb, spoof=sa; returns (eer, thr) minimizing |far-frr|."""
    x = np.unique(np.concatenate([sa, sb]))
    best = (2.0, None)
    for t in x:
        far = float((sa >= t).mean())
        frr = float((sb < t).mean())
        if abs(far - frr) < best[0]:
            best = (abs(far - frr), t)
    t = best[1] if best[1] is not None else float(np.median(x))
    far = float((sa >= t).mean())
    frr = float((sb < t).mean())
    return (float((far + frr) / 2), float(t))


def auc_dir(sa, sb):
    """P(bona > spoof) + ties/2 (bonafide-higher direction)."""
    order = np.argsort(np.argsort(np.concatenate([sa, sb])))
    n0, n1 = len(sa), len(sb)
    r_sp = order[:n0].astype(float)
    auc_sp = (r_sp.sum() - n0 * (n0 - 1) / 2) / (n0 * n1)
    return float(1.0 - auc_sp)


def ci_boot(sa, thr, n=10000, gt=True):
    rng = np.random.default_rng(SEED)
    if gt:
        xs = [float((sa[rng.integers(0, len(sa), len(sa))] >= thr).mean()) for _ in range(n)]
    else:
        xs = [float((sa[rng.integers(0, len(sa), len(sa))] < thr).mean()) for _ in range(n)]
    import numpy as _np
    lo, hi = _np.percentile(xs, [2.5, 97.5])
    return [float(lo), float(hi)]


def rate(sa, thr, accept=True):
    if accept:
        n = int((sa >= thr).sum())
        return [float((sa >= thr).mean()), n, len(sa)]
    n = int((sa < thr).sum())
    return [float((sa < thr).mean()), n, len(sa)]


def main():
    det = sys.argv[1] if len(sys.argv) > 1 else "D2"
    out = {"detector": det}
    # ---- threshold from FULL dev (D2) or stated subset ----
    dev = dev_cache(det)
    man = json.load(open(os.path.join(EVAL, "u1", "track_manifest.json"))) if False else None
    import csv
    bona, spoo = [], []
    proto = r"ASVspoof2019_LA_cm_protocols\ASVspoof2019.LA.cm.dev.trl.txt"
    flac = r"ASVspoof2019_LA_dev\flac"
    for line in open(proto):
        p = line.strip().split()
        if len(p) >= 5:
            f = os.path.join(flac, p[1] + ".flac")
            s = dev.get(f)
            if s is None:
                continue
            (bona if p[4] == "bonafide" else spoo).append(s)
    sb = np.array(bona); sa = np.array(spoo)
    eer, thr = eer_point(sa, sb)
    out["dev"] = {"n_bona": len(sb), "n_spoof": len(sa),
                  "eer": eer, "threshold": thr,
                  "auc_bonadir": auc_dir(sa, sb)}
    T = thr
    json.dump(out, open(os.path.join(U3, f"u3_metrics_{det}.json"), "w"), indent=1)
    print(f"[{det}] dev n={len(sb)}+{len(sa)} EER={eer:.4%} thr={T:.6f}")
    return 0


def load(det, mode):
    p = _cache_path(det, mode)
    return json.load(open(p)) if os.path.exists(p) else {}


def labels_of(mode):
    import csv
    if mode in ("a2", "a3"):
        rows = []
        with open(os.path.join(EVAL, "sample_manifest_u2.csv")) as f:
            for r in csv.DictReader(f):
                rows.append(r)
        return rows
    return None


def score_list(cache, paths):
    return np.array([cache[p] for p in paths if p in cache], dtype=float)


def add_attack(out, det, mode, tag, cache, sp_paths, bo_paths):
    sa = score_list(cache, sp_paths)
    sb = score_list(cache, bo_paths)
    T = out["dev"]["threshold"]
    d = {"n_sp": len(sa), "n_bo": len(sb),
         "far": rate(sa, T) if len(sa) else None,
         "far_ci95": ci_boot(sa, T) if len(sa) else None}
    if len(sb):
        d["frr"] = rate(sb, T, accept=False)
        d["frr_ci95"] = ci_boot(sb, T, gt=False)
    if len(sa) and len(sb):
        d["auc_bonadir"] = auc_dir(sa, sb)
        d["eer"] = eer_point(sa, sb)
    out[tag] = d


def a3_window_groups(rows, cache, det):
    """Inside-window = splice region entirely within [0, nb_samp]; uses each
    splice file's own length + frac + position (detector window truncates)."""
    import soundfile as sf
    NB = 64600  # all three detectors window on the first 64,600 samples
    groups = {"inside": [], "beyond": []}
    for r in rows:
        lab = r["label"]
        if lab != "bonafide":
            continue
        for fr in FRACS:
            for pos in POSITIONS:
                p = os.path.join(U2ROOT, "a3", fr, pos, r["file_id"], "splice.flac")
                if p not in cache or not os.path.isfile(p):
                    continue
                n = sf.info(p).frames
                f = float(fr)
                if pos == "start":
                    lo, hi = 0.0, f
                elif pos == "middle":
                    lo, hi = 0.5 - f / 2, 0.5 + f / 2
                else:
                    lo, hi = 1.0 - f, 1.0
                span_in = lo * n >= 0 and hi * n <= NB
                groups["inside" if span_in else "beyond"].append(p)
    return groups


def write_all(det):
    out = json.load(open(os.path.join(U3, f"u3_metrics_{det}.json")))
    T = out["dev"]["threshold"]
    # LA eval subset (experiment 1's pooled eval EER on the feasible subset)
    cache = load(det, "eval")
    if cache:
        prot = (r"ASVspoof2019_LA_cm_protocols"
                r"\ASVspoof2019.LA.cm.eval.trl.txt")
        sp3 = [l.strip().split() for l in open(prot) if len(l.split()) >= 5]
        import random
        rng = random.Random(SEED)
        by = {}
        for p in sp3:
            if p[4] != "bonafide":
                by.setdefault(p[3], []).append(p)
        sp_paths = []
        for a in sorted(by):
            picks = by[a][:]
            rng.shuffle(picks)
            sp_paths += [os.path.join(LA_EVAL_FLAC, p[1] + ".flac") for p in picks[:500]]
        bo_paths = [os.path.join(LA_EVAL_FLAC, p[1] + ".flac")
                    for p in sp3 if p[4] == "bonafide"]
        add_attack(out, det, "eval", "eval_subset", cache, sp_paths, bo_paths)
    rows = labels_out = None
    import csv
    with open(os.path.join(EVAL, "sample_manifest_u2.csv")) as f:
        rows = list(csv.DictReader(f))
    # ---- clean seed-44 sample (experiment 1) ----
    cache = load(det, "clean")
    if cache:
        sp = [r["flac_path"] for r in rows if r["label"] == "spoof"]
        bo = [r["flac_path"] for r in rows if r["label"] == "bonafide"]
        add_attack(out, det, "clean", "clean_sample", cache, sp, bo)
    # ---- A2 ----
    cache = load(det, "a2")
    per_cond = {}
    for c in CONDS:
        ps = [os.path.join(U2ROOT, "a2", c, r["file_id"], "transform.flac")
              for r in rows if r["label"] == "spoof"]
        bo = [os.path.join(U2ROOT, "a2", c, r["file_id"], "transform.flac")
              for r in rows if r["label"] == "bonafide"]
        add_attack(out, det, "a2", f"a2_{c}", cache, ps, bo)
    n_ok = sum(len(cache) for _ in [1])
    out["a2_scored"] = len(cache)
    # ---- A3 ----
    cache = load(det, "a3")
    bona_rows = [r for r in rows if r["label"] == "bonafide"]
    for fr in FRACS:
        for pos in POSITIONS:
            ps = [os.path.join(U2ROOT, "a3", fr, pos, r["file_id"], "splice.flac")
                  for r in bona_rows]
            add_attack(out, det, "a3", f"a3_{fr}_{pos}", cache, ps, [])
    grp = a3_window_groups(rows, cache, det)
    for g, ps in grp.items():
        add_attack(out, det, "a3wb", f"a3_{g}", cache, ps, [])
    # ---- U1 C1 / C2 ----
    man = json.load(open(os.path.join(EVAL, "u1", "track_manifest.json")))
    for tag, segdir in (("u1c1", "C1_segments"), ("u1c2", "C2_segments")):
        cache = load(det, tag)
        sp = [os.path.join(EVAL, "u1", segdir,
                           f"{c['order']:03d}_spoof_{c['file_id']}.wav")
              for c in man["clips"] if c["kind"] == "spoof"]
        bo = [os.path.join(EVAL, "u1", segdir,
                           f"{c['order']:03d}_bonafide_{c['file_id']}.wav")
              for c in man["clips"] if c["kind"] == "bonafide"]
        add_attack(out, det, tag, tag, cache, sp, bo)
        out[tag + "_scored"] = {"sp": len([p for p in sp if p in cache]),
                                "bo": len([p for p in bo if p in cache])}
    json.dump(out, open(os.path.join(U3, f"u3_metrics_{det}.json"), "w"), indent=1)
    return out


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[2] == "full":
        o = write_all(sys.argv[1])
        print(json.dumps({k: v for k, v in o.items() if k != "dev"}, indent=1)[:2000])
    else:
        o = main()
