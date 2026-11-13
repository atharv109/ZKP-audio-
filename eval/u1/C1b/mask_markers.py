#!/usr/bin/env python
"""eval/u1/C1b/mask_markers.py -- zero out the two 2-s 1 kHz markers in a C1b
capture so segment3.py (built for C1's marker-free capture) can run unchanged.
Usage: python mask_markers.py <capture> <masked_out>"""
import sys
import numpy as np
import soundfile as sf

cap, out = sys.argv[1], sys.argv[2]
y, sr = sf.read(cap, dtype='float64')
if y.ndim > 1:
    y = y.mean(axis=1)
# sustained-1kHz share trace in 100ms frames
fr = int(0.1 * sr)
n = len(y) // fr
w = np.hanning(fr)
freqs = np.fft.rfftfreq(fr, 1 / sr)
m = (freqs > 900) & (freqs < 1100)
band = []
for i in range(n):
    s = y[i*fr:(i+1)*fr] - y[i*fr:(i+1)*fr].mean()
    S = np.abs(np.fft.rfft(s * w))
    band.append(S[m].sum() / (np.sqrt(np.sum(S**2)) + 1e-12))
band = np.array(band)
hi = band > 0.6
runs = []
i = 0
while i < n:
    if hi[i]:
        j = i
        while j + 1 < n and hi[j + 1]:
            j += 1
        runs.append((i * 0.1, (j + 1) * 0.1))
        i = j + 1
    else:
        i += 1
runs = [r for r in runs if r[1] - r[0] >= 1.5]
runs.sort(key=lambda r: r[1] - r[0], reverse=True)
keep = sorted(runs[:2]) if len(runs) >= 2 else []
print("marker runs (s):", keep)
assert len(keep) == 2, f"expected 2 markers, found {keep}"
ym = y.copy()
for a, b in keep:
    ym[int(max(0, (a - 0.3) * sr)):int(min(len(y), (b + 0.3) * sr))] = 0.0
sf.write(out, ym, sr, subtype='PCM_16')
print("wrote", out)
