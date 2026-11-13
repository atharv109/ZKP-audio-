# RESULTS — binding-attack measurement (A1/A4/A5/A6/A7 × S1–S4)

Measured 2026-11-03 on the UNCHANGED pipeline (real commands only: `demo_workflow.js`,
`provenance_cli.js`, `issue_capture_record.js`, `verify_media.js` (via Part A),
`verify_fully.js`), by `eval/run_binding_eval.py` + supplement
(`eval/a1_supplement.py` / `eval/append_supplement_rows.py`). Full per-run data:
`eval/results_binding.csv` (203 data rows), cost detail: `eval/run_costs.json`.

Sample (seed 42, `eval/sample_manifest.csv`): 10 bona fide + 10 spoof, spoof
files spanning **10 distinct attack IDs (A07–A18)**; A12/A16/A19 not represented
(protocol has 13 attack types; 10 slots). One genuine sample (`LA_E_8374049`)
has a frozen score (1.448) below both thresholds — see Surprises.

---

## How S1–S4 were measured

- **S1 (full pipeline)** = `verify_fully.js` exit code + `RESULT : FULL-VERIFY …` line.
- **S2 (hash + Ed25519 record only)** = Part B outcome **of the same run**.
  Separation method (important, because `verify_fully.js` buffers its check
  lines — the `[ OK ] part A` line only appears in ACCEPT output): Part A
  failed ⇔ the RESULT reason starts with `existing-proof verification rejected`;
  any **other** reason means Part A passed and the verdict belongs to Part B.
  Every run in this eval presented a proof valid for the presented file, so
  every S2 verdict is a genuine Part B outcome.
- **S3 (local hash registry)** = `eval/s3_registry.py` (`{file_sha256, metadata,
  issued_at}`; ACCEPT iff hash enrolled). Enrolled entries carry the demo
  metadata; lookups are direct hash comparisons.
- **S4 (detector only)** = frozen AASIST-L score read from
  `final_outputs/minnah_comparison/dataset_acquisition/merged_scores.csv` (no
  re-scoring; AASIST was NOT rerun in this step) with verdict = bonafide iff
  `score >= threshold`, at **1.7635419737** (primary, full-eval EER point) and
  **1.81681** `--threshold` (code default). Both threshold verdicts appear in
  each row's reason string.

---

## Headline counts (n per cell; full per-file rows in the CSV)

| Attack | S1 full (FV) | S2 hash+record | S3 hash registry | S4 detector |
|---|---|---|---|---|
| **A1** substitution | **11/11 REJECT** ✅ | **11/11 REJECT** | 10/10 ACCEPT (enrolled substitute) + **1/1 REJECT (supplementary unenrolled substitute)** | 10/10 spoof (substitute detected at both thresholds — but never consulted) |
| **A4** metadata substitution | **10/10 ACCEPT ❌** | **10/10 ACCEPT** | 10/10 ACCEPT (same file → hash match) | 9/10 bonafide, 1/10 spoof (false-reject file; **unchanged** vs enrollment — attack invisible to S4) |
| **A5** detector-record forgery | **10/10 ACCEPT ❌** | **10/10 ACCEPT** | 10/10 ACCEPT | **10/10 bonafide — 100% attacker-controlled; true scores all "spoof" (−1.93…−9.32)** |
| **A6** record replay | **10/10 ACCEPT** (expected; nothing checks `issued_at_utc`) | 10/10 ACCEPT | 10/10 ACCEPT | 9/10 bonafide + 1/10 false-reject file |
| **A7** spoof enrollment | **10/10 ACCEPT ❌** | **10/10 ACCEPT** | 10/10 ACCEPT (spoof hashes enrolled) | **10/10 spoof at both thresholds — the ONLY layer that correctly says "spoof"; ignored by S1–S3** |

Verify-run inventory: 61 `verify_fully.js` runs (A1 11, A4 10, A5 10, A6 10,
A7 10) → 122 S1/S2 rows; 51 S3 lookup rows; 51 S4 rows; 203 total.

## Hypothesis verdicts (each THREAT_MODEL §4/§5 hypothesis → CONFIRMED/REFUTED)

| THREAT_MODEL hypothesis | Result | Status |
|---|---|---|
| A1: full pipeline rejects substituted file (hash/record binding) | 11/11 REJECT — verbatim reason from the UTF-8 log: `record file_sha256 5e73db12…81fe6 != file 2ad62de3…b1517f — record is for a DIFFERENT file (or file altered)` | **CONFIRMED (MEASURED)** |
| A1 S3 scope: registry rejects *unenrolled* substitutes | supplementary unenrolled substitute (`LA_E_1000147`): REJECT | **CONFIRMED, scope narrowed** |
| A4: full pipeline wrongly ACCEPTs new proof w/ fabricated same-file metadata | 10/10 ACCEPT (exit 0) | **CONFIRMED — wrong-accept** |
| A5: no verifier output changes when `demo_result.json` is tampered | 10/10 verifier outputs byte-IDENTICAL vs untampered runs | **CONFIRMED** |
| A5 (S4): verdict follows the attacker's forged score | 10/10 "bonafide" (score 7.5) vs true scores all spoof | **CONFIRMED — fully exploitable** |
| A6: replay accepted; `issued_at_utc` never checked | 10/10 ACCEPT | **CONFIRMED** |
| A7: enrollment accepts spoofs (no decision gate) | 10/10 ACCEPT; exit-code/parseability only | **CONFIRMED — wrong-accept** |
| A7 (S4): detector would catch enrolled spoofs but is never consulted | 10/10 spoof at both thresholds; no layer consults it | **CONFIRMED** |
| S2-vs-S1: record-only vs full verdicts coincide | all 61 runs: Part A accepted, so S1 = S2 | **CONFIRMED** |

**Zero hypotheses refuted** — the pipeline is exactly as weak as THREAT_MODEL
predicted, plus one stronger finding (Surprise 1).

---

## Surprises

1. **A1×S3 measured artifact → stronger finding.** The main A1 substitute
   (LA_E_9394669) was itself enrolled (A7 infrastructure), so the registry
   ACCEPTed it 10/10 — i.e. the hash registry is blind not only to unenrolled
   substitution (hypothesis: confirmed by the 1/1 supplementary REJECT) but to
   **substitution between two enrolled files**. S3 defends strictly "was this
   exact byte-stream ever enrolled", nothing more.
2. **S4 false-reject of a genuine sample at both thresholds**:
   `LA_E_8374049` (frozen score 1.448 < 1.76354/1.81681) is predicted "spoof"
   by score alone. Irrelevant to the cryptographic cells, but it shows the
   detector-first (Minnah-style) gate rests on a noisy quantity — while the
   crypto pipeline doesn't gate on the detector at all (A7).
3. ** warm-cache effect:** first-ever detector run paid ~69 s
   (cold read of torch/model files); subsequent runs score in ~2.6–2.9 s.
4. **A5's exploitability is total**: a favorable forgery (score 7.5,
   decision "bonafide") makes the recorded layer claim a clean verdict while
   every true score is spoof (−1.93…−9.32). The proof and record artifacts
   stay untouched; the tampered copy is a manifest no verifier consumes —
   that is the measured point.

---

## Costs (this run)

| Quantity | Mean | Median | n | Note |
|---|---|---|---|---|
| `verify_fully.js` (S1/S2 run) | 692–702 ms | 686–706 ms | 50 | node peak ≤ 367 MB |
| `issue_capture_record.js` | 750 ms | 767 ms | 20 | mtime-derived |
| enrollment prove (demo_workflow, warm) | 4,760 ms | — | 19 | stages: detect 2,907 / prove 894 / verify 335 ms; first run of session 6.5 s (6,471 ms), first-ever ~69 s ( cold read) |
| A4 new-proof run (provenance_cli) | 6,145 ms | — | 10 | includes a detector pass |
| **Detector memory (torch)** | **908 MB** | — | 1 probe | warm-cache prove run; sampler name-gap fix (`python3.12.exe`) applied post-run, probe in `run_costs.json` |
| Total wall for 203 measured rows | 233.5 s | — | — | sequential, RAM-gate-checked |

`demo_result.json` stage timings come from the pipeline's own
`performance.now()`; wrapper wall times include ~0.3–0.7 s spawn overhead.

---

## Notes & limits

- Sequential; fresh dirs; env-overridable RAM gate (default 2,000 MB; this run
  used 1,500 MB after the measured `MemoryError()` at 1.84 GB free earlier the
  same day); nothing overwritten — crashed attempts preserved as
  `outputs/v3/eval_binding_crashed_*` and `eval/*_crashed_*` for forensics.
- A5's verify runs are deliberately command-identical to A7's (the tampered
  manifest is adjacent-but-unconsumed); the cell demonstrates invisibility +
  S4-forgery, not a second attack surface.
- A1 supplementary file (`LA_E_1000147`) was proven + recorded + verified but
  deliberately NOT enrolled in S3 (that is the point of the unenrolled case);
  its S4 score is the frozen merged_scores value (−1.303891 → spoof at both).
- Thresholds 1.7635419737 and 1.81681 agreed for every sampled file; both are
  recorded in each S4 row's reason string.