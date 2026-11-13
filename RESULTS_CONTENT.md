# RESULTS — content-attack measurement (A1 cleanup, A2 re-encode, A3 splice)

Measured 2026-11-03/04 on the UNCHANGED pipeline (real commands only). Harness:
eval/content_sample.py (seed 43, disjoint from seed 42), eval/transform_content.py,
eval/score_content.py (batched via audio_benchmark/run_inference.py, ≤32 files
per fresh Python process), eval/content_eval.py. Data: eval/results_content.csv
(3,277 rows, append-only), eval/content_scores.json, eval/transform_params.json,
eval/splice_index_manifest.csv.

Note 1 (superseded rows): phase 0 first ran BEFORE any enrollments existed, so its
10 A1 rows recorded verify_fully REJECT with reason `record unreadable: ENOENT...`
— an environment error, not an attack verdict. They remain in the CSV as audited
evidence; the valid measurements are the attack_id="A1c" rows (same 10 pairs,
re-measured against existing records).
Note 2: a correction pass reset content_run_costs.json (fresh process, empty
log); prove-run costs were RECOVERED from all 870 run dirs' demo_result.json
stage timings.

## A1 cleanup — 10 distinct unenrolled substitutes (S1/S2/S3/S4)

| metric | result |
|---|---|
| substitutes | 10 distinct LA-eval spoof files (seed 44), never enrolled, never reused |
| S1 (FV) | **10/10 REJECT** |
| S2 (Part B) | **10/10 REJECT** |
| S3 (registry) | **10/10 REJECT** (unenrolled) |
| S4 (detector) | 10/10 spoof @1.7635419737 |
| representative reason | `record file_sha256 2a030cd6...ba4b != file a4fbad7d... — record is for a DIFFERENT file (or file altered)` |

THREAT_MODEL A1 hypothesis: **CONFIRMED** (10/10 new substitutes + 11/11 earlier).

## A2 benign re-encode (seed-43: 50 bona fide + 50 spoof; 7 conditions)

Detector (AASIST-L re-scored on the SAME 100 files; clean baseline from frozen scores):

| condition | EER | AUC | FRR@thr (bona→spoof) | FAR@thr (spoof→bona) |
|---|---|---|---|---|
| clean baseline (frozen) | 2.00% | 0.99920 | 1/50 | 0/50 |
| MP3 64 kbps | 2.00% | 0.99960 | 1/50 | 0/50 |
| MP3 32 kbps | 2.00% | 0.99840 | 1/50 | 0/50 |
| Opus 32 kbps | 2.00% | 0.99960 | 1/50 | 0/50 |
| resample 16k→8k→16k | 2.00% | 0.99760 | 1/50 | 0/50 |
| noise 20 dB | 2.00% | 0.99520 | **14/50** | 0/50 |
| noise 10 dB | **14.00%** | 0.94120 | **50/50** | 0/50 |
| reverb RT60 0.3 s | **52.00%** | **0.44720 (inverted)** | **50/50** | 0/50 |

Transform parameters: exact formulas/commands in eval/transform_params.json.

Crypto layers (50 bona fide enrolled clean, each transform verified against the
CLEAN record — S1/S2, with S3 registry lookup and S4 score rows per file):

| system | result over 350 rows | meaning |
|---|---|---|
| S1 (FV) | **350/350 REJECT** | a harmless re-encode breaks provenance binding |
| S2 (Part B) | **350/350 REJECT** | |
| S3 (registry) | **350/350 REJECT** | transform not enrolled |
| S4 (detector) | 232/350 bonafide, 118/350 spoof (per-file verdicts @1.76354) | detector mostly still says bonafide |

THREAT_MODEL A2 hypotheses: detector degrades (partial) — **CONFIRMED**
(noise/reverb severe); "zero false accepts" robustness pattern — **CONFIRMED**
(FAR = 0/50 in every condition); enrollment path of benign re-encodes — **OPEN**
(not run here; A3re below is its splice analogue).

## A3 splice (50 bona fide × 3 fractions × 3 positions = 450)

Insertion = concatenation of a spoof segment (L = frac × N_target samples, taken
from the paired spoof file from its beginning) at insert_idx ∈ {0, N//2, N};
exact indices in eval/splice_index_manifest.csv.

Detector (spliced → "spoof" @1.7635419737, n=50 per cell):

| fraction | start | middle | end |
|---|---|---|---|
| 10% | 17/50 | 14/50 | **9/50** |
| 25% | 20/50 | 14/50 | **4/50** |
| 50% | 30/50 | 23/50 | **4/50** |

Crypto layers:

| measurement | result |
|---|---|
| S1/S2/S3 vs clean record (450 each) | **450/450, 450/450, 450/450 REJECT** |
| S4 per file | 135/450 spliced → spoof (aggregates of the detection cells) |
| re-enrollment (10 splices: file #1's 9 variants + file #2's 0.5/middle) | **10/10 S1 ACCEPT** — fresh proof + issuer record over the splice (A7-style wrong-accept) |

THREAT_MODEL A3 hypotheses: detector uncertain — **CONFIRMED as unreliable**
(4/50..30/50, strong position effect); re-enrollment accepts spliced audio —
**CONFIRMED** (10/10, including a 50%-spoof-content splice).

## Hypothesis scoreboard

| THREAT_MODEL hypothesis | status |
|---|---|
| A1 (substitution rejected, real reason strings) | **CONFIRMED** |
| A2 detector layers degrade with content transforms | **CONFIRMED** (noise10/reverb severe) |
| A2 zero-false-accept pattern | **CONFIRMED** |
| A2 crypto rejects re-encodes ("a harmless re-encode breaks provenance") | **CONFIRMED** 350/350 |
| A3 detector uncertain | **CONFIRMED** (unreliable: 4/50..30/50) |
| A3 re-enrollment accepts spliced audio | **CONFIRMED** 10/10 |
| **No hypothesis refuted** | |

## Surprises

1. **Reverb RT60 0.3 s inverts the detector's ranking** (AUC 0.4472 < 0.5) and
   collapses FRR to 50/50 — this synthetic-IR reverb (direct tap + decaying
   noise tail) is far more damaging than the real-world reverb implied by the
   batch-2 robustness naming; the "harmless" transformation is detector-fatal.
2. **Splice position matters enormously**: end-inserted 50% splices are detected
   4/50 where start-inserted reach 30/50 — consistent with AASIST-L's
   front-loaded features / nb_samp front truncation behavior.
3. **FAR stayed 0/50 in every A2 condition**: re-encoding a SPOOF never let it
   pass as bonafide — the wrong-accept risk lies only in re-enrollment (A3re:
   10/10 ACCEPT), not in the detector being fooled by transformations.
4. Clean-baseline FRR = 1/50 again reproduces the seed-42 finding
   (`LA_E_8374049`).

## Costs

| quantity | value |
|---|---|
| verify_fully runs (830) | mean 708 ms, median 705 ms, max 949 ms; node peak small |
| prove runs (870, recovered) | detect mean 7,688 / median 2,824 ms (median = warm steady state; mean inflated by -cold runs); prove 1,061/1,016 ms; verify 365/333 ms |
| scoring (36 batches × ≤32) | ~22 s/batch; python peak ~1,050 MB per batch |
| wall (phases all) | 5,065 s (plus rescoring/cache attempts before the resume machinery) |
| RAM discipline | gate 1,500 MB (EVAL_RAM_GATE_MB; protocol default 2,000); 2 gate stops + 1 timeout, all recovered by resume |

## Limits

- The detector threshold was tuned on the eval set (full-eval EER point) — not a
  validated deployment operating point; all detector numbers inherit that.
- Splices are INSERTIONS (concatenation); replacement splices are a different
  (harder) condition, not measured here.
- The reverb IR is synthetic (not a measured room response) — see Surprise 1;
  treat that condition as stress, not realism.
- A2's re-enrollment path was not itself run; A3re is its direct analogue
  (10/10 ACCEPT).
- Prover artifacts all in fresh dirs, nothing overwritten; the invalid
  first-pass A1 rows are retained as audit evidence (Note 1); the clobbered
  cost file was recovered, not silently dropped (Note 2).

## Verification (post-hoc checks on Surprises 1 and 2)

Harness: `eval/verify_surprises.py`; data: `eval/verify_truncation.csv`,
`eval/verify_levels.csv`, control crops under
`outputs/v3/eval_content/control_crops/`.

### V1 — End-insert blind spot: truncation, recency, or both?

**Ground truth (read-only):** `nb_samp = 64,600` samples = **4.0375 s at 16 kHz**
(`AASIST-L.conf:15`, default mirrored at `audio_benchmark/models.py:129`). The
loader **front-truncates** (`y[:nb_samp]`) when the clip is longer and
**tile-repeats** (`np.tile(y, reps)[:nb_samp]`) when shorter — never zero-pads
(`models.py:264-275`). The model therefore sees only the first 4.04 s (or 2.1+
rotations of a shorter file).

**Per-splice visibility over all 450 splices** (spoof visible = any spoof sample
maps into the model window, including via tiling):

| spoof position in the model window | group | n | detection |
|---|---|---|---|
| window start | start-inserts (all visible) | 150 | **67/150** |
| window middle | middle-inserts (all visible) | 150 | **51/150** |
| window late | end-inserts on short files (visible via window/tiling) | 111 | **17/111** |
| beyond window | end-inserts on long files (truncated away) | 39 | **0/39** |

Detection falls **monotonically** with the spoof's position in the 4.04 s
window and is **exactly 0** when entirely beyond it.

**Control** (10 missed end-inserts, cropped so the spoof segment falls inside
the first `nb_samp` window, re-scored): **1/10 detected** (pre-crop 0/10).
Critical nuance, stated plainly: 6 of the 10 crops were **no-ops** — those
spliced files are shorter than `nb_samp`, so `y[-nb_samp:]` returns the whole
file and the model input is unchanged (identical scores to 6 decimals, e.g.
7.533827 → 7.533827). For the 4 genuine long-file crops (spoof moved to the
end of the window): **1/4 detected**.

**Verdict:** the end-insert blind spot is **NOT explained by truncation alone**.
Plain statement: front-truncation fully explains only the beyond-window subset
(0/39). The dominant factor is **spoof position within the model's 4.04 s
window** — the detector's effective attention decays toward the window's end
(67/150 → 51/150 → 17/111 → 0), and merely placing spoof content "somewhere in
the window" (1/10 control) does not restore detection. Paper wording should use
the recency gradient, not "truncation".

### V2 — Reverb/noise sanity: levels and format

5 bona fide files per condition vs clean (full table: `eval/verify_levels.csv`):

| condition | findings across all 5 files |
|---|---|
| clean originals | sr 16000, mono, durations unchanged, peak exactly 1.0, **1 clipped sample each** (pre-existing in the dataset) |
| reverb RT60 0.3 s | sr/mono/durations identical; peak clamped to 0.99 (transform's anti-clip clamp); **0 clipped samples**; RMS 0.098–0.156 vs clean 0.103–0.158 — **no level jump** |
| noise 10 dB | sr/mono/durations identical; RMS +~3–5% over clean (SNR exact by construction); 0–5 clipped samples (at already-full-scale peaks); no level jump |

**RIR source:** synthetic, not a measured room response — direct tap = 1.0 plus
a 4,800-tap (0.3 s) exponentially decaying white-noise tail
`10^(−3·t/RT60)`, tail peak-normalized to 0.5, `fftconvolve`, peak-clamped to
0.99 (full parameters: `eval/transform_params.json`, formula in
`eval/transform_content.py`).

**Verdict: nothing is off — stated explicitly.** No sample-rate/channel/
duration mismatch, no clipping introduced, no level jump; the clean originals
themselves already sit at full scale. **No regeneration was needed** — the
inversion (below) is a genuine detector response, not a generation artifact.

### V3 — Score distributions (why the reverb "inversion" is real)

min/median/max of raw AASIST-L bonafide scores (higher = more bonafide):

| condition | bona fide (n=50) | spoof (n=50) |
|---|---|---|
| clean (frozen) | −0.410 / **6.720** / 8.704 | −10.024 / **−4.113** / 1.196 |
| MP3 64 kbps | −0.007 / 6.679 / 8.778 | −9.912 / −4.111 / 1.030 |
| MP3 32 kbps | −0.976 / 6.486 / 8.410 | −9.453 / −4.229 / 0.153 |
| Opus 32 kbps | −0.569 / 6.490 / 8.819 | −9.497 / −4.272 / 1.136 |
| resample 16→8→16 | −2.963 / 5.367 / 8.167 | −10.085 / −5.197 / −1.305 |
| noise 20 dB | −2.176 / 2.782 / 5.955 | −6.692 / −3.275 / −0.381 |
| noise 10 dB | −3.592 / **−1.733** / 0.960 | −5.273 / **−3.676** / −2.040 |
| reverb RT60 0.3 s | −10.977 / **−5.956** / −1.515 | −11.624 / **−5.717** / −2.410 |

The table makes both phenomena visible: under reverb the bona fide median
(**−5.956**) drops **below** the spoof median (**−5.717**) — the ranking
inversion behind AUC 0.4472 is real, with both distributions displaced ~12
points below their clean positions. Under noise 10 dB the bona fide median
collapses to −1.733 with max 0.960 — every file lands below the 1.7635
threshold (FRR 50/50) — while the spoof distribution barely moved
(−4.113 → −3.676). Both are *bonafide-distribution displacement* effects,
consistent with the zero-false-accept pattern (FAR 0/50 everywhere).