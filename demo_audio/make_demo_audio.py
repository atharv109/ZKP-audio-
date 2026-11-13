#!/usr/bin/env python3
"""make_demo_audio.py -- generate the artifact's synthetic demo WAVs.

Everything in demo_audio/ is SYNTHETIC: fixed-seed numpy signals written as
16 kHz mono PCM_16 WAV via soundfile. No recordings, no dataset audio.

Files produced (settings selected by measuring with the REAL AASIST-L
checkpoint via demo_audio/tune_demo_audio.py, see the measured scores in
README.md "Demo assets"):

  bon_00.wav     byte-exact reproduction of the tiny synthetic bonafide clip
                 the v3 verifier tests bind their shipped proof to
                 (audio_benchmark/make_synthetic_data.py recipe, seed 0,
                 2.0 s). Byte-exactness matters: outputs/v3/proof_v3.json is
                 bound to this file's SHA-256 limbs. Pin:
                 d77437d81d0608a3e459c2b9cd10fa969bb8ee4dc724bb7e101ec0521e7ab9fd

  demo_la_e_1194478.wav   "genuine-side" demo clip (5.0 s, seed 1234):
                 harmonic tone stack (f0 = 180 Hz + 2nd/3rd/4th harmonics at
                 amplitudes 0.95/0.4/0.25/0.12) through two cheap 2-pole
                 formant resonators (350 Hz/90 Hz bw, 2000 Hz/120 Hz bw),
                 slow 2 Hz pitch wobble (2% depth), 4 Hz AM (0.5 depth) and a
                 0.02 noise floor. Scores BONAFIDE under AASIST-L at the
                 issuer threshold 1.7635419737 (measured logit +5.4986).
                 Filename mirrors the nominal eval utterance ID the test
                 manifests use, so demo_audio/demo_assets.json reads clearly.

  demo_la_e_1000147.wav   "spoof-side" demo clip (5.0 s, seed 1234): heavy
                 broadband noise (0.5) over a weak 110 Hz sine (0.25) plus a
                 square-wave buzz (0.2) -- flat spectrum. Scores SPOOF at the
                 same threshold (measured logit -0.6585).

demo_assets.json maps whatever nominal utterance paths the test manifests use
onto these files. Nothing here asserts anything about real audio.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "demo_audio"
SR = 16000

BON_00_SHA256 = "d77437d81d0608a3e459c2b9cd10fa969bb8ee4dc724bb7e101ec0521e7ab9fd"


def write_wav(path: Path, sig: np.ndarray) -> str:
    buf = io.BytesIO()
    sf.write(buf, sig.astype(np.float32), SR, subtype="PCM_16", format="WAV")
    data = buf.getvalue()
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def bonafide_make_synthetic(seed: int, sec: float) -> np.ndarray:
    """The make_synthetic_data.py bonafide recipe (bon_00.wav must be exact)."""
    rng = np.random.RandomState(seed if seed else 0)  # module seed 0 == seed 0
    n = int(SR * sec)
    t = np.arange(n) / SR
    f0 = 120.0 + 20.0 * np.sin(2 * np.pi * 2.0 * t)
    sig = (0.6 * np.sin(2 * np.pi * f0 * t)
           + 0.3 * np.sin(2 * np.pi * 2 * f0 * t)
           + 0.15 * np.sin(2 * np.pi * 3 * f0 * t))
    sig *= 0.5 + 0.5 * np.sin(2 * np.pi * 4.0 * t)
    sig += 0.03 * rng.randn(n)
    return sig


def formant_resonate(sig: np.ndarray, formants) -> np.ndarray:
    """Cheap 2-pole IIR formant resonators (documented synthetic texture)."""
    n = sig.size
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
    return out


def genuine_side(seed: int, sec: float) -> np.ndarray:
    """Tuned tonal+formant clip, BONAFIDE-side (seed 1234 -> logit +5.4986)."""
    rng = np.random.RandomState(seed)
    n = int(SR * sec)
    t = np.arange(n) / SR
    f0 = 180.0 * (1.0 + 0.02 * np.sin(2 * np.pi * 2.0 * t))
    sig = 0.95 * np.sin(2 * np.pi * f0 * t)
    sig += 0.95 * 0.4 * np.sin(2 * np.pi * 2 * f0 * t)
    sig += 0.95 * 0.25 * np.sin(2 * np.pi * 3 * f0 * t)
    sig += 0.95 * 0.12 * np.sin(2 * np.pi * 4 * f0 * t)
    sig *= 0.5 + 0.5 * np.sin(2 * np.pi * 4.0 * t)
    sig += 0.02 * rng.randn(n)
    return formant_resonate(sig, ((350.0, 90.0, 1.0), (2000.0, 120.0, 0.5)))


def spoof_side(seed: int, sec: float) -> np.ndarray:
    """Tuned noise+buzz clip, SPOOF-side (seed 1234 -> logit -0.6585)."""
    rng = np.random.RandomState(seed)
    n = int(SR * sec)
    t = np.arange(n) / SR
    f0 = 110.0
    sig = 0.25 * np.sin(2 * np.pi * f0 * t)
    sig += 0.5 * rng.randn(n)
    sig += 0.2 * np.sign(np.sin(2 * np.pi * f0 * t))
    return sig


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    args = ap.parse_args()

    OUT.mkdir(exist_ok=True)
    written = {}
    written["bon_00.wav"] = write_wav(OUT / "bon_00.wav", bonafide_make_synthetic(0, 2.0))
    written["demo_la_e_1194478.wav"] = write_wav(
        OUT / "demo_la_e_1194478.wav", genuine_side(1234, 5.0))
    written["demo_la_e_1000147.wav"] = write_wav(
        OUT / "demo_la_e_1000147.wav", spoof_side(1234, 5.0))
    for name, sha in written.items():
        print(f"[make_demo_audio] {name}  sha256 {sha}")
    if written["bon_00.wav"] != BON_00_SHA256:
        print(f"[make_demo_audio] WARNING: bon_00.wav sha differs from pin "
              f"{BON_00_SHA256} -- the v3 proof binding needs byte-exactness",
              file=sys.stderr)
        return 1
    print("[make_demo_audio] bon_00.wav pin verified (v3 proof binding)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
