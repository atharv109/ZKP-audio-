#!/usr/bin/env python
"""eval/u1/C1b/segment3b.py -- C1b variant of segment3.py.

C1b captures (48 kHz, volume 70-80%, enhancements off) do NOT preserve the
200 ms sync beeps: the mic array's adaptive noise suppression eats short
tones after loud speech (measured: 1-2 of 100 beeps detectable per take).
The C1 beep-anchor fit therefore cannot run. Everything downstream of the
anchor fit is IDENTICAL to segment3.py (schedule cut at track_pos+1.7,
+-150 ms margin, normalized content xcorr vs the original, 2x-far-baseline
verification rule) -- only the anchor stage is swapped:

  anchor = envelope-affine alignment: correlate the capture's broad-band
  envelope (resampled to 16 k) with the playback track's envelope; chain
  per-clip envelope matches; robust affine lstsq (b, t0) over all matched
  clip onsets, MAD-trimmed.

Usage: python segment3b.py <capture.wav> <segdir> <mkey>
"""
import json, os, sys
import numpy as np
import soundfile as sf
from scipy.signal import fftconvolve, resample_poly

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import segment3 as s3

U1 = s3.U1
FS_T = s3.FS_T
ENV_SR = 100          # envelope rate (Hz)
PAD = 1.5             # per-clip envelope search half-window (s)


def envelope16(y):
    e = np.abs(y)
    k = FS_T // ENV_SR
    n = len(e) // k
    return e[:n * k].reshape(n, k).mean(axis=1)


def match_clip_env(capenv, tmpl, pred):
    """Envelope-level match of one clip near pred (s). Returns (found_s, q)."""
    tn = np.sqrt(float(np.sum(tmpl ** 2)))
    lo = max(0, int((pred - PAD) * ENV_SR))
    hi = min(len(capenv), int((pred + PAD) * ENV_SR) + len(tmpl))
    w = capenv[lo:hi]
    if len(w) < len(tmpl):
        return None, 0.0
    x = fftconvolve(w, tmpl[::-1], mode="valid")
    e2 = fftconvolve(w ** 2, np.ones(len(tmpl)), mode="valid")
    q = np.abs(x) / np.maximum(np.sqrt(e2) * tn, 1e-12)
    pk = int(np.argmax(q))
    return (lo + pk) / ENV_SR, float(q[pk])


def main(cap_path, segdir="C1b_segments", mkey="C1b"):
    man = json.load(open(os.path.join(U1, "track_manifest.json")))
    clips = man["clips"]
    y, sr = sf.read(cap_path, dtype="float64")
    if y.ndim > 1:
        y = y.mean(axis=1)
    cap16 = resample_poly(y, FS_T, int(sr)).astype(np.float64)
    capenv = envelope16(cap16)

    # ---- stage 1: global envelope xcorr -> coarse t0 (b assumed ~1.0)
    track, _ = sf.read(os.path.join(U1, "playback_16k.wav"), dtype="float64")
    te = envelope16(track)
    xc = fftconvolve(capenv - capenv.mean(), (te - te.mean())[::-1], mode="full")
    lag = int(np.argmax(xc))
    t0 = float(len(te) - 1 - lag) / ENV_SR
    print(f"global envelope xcorr: coarse t0 = {t0:.2f}s", flush=True)

    # ---- stage 2: chained per-clip envelope matches -> robust affine (t0, b)
    src_cache = {}
    def clipenv(c):
        if c["order"] not in src_cache:
            src, fsx = sf.read(c["src"], dtype="float64")
            if fsx != FS_T:
                src = resample_poly(src, FS_T, int(fsx))
            tm = envelope16(src[:2 * FS_T])
            src_cache[c["order"]] = (src, tm)
        return src_cache[c["order"]]
    pts = []
    prev_found = None
    for idx, c in enumerate(clips):
        if prev_found is None:
            pred = t0 + c["track_pos_s"] + 1.7
        else:
            pred = prev_found + c["track_pos_s"] - clips[idx - 1]["track_pos_s"]
        found, q = match_clip_env(capenv, clipenv(c)[1], pred)
        if found is None or q < 0.10:
            continue
        pts.append((c["track_pos_s"] + 1.7, found))
        prev_found = found
    if len(pts) < 30:
        print(f"STOP: too few envelope matches ({len(pts)}) -- capture unusable")
        return 2
    T = np.array([p[0] for p in pts])
    O = np.array([p[1] for p in pts])
    for _ in range(3):
        A = np.vstack([np.ones(len(T)), T]).T
        sol = np.linalg.lstsq(A, O, rcond=None)[0]
        t0, b = float(sol[0]), float(sol[1])
        resid = O - (t0 + b * T)
        mad = float(np.median(np.abs(resid - np.median(resid))))
        keep = np.abs(resid) < max(4.0 * 1.4826 * mad, 0.03)
        if keep.all():
            break
        T, O = T[keep], O[keep]
    resid = (O - (t0 + b * T)) * 1000.0
    print(f"envelope-affine anchor: t0={t0:.4f}s b={b:.6f} matched {len(T)}/{len(clips)}"
          f" resid std {np.std(resid):.1f} ms range {resid.min():+.1f}..{resid.max():+.1f}",
          flush=True)

    # ---- stage 3: segment3's cut + verify loop, IDENTICAL
    outdir = os.path.join(U1, segdir)
    os.makedirs(outdir, exist_ok=True)
    rows = []
    flags = []
    ver_n = misal_n = unver_n = 0
    for idx, c in enumerate(clips):
        src, tm = clipenv(c)
        tmpl = src[:min(len(src), 2 * FS_T)]
        tn = np.sqrt(float(np.sum(tmpl ** 2)))
        pred = t0 + b * (c["track_pos_s"] + 1.7)
        lo = max(0, int((pred - s3.WIN_PAD) * FS_T))
        hi = min(len(cap16), int((pred + s3.WIN_PAD) * FS_T) + len(tmpl))
        w = cap16[lo:hi]
        x = fftconvolve(w, tmpl[::-1], mode="valid")
        e2 = fftconvolve(w ** 2, np.ones(len(tmpl)), mode="valid")
        q = np.abs(x) / np.maximum(np.sqrt(e2) * tn, 1e-12)
        pk = int(np.argmax(q))
        found = (lo + pk) / FS_T
        off_s = found - pred
        n = c["len_samples"]
        ist = int(round((t0 + b * (c["track_pos_s"] + 1.7)) * FS_T))
        m = int(0.15 * FS_T)
        cut = cap16[ist - m: ist + n + m]
        if len(cut) < n + 2 * m:
            flags.append(f"clip {c['order']} ({c['file_id']}) truncated at capture end")
            cut = np.concatenate([cut, np.zeros(n + 2 * m - len(cut))])
        x2 = fftconvolve(src, cut[::-1], mode="valid")
        if len(x2):
            qs_ = np.abs(x2)
            i0, i1 = max(0, m - 800), min(len(qs_), m + 800)
            k_q = int(np.argmax(qs_[i0:i1])) + i0
            lag_ms = (k_q - m) / FS_T * 1000.0
            sn = np.sqrt(float(np.sum(src ** 2)))
            wnorm = np.sqrt(float(np.sum(cut[k_q:k_q + n] ** 2)))
            q2 = float(qs_[k_q]) / max(wnorm * sn, 1e-12)
            far_lo = qs_[: max(1, m - 1600)]
            far_hi = qs_[m + 1600:]
            far_all = np.concatenate([far_lo, far_hi]) if far_hi.size else far_lo
            q_far = float(far_all.max()) if far_all.size else 0.0
            wnorm_f = np.sqrt(float(np.sum(cut ** 2)))
            q_far_n = q_far / max(wnorm_f * sn, 1e-12)
        else:
            lag_ms, q2, q_far_n = 0.0, 0.0, 0.0
        verified = (q2 >= max(2.0 * q_far_n, 0.010))
        ver_n += 1 if verified else 0
        if verified and abs(lag_ms) <= s3.FLAG_MS:
            pass
        rows.append((c["order"], c["file_id"], round(ist / FS_T, 2), round(q2, 3),
                     round(float(lag_ms), 1), round(q_far_n, 4), int(verified)))
        if q[pk] < s3.Q_MIN:
            flags.append(f"clip {c['order']} ({c['file_id']}) weak match q={q[pk]:.2f}")
        if verified and abs(lag_ms) > s3.FLAG_MS:
            misal_n += 1
            flags.append(f"clip {c['order']} ({c['file_id']}) verified lag {lag_ms:.0f} ms > 50 ms")
        if not verified:
            unver_n += 1
            flags.append(f"clip {c['order']} ({c['file_id']}) lag-unverifiable "
                         f"(q2={q2:.3f} far={q_far_n:.4f}); schedule cut")
        seg = cut[k_q:k_q + n] if verified else cut[m:m + n]
        if len(seg) < n:
            seg = np.concatenate([seg, np.zeros(n - len(seg))])
        sf.write(os.path.join(outdir, f"{c['order']:03d}_{c['kind']}_{c['file_id']}.wav"),
                 seg.astype(np.float32), FS_T, subtype="PCM_16")
        if idx % 20 == 0:
            print(f"  clip {idx:3d}: cap={ist/FS_T:8.2f}s q={q[pk]:.2f} "
                  f"lag={lag_ms:+.1f}ms q2={q2:.3f} verified={verified}", flush=True)
    man = json.load(open(os.path.join(U1, "track_manifest.json")))
    man[mkey] = {
        "capture": os.path.basename(cap_path),
        "segmenter": "segment3b.py (envelope-affine anchor + segment3 cut/verify)",
        "anchor": {"t0_s": round(t0, 4), "b": round(b, 6),
                   "envelope_matches": int(len(T)),
                   "resid_std_ms": round(float(np.std(resid)), 1),
                   "resid_ms": [round(float(resid.min()), 1), round(float(resid.max()), 1)]},
        "counts": {"content_verified": ver_n,
                   "schedule_cut_unverified": unver_n,
                   "verified_but_lag>50ms": misal_n,
                   "content_aligned<=50ms_or_unverifiable": ver_n - misal_n + unver_n},
        "clip_table": rows,
        "flags": flags,
        "note": "C1b: sync beeps suppressed by mic DSP at 70-80% volume; "
                "envelope-affine anchor substituted (segment3 cut/verify reused)"}
    json.dump(man, open(os.path.join(U1, "track_manifest.json"), "w"), indent=2)
    print(f"content-verified: {ver_n}/{len(clips)}  unverifiable(schedule-cut): {unver_n}  "
          f"verified->50ms(misaligned): {misal_n}", flush=True)
    ok = (ver_n + unver_n >= 90)
    return 0 if ok else 2


if __name__ == "__main__":
    cap = sys.argv[1] if len(sys.argv) > 1 else ""
    segdir = sys.argv[2] if len(sys.argv) > 2 else "C1b_segments"
    mkey = sys.argv[3] if len(sys.argv) > 3 else "C1b"
    sys.exit(main(cap, segdir, mkey))
