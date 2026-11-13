#!/usr/bin/env python
"""eval/transform_u2.py -- A2 (7 x 200) + A3 (9 x 200) transforms for the u2 sample.
Same exact formulas as eval/transform_content.py (parameterized paths); idempotent."""
import csv, json, os, sys
import numpy as np
import soundfile as sf
from scipy.signal import resample_poly, fftconvolve

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAN = os.path.join(REPO, "eval", "sample_manifest_u2.csv")
ROOT = os.path.join(REPO, "outputs", "v3", "eval_content", "u2")
FS = 16000
CONDS = ["mp3_64k", "mp3_32k", "opus_32k", "resample_8k_rt",
         "noise_20db", "noise_10db", "reverb_rt60_0.3s"]
FRACS = ["0.1", "0.25", "0.5"]
POSITIONS = ["start", "middle", "end"]

def codec(src, tmp, out, kbps, codec):
    import subprocess
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", src,
                    "-codec:a", codec, "-b:a", f"{kbps}k", "-ac", "1", "-ar", "16000", tmp],
                   check=True, capture_output=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", tmp,
                    "-ac", "1", "-ar", "16000", "-sample_fmt", "s16", out],
                   check=True, capture_output=True)
    os.remove(tmp)

def main():
    with open(MAN) as f: rows = list(csv.DictReader(f))
    bona = [r for r in rows if r["label"] == "bonafide"]
    spoof = [r for r in rows if r["label"] == "spoof"]
    n_done, n_sp = 0, 0
    for i, r in enumerate(bona + spoof):
        x, fsx = sf.read(r["flac_path"], dtype="float64")
        if fsx != FS or x.ndim != 1:
            print(f"STOP {r['file_id']}"); return 1
        rng = np.random.default_rng(44000 + i)
        for c in CONDS:
            d = os.path.join(ROOT, "a2", c, r["file_id"]); os.makedirs(d, exist_ok=True)
            out = os.path.join(d, "transform.flac")
            if os.path.exists(out) and os.path.getsize(out) > 0: n_done += 1; continue
            if c in ("mp3_64k", "mp3_32k"):
                codec(r["flac_path"], out + ".tmp.mp3", out, c.split("_")[1].rstrip("k"), "libmp3lame")
            elif c == "opus_32k":
                codec(r["flac_path"], out + ".tmp.ogg", out, 32, "libopus")
            elif c == "resample_8k_rt":
                y = resample_poly(resample_poly(x, 1, 2), 2, 1)
                y = y[:len(x)] if len(y) >= len(x) else np.pad(y, (0, len(x) - len(y)))
                sf.write(out, y, FS, subtype="PCM_16")
            elif c.startswith("noise_"):
                snr = 20 if "20db" in c else 10
                scale = float(np.sqrt(np.mean(x ** 2) / 10 ** (snr / 10)))
                y = x + rng.normal(0, 1, x.shape) * scale
                sf.write(out, y, FS, subtype="PCM_16")
            else:
                nt = int(np.ceil(0.3 * FS))
                env = 10.0 ** (-3.0 * (np.arange(1, nt + 1) / FS) / 0.3)
                tail = rng.normal(0, 1, nt) * env
                tail = tail / np.max(np.abs(tail)) * 0.5
                y = fftconvolve(x, np.concatenate([[1.0], tail]))[: len(x)]
                m = np.max(np.abs(y))
                if m > 1.0: y = y / m * 0.99
                sf.write(out, y, FS, subtype="PCM_16")
            n_done += 1
            if n_done % 200 == 0: print(f"  a2 done={n_done}/2800", flush=True)
    for bi, b in enumerate(bona):
        x, _ = sf.read(b["flac_path"], dtype="float64")
        s, _ = sf.read(spoof[bi % len(spoof)]["flac_path"], dtype="float64")
        n = len(x)
        for frac in FRACS:
            L = int(round(float(frac) * n))
            for pos in POSITIONS:
                idx = {"start": 0, "middle": n // 2, "end": n}[pos]
                d = os.path.join(ROOT, "a3", frac, pos, b["file_id"]); os.makedirs(d, exist_ok=True)
                p = os.path.join(d, "splice.flac")
                n_sp += 1
                if os.path.exists(p) and os.path.getsize(p) > 0: continue
                sf.write(p, np.concatenate([x[:idx], s[:L], x[idx:]]), FS, subtype="PCM_16")
        if (bi + 1) % 50 == 0: print(f"  a3 targets={bi + 1}/200", flush=True)
    print(f"transforms complete: a2_present={n_done}/2800 splices={n_sp}/1800")
    return 0

if __name__ == "__main__":
    sys.exit(main())
