#!/usr/bin/env python
"""eval/u1/segment.py -- beep-guided segmentation of the C1 capture.
Cross-correlates the 200 ms/1 kHz beep pattern to find each clip's beacon,
cuts the clip audio, resamples to 16 kHz mono, verifies alignment vs the
manifest (flag > 50 ms), and writes per-condition setup notes."""
import json, os, sys
import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
U1 = os.path.join(REPO, "eval", "u1")
FS_T = 16000            # template fs
BEF_MS, BEEP_MS = 1000, 200

def main(cap_path):
    man = json.load(open(os.path.join(U1, "track_manifest.json")))
    y, sr = sf.read(cap_path, dtype="float64")
    if y.ndim > 1: y = y.mean(axis=1)
    # resample capture to template fs for 1-sample cross-corr
    if sr != FS_T:
        y = resample_poly(y, FS_T, sr)
    dur = len(y) / FS_T
    beep_len = int(0.2 * FS_T)
    t = np.arange(beep_len) / FS_T
    beep = np.sin(2 * np.pi * 1000 * t)
    # cross-correlate (FFT) on the full capture
    from scipy.signal import fftconvolve
    corr = fftconvolve(y, beep[::-1], mode="valid")
    # find peaks: the strongest per 2-s window (beeps are 9 s apart)
    cand = np.argsort(corr)[::-1]
    picked = []
    for idx in cand:
        px = idx / FS_T
        if all(abs(px - p) > 2.0 for p in picked):
            picked.append(px)
        if len(picked) >= len(man["clips"]):
            break
    picked.sort()
    flags = []
    segs = []
    for i, (clip, px) in enumerate(zip(man["clips"], picked)):
        start = int((px + 0.5 - BEF_MS / 1000.0) * FS_T)  # cut 1 s BEFORE the beep end
        n = clip["len_samples"]
        seg = y[start:start + n]
        if len(seg) < n:
            flags.append(f"clip {i} truncated (capture ended)")
            seg = np.pad(seg, (0, n - len(seg)))
        length_err_ms = 0.0  # windows cut to manifest length by construction
        segs.append(seg)
        manifest_pos_err_ms = round((px - clip["track_pos_s"] - 1.2) * 1000, 1)  # beep pos vs expected
        if abs(manifest_pos_err_ms) > 50:
            flags.append(f"clip {i} ({clip['file_id']}) beep offset {manifest_pos_err_ms} ms > 50 ms")
        clip.update({"cap_beep_pos_s": round(px, 4),
                     "beep_offset_vs_manifest_ms": manifest_pos_err_ms})
    # write segmented clips
    outdir = os.path.join(U1, "C1_segments")
    os.makedirs(outdir, exist_ok=True)
    for i, (clip, seg) in enumerate(zip(man["clips"], segs)):
        sf.write(os.path.join(outdir, f"{clip['order']:03d}_{clip['kind']}_{clip['file_id']}.wav"),
                 seg, FS_T, subtype="PCM_16")
    man["C1"] = {"capture": cap_path, "capture_dur_s": round(dur, 2),
                 "flags": flags,
                 "beep_offsets_ms": [c.get("beep_offset_vs_manifest_ms") for c in man["clips"]]}
    man["C1"]["n_aligned"] = sum(1 for f in man["clips"]
                                 if abs(f.get("beep_offset_vs_manifest_ms", 9999)) <= 50)
    json.dump(man, open(os.path.join(U1, "track_manifest.json"), "w"), indent=2)
    print(f"segmented {len(segs)} clips; aligned within 50 ms: {man['C1']['n_aligned']}/{len(segs)}")
    for f in flags: print("  FLAG:", f)
    return 0 if man["C1"]["n_aligned"] >= 90 else 2

if __name__ == "__main__":
    cap = sys.argv[1] if len(sys.argv) > 1 else os.path.join(U1, "raw", "c1_capture.wav")
    sys.exit(main(cap))
