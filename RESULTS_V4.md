# RESULTS — v4 attack matrix (Part B: before/after + closures)

Measured 2026-11-04/05, harness eval/v4_attacks.py (resumable, append-only).
Data: eval/results_v4.csv (1,666 rows), state eval/v4_att_state.json. Pipeline
UNCHANGED code: issue_capture_record_v4 -> provenance_cli_v4 (holder) ->
verify_fully_v4 (incl. the 2b record-file binding check added 2026-11-04 after
the A3 pre-check exposed its absence). Threshold 1.7635419737 everywhere.
Seed-42 and seed-43 samples reused exactly; NO detector re-scoring of content
(frozen scores reused for S4).

## Headline BEFORE/AFTER

| attack | v3 S1 (measured) | v4 S1 (measured) | closed by | still open? |
|---|---|---|---|---|
| A1 substitution (sub+fresh proof, seed-44 subs) | 10/10 REJECT (cleanup; +11 earlier) | **9/9 REJECT** (limb mismatch at Part A' + 10/10 substitutes BLOCKED at enrollment) | C + record-file binding + enrollment gate | no |
| A4 metadata substitution (fabricated meta+salt, in-rule) | 10/10 ACCEPT ❌ | **9/9 REJECT** (metadata_commitment mismatch) | Change 1 (C) | no |
| A4' true metadata + OWN salt | n/a | **9/9 REJECT** | Change 1 (C preimage) | no |
| A5 detector-record forgery (det_decision flip) | 10/10 ACCEPT ❌ | **9/9 REJECT** (canonical digest) | Change 2 (signed attestation) | no |
| A6 within-window replay (no nonce) | 10/10 ACCEPT | **9/9 ACCEPT** (documented residual) | — | RESIDUAL (stated) |
| A6 fresh-nonce replay (--expect-nonce) | n/a | **9/9 REJECT** | Change 4 | no |
| A6 after-expiry (--now) | n/a | **9/9 REJECT** | Change 4 | no |
| enrollment of spoof (A7) | 10/10 records signed ❌ | **10/10 issuer refusals** (seed-44 spoof subs) | Change 3 | inherits detector errors |
| policy downgrade (wide proof -> strict verifier) | n/a | **9/9 REJECT** | verifier-chosen publics (Change 1b) | no |
| A2 re-encode: crypto vs clean record | 350/350 REJECT | **343/343 REJECT** (1 seed-43 file unenrollable) | hash binding (2b) | content-identity OPEN |
| A3 splice: crypto vs clean record | 450/450 REJECT | **441/441 REJECT** | hash binding (2b) | content-identity OPEN |
| A3 splice re-enrollment residual | 10/10 ACCEPT ❌ | **8/10 ACCEPT** + **2/10 REFUSED by the v4 detector gate** | Change 3 partially | content-identity OPEN |
| A8 laundering | design-only | not run | — | OPEN (physical) |

## Enrollment-gate counts (the detector becomes policy)

- Seed-42 bona fide: **9/10 enrolled; 1/10 refused = LA_E_8374049** (frozen
  score 1.448 < 1.7635) — exactly the predicted false-reject casualty.
- Seed-44 spoof substitutes: **10/10 refused** at enrollment (no proof possible).
- Seed-43 clean bona fide: **49/50 enrolled; 1/10 refused = LA_E_2805188**
  (another near-threshold genuine).
- 10-splice re-enrollment (file #1's 9 cells + file #2's 0.5/middle):
  **2/10 refused** (0.1_start score 1.392; 0.25_start score 0.487 — both
  correctly detected as spoof-topped), **8/10 enrolled and FULL-VERIFY ACCEPTED**
  — including splices whose spoof segment is placed late/far from the window's
  front (see RESULTS_CONTENT.md Verification: recency gradient). This is the
  measured A3 residual: v4's gate is exactly as strong as the detector.

## FIX_DESIGN hypothesis scoreboard (all confirmed; none refuted)

| hypothesis | status |
|---|---|
| A4 closed by C (fabricated metadata+salt, real limbs) | **CONFIRMED** 9/9 |
| A4' closed by C (true metadata, own salt) | **CONFIRMED** 9/9 |
| A5 neutralized by signed attestation | **CONFIRMED** 9/9 |
| A6: expiry+nonce close cross-time replay; within-window replay remains | **CONFIRMED** (9 REJECT fresh-nonce, 9 REJECT expired, 9 ACCEPT within-window — as stated) |
| A7 closed by enrollment refusal | **CONFIRMED** 10/10 spoof refusals (+2/10 splice refusals) |
| Policy downgrade impossible (publics in the proof statement) | **CONFIRMED** 9/9 |
| A2/A3 crypto layers reject transformed content vs the clean record | **CONFIRMED** 343/343 + 441/441 |
| A2/A3 re-enrollment path open (content identity) | **CONFIRMED open** (8/10 splice re-enrollments ACCEPT) |

## Costs (medians; v3 numbers from results_binding/content logs)

| stage | v3 | v4 | note |
|---|---|---|---|
| enrollment (issuer) | ~767 ms (hash+sign only) | 3,721 ms | v4 adds the DETECTOR + witness calc at enrollment — by design |
| proof (holder/CLI) | ~2.8 s detect + ~1.0 s prove per proof | **686–936 ms** | v4's holder proves WITHOUT the detector (already attested at enrollment) — per-proof cost collapsed |
| verify (FV) | ~705 ms | 639 ms | +C/policy/freshness checks ≈ −9% vs v3 (one process spawn more, same shape) |
| fabricated-attempt prove (attacker, no holder) | n/a | ~270–400 ms | fullProve only |

## Notes

- The 2b record-file binding check was added to verify_fully_v4 BEFORE this
  run surfaced any wrong-accept (found in pre-check design walk-through;
  f7 regression test added; FIX_DESIGN updated 2026-11-04).
- A6-within-window ACCEPT (9/9) is the documented residual: expiry+nonce close
  cross-time/cross-session replay; same-window replay without an expected
  nonce remains accepted by design.
- A2's 343 = 49 enrolled x 7 conditions (LA_E_2805188's transforms were not
  measurable against a record — its enrollment was refused); A3's 441 = 49 x 9
  for the same reason. S4 rows = frozen per-file scores (no re-scoring).
- All runs RAM-gated (1,500 MB env; several pressure stops + one harness reap
  recovered by resume); runtime_ms for these rows recovered from measurement
  log mtimes after a CSV-writer kwarg bug left the column empty (fixed in the
  harness for future runs).


## Fair cost table (apples-to-apples; added 2026-11-05)

Detection cost is included wherever it runs (v3: in every demo/prove run;
v4: ONLY in enrollment). v3 medians from 870 frozen run records + the issuer
timing (767 ms); v4 medians from 10 warm end-to-end runs (n=10 per stage).

| quantity | v3 | v4 | note |
|---|---|---|---|
| **TOTAL e2e per file (detect + prove + verify + signing)** | **4.19 s + 0.77 s = 4.96 s** | **7.02 s** | v4 = enroll 5.93 + prove 0.58 + verify 0.50 (medians); +42%/file for the commitment + policy machinery |
| per-stage: detect (AASIST-L) | 2,824 ms (in demo) | 2.8–3.7 s equivalent (inside enroll) | identical detector |
| per-stage: witness + prove | 1,016 ms demo-prove (incl. detect) | 580 ms holder prove (no detector) | v4's per-proof cost collapsed |
| per-stage: verify | 705 ms (FV) | 504 ms (FV v4) | +C/policy/freshness, still cheaper |
| per-stage: issuer sign | 767 ms | (inside enroll) | |
| proof.json size | 855 B | 717 B (publics separate) | snarkjs 8 field elements |
| public.json size | 106 B (4 publics) | 264 B (16 publics) | policy statements are public by design |
| record size | 683 B (v1 format) | 1,052 B (v2 record) | +commitment + attestation + expiry + flagged |
| constraints (r1cs) | 458 | 1,426 | Poseidon(6) = 968 |
| peak memory — proving (node) | ≤ 52 MB | ≤ 55 MB | holder/FV have NO detector |
| peak memory — detector (python, at enrollment) | ~908–1,050 MB | same (one detector run per file) | torch dominates |

## Enrollment-gate casualty counts (both samples)

| sample | genuine files | enrolled | refused | notes |
|---|---|---|---|---|
| seed-42 (10 bona + 10 spoof + 10 seed-44 substitutes) | 10 | **9** | **1** | refused = LA_E_8374049 (frozen score 1.448, predicted); all 10 spoof substitutes + 10 seed-44 a1sub substitutes refused |
| seed-43 (50 bona + 50 spoof) | 50 | **49** | **1** | refused = LA_E_2805188 |
| A3re 10-splice re-enrollment | 10 splices | 8 | 2 | refused the two low-score splices (1.392 / 0.487); the 8 accepted confirm the content-identity residual |

Aggregate: genuine-file refusal rate = 2/60 (3.3% of sampled genuine, both
at/near threshold); spoof/splice enrollment refusal = 12/20 tested spoof-ish
content — the gate's behavior is exactly the detector's.
