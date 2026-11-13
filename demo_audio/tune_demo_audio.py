#!/usr/bin/env python3
"""tune_demo_audio.py -- select the demo clip generator settings.

The demo "genuine-side" clip must score BONAFIDE and the "spoof-side" clip
must score SPOOF at the issuer threshold 1.7635419737 under the real AASIST-L
checkpoint (scripts/issue_capture_record_v4.js hard-codes that threshold; the
tests pin it, so the CLIPS -- not the threshold -- are what we tune).

This script loads the real model ONCE and grid-searches a family of fully
synthetic generators (tonal/formant/AM/noise mixes, all numpy-synthesized,
no recordings) over the bonafide logit, then prints per-preset scores.
Results documented in README.md "Demo assets".

Usage:
    python demo_audio/tune_demo_audio.py            # score all presets
    python demo_audio/tune_demo_audio.py --write    # also write chosen clips
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "audio_benchmark"))

import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402

import models  # audio_benchmark/models.py  # noqa: E402

SR = 16000
NB_SAMP = 64600          # AASIST-L fixed input length (~4.04 s)
THRESHOLD = 1.7635419737  # issuer threshold (pinned by the test suite)


def build():
    root = ROOT
    weights = os.getenv("ZKP_DEMO_WEIGHTS") or str(root / "models" / "AASIST-L.pth")
    repo = os.getenv("ZKP_DEMO_AASIST_REPO") or str(root / "models" / "aasist")
    cfg = os.getenv("ZKP_DEMO_CONFIG") or str(root / "models" / "aasist" / "config" / "AASIST-L.conf")
    return models.build_model("aasist", weights=weights, device="cpu",
                              aasist_repo=repo, config_path=cfg)


def score_clip(model, wav_path: Path) -> float:
    tmp = Path(os.environ.get("TMPDIR", os.environ.get("TEMP", "/tmp"))) / "tune_score.wav"
    sf.write(tmp, wav_path, SR, subtype="PCM_16")
    return model.score(str(tmp))


# ------------------------------------------------------------------ generators
def gen_tonal(seed, sec=5.0, f0=120.0, amp=0.6, harm=(0.3, 0.15), wob=2.0,
              am=4.0, am_amt=0.5, noise=0.03, formants=None):
    rng = np.random.RandomState(seed)
    n = int(SR * sec)
    t = np.arange(n) / SR
    f = f0 + f0 * 0.02 * np.sin(2 * np.pi * wob * t)
    sig = amp * np.sin(2 * np.pi * f * t)
    for i, h in enumerate(harm, start=2):
        sig += amp * h * np.sin(2 * np.pi * (i * f) * t)
    sig *= 1.0 - am_amt + am_amt * np.sin(2 * np.pi * am * t)
    sig += noise * rng.randn(n)
    if formants:
        # cheap formant resonators (2-pole IIR) over the harmonic source
        out = np.zeros(n)
        for fc, bw, g in formants:
            r = np.exp(-np.pi * bw / SR)
            theta = 2 * np.pi * fc / SR
            a1, a2 = -2 * r * np.cos(theta), r * r
            x = sig * g
            y = np.zeros(n)
            for k in range(2, n):
                y[k] = x[k] - a1 * y[k - 1] - a2 * y[k - 2]
            out += y
        sig = out
    return sig


def gen_noise_buzz(seed, sec=5.0, noise=0.5, buzz=0.2, f0=110.0):
    rng = np.random.RandomState(seed)
    n = int(SR * sec)
    t = np.arange(n) / SR
    sig = 0.25 * np.sin(2 * np.pi * f0 * t)
    sig += noise * rng.randn(n)
    sig += buzz * np.sign(np.sin(2 * np.pi * f0 * t))
    return sig


def presets():
    prs = {"current_bon": ("bonafide_like", 1234), "current_spf": ("noise_buzz", 1237)}
    # genuine-side family: richer tonal + formant structure
    for f0 in (100.0, 140.0, 180.0):
        for amp in (0.8, 0.95):
            for fset, fname in [  # static formant sets
                (((700, 130, 1.0), (1220, 90, 0.7), (2600, 120, 0.3)), "a"),
                (((350, 90, 1.0), (2000, 120, 0.5)), "u"),
            ]:
                prs[f"tonal_f{int(f0)}_a{int(amp*100)}_{fname}"] = (
                    "tonal_formant", f0, amp, fset)
    # noise levels on the spoof side, incl. a very flat option
    for s in (1234, 1236, 1237, 1239):
        prs[f"noise_buzz_{s}"] = ("noise_buzz", s)
    prs["noise_only"] = ("noise_only", 1240)
    return prs


def synth(name, spec):
    kind, *args = spec
    if kind == "bonafide_like":
        rng = np.random.RandomState(args[0])
        n = int(SR * 5.0)
        t = np.arange(n) / SR
        f0 = 120.0 + 20.0 * np.sin(2 * np.pi * 2.0 * t)
        sig = (0.6 * np.sin(2 * np.pi * f0 * t) + 0.3 * np.sin(2 * np.pi * 2 * f0 * t)
               + 0.15 * np.sin(2 * np.pi * 3 * f0 * t))
        sig *= 0.5 + 0.5 * np.sin(2 * np.pi * 4.0 * t)
        sig += 0.03 * rng.randn(n)
        return sig
    if kind == "noise_buzz":
        return gen_noise_buzz(args[0])
    if kind == "noise_only":
        rng = np.random.RandomState(args[0])
        return 0.6 * rng.randn(int(SR * 5.0))
    if kind == "tonal_formant":
        f0, amp, fset = args
        return gen_tonal(1234, f0=f0, amp=amp, harm=(0.4, 0.25, 0.12),
                         formants=fset, noise=0.02)
    raise ValueError(kind)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    model = build()
    rows = []
    for name, spec in presets().items():
        sig = synth(name, spec)
        tmp = Path(os.environ.get("TEMP", "/tmp")) / f"tune_{name}.wav"
        sf.write(tmp, sig.astype(np.float32), SR, subtype="PCM_16")
        s = model.score(str(tmp))
        rows.append((s, name))
        tmp.unlink(missing_ok=True)
    for s, name in sorted(rows, reverse=True):
        print(f"{s:+9.4f}  {'BONAFIDE' if s >= THRESHOLD else 'spoof    '}  {name}")
    if args.write:
        best_bon = max(rows)[-1]
        best_spf = min(rows)[-1]
        print(f"\nbest bonafide-side preset: {best_bon}; best spoof-side: {best_spf}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
