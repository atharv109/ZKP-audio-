#!/usr/bin/env python
"""eval/u1/segment2.py -- v2 beep-guided segmentation of the C1 capture.

Why v2: segment.py (v1) failed on the capture (1/100 aligned) because sine-
template correlation is killed by ~1 Hz playback-vs-capture clock skew and
speech produces spurious 1 kHz peaks; v1 also matched peaks greedily over the
whole capture, so one missed beep shifted everything.

v2 method (frequency-robust):
  a. chunked stateful SOS band-pass 940-1060 Hz; envelope = 10 ms max hops.
  b. anchors: first/last burst >= 1.5 s = start/end markers -> playback-to-
     capture clock rate b fitted from the marker span.
  c. per clip, expected beep end (track_pos + 1.2 s) mapped into capture time;
     nearest burst within +-1.0 s matched; missing/unmatched = flag.
  d. cuts in 16 kHz; per-clip FFT xcorr vs original flags > 50 ms.
"""
import json, os, sys
import numpy as np
import soundfile as sf
from scipy.signal import butter, sosfilt, sosfilt_zi, resample_poly, fftconvolve

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
U1 = os.path.join(REPO, "eval", "u1")
FS_T = 16000
SR_C = 44100
HOP = 441                       # 10 ms hops at capture rate
MARKER_MIN_S = 1.5
WIN_S = 1.0
FLAG_MS = 50.0
PAD_S = 10.0                    # search window half-width around prediction


def bandpass_env(cap_path):
    """Whole-capture 16 kHz mono (float32) for content xcorr."""
    y, sr = sf.read(cap_path, dtype="float64")
    if y.ndim > 1:
        y = y.mean(axis=1)
    y = resample_poly(y, FS_T, sr).astype(np.float32)
    return y


def tone_env(cap_path):
    sos = butter(4, [980.0, 1020.0], btype="band", fs=SR_C, output="sos")
    zi = sosfilt_zi(sos) * 0.0
    yy, sr = sf.read(cap_path, dtype="float64")
    if yy.ndim > 1:
        yy = yy.mean(axis=1)
    out = []
    h = SR_C // 100
    for i in range(0, len(yy) - 2 * h, h):
        z, zi = sosfilt(sos, yy[i:i + 2 * h], zi=zi)
        out.append(np.abs(z).max())
    return np.asarray(out)          # 20 ms hops at 100 Hz


def main(cap_path):
    man = json.load(open(os.path.join(U1, "track_manifest.json")))
    clips = man["clips"]
    cap = bandpass_env(cap_path)          # 16 kHz float32, capture timeline
    beeps = tone_env(cap_path)            # 100 Hz, capture timeline
    te_max = beeps.max()

    # seed: best t0 for clip 0 over a coarse prior from beep analysis
    seeds = []
    for t0 in np.arange(0.0, 30.0, 0.1):
        i = int((t0 + 2.5) * FS_T)
        w = cap[i:i + 2 * FS_T]
        if len(w) < 2 * FS_T:
            continue
        src, _ = sf.read(clips[0]["src"], dtype="float64")
        x = fftconvolve(w, src[: 2 * FS_T][::-1], mode="valid")
        seeds.append((float(x.max()), t0))
    seeds.sort(key=lambda t: -t[0])
    print(f"clip-0 seed search: best t0 {seeds[0][1]:.1f} (score {seeds[0][0]:.1f}),"
          f" runner-up {seeds[1][1]:.1f} ({seeds[1][0]:.1f})")

    pos = {}           # order -> capture-16k position of clip start
    qual = {}
    flags = []
    prev_found = None
    for idx, c in enumerate(clips):
        src, fsx = sf.read(c["src"], dtype="float64")
        if fsx != FS_T:
            src = resample_poly(src, FS_T, int(fsx))
        tmpl_len = min(len(src), 2 * FS_T)
        tmpl = src[:tmpl_len]
        if prev_found is None:
            pred = seeds[0][1] + clips[0]["track_pos_s"] + 1.2
        else:
            pred = prev_found + (c["track_pos_s"] - clips[idx - 1]["track_pos_s"])
        lo = max(0, int((pred - PAD_S) * FS_T))
        hi = min(len(cap), int((pred + PAD_S + tmpl_len / FS_T + 1) * FS_T))
        w = cap[lo:hi]
        x = fftconvolve(w, tmpl[::-1], mode="valid")
        pk = int(np.argmax(x))
        found = (lo + pk) / FS_T
        # quality: xcorr peak / sqrt(energy of template * local cap energy)
        lnorm = np.sqrt(float(np.sum(cap[lo + pk: lo + pk + tmpl_len].astype(np.float64) ** 2)) + 1e-12)
        snorm = np.sqrt(float(np.sum(tmpl.astype(np.float64) ** 2)) + 1e-12)
        q = x[pk] / (lnorm * snorm)
        second = None
        if 0.5 <= q:
            # second pass: cut at found, verify lag vs full original
            n = c["len_samples"]
            cut = cap[int(round(found * FS_T)): int(round(found * FS_T)) + n]
            if len(cut) < n:
                cut = np.concatenate([cut, np.zeros(n - len(cut))]).astype(np.float32)
            x2 = fftconvolve(src, cut[::-1], mode="valid")
            lag_ms = (len(src) - int(np.argmax(x2)) - 1) / FS_T * 1000.0
            lnorm2 = np.sqrt(float(np.sum(src ** 2)) + 1e-12)
            q2 = x2.max() / (lnorm2 * snorm_full(src))
            second = (round(float(lag_ms), 1), round(float(q2), 3))
        pos[idx] = round(found, 4)
        qual[idx] = round(float(q), 3)
        if q < 0.5:
            flags.append(f"clip {c['order']} ({c['file_id']}) weak match q={q:.2f} at {found:.2f}s")
        elif second and abs(second[0]) > FLAG_MS:
            flags.append(f"clip {c['order']} ({c['file_id']}) vs-original lag {second[0]:.0f} ms > 50 ms")
        c["cap_pos_s"] = pos[idx]
        c["beep_offset_vs_manifest_ms"] = round((found - (seeds[0][1] + c["track_pos_s"]) if prev_found is None else found - pred) * 1000, 1)
        c["match_q"] = qual[idx]
        c["align_err_ms"] = second[0] if second else None
        c["align_q"] = second[1] if second else None
        prev_found = found
        if idx % 20 == 0:
            print(f"  clip {idx:3d}: cap {found:8.2f}s q={q:.2f}"
                  + (f" lag={second[0]:+.1f}ms q2={second[1]:.2f}" if second else ""))

    # write cuts + final alignment
    outdir = os.path.join(U1, "C1_segments")
    os.makedirs(outdir, exist_ok=True)
    lags = [c["align_err_ms"] for c in clips if c["align_err_ms"] is not None]
    fin = sum(1 for l in lags if abs(l) <= FLAG_MS)
    man["C1"] = {"capture": cap_path, "capture_dur_s": len(cap) / FS_T,
                 "segmenter": "segment2.py v2c (content-xcorr walk-forward)",
                 "aligned_vs_original": f"{fin}/{len(lags)}",
                 "flags": flags,
                 "beep_offsets_ms": [c["beep_offset_vs_manifest_ms"] for c in clips]}
    json.dump(man, open(os.path.join(U1, "track_manifest.json"), "w"), indent=2)
    print(f"aligned vs original <=50ms: {fin}/{len(lags)}")
    for f_ in flags[:20]:
        print("  FLAG:", f_)
    return 0 if fin >= 90 else 2


def snorm_full(src):
    return np.sqrt(float(np.sum((src if isinstance(src, np.ndarray) else src) ** 2)) + 1e-12)


if __name__ == "__main__":
    cap = sys.argv[1] if len(sys.argv) > 1 else os.path.join(U1, "raw", "c1_capture.wav")
    sys.exit(main(cap))
