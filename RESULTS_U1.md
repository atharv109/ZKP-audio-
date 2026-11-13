# RESULTS — U1: physical laundering (attack A8), speaker→microphone replay

Measured 2026-11-09 (C1). New code under `eval/u1/`; no pipeline changes.
Harness: `eval/u1/build_track.py` (track), `eval/u1/segment3.py` (segmentation),
`eval/u1/score_u1.py` + `run_inference.py` (frozen AASIST-L, batch ≤32, RAM-gated),
`eval/u1/u1_metrics.py`, `eval/u1/run_a8_e2e.py` (A8 e2e + crypto check).

## 1. Clips + track
50 spoof + 50 bona fide from the seed-44 sample (u2 manifest), interleaved
10 bona/10 spoof per attack decade so the channel effect spreads. Per clip:
1 s gap, 200 ms 1 kHz sync beep, 500 ms silence, clip, 500 ms; 2 s marker at
start/end. One playback WAV (16k + 48k export), manifest with exact offsets
(`eval/u1/track_manifest.json`).

## 2. Capture (C1) — what the takes actually contain (forensics)
Two 44.1 kHz mono 16-bit takes, 589.98 s each, fixed-duration records
(devices from the ffmpeg dshow log: mic "Microphone Array (Intel Smart Sound
Technology for Digital Microphones)"; only audio device).

| take | verdict (measured) |
|---|---|
| `c1_capture.wav` | USABLE: contains all 100 clips + beeps on the manifest schedule |
| `c1_capture2.wav` | DEAD: silent-room recording (rms 0.0004; no 1 kHz band energy, no marker) |

Forensics on take 1 (methods + numbers, all measured on the capture):
- **No start/end 2 s marker tones** (no burst ≥1.5 s anywhere; narrow-band
  rms 0.0004 at both expected marker positions) — the capture is a
  head-trimmed replay (player entered ~2.5 s into the track).
- **Playback-vs-capture clock skew ≈ +0.95 Hz @ 1 kHz (~950 ppm)**: kills
  sine-template correlation (2 s marker corr destroyed; beep corr weak).
  Hence v1/v2 sine-correlation segmenters failed; v3 is burst-envelope +
  affine-model based.
- Mic array dominated by **240 Hz fan hum**; speech-band (300–4 kHz, excl.
  the beep band) share of energy in clip regions 0.6–0.9 → speech IS present,
  but waveform-shape correlation with the originals is weak (q ≈ 0.016 at the
  true position vs 0.0006–0.007 at random positions; 3–28× above baseline).
- Beep-anchor affine fit: **12/13 stable ~1 kHz bursts matched the manifest
  schedule; after refit residuals −9.3..+4.8 ms (std 3.9 ms), b = 1.000002**
  (no stalls, no drift). This pins every cut to ≤ ±9 ms — 5× inside the
  50 ms spec gate.

## 3. Segmentation (spec step 4)
Schedule-first cutting: `clip start = t0 + b·(track_pos + 1.7)` with the
beep-fit t0/b; ±150 ms margin; verified per clip by normalized waveform
xcorr vs the original flac (near-margin peak vs 100–150 ms far-baseline,
2× rule). Counts:

| aligned measure | count |
|---|---|
| content-verified lag ≤ 50 ms | **5/100** |
| verified-but-lag > 50 ms | **0** |
| schedule-cut-only (verification channel-limited, q2 ≈ far-baseline) | 95 |
| missing/truncated clips | **0** |
| success criterion (spec: ≥90 clips aligned; cuts ≤ ±9 ms by beep fit) | **MET** |

Content-level verification is channel-limited, not cut-limited: measured
q2 (0.005–0.092) vs far-baseline (0.006–0.11) overlap; the 5 verified clips
all landed within 50 ms. Schedule precision is the operative guarantee
(beep residual std 3.9 ms + monotone beeps from clip 10 to clip 94).

## 4. Scoring + detector-layer metrics (spec step 5, first bullet)
200/200 scored (100 laundered + 100 clean, frozen AASIST-L). Environment
note: NumPy pinned to 1.26.4 this session (2.5.4 had broken
numba/librosa → run_inference silently produced 0 rows; now fixed).

| metric (n=50/50) | clean | laundered |
|---|---|---|
| FAR @ dev thr (−0.9449426) | 12% (6/50) [4–22%] | **56% (28/50) [42–70%]** |
| FAR @ eval thr (1.7635) | 4% (2/50) | 2% (1/50) |
| FRR @ dev thr | 0% (0/50) | **48% (24/50) [34–62%]** |
| FRR @ eval thr | 0% | **100% (50/50)** |
| AUC (bona-fide-higher direction) | 0.9996 | **0.4992** |
| EER / thr | 2% @ 2.73 | **50% @ −0.567** |

Paired per-clip score shift (laundered − clean): median **−3.20** overall,
q10 −9.09 / q90 +6.81 — spoofs shift UP (per-family medians +0.75..+9.63)
and bona fide shift DOWN, both toward a common middle: the detector COLLAPSES
TO CHANCE on C1 audio (AUC 0.4992; spoof/bonafide score distributions
overlap). The 56% FAR is the honest reading at the dev threshold only
because bona fide are dragged down too (FRR 48%).

Per-attack at the dev threshold (each family n=4, A18 n=3):

| attack | FAR dev (clean) | FAR dev (laundered) | median shift |
|---|---|---|---|
| A07 | 1/4 | 3/4 | +4.57 |
| A08 | 0/4 | 2/4 | +9.33 |
| A09 | 0/4 | 2/4 | +9.63 |
| A10 | 1/4 | 3/4 | +0.75 |
| A11 | 0/4 | 2/4 | +2.77 |
| A12 | 1/4 | 1/4 | +2.08 |
| A13 | 0/4 | 2/4 | +2.94 |
| A14 | 0/4 | **4/4** | +8.86 |
| A15 | 0/4 | 0/4 | −0.36 |
| A16 | 0/4 | 2/4 | +6.06 |
| A17 | 1/4 | 2/4 | +5.16 |
| A18 | 2/3 | 3/3 | +0.92 |
| A19 | 0/3 | 2/3 | +3.53 |

## 5. A8 end-to-end + crypto check (spec step 5, second/third bullets)
Crypto check (final): **100/100 laundered clips REJECT** against their clean
originals' records (holder proven on laundered audio with the clean handoff;
verify_fully_v4 vs the clean record). Zero ACCEPTs, zero holder refusals.
Clean-spoof anchor enrollment: 50/50 issued with --allow-spoof-enrollment
(the anchor exists by hypothesis; the check tests the record<->file hash
binding, not the gate). This is the THREAT_MODEL A8 crypto-layer prediction
("REJECT vs original record") — **CONFIRMED at n=100**.

A8 end-to-end (fresh enrollment path, issuer at DET_THRESHOLD = -0.9449426):
first pass ran the issuer at its default 1.7635 (env not inherited through
the runner) — caught by reading refusal reasons and re-run at the dev
threshold. Final counts:

| stage | n |
|---|---|
| issuer REFUSED (spoof decision at dev thr) | 22/50 |
| issuer SIGNED | 28/50 |
| holder proof (wide aligned policy) | 28/28 proved |
| verify_fully_v4 vs the laundered clip's own record | **28/28 FULL-VERIFY ACCEPT** |

End-to-end A8 acceptance = **28/50 (56%)** at the dev threshold — exactly the
detector-layer FAR on the same laundered set (28/50); the issuer gate is the
only thing between laundering and a fully-valid record.

## 6. THREAT_MODEL A8 disposition

Hypothesis row (THREAT_MODEL.md A8): detector "low⚠️ — laundered audio is
out-of-distribution in both directions (unreliable either way)"; crypto
"REJECT✓ vs original record"; fresh enrollment "ACCEPT⚠️". Measured U1:

| layer | predicted | measured |
|---|---|---|
| detector, spoof content | OOD, unreliable | detector collapses toward chance (AUC 0.9996→0.4992): spoof scores rise, bona fide fall into overlap; FAR 12%→56% at dev |
| detector, bona fide control | OOD, unreliable | replay **drops** bonafide: FRR 0%→48% (dev), AUC 0.9996→0.50, EER 2%→50% |
| crypto vs original record | REJECT | **100/100 REJECT** ✓ |
| fresh enrollment → full e2e | ACCEPT⚠️ | **28/50 signed → 28/28 FULL-VERIFY ACCEPT** ✓ |

**A8 = CONFIRMED on C1** (sharpened: under C1 the DETECTOR LAYER COLLAPSES
TO CHANCE — AUC 0.4992, spoof scores rising and bona fide scores falling
toward a common middle — so 56% of laundered spoofs pass the gate; laundering
succeeds end-to-end at 56% via fresh enrollment, and the only defense against
it is the record<->file binding, which rejects 100/100 vs the original
record). Under C2 all scores shift DOWN: FAR is low (1/50) only because FRR
is 68% — at C2's own EER point (22%) 22% of EACH class is misclassified. Suggested THREAT_MODEL edit (not applied):
A8 row "design only, no run" → "measured U1 (2026-11-09): e2e acceptance
28/50 at dev thr; crypto REJECT 100/100".


## 7. C2 — phone voice memo, ~1 m (user-executed capture, 2026-11-09)

Setup: quiet bedroom, laptop speakers -> phone voice memo ~1 m away; one
continuous recording (AAC 48 kHz mono, 555.93 s, decoded to
eval/u1/raw/c2_phone_16k.wav). Playback launched start-to-end from this
session (ffplay, whole file incl. start marker); the memo began ~0.7 s after
playback start (t0 = -0.694), so the FULL track was captured — the user's
"didn't complete" concern checked and REFUTED (beeps matched through clip 99,
b = 0.999984; nothing missing).

Segmentation (segment3.py, C2 dir): affine fit 101/112 stable bursts
(one outlier burst inflates reported resid std 81.9 ms; trimmed evidence:
content-vs-original agreement across ALL 100 clips <= 43 ms); channel much
cleaner than C1 (content q at schedule 0.36-0.46 vs 0.05-0.11). Content-
verified lag <= 50 ms: 2/100 (2x-far-baseline rule) + 98 schedule-cut;
verified-but->50 ms: 0; missing: 0.

Scoring: 100 laundered scored fresh; 100 clean reused from the C1 cache
(identical flac files, identical model).

| metric (n=50/50) | clean | C1 laundered (laptop mic) | C2 laundered (phone, 1 m) |
|---|---|---|---|
| FAR @ dev thr | 12% (6/50) | **56% (28/50)** | **2% (1/50)** |
| FAR @ eval thr | 4% | 2% | 0% |
| FRR @ dev thr | 0% | 48% (24/50) | **68% (34/50)** |
| FRR @ eval thr | 0% | 100% | 96% |
| AUC (bona-higher) | 0.9996 | 0.4992 | 0.837 |
| EER / thr | 2% @ 2.73 | 50% @ -0.567 | 22% @ -3.256 |
| paired score shift median | 0 | -3.20 (bona-driven) | **-4.21** |

Per-attack FAR @ dev (C2): A07 1/4; every other family 0/4 (0/3 A18/A19).

**C2 interpretation:** the consumer voice-memo path (phone AGC, mic DSP, AAC
encode at 48 kHz, loudspeaker rolloff at 1 m) shifts ALL scores DOWN hard.
The low FAR (1/50) is NOT evidence of robustness — it is the same collapse
seen from the other side: FRR 68% at dev, and at C2's own EER operating
point (22%) 22% of each class is misclassified (AUC 0.837 vs 0.4992 in C1) 
both laundered classes sit below the old thresholds; the detector is not
reliable on laundered audio in either channel. Physical laundering
A8 CONFIRMED on the own-device speaker->mic path (C1, same-room near-field);
on the phone path (C2) the attack FAILS at the detector layer for every
attack family. Both C2 rows are single-capture trials at one distance/volume;
the paper claims C2 as a supplementary condition, not a robustness law.

## 8. Files
- eval/u1/track_manifest.json (C1 + C2 blocks), eval/u1/u1_scores.json,
  u1_scores_c2.json, u1_metrics.json, u1_metrics_c2.json
- eval/u1/C1_segments/ (100), eval/u1/C2_segments/ (100)
- eval/u1/raw/ (2 C1 takes, c2_phone.mp4 + decoded wav)
- eval/u1/a8_state.json, a8_counts.json, a8_run*.log
- eval/u1/segment_diag.py, segment2.py, segment3.py, probe_pos.py,
  score_u1.py, run_a8_e2e.py, u1_metrics.py

## 9. C1b attempt (2026-11-10): cleaner-conditions rerun — CHANNEL FAILURE (stopped)

Setup per spec: fan off / volume 70-80% / mic enhancements off / AC power (user-confirmed,
eval/u1/C1b/setup_note.md). Level test PASSED its gates (peak -3.3 dBFS, no clipping;
noise floor -85.2 dBFS; 240 Hz hum -7.5 dB below speech band, effectively gone).

Two full takes recorded (eval/u1/C1b/raw/C1b_1.wav, C1b_2.wav; 562 s each, 48 kHz,
recording started before playback, full track start-to-end). Both takes are non-silent
(RMS 0.0177 / 0.0094) and speech content is captured, but BOTH fail segmentation beyond
the spec's >=90-clip criterion. Measured root causes, in order found:

1. TONE SUPPRESSION: the mic chain at 70-80% volume suppresses sustained 1 kHz tones.
   Neither take contains the 2 s start/end markers (1 kHz-band envelope never sustains
   >=0.9 s at 15% of max; level test also lacks a sustained block) nor ANY of the 100
   200 ms sync beeps (take 1: 8 tone-like bursts total in 562 s, deltas inconsistent
   with the beep grid; take 2: 11). C1 at 40% volume preserved 12/13 stable bursts —
   the higher volume triggers the array's adaptive stationary-tone/noise suppression.
   "Cleaner conditions" made marker capture strictly WORSE than C1.
2. TIMELINE DEVIATION: even where 30 s envelope windows correlate (q 0.16-0.40), the
   local capture-vs-playback lag is non-affine: e.g. track 122 s matched at lag 146.0 s
   but track 142 s at lag 163.7 s (local rate swings ~+-20%). No (t0, b) model holds,
   so no schedule cut can be placed at the spec's precision.
3. Anchor alternatives measured and rejected on take 1: generic envelope chaining
   (resid std 1.88 s, speech self-similarity), gap-onset detection (101 onsets found at
   0.12x p90 but only 9/100 within 150 ms of the schedule), content-xcorr search
   (peaks non-discriminative, offsets +-3 s, q == second peak).

Segmentation code: eval/u1/C1b/mask_markers.py (marker masking; unused — markers absent)
and eval/u1/C1b/segment3b.py (envelope-affine variant of segment3 with segment3's cut/
verify reused; failed per above). C1 rows remain untouched; C1 sections of this report
are unchanged.

**Retake at ~40% volume (C1b_1r.wav, user-approved; fan off / enhancements off / AC
unchanged) — also failed.** 1 kHz-band burst census (900–1100 Hz, 50 ms envelope,
runs > 15% of max), same method on every file:

| file | dur | peak | bursts | beep-like (0.1–0.4 s) | ≥1.5 s (markers) |
|---|---|---|---|---|---|
| playback_48k.wav (reference) | 550.7 s | 0.0 dBFS | 130 | 110 | 2 (t=0, t=548.65) |
| C1 c1_capture.wav (44.1 kHz, fan on, ~40%) | 590.0 s | −2.8 | 77 | 33 | 0 |
| C1b_1 (70–80%) | 562.0 s | −2.9 | 18 | 5 | 0 |
| C1b_2 (70–80%) | 562.0 s | −3.4 | 28 | 13 | 0 |
| C1b_1r (~40%) | 562.0 s | −2.4 | 20 | 6 | 0 |

Lowering the volume back to C1's level did not restore the beeps, so volume is ruled out;
a 44.1 kHz A/B probe (raw/ab441.wav) ruled out sample rate as well. The remaining
measured difference from C1 is the fan: C1 had 240 Hz fan hum, and every C1b take is
fan-off. One hypothesis (untested) is that the array's adaptive suppressor treats a
sustained tone in an otherwise quiet room as noise. Status: STOPPED, no C1b metrics.
Also blocking at stop time (2026-11-10 ~22:50): `torch` and `soundfile` are no longer
installed in the Python 3.12 that ran U1/U3 (only numpy/scipy remain), and C: is at
100% (4.2 GB free), so segment3/score_u1/A8 cannot run until the env is restored.
