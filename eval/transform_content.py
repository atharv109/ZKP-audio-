#!/usr/bin/env python
"""eval/transform_content.py -- build A2 (7 conditions x 100 files) + A3 (450 splices).

Outputs 16 kHz mono FLAC under outputs/v3/eval_content/transforms/. Exact
parameters logged to eval/transform_params.json; splice sample indices to
eval/splice_index_manifest.csv. Deterministic seeds. Idempotent (resume).
"""
import csv, json, os, subprocess, sys
import numpy as np
import soundfile as sf
from scipy.signal import resample_poly, fftconvolve

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVAL = os.path.join(REPO, "eval")
ROOT = os.path.join(REPO, "outputs", "v3", "eval_content")
MANIFEST = os.path.join(EVAL, "sample_manifest_content.csv")
PARAMS = os.path.join(EVAL, "transform_params.json")
SPLICE_MANIFEST = os.path.join(EVAL, "splice_index_manifest.csv")
CONDITIONS = ["mp3_64k", "mp3_32k", "opus_32k", "resample_8k_rt",
              "noise_20db", "noise_10db", "reverb_rt60_0.3s"]
FRACS = ["0.1", "0.25", "0.5"]
POSITIONS = ["start", "middle", "end"]
FS = 16000

def ffmpeg_codec(src, tmp, out, kbps, codec):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", src,
                    "-codec:a", codec, "-b:a", f"{kbps}k", "-ac", "1",
                    "-ar", "16000", tmp], check=True, capture_output=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", tmp,
                    "-ac", "1", "-ar", "16000", "-sample_fmt", "s16", out],
                   check=True, capture_output=True)
    os.remove(tmp)

def build_a2(bona_spoof):
    log = {}
    for i, r in enumerate(bona_spoof):
        x, fs = sf.read(r["flac_path"], dtype="float64")
        if fs != FS or x.ndim != 1:
            print(f"STOP: {r['flac_path']} fs={fs} ndim={x.ndim}", file=sys.stderr)
            sys.exit(1)
        rng = np.random.default_rng(43000 + i)
        cond_dir = lambda c: os.path.join(ROOT, "transforms", "a2", c, r["file_id"])
        fl = {}
        for c in CONDITIONS:
            out = os.path.join(cond_dir(c), "transform.flac")
            os.makedirs(cond_dir(c), exist_ok=True)
            if os.path.exists(out) and os.path.getsize(out) > 0:
                continue
            if c in ("mp3_64k", "mp3_32k"):
                kbps = c.split("_")[1].rstrip("k")
                ffmpeg_codec(r["flac_path"], out + ".tmp.mp3", out, kbps, "libmp3lame")
                fl[c] = f"libmp3lame {kbps} kbps, decoded to 16 kHz mono FLAC"
            elif c == "opus_32k":
                ffmpeg_codec(r["flac_path"], out + ".tmp.ogg", out, 32, "libopus")
                fl[c] = "libopus 32 kbps (ogg), decoded to 16 kHz mono FLAC"
            elif c == "resample_8k_rt":
                y = resample_poly(resample_poly(x, 1, 2), 2, 1)
                y = y[:len(x)] if len(y) > len(x) else np.pad(y, (0, len(x) - len(y)))
                sf.write(out, y, FS, subtype="PCM_16")
                fl[c] = "resample_poly 16k->8k (1:2) -> 16k (2:1), default Kaiser FIR"
            elif c.startswith("noise_"):
                snr_db = 20 if "20db" in c else 10
                scale = float(np.sqrt(np.mean(x ** 2) / 10 ** (snr_db / 10)))
                y = x + rng.normal(0, 1, x.shape) * scale
                sf.write(out, y, FS, subtype="PCM_16")
                fl[c] = f"additive white Gaussian at SNR {snr_db} dB (scale {scale:.6f})"
            elif c.startswith("reverb"):
                n_tail = int(np.ceil(0.3 * FS))          # 4800-tap tail
                env = 10.0 ** (-3.0 * (np.arange(1, n_tail + 1) / FS) / 0.3)
                tail = rng.normal(0, 1, n_tail) * env
                tail = tail / np.max(np.abs(tail)) * 0.5  # peak-normalized tail
                h = np.concatenate([[1.0], tail])          # direct path tap 1.0
                y = fftconvolve(x, h)[: len(x)]
                m = np.max(np.abs(y))
                if m > 1.0:
                    y = y / m * 0.99
                sf.write(out, y, FS, subtype="PCM_16")
                fl[c] = "IR: tap0=1.0 direct + 4800-tap exp-decay noise (RT60 0.3 s), tail peak 0.5"
        if fl:
            log[r["file_id"]] = fl
    return log

def build_a3(bona, spoof):
    fields = ["target", "source", "frac", "position", "insert_idx",
              "insert_len", "target_len", "out_len", "path"]
    rows = []
    for bi, b in enumerate(bona):
        x, fs = sf.read(b["flac_path"], dtype="float64")
        s, _ = sf.read(spoof[bi % len(spoof)]["flac_path"], dtype="float64")
        n = len(x)
        for frac in FRACS:
            L = int(round(float(frac) * n))
            for pos in POSITIONS:
                idx = {"start": 0, "middle": n // 2, "end": n}[pos]
                out_dir = os.path.join(ROOT, "transforms", "a3", frac, pos, b["file_id"])
                os.makedirs(out_dir, exist_ok=True)
                path = os.path.join(out_dir, "splice.flac")
                rows.append({"target": b["file_id"], "source": spoof[bi % len(spoof)]["file_id"],
                             "frac": frac, "position": pos, "insert_idx": idx,
                             "insert_len": L, "target_len": n, "out_len": n + L,
                             "path": path})
                if os.path.exists(path) and os.path.getsize(path) > 0:
                    continue
                spliced = np.concatenate([x[:idx], s[:L], x[idx:]])
                sf.write(path, spliced, FS, subtype="PCM_16")
        with open(SPLICE_MANIFEST, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)
    else:
        with open(SPLICE_MANIFEST) as f:
            rows = list(csv.DictReader(f))
    return rows

def main():
    with open(MANIFEST) as f:
        rows = list(csv.DictReader(f))
    bona = [r for r in rows if r["label"] == "bonafide"]
    spoof = [r for r in rows if r["label"] == "spoof"]
    if len(bona) != 50 or len(spoof) != 50:
        print(f"STOP: need 50/50, got {len(bona)}/{len(spoof)}", file=sys.stderr)
        return 1
    if not os.path.exists(PARAMS):
        log = build_a2(bona + spoof)
        with open(PARAMS, "w") as f:
            json.dump({"formulas": "see eval/transform_content.py docstring",
                       "per_file": log}, f, indent=2)
        print(f"wrote {PARAMS}")
    else:
        print("reusing existing transform_params.json (resume)")
    splices = build_a3(bona, spoof)
    n_done = sum(1 for s in splices
                 if os.path.exists(s["path"]) and os.path.getsize(s["path"]) > 0)
    print(f"A3: {n_done}/{len(splices)} splices present")
    return 0

if __name__ == "__main__":
    sys.exit(main())
