# RESULTS_U2 — dev-set threshold + n=200 large-sample measurement

Measured 2026-11-05/06. Everything detector-dependent is now reported at TWO
detected thresholds: the old eval-set point (1.7635419737) and the NEW
**dev-set point (−0.9449426)**, computed from the FULL freshly-scored LA dev
set (24,844 utterances = 2,548 bona fide + 22,296 spoof, 100% of the official
dev protocol; frozen AASIST-L, batched RAM-gated scoring).

## Dev-set detector quality (Part 1)

| metric | LA dev (frozen AASIST-L) | LA eval (prior measurement) |
|---|---|---|
| pooled EER | **0.5102%** | 0.9909% |
| ROC AUC | 0.999641 | 0.999200 |
| EER-point threshold | **−0.9449426** | 1.7635419737 |

The dev set is "easier" (fewer/unseen attack types differ from eval) — its EER
threshold sits 2.7 units LOWER. min t-DCF is unchanged by threshold choice
(threshold-free; Step-5 reproduct at 0.030947 stands).

## 2. Threshold trade-off on the frozen scores (no rescoring; CIs = 1,000
bootstrap resamples, seed 4400)

| sample (n bona/spoof) | FRR @eval | FRR @dev | FAR @eval | FAR @dev |
|---|---|---|---|---|
| seed-42 (10/10) | 10% [0,30] | **0%** [0,0] | 0% [0,0] | 0% [0,0] |
| seed-43 (50/50) | 2% [0,6] | **0%** [0,0] | 0% [0,0] | 4% [0,10] |
| u2 (200/200) | 0% [0,0] | **0%** [0,0] | **1.5% [0,3.5]** | **12% [8,16.5]** |

## 3. Part-1 confirm runs (real issuer at the dev threshold, DET_THRESHOLD env)

| artifact | eval threshold | dev threshold |
|---|---|---|
| LA_E_8374049 (seed-42 casualty) | REFUSED ❌ | **ENROLLED ✓** |
| LA_E_2805188 (seed-43 casualty) | REFUSED ❌ | **ENROLLED ✓** |
| 10 v3-A3re splices | 2/10 refused | **10/10 ENROLLED** — 0 refusals |

## 4. n=200 large-sample results (Part 2; seed-44, spoofs across all 13 attack IDs)

Data: eval/results_u2.csv (5,116 rows). Crypto layers unchanged at any
threshold: A2 **1,400/1,400 REJECT**, A3 **1,800/1,800 REJECT** (vs small-n:
350/350, 450/450 — identical behavior, now confirmed at n=200).

### A2 per-condition rates (u2 transforms, n=200 per cell, MEASURED @dev-thr)

| condition | FRR @dev (95% CI) | FAR @dev (95% CI) |
|---|---|---|
| MP3 64 kbps | 0/200 [0, 0] | 24/200 = 12.0% [6.0, 19.5] |
| MP3 32 kbps | 0/200 [0, 0] | 22/200 = 11.0% [5.0, 19.0] |
| Opus 32 kbps | 0/200 [0, 0] | 19/200 = 9.5% [4.0, 16.5] |
| resample 16→8→16 | 0/200 [0, 0] | 4/200 = 2.0% [0.0, 5.5] |
| noise 20 dB | 4/200 = 2.0% [0.0, 7.0] | 19/200 = 9.5% [2.5, 15.5] |
| noise 10 dB | 151/200 = 75.5% [65.5, 85.5] | 1/200 = 0.5% [0.0, 2.5] |
| reverb RT60 0.3 s | 198/200 = 99.0% [95.5, 100] | 1/200 = 0.5% [0.0, 2.5] |

(Old small-n @eval-thr: FRR 1/50..2/50, FAR 0/50 — at the LOWER dev threshold
the far-reach of FAR flips to ~10-12% on codec-transformed spoofs; reverb and
noise-10dB remain detector-fatal on the FALSE-REJECT side.)

### A3 splice detection per cell (n=200/cell, MEASURED @dev-thr: spliced → "spoof")

| fraction | start | middle | end |
|---|---|---|---|
| 10% | 53/200 = 26.5% [15.0, 37.0] | 16/200 = 8.0% [3.0, 13.5] | 10/200 = 5.0% [1.0, 10.5] |
| 25% | 49/200 = 24.5% [14.5, 35.5] | 16/200 = 8.0% [3.0, 14.5] | 5/200 = 2.5% [0.0, 7.5] |
| 50% | 70/200 = 35.0% [25.0, 45.5] | 42/200 = 21.0% [9.5, 30.0] | 11/200 = 5.5% [1.5, 11.5] |

(The recency gradient PERSISTS at n=200: start ≫ middle ≫ end in every
fraction row — unchanged conclusion.)

### A3 re-enrollment on v4 (50 splices stratified over 9 cells, dev threshold)

- issuer refusals: **7/50** (14%; eval-threshold was 2/10 = 20% — with the
  lower threshold MORE borderline spoof-topped splices enroll)
- enrolled + FULL-VERIFY ACCEPT: **43/50** (86%)

### Enrollment-gate casualties on 200 genuine files

- v4 issuer refusals: **0/200** at the dev threshold (95% CI [0, 1.5%]);
  old small-n: 1/10 + 1/50 (~3%). **Conclusion change: the "genuine refused"
  casualty column vanishes at the dev threshold — at the cost of FAR@dev 12%
  on spoof content.**

## 5. Flagged conclusion changes vs RESULTS_CONTENT/RESULTS_V4

1. **"2/60 genuine casualties" → 0/200 at the dev threshold** (the false-reject
   weakness is repaired by re-thresholding alone).
2. **"FAR = 0 everywhere" → FAR@dev = 12% clean-spoof / 9.5-12% codec-transformed
   spoof** (measured n=200) — the lower threshold trades false accepts for
   false rejects asymmetrically (reverb/noise10 false-REJECT rates hit 99%/75%);
   the paper's detector-layer table must present BOTH operating points as a
   pair, and the "zero false accepts under transforms" claim from the eval
   threshold does NOT survive re-thresholding.
3. **A3 re-enrollment residual WORSENS at the dev threshold**: 43/50 splices
   enroll and verify (86%) vs 8/10 (80%) at the eval point — and 0/10 refused
   among the v3-legacy splices (vs 2/10). The content-identity opening is
   structurally unaffected by re-thresholding (crypto REJECTs remain
   1,400+1,800/1,400+1,800), but the GATE's filtering power drops with the
   lower threshold.
4. The recency-gradient finding (start ≫ middle ≫ end) is CONFIRMED at n=200 —
   unchanged conclusion.
5. Crypto-layer conclusions (A2/A3 hash+record binding REJECT everything) are
   CONFIRMED at n=200 — unchanged conclusion.

Sources: eval/results_u2.csv; eval/u2_scores.json; eval/dev_scores.json +
eval/dev_labels.csv; eval/dev_metrics.json; eval/rethreshold_results.json;
eval/u2_state.json (enrollment decisions); outputs/v4/u2_att/confirm/*.


## 6. Pooled-eval FAR/FRR at the dev threshold (added 2026-11-05, Part 0)

Counts from the 63,882-spoof / 7,355-bonafide eval scores (no rescoring):

| metric | @eval thr (1.7635) | @dev thr (−0.9449) |
|---|---|---|
| FRR (bona fide rejected) | 73/7,355 = 0.99% | **7/7,355 = 0.10%** |
| FAR (spoof accepted) | 633/63,882 = 0.99% | **7,115/63,882 = 11.14%** |
| min t-DCF | 0.030947 (threshold-free; Step 5) | unchanged |

Per-attack FAR (n = 4,914 per attack ID):

| attack | FAR @eval | FAR @dev |
|---|---|---|
| A07 | 3 | 950 |
| A08 | 0 | 22 |
| A09 | 0 | 0 |
| A10 | 50 | **2,443** (49.7%) |
| A11 | 0 | 14 |
| A12 | 6 | 996 |
| A13 | 0 | 70 |
| A14 | 0 | 0 |
| A15 | 13 | 298 |
| A16 | 19 | 119 |
| A17 | 169 | 715 |
| A18 | **345** | **1,318** |
| A19 | 28 | 170 |

Per-attack conclusion: at the dev threshold the attack split becomes dramatic —
A10 (a codec/VC-family attack with high-quality vocoded speech) passes the gate
at 49.7%, while A14 stays at 0%. Genuine casualties pool-wide: 7/7,355 (the
predicted LA_E_8374049 + LA_E_2805188 are among this set of 7).
