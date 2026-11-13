#!/usr/bin/env python
"""eval/u1/segment_diag.py -- capture diagnostics before re-segmentation.

For each capture WAV: find the 2 s 1 kHz start marker (band-passed
cross-correlation), then scan for ALL 1 kHz beep-like peaks and report:
  - marker hit strength / position
  - number of detected beep candidates vs the 100 expected sync beeps
  - whether the candidate spacing histogram matches the manifest's expected
    spacings (6.4 s inter-beep within runs, longer at boundary gaps)
This determines which take to segment and whether missed beeps are the failure
mode (vs. no playback signal at all in the capture).
"""
import json, os, sys
import numpy as np
import soundfile as sf
from scipy.signal import resample_poly, fftconvolve

U1 = os.path.dirname(os.path.abspath(__file__))
FS_T = 16000
CAPS = [(name, os.path.join(U1, "raw", name))
        for name in ("c1_capture.wav", "c1_capture2.wav")]


def bandpass_1k(y, fs, lo=880.0, hi=1120.0):
    """FFT brick-wall band-pass around 1 kHz (cheap, sufficient for beeps)."""
    Y = np.fft.rfft(y)
    f = np.fft.rfftfreq(len(y), 1.0 / fs)
    m = (f >= lo) & (f <= hi)
    Y[~m] = 0
    return np.fft.irfft(Y, len(y))


def main():
    man = json.load(open(os.path.join(U1, "track_manifest.json")))
    fs_t = man["fs"]
    beep = np.sin(2 * np.pi * 1000 * np.arange(int(0.2 * fs_t)) / fs_t)
    marker = np.sin(2 * np.pi * 1000 * np.arange(2 * fs_t) / fs_t)
    # expected beep-END positions in track time: clip start - 0.5 s
    exp_ends = [c["track_pos_s"] - 0.5 for c in man["clips"]]

    for name, path in CAPS:
        y, sr = sf.read(path, dtype="float64")
        if y.ndim > 1:
            y = y.mean(axis=1)
        y = y / (np.abs(y).max() + 1e-12)
        yb = bandpass_1k(y, sr)
        yb = resample_poly(yb, fs_t, sr)
        # --- start marker ---
        cm = fftconvolve(yb, marker[::-1], mode="valid")
        i0 = int(np.argmax(cm))
        print(f"== {name} ==", f"dur={len(y)/sr:.2f}s sr={sr}")
        marker_ratio = cm[i0] / (np.linalg.norm(marker) ** 2)
        print(f"  start marker: t={i0/fs_t:.2f}s  match ratio={marker_ratio:.4f}"
              f"  (>=0.5 means a clean 2 s sine is present there)")
        # --- beep candidates: local maxima above an adaptive threshold ---
        cb = fftconvolve(yb, beep[::-1], mode="valid")
        thr = 0.25 * np.sort(cb)[-50:].mean() if len(cb) > 50 else 0.0
        cand = []
        for i in range(1, len(cb) - 1):
            if cb[i] >= cb[i - 1] and cb[i] >= cb[i + 1] and cb[i] > thr:
                t = i / fs_t
                if not cand or t - cand[-1][0] > 0.5:
                    cand.append((t, cb[i]))
                elif cb[i] > cand[-1][1]:
                    cand[-1] = (t, cb[i])
        print(f"  beep-like candidates: {len(cand)} (expected 100 sync beeps)")
        # absolute scale sanity: beep self-convolution value on clean sine
        self_v = float(np.linalg.norm(beep) ** 2)
        strong = sum(1 for _, s in cand if s > 0.5 * self_v)
        print(f"  candidates with corr > 0.5 of a clean-beep maximum: {strong}")
        # nearest-expected-end distance per candidate (captures take quality)
        exp_arr = np.array(exp_ends) + i0 / fs_t
        if cand:
            d = np.sort([min(abs(t - e) for e in exp_arr)
                         + i0 / fs_t * 0 for (t, _) in cand])
            print(f"  candidate→nearest-expected |off|: med={np.median(d):.3f}s"
                  f"  <=50ms: {(d<=0.05).sum()}  <=200ms: {(d<=0.2).sum()}"
                  f"  <=6.5s: {(d<=6.5).sum()}")
        else:
            print("  candidate→nearest-expected: none")
    return 0


if __name__ == "__main__":
    sys.exit(main())
