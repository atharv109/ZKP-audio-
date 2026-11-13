#!/usr/bin/env python
"""eval/verify_surprises.py -- verify the two surprising RESULTS_CONTENT.md results.

V1 truncation: for all 450 splices, is any spoof sample visible to the model
(model window = first nb_samp=64600 samples, front-truncated or np.tile-repeated)?
Split detection rates by visible vs entirely-beyond. Control: 10 missed
end-inserts cropped so the spoof falls inside the first window, re-scored.

V2 levels: 5 bona fide files per condition (reverb_rt60_0.3s, noise_10db):
sr/channels/duration/peak/RMS/clipping vs clean. Plus score distributions
(min/median/max) per condition, bona fide vs spoof.
Writes eval/verify_truncation.csv + eval/verify_levels.csv.
"""
import csv, json, os, sys
import numpy as np, soundfile as sf
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from content_common import REPO, EVAL, THRESHOLD
import score_content

ROOT = os.path.join(REPO, "outputs", "v3", "eval_content")
NB_SAMP = 64600  # audio_benchmark/models.py:129 + AASIST-L.conf:15

def visible_window(N_total, idx, L):
    """Positions k in [0, NB_SAMP) the model sees: spliced[k] if long, else tiled.
    Spoof occupies spliced coords [idx, idx+L). Returns (visible_bool, first_k)."""
    if N_total >= NB_SAMP:
        win = range(NB_SAMP)
    else:
        win = [(k % N_total) for k in range(NB_SAMP)]  # tiled mapping
    for k in win:
        if idx <= k < idx + L:
            return True, k
    return False, None

def v1_truncation():
    with open(os.path.join(EVAL, "splice_index_manifest.csv")) as f:
        sp = list(csv.DictReader(f))
    scores = json.load(open(os.path.join(EVAL, "content_scores.json")))
    rows = []
    for s in sp:
        N_total, idx, L = int(s["out_len"]), int(s["insert_idx"]), int(s["insert_len"])
        vis, first_k = visible_window(N_total, idx, L)
        sc = scores[s["path"]]
        rows.append({"target": s["target"], "frac": s["frac"], "position": s["position"],
                     "N_total": N_total, "visible": vis, "first_visible_k": first_k or "",
                     "score": sc, "detected": sc < THRESHOLD, "path": s["path"]})
    with open(os.path.join(EVAL, "verify_truncation.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)
    for pos in ("start", "middle", "end"):
        grp = [r for r in rows if r["position"] == pos]
        for vis in (True, False):
            g = [r for r in grp if r["visible"] == vis]
            if g:
                det = sum(r["detected"] for r in g)
                print(f"  [{pos}] visible={vis}: detection {det}/{len(g)}")
    miss_end = [r for r in rows if r["position"] == "end" and not r["detected"]]
    print(f"  missed end-inserts: {len(miss_end)}; of them spoof-visible: "
          f"{sum(r['visible'] for r in miss_end)}")
    return rows, miss_end

def v1_control(miss_end):
    """Crop each missed end-insert to its LAST nb_samp samples: the spoof segment
    (file tail) then falls inside the model's first window. Re-score."""
    picks = sorted(miss_end, key=lambda r: r["path"])[:10]
    ctrl_paths = []
    os.makedirs(os.path.join(ROOT, "control_crops"), exist_ok=True)
    for r in picks:
        y, fsx = sf.read(r["path"], dtype="float64")
        crop = y[-NB_SAMP:] if len(y) > NB_SAMP else np.tile(y, NB_SAMP // len(y) + 1)[:NB_SAMP]
        out = os.path.join(ROOT, "control_crops",
                           f"{r['target']}_{r['frac']}_{r['position']}.flac")
        sf.write(out, crop, fsx, subtype="PCM_16")
        ctrl_paths.append((out, r))
    scs = score_content.score([p for p, _ in ctrl_paths], "control")
    det = 0
    print("  control (crop so spoof is inside first window):")
    for out, r in ctrl_paths:
        sc = scs.get(out, float("nan"))
        d = sc < THRESHOLD
        det += d
        print(f"    {r['target']} frac={r['frac']}: orig {r['score']:.6f} -> crop "
              f"{sc:.6f} {'DETECTED' if d else 'miss'}")
    print(f"  control total: {det}/{len(ctrl_paths)} detected "
          f"(vs {sum(1 for r in picks) } pre-crop all missed)")

def wav_stats(path):
    y, sr = sf.read(path, dtype="float64")
    ch = 1 if y.ndim == 1 else y.shape[1]
    y1 = y if y.ndim == 1 else y[:, 0]
    clips = int(np.sum(np.abs(y) > 0.999))
    return {"sr": sr, "channels": ch, "dur_s": round(len(y1) / sr, 3),
            "peak": round(float(np.max(np.abs(y1))), 4),
            "rms": round(float(np.sqrt(np.mean(y1 ** 2))), 4), "clips": clips}

def v2_levels():
    with open(os.path.join(EVAL, "sample_manifest_content.csv")) as f:
        bona = [r for r in csv.DictReader(f) if r["label"] == "bonafide"][:5]
    conds = ["reverb_rt60_0.3s", "noise_10db"]
    rows = []
    for r in bona:
        c = wav_stats(r["flac_path"]); c.update({"file": r["file_id"], "cond": "clean"})
        rows.append(c)
        for cond in conds:
            p = os.path.join(ROOT, "transforms", "a2", cond, r["file_id"], "transform.flac")
            c = wav_stats(p); c.update({"file": r["file_id"], "cond": cond})
            rows.append(c)
    with open(os.path.join(EVAL, "verify_levels.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)
    for r in rows:
        print(f"  {r['cond']:18s} {r['file']}: sr={r['sr']} ch={r['channels']} "
              f"dur={r['dur_s']} peak={r['peak']} rms={r['rms']} clips={r['clips']}")

def v3_distributions():
    scores = json.load(open(os.path.join(EVAL, "content_scores.json")))
    with open(os.path.join(EVAL, "sample_manifest_content.csv")) as f:
        m = list(csv.DictReader(f))
    bona_ids = {r["file_id"] for r in m if r["label"] == "bonafide"}
    spoof_ids = {r["file_id"] for r in m if r["label"] == "spoof"}
    CONDS = ["mp3_64k", "mp3_32k", "opus_32k", "resample_8k_rt", "noise_20db",
             "noise_10db", "reverb_rt60_0.3s"]
    def stats(xs):
        xs = sorted(xs); import statistics as st
        return f"min {xs[0]:.3f} / med {st.median(xs):.3f} / max {xs[-1]:.3f}"
    print("  per-condition score distributions (bonafide | spoof):")
    merged = os.path.join(REPO, "final_outputs", "minnah_comparison",
                          "dataset_acquisition", "merged_scores.csv")
    import csv as _csv
    clean = {}
    with open(merged, newline="") as f:
        for row in _csv.DictReader(f):
            k = os.path.splitext(os.path.basename(row["file"]))[0]
            clean[k] = float(row["score"])
    print(f"    {'clean(frozen)':18s} B {stats([clean[i] for i in bona_ids])} | "
          f"S {stats([clean[i] for i in spoof_ids])}")
    for cond in CONDS:
        b = [scores[os.path.join(ROOT, "transforms", "a2", cond, i, "transform.flac")]
             for i in bona_ids]
        s = [scores[os.path.join(ROOT, "transforms", "a2", cond, i, "transform.flac")]
             for i in spoof_ids]
        print(f"    {cond:18s} B {stats(b)} | S {stats(s)}")

if __name__ == "__main__":
    print("== V1 truncation ==")
    rows, miss_end = v1_truncation()
    print("== V1 control ==")
    v1_control(miss_end)
    print("== V2 levels ==")
    v2_levels()
    print("== V3 score distributions ==")
    v3_distributions()
