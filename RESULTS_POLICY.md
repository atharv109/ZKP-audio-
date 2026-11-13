# RESULTS — policy experiment + leakage measurement (v4, final measurement step)

Measured 2026-11-05. Harness: eval/policy_experiment.py, eval/leakage_sim.py
(data: eval/policy_exp_results.csv, eval/leakage_sim_results_v2.json,
eval/leakage_consistency.json). One enrollment reused for everything
(LA_E_1250691, record + handoff from the v4 matrix phase) — no re-enrollment,
no issuer contact anywhere. Enrollment record's freshness handled with
`--now` inside its validity window during verification.

## 1. Policy table — one record, 9 grid-aligned verifier policies

Same record, same handoff, all policies grid-aligned (timestamp bounds
multiples of 3600 with t_max+1 aligned; gps bounds multiples of 100):

| # | case | expected | holder stage | actual | verify |
|---|---|---|---|---|---|
| 1 | equal-cell (2 grid cells containing the value) | ACCEPT | proved | **ACCEPT ✓** | ACCEPT |
| 2 | same record, wide window (the enrollment-era window, re-aligned) | ACCEPT | proved | **ACCEPT ✓** | ACCEPT |
| 3 | wider still (year-scale window) | ACCEPT | proved | **ACCEPT ✓** | ACCEPT |
| 4 | narrower window, excluding the value | REFUSE | refused | **REFUSE ✓** (no proof) | — |
| 5 | device allow-list excluding the hidden device | REFUSE | refused | **REFUSE ✓** | — |
| 6 | sensor_min stricter but satisfied (71 ≤ value) | ACCEPT | proved | **ACCEPT ✓** | ACCEPT |
| 7 | sensor_min above the value (80) | REFUSE | refused | **REFUSE ✓** | — |
| 8 | stale window (entirely in the past, aligned) | REFUSE | refused | **REFUSE ✓** | — |
| 9 | malformed (min > max) | validator reject | refused | **REFUSE ✓** (holder exit 1) | — |

**9/9 expectations met.** The SAME record + handoff served every policy: the
holder proved **4** accepting policies (cases 1, 2, 3, 6 — mean 695 / median
708 ms), all verified
ACCEPT; refusing policies produced NO proof (and no distinguishable
reason-value beyond the rule name). Deviation noted: the holder refuses
MALFORMED policies at its own exit 1 (refusal contract); the POLICY VALIDATOR
inside verify_media_v4 rejects malformed files at exit 2 as specified there.

## 2. Leakage — adaptive verifier vs the holder's real refusal/accept oracle

Every oracle query was a REAL holder CLI invocation (67 queries; 26 accepted).
Search ranges: timestamp [1780279200, 1780865999) (163 grid cells / 588,800 s),
gps_lat [407400, 408400) (10 cells / 1,000 units). Strategy per setting:
(a) direct bisection with right-extended windows; (b) same, but the window must
keep width ≥ floor; (c) probe positions grid-aligned (shifts are grid multiples).

| setting | timestamp: queries | precision | bits learned | gps_lat: queries | precision | bits learned |
|---|---|---|---|---|---|---|
| (a) no guard | 18 | **2 s** (exact ±1) | **18.16** | 9 | 2 units (exact ±1) | **8.97** |
| (b) min-width only (3600 s / 100 units) | 18 | **2 s — DEFEATED** | **18.16** | 9 | 2 units — DEFEATED | **8.97** |
| (c) grid-aligned | **8** | **3,600 s = one grid cell** | **7.35** | **5** | **100 units = one cell** | **3.32** |

**The width floor is defeated.** Measured mechanism: the verifier anchors the
probe window's RIGHT edge beyond its candidate interval (any [t, HI] with HI at
the range end keeps width ≥ floor for arbitrary t) — accept stays monotone in t,
so bisection reaches the exact value at the same query count as no guard.
Honest correction to FIX_DESIGN.md's layer-1 story (now updated there): a width
floor constrains the WINDOW, but the attack lives in the window's POSITION,
which the floor never constrained.

**The grid is the only effective guard** (measured): probe positions quantized
to the lattice collapse the candidates to one CELL — 3,600 s (timestamp) and
100 units (gps) — preserving 10.8 of the 18.2 + 5.6 of the 9.0 bits an
unguarded verifier learns. Bits learned per field: 18.16 → 7.35 (timestamp),
8.97 → 3.32 (gps_lat).

Bits-learned definition (Part 0, recomputed): log2(prior range / final
candidate-set size), never more than the number of queries. Prior ranges stated
per field: timestamp = 588,800 s ([1780279200, 1780865999), 163 grid cells of
3,600 s); gps_lat = 1,000 units ([407400, 408400), 10 cells of 100).
Recomputed: (a) timestamp 18.16 bits <= 18 queries OK; gps_lat 8.97 <= 9 OK;
(b) identical (the floor was defeated, so its final candidates are the same as
(a)); (c) timestamp 7.35 bits <= 8 queries OK; gps_lat 3.32 <= 5 OK. (The
measured "precision=2" cells are the candidate interval [lo, hi) of width 2 —
log2 uses the interval SIZE, so those entries stand.)

Consistency: 12 prove+verify ACCEPT-ACCEPT pairs across the three settings
(5 + 5 + 2 — the grid setting's remaining cases were CORRECT refusals:
aligned windows starting above the value are refused without proof); the
holder-prove node peak ≈ 50 MB (no detector in the proving path), verify node
peak ≈ 56 MB — both trivial.

## 8. Detector-layer context: pooled eval FAR/FRR at the dev threshold (Part 0, added 2026-11-09)

From the full LA eval scores (63,882 spoof / 7,355 bonafide, no rescoring;
source: eval/eval_rethreshold_pooled.json), so the policy and leakage
measurements read against the right operating point:

| metric | @eval thr (1.7635) | @dev thr (−0.9449426) |
|---|---|---|
| FRR (bona fide rejected) | 73/7,355 = 0.99% | **7/7,355 = 0.10%** |
| FAR (spoof accepted) | 633/63,882 = 0.99% | **7,115/63,882 = 11.14%** |

Per-attack FAR (n = 4,914 per attack ID):

| attack | FAR @eval | FAR @dev |
|---|---|---|
| A07 | 3 (0.06%) | 950 (19.3%) |
| A08 | 0 | 22 (0.45%) |
| A09 | 0 | 0 |
| A10 | 50 (1.02%) | **2,443 (49.7%)** |
| A11 | 0 | 14 (0.28%) |
| A12 | 6 (0.12%) | 996 (20.3%) |
| A13 | 0 | 70 (1.42%) |
| A14 | 0 | 0 |
| A15 | 13 (0.26%) | 298 (6.07%) |
| A16 | 19 (0.39%) | 119 (2.42%) |
| A17 | 169 (3.44%) | 715 (14.6%) |
| A18 | **345 (7.02%)** | **1,318 (26.8%)** |
| A19 | 28 (0.57%) | 170 (3.46%) |

For A8 specifically: the corpus-wide background accept rate for A08 content at
the dev threshold is 22/4,914 = 0.45% — the U1 physical-laundering measurement
tests whether the speaker→microphone channel alone lifts that above the
background. (Same table appended to RESULTS_U2.md §6.)
