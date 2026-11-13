#!/usr/bin/env python
"""eval/u1/probe_pos.py -- global envelope search: where does each clip's
content actually live in the capture, vs the affine (beep-fitted) schedule?
Uses 300-800 Hz band, envelope xcorr over the WHOLE capture, correctly
normalized. Prints top-3 candidate positions per probe clip."""
import json, os, sys
import numpy as np
import soundfile as sf
from scipy.signal import resample_poly, fftconvolve, butter, sosfilt, sosfilt_zi

U1 = os.path.dirname(os.path.abspath(__file__))
FS = 16000
T0, B = 8.5311, 1.000002


def env(yin, w=800):
    p = np.square(yin)
    cs = np.concatenate([[0.0], np.cumsum(p)])
    out = np.sqrt((cs[w:] - cs[:-w]) / w)
    out = np.concatenate([np.full(w // 2, out[0]), out, np.full(len(yin) - len(out) - w // 2, out[-1])])
    return out[: len(yin)]


def main():
    man = json.load(open(os.path.join(U1, "track_manifest.json")))
    y, sr = sf.read(os.path.join(U1, "raw", "c1_capture.wav"), dtype="float64")
    if y.ndim > 1:
        y = y.mean(axis=1)
    cap16 = np.asarray(resample_poly(y, FS, sr), dtype=np.float64)
    sos = butter(4, [300.0, 800.0], btype="band", fs=FS, output="sos")
    zi = sosfilt_zi(sos) * 0.0
    capb, _ = sosfilt(sos, cap16, zi=zi)
    cape = env(capb)          # envelope of the capture (300-800 Hz band)
    for idx in [int(a) for a in sys.argv[1:]] or [0, 12, 20, 60, 80, 99]:
        c = man["clips"][idx]
        src, fsx = sf.read(c["src"], dtype="float64")
        s16 = resample_poly(src, FS, int(fsx))
        sz, _ = sosfilt(sos, s16, zi=sosfilt_zi(sos) * 0.0)
        n = c["len_samples"]
        ee = env(sz)[:n]
        xn = np.sqrt(float(np.sum(ee ** 2)))
        x = fftconvolve(cape, ee[::-1], mode="valid")
        cs2 = np.concatenate([[0.0], np.cumsum(np.square(cape))])
        L = len(x)
        ar = np.arange(L)
        wn = np.sqrt(np.maximum(cs2[ar + n] - cs2[ar], 0.0))
        q = np.abs(x) / np.maximum(wn * xn, 1e-12)
        q[wn < 1.6] = 0
        top = sorted(range(len(q)), key=lambda i: -q[i])[:3]
        sched = T0 + B * (c["track_pos_s"] + 1.7)
        print(f"clip {idx:2d} ({c['file_id']}): sched={sched:.2f}s "
              f"top: {[(round(i/FS,2), round(float(q[i]),3)) for i in top]}")
        del x, cs2, wn, q
    return 0


if __name__ == "__main__":
    sys.exit(main())
