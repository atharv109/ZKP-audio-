# RESULTS_U3.md — Detector generality (U3)

Question: do the frozen-pipeline findings (front-window blind spot, reverb
inversion, splice-beyond-window misses, laundering collapse) hold when the
detector is swapped? Three detectors, same frozen files (no regeneration):

- **D1 = AASIST-L** (clovaai/aasist, frozen in-repo pipeline asset):
  `<HOME>\external\aasist\models\weights\AASIST-L.pth`,
  sha256 `51d2d9...` (pinned in eval/u3/D2_PIN.json covers AASIST.pth; AASIST-L
  weights were the pipeline's frozen D1 asset throughout U2/U1).
- **D2 = AASIST (full-width)** same architecture family, official repo weights
  `AASIST.pth` (sha256 pinned in eval/u3/D2_PIN.json).
- **D3 = RawNet2** (Tak et al., ICASSP 2020), NII comparative-study checkpoint
  trained on ASVspoof2019 LA (Zenodo record 8337778, file
  `<HOME>\external\nii_asvspoof\rawnet2\01\__pretrained\trained_network.pt`).
  Different architecture family (raw-waveform sinc + residual + GRU) — no
  form-gated download needed; no untrained or unofficial model substituted.

## 1. Input policies (quoted from code)

**D1/D2** (`audio_benchmark/models.py`, `AASISTModel.score`, lines 264–275):
```
# length (nb_samp, 64600 for AASIST-L) so the spectral axis comes out
# long, else TILE-REPEAT the clip (np.tile) to fill nb_samp. The repo
# ... does NOT zero-pad
if self.nb_samp and y.size != self.nb_samp:
    if y.size >= self.nb_samp:
        y = y[: self.nb_samp]          # front-truncate: window = FIRST 64,600 samples
    else:
        num_repeats = self.nb_samp // y.size + 1
```
Score = raw bonafide logit `o[self.bonafide_idx]` (models.py:295, bonafide_idx=1).

**D3** (`eval/u3/rawnet2_nii.py:56-71`, following
`<HOME>\external\nii_asvspoof\code\model_01.py` forward, lines 164-179, verbatim):
```
if x.shape[1] < self.m_seg_len:
    # too short, no need to split
    scores = self.m_rawnet.inference(x)
else:
    # split input into segments
    num_seq = x.shape[1] // self.m_seg_len
    scores = []
    for idx in range(num_seq):
        stime = idx * self.m_seg_len
        etime = idx * self.m_seg_len + self.m_seg_len
        scores.append(self.m_rawnet.inference(x[:, stime:etime]))
    # average scores
    scores = torch.stack(scores, dim=2).mean(dim=-1)
```
D3 segment length is also 64,600 samples (model_01.py:84: `self.m_seg_len = 64600`).
Score = bonafide logit `sc[0, -1]` (class 1 = bonafide).

## 2. Thresholds (each detector's own LA dev EER point)

| det | dev set used | n bona | n spoof | EER @ dev | threshold | dev AUC (bona-higher) |
|---|---|---|---|---|---|---|
| D1 AASIST-L | full dev | 2,548 | 22,296 | 0.5108% | -0.947072 | 0.99964 |
| D2 AASIST-full | full dev | 2,548 | 22,296 | 0.5108% | -1.093836 | 0.99963 |
| D3 RawNet2 | stratified subset (see note) | 2,548 | 1,800 | 1.7719% | -2.317568 | 0.99895 |

Note on attacks: dev protocols contain only A07-A12 in ASVspoof2019 LA (A01-A06
are train-only attacks), so the D3 spec wording "spread over A01-A06" is
implemented as "spread over the distinct dev attacks", fixed seed 44, 300 per
attack (n = 4,348 total). D2's dev EER equals D1's to four decimals (both
AASIST variants, same data) at a different operating point.

## 3. Experiments (same frozen files, each detector at its OWN dev threshold)

### 3.1 Clean seed-44 sample (n = 200 spoof + 200 bona fide)

| metric | D1 AASIST-L | D2 AASIST-full | D3 RawNet2 |
|---|---|---|---|
| FAR @ dev thr (95% CI) | 12.00% (24/200) [7.50–16.50%] | 11.50% (23/200) [7.50–16.00%] | 15.00% (30/200) [10.00–20.00%] |
| FRR @ dev thr (95% CI) | 0.00% (0/200) [0.00–0.00%] | 0.00% (0/200) [0.00–0.00%] | 2.50% (5/200) [0.50–5.00%] |
| AUC (bona-higher) | 0.9986 | 0.9996 | 0.9877 |
| pooled EER | 0.50% @ 3.011 | 0.50% @ 2.332 | 5.50% @ -0.405 |

### 3.2 A2 (7 codec/noise/room transforms, all 200 spoofs + 200 bona fide per condition)

| condition | D1 FAR / FRR | D2 FAR / FRR | D3 FAR / FRR |
|---|---|---|---|
| mp3_64k | 12.00% (24/200) [7.50–16.50%] / 0.00% (0/200) [0.00–0.00%] | 10.50% (21/200) [6.50–15.00%] / 0.00% (0/200) [0.00–0.00%] | 14.00% (28/200) [9.50–19.00%] / 2.50% (5/200) [0.50–5.00%] |
| mp3_32k | 11.00% (22/200) [7.00–15.50%] / 0.00% (0/200) [0.00–0.00%] | 11.50% (23/200) [7.50–16.00%] / 0.00% (0/200) [0.00–0.00%] | 15.00% (30/200) [10.50–20.00%] / 3.00% (6/200) [1.00–5.50%] |
| opus_32k | 9.50% (19/200) [5.50–14.00%] / 0.00% (0/200) [0.00–0.00%] | 10.50% (21/200) [6.50–15.00%] / 0.00% (0/200) [0.00–0.00%] | 10.00% (20/200) [6.00–14.50%] / 3.00% (6/200) [1.00–5.50%] |
| resample_8k_rt | 2.00% (4/200) [0.50–4.00%] / 0.00% (0/200) [0.00–0.00%] | 2.00% (4/200) [0.50–4.00%] / 0.00% (0/200) [0.00–0.00%] | 8.00% (16/200) [4.50–12.00%] / 4.50% (9/200) [2.00–7.50%] |
| noise_20db | 9.50% (19/200) [5.50–13.50%] / 2.00% (4/200) [0.50–4.00%] | 3.00% (6/200) [1.00–5.50%] / 9.00% (18/200) [5.00–13.00%] | 61.50% (123/200) [54.50–68.00%] / 0.50% (1/200) [0.00–1.50%] |
| noise_10db | 0.50% (1/200) [0.00–1.50%] / 75.50% (151/200) [69.50–81.50%] | 0.00% (0/200) [0.00–0.00%] / 71.50% (143/200) [65.00–78.00%] | 79.00% (158/200) [73.50–84.50%] / 0.00% (0/200) [0.00–0.00%] |
| reverb_rt60_0.3s | 0.50% (1/200) [0.00–1.50%] / 99.00% (198/200) [97.50–100.00%] | 0.00% (0/200) [0.00–0.00%] / 98.50% (197/200) [96.50–100.00%] | 26.00% (52/200) [20.00–32.00%] / 27.50% (55/200) [21.50–33.50%] |

A2 AUCs (bona-higher): D1 reverb **0.4652** (inverted), D2 reverb **0.3763**
(inverted worse), D3 reverb 0.8161 (degraded, NOT inverted); noise_10db: D1
0.9182, D2 0.9456, D3 0.9413 — but at their own thresholds D1/D2 fail toward
REJECTING bona fide (FRR 75.5%/71.5%) while D3 fails toward ACCEPTING spoofs
(FAR 79%).

### 3.3 A3 (splice-into-bona-fide, 9 frac×position cells × 200 bona-fide hosts)

| cell | D1 FAR | D2 FAR | D3 FAR |
|---|---|---|---|
| 0.1/start | 73.50% (147/200) [67.00–79.50%] | 50.00% (100/200) [43.00–57.00%] | 76.50% (153/200) [70.50–82.00%] |
| 0.1/middle | 92.00% (184/200) [88.00–95.50%] | 94.00% (188/200) [90.50–97.00%] | 97.00% (194/200) [94.50–99.00%] |
| 0.1/end | 95.00% (190/200) [92.00–98.00%] | 98.00% (196/200) [96.00–99.50%] | 98.50% (197/200) [96.50–100.00%] |
| 0.25/start | 75.50% (151/200) [69.50–81.50%] | 55.00% (110/200) [48.00–62.00%] | 55.50% (111/200) [48.50–62.50%] |
| 0.25/middle | 92.00% (184/200) [88.00–95.50%] | 96.00% (192/200) [93.00–98.50%] | 90.50% (181/200) [86.50–94.50%] |
| 0.25/end | 97.50% (195/200) [95.00–99.50%] | 97.50% (195/200) [95.00–99.50%] | 95.50% (191/200) [92.50–98.00%] |
| 0.5/start | 65.00% (130/200) [58.00–71.50%] | 51.00% (102/200) [44.00–58.00%] | 30.50% (61/200) [24.00–37.00%] |
| 0.5/middle | 79.00% (158/200) [73.49–84.50%] | 88.00% (176/200) [83.50–92.50%] | 77.50% (155/200) [71.50–83.00%] |
| 0.5/end | 94.50% (189/200) [91.00–97.50%] | 97.00% (194/200) [94.50–99.00%] | 93.00% (186/200) [89.50–96.50%] |

**A3 inside/beyond-window breakdown** (inside = splice region entirely within
the first 64,600 samples; beyond = any part of it past that mark; D3's segment
policy also windows on 64,600-sample segments, so the same cut applies):

| group | D1 FAR (n) | D2 FAR (n) | D3 FAR (n) |
|---|---|---|---|
| inside-window | 81.95% (1158/1413) [79.97–83.93%] (1413) | 76.29% (1078/1413) [74.10–78.49%] (1413) | 75.51% (1067/1413) [73.25–77.78%] (1413) |
| beyond-window | 95.61% (370/387) [93.54–97.42%] (387) | 96.90% (375/387) [95.09–98.45%] (387) | 93.54% (362/387) [90.96–95.87%] (387) |

### 3.4 U1 laundered clips (C1 laptop speaker->mic; C2 phone voice memo)

| metric | D1 | D2 | D3 |
|---|---|---|---|
| C1 FAR (50 spoof) | 56.00% (28/50) [42.00–70.00%] | 72.00% (36/50) [60.00–84.00%] | 84.00% (42/50) [74.00–94.00%] |
| C1 FRR (50 bona) | 48.00% (24/50) [34.00–62.00%] | 32.00% (16/50) [20.00–46.00%] | 16.00% (8/50) [6.00–28.00%] |
| C1 AUC | 0.4992 | 0.5152 | 0.5428 |
| C1 pooled EER | 50.00% @ -0.567 | 48.00% @ 0.359 | 48.00% @ -0.946 |
| C2 FAR (50 spoof) | 2.00% (1/50) [0.00–6.00%] | 2.00% (1/50) [0.00–6.00%] | 62.00% (31/50) [48.00–76.00%] |
| C2 FRR (50 bona) | 68.00% (34/50) [56.00–80.00%] | 64.00% (32/50) [50.00–76.00%] | 10.00% (5/50) [2.00–20.00%] |
| C2 AUC | 0.8372 | 0.8064 | 0.8392 |
| C2 pooled EER | 22.00% @ -3.256 | 28.00% @ -3.474 | 26.00% @ -0.638 |

### 3.5 LA eval subset (bona fide n=7,355 + 500/attack, seed 44; n=13,855)

| metric | D1 | D2 | D3 |
|---|---|---|---|
| FAR @ own dev thr | 11.42% (742/6500) [10.65–12.20%] | 10.26% (667/6500) [9.52–11.03%] | 14.80% (962/6500) [13.95–15.66%] |
| FRR @ own dev thr | 0.10% (7/7355) [0.03–0.16%] | 0.16% (12/7355) [0.08–0.26%] | 0.82% (60/7355) [0.63–1.03%] |
| AUC (bona-higher) | 0.9991 | 0.9993 | 0.9898 |
| pooled EER | 1.08% @ 1.868 | 0.82% @ 1.487 | 4.38% @ 0.113051 |

(The 11.14% pooled-eval FAR / 0.10% FRR in RESULTS_POLICY.md section 8 is the
projection from the FULL eval corpus at the dev threshold — a different,
larger population; this subset is what per-detector scoring was feasible on.)


## 4. Which findings hold across detectors

1. **Laundering collapse (U1 C1, speaker->mic replay) — HOLDS universally.**
   Pooled C1 AUC: D1 0.4992 / D2 0.5152 / D3 0.5428; pooled EER 50/48/48%.
   All three detectors fall to ~chance on laundered audio, and all three
   accept laundered spoofs at rates FAR above their clean-sample FAR
   (12%->56%, 11.5%->72%, 15%->84%).
2. **Beyond-window splice acceptance — HOLDS for all three.** FAR on splices
   with any part beyond sample 64,600 is higher than for fully-inside-window
   splices everywhere: D1 95.6% vs 82.0%, D2 96.9% vs 76.3%, D3 93.5% vs
   75.5%. (For D3 the window semantics are segment-averaging rather than
   front-truncation; the geometry cut is identical.)
3. **Positional recency gradient in splices — HOLDS.** start < middle < end
   in every fraction: e.g. 0.5-frac FAR D1 65/79/94.5%, D2 51/88/97%,
   D3 30.5/77.5/93%. D2 and D3 sharpen the gradient D1 showed.
4. **Codec/recompression FAR at the dev threshold ~10% — HOLDS.** mp3/opus
   FAR by detector: D1 9.5-12%, D2 10.5-11.5%, D3 10-15% (and resample 8k
   2-8% everywhere). The U2 finding that "zero FAR under transforms" does
   not survive a dev-calibrated threshold generalizes across families.
5. **Reverb inversion — AASIST-family specific, does NOT generalize.**
   Synthetic reverb RT60 0.3 s inverts D1 (AUC 0.4652, FRR 99%) and D2
   (AUC 0.3763, FRR 98.5%); D3 degrades (AUC 0.8161, EER 27.5%) without
   flipping. The paper must attribute inversion to the AASIST front-end,
   not to all raw-waveform detectors.
6. **"Noise defeats detection" — HOLDS, but the failure side differs.**
   At -10 dB noise the AASIST pair rejects bona fide en masse (FRR 75.5%
   D1, 71.5% D2, FAR 0%), while D3 accepts spoofs en masse (FAR 79%, FRR
   0%). The channel breaks the decision boundary for every detector; which
   direction it moves is architecture-dependent.
7. **Phone-channel laundering defeat (U1 C2) — AASIST-family specific.**
   C2 FAR/FRR: D1 2%/68%, D2 2%/64% (phone DSP drops all AASIST scores,
   laundered spoof acceptance dies) — but D3 accepts 62% of C2 laundered
   spoofs at its own threshold (FRR 10%, AUC 0.8392). RawNet2's scores on
   laundered audio do NOT get suppressed by the phone channel the way
   AASIST's do. The A8 e2e conclusion (RESULTS_U1) stands for the pipeline's
   frozen D1 detector; the paper should state that C2-style channel
   protection is detector-dependent, not a law of the channel.
8. **Dev-EER thresholds transfer imperfectly to eval for all detectors**
   (D1 11.4% / D2 10.3% FAR at eval subset vs 0.5% dev EER) — consistent
   with the known LA dev->eval difficulty shift; D3 column pending scoring.

## 5. Files

- eval/u3/score_u3.py — per-detector batch scorer (modes dev/eval/a2/a3/
  clean/u1c1/u1c2; scratch labels unique per det/mode/batch; RAM-gated,
  resumable path-keyed caches)
- eval/u3/u3_metrics.py — per-detector metrics (dev EER point, FAR/FRR w/
  95% bootstrap CI, AUC, pooled EER, A3 window geometry)
- eval/u3/rawnet2_nii.py — D3 wrapper (NII RawNet2, Zenodo 8337778)
- eval/u3/remap_d1.py — D1 column from frozen U2/U1 caches (no re-scoring)
- eval/u3/D2_PIN.json + eval/u3/aasist_full_modelcfg.json — D2 assets
- eval/u3/supervisor_serial.sh / chain_d2.sh / chain_d3.sh — orchestration
- Caches: %TEMP%\u3work\u3_scores_<D>_<mode>.json (D1 also remapped to
  eval/u3/); metrics at eval/u3/u3_metrics_{D1,D2,D3}.json
