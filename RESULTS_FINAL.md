# RESULTS_FINAL — final paper verification

Sections: 1 full-eval rates · 2 official dev EER · 3 policy count · 4 C1b status · 5 anonymized artifact.

computed 2026-11-12; no pipeline changes; scripts under `eval/final/`.

Interpreter used for every command below: `python` (Python 3.12.10, user
site-packages, imports torch/soundfile/numpy/pandas OK). Machine-readable
copies of both computations: `eval/final/rates_json.json`,
`eval/final/eer_json.json`.

## 1. Full-eval error rates at dev threshold

Score source: `final_outputs/minnah_comparison/dataset_acquisition/merged_scores.csv`
(10,130,341 bytes, mtime 2026-10-11 12:57; sha256 `56375d2fcfff90ededd05ec795225b6548f2fcf23af5610ab66e5604342d91b4`).
This is the ONLY file named `merged_scores.csv` in the repo. Row count
71237 data rows (+1 header), 71237 unique utterance IDs — the full ASVspoof
2019 LA eval corpus. Cross-check performed by the script below against the
OFFICIAL CM eval protocol
(`ASVspoof2019_LA_cm_protocols\ASVspoof2019.LA.cm.eval.trl.txt`):
63,882 spoof + 7,355 bonafide = 71,237; 0 utterances missing, 0 extra, 0
duplicate IDs, 0 label mismatches between the CSV label column and the
official protocol labels. (The CSV's `prediction` column holds `score-only`
tags and the `correct` column is empty; both were ignored — labels and attack
tags come exclusively from the official protocol.)

Label/attack convention (verified, not guessed): scores are raw bonafide
logits — higher = more bonafide (matches `eval/u3/u3_metrics.py` `rate()`:
spoof ACCEPT uses `score >= thr`, bona-fide REJECT uses `score < thr`; the
protocol line format is `speaker utt - Axx spoof/bonafide`, so field 4 gives
the attack tag). The threshold −0.9449426 originates from
`eval/dev_metrics.json` (`"threshold_at_eer": -0.944942612244898`), the
dev-optimal EER point for the frozen AASIST-L model on eval/dev_scores.json
(see §2).

Command (run; output below reproduced verbatim from `eval/final/rates_json.json`):

```
python eval/final/compute_rates.py --scores final_outputs/minnah_comparison/dataset_acquisition/merged_scores.csv --protocol ASVspoof2019_LA_cm_protocols/ASVspoof2019.LA.cm.eval.trl.txt --threshold -0.944942612244898 --json-out eval/final/rates_json.json
```

Pooled (no score equal to the threshold exists, so >= and > give identical counts):

- spoof-accept rate: **7,115 / 63,882 (11.14%)**
- bona-fide-reject rate: **7 / 7,355 (0.10%)**

Per-attack spoof-accept rate, attacks A07–A19 (n = 4,914 utterances each):

| attack | spoof-accept @ −0.9449426 |
|---|---|
| A07 | 950 / 4,914 (19.33%) |
| A08 | 22 / 4,914 (0.45%) |
| A09 | 0 / 4,914 (0.00%) |
| A10 | 2,443 / 4,914 (49.72%) |
| A11 | 14 / 4,914 (0.28%) |
| A12 | 996 / 4,914 (20.27%) |
| A13 | 70 / 4,914 (1.42%) |
| A14 | 0 / 4,914 (0.00%) |
| A15 | 298 / 4,914 (6.06%) |
| A16 | 119 / 4,914 (2.42%) |
| A17 | 715 / 4,914 (14.55%) |
| A18 | 1,318 / 4,914 (26.82%) |
| A19 | 170 / 4,914 (3.46%) |

**Comparison with RESULTS_POLICY.md §8: CONFIRMED.** The quoted "11.14% /
0.10%" reproduces exactly (7,115 / 63,882 spoof-accept; 7 / 7,355
bona-fide-reject), and every per-attack accept count in RESULTS_POLICY §8 /
RESULTS_U2 §6 (950, 22, 0, 2443, 14, 996, 70, 0, 298, 119, 715, 1318, 170 at
n = 4,914) matches this recomputation.

## 2. Which dev EER is official

Command (run; output reproduced from `eval/final/eer_json.json`):

```
python eval/final/compute_eer.py --scores eval/dev_scores.json --labels eval/dev_labels.csv --json-out eval/final/eer_json.json
```

Dev score source: `eval/dev_scores.json` (691,071 bytes, sha256
`d167de94993f23e9...`, 24,844 entries = 2,548 bona fide + 22,296 spoof per
`eval/dev_labels.csv` — 100% of the official CM dev protocol). Labels from
`eval/dev_labels.csv`. n_bonafide=2548 n_spoof=22296. No missing utterances.

Recomputed, three methods (bona-fide-higher direction; FAR = (spoof >= t),
FRR = (bona < t)):

| method | dev EER | threshold |
|---|---|---|
| A. discrete point search (min \|FAR−FRR\| over observed scores; identical to `eval/u3/u3_metrics.py::eer_point`) | 0.510753% | −0.947072 |
| B. linear interpolation between the two adjacent ROC points bracketing FAR=FRR | **0.510204% @ FAR=FRR** | **−0.944942612244898** |
| C. ROC curve, scipy interp1d + brentq root of FRR(FAR)−FAR | 0.510204% | (continuous crossing) |

AUC (bona-higher, ties = 0.5): 0.9996414024747102.

**Diagnosis of the U2/U3 discrepancy.** Both RESULTS_U2.md (dev EER 0.5102% @
−0.9449426) and RESULTS_U3.md (D1 row: 0.5108% @ −0.947072) were computed
from the SAME dev score file — `eval/dev_scores.json` (both quote 2,548 bona
+ 22,296 spoof, and `eval/dev_metrics.json` records `"scores_source": "eval/
dev_scores.json"` with exactly both value pairs in one file: `eer_pooled_
interpolated` = 0.510204% @ −0.9449426 and `eer_bisection` = 0.510753% @
−0.947072). The difference is purely the EER/threshold extraction method:

- **U2 (0.5102% @ −0.9449426)** linearly interpolates between the two
  adjacent observed-score operating points that bracket the continuous
  FAR = FRR crossing (methods B and C above, which agree to 13 significant
  digits).
- **U3 (0.5108% @ −0.947072)** reports the single observed score minimizing
  |FAR − FRR| (a discrete search equivalent to a bisection that stops at the
  score-step discontinuity). At that point FAR = 0.511302% and FRR =
  0.510204% are NOT equal; the 0.5108% is the midpoint of an unequal pair,
  so it is not a true equal-error point. No interpolation or tie-handling
  difference in the data is involved — the same 24,844 scores produce both.

**Official value for the paper: dev EER = 0.5102% at threshold
−0.944942612244898 (quote −0.9449426), attributed to RESULTS_U2.md Part 1**
and `eval/dev_metrics.json` (`eer_pooled_interpolated`/
`threshold_at_eer`). Reasons: (1) it is the exact FAR = FRR crossing,
confirmed by two independent methods (B, C), whereas the U3 number is the
midpoint of unequal FAR/FRR at a discretely-observed score; (2) −0.9449426
is the operating point actually deployed by every downstream measurement the
paper quotes (RESULTS_POLICY §8, RESULTS_U2 §6, the U1/U2 enrollment-gate
runs and this document's §1), so quoting a different EER threshold alongside
them would be internally inconsistent; (3) the two candidates differ by only
0.0006 percentage points, but one must be quoted. RESULTS_U3's 0.5108% row
should be footnoted as the same-dev-file discrete-search variant, not used.

(RESULTS_U3's other thresholds are per-detector values for D2/D3 and are out
of scope here.)

## 3. Policy-experiment count

Source: `eval/policy_exp_results.csv` (verdict column: `actual`).

- ACCEPT rows: **4** — cases **1, 2, 3, 6** (CSV lines 2, 3, 4, 7).
- All other cases (4, 5, 7, 8, 9) are `REFUSAL(exit 1)`.

`RESULTS_POLICY.md` was checked on 2026-11-12: its prose (line 28) already
reads "holder proved **4** accepting policies (cases 1, 2, 3, 6 — mean 695 /
median 708 ms), all verified", and its accept table marks exactly cases
1, 2, 3, 6. Prose and table already agree with the CSV — the earlier "5
accepting policies" wording was already corrected (Nov 9 fix). **No edit
was needed or made today**, and no inline correction note was added since
there is no remaining "5" to annotate.

## 4. C1b — what is left (audit 2026-11-12, claims verified on disk)

**Verdict: C1b not finished** — three beep-less takes + one 40% retake are
on disk with a channel-failure write-up in `RESULTS_U1.md` §9 ("STOPPED,
no C1b metrics"); the fan-ON hypothesis is untested; none of the four
requested deliverables (side-by-side table, C1-vs-C1b noise/SNR
comparison, take-to-take agreement, C1b A8 count) exist.

- [ ] **Decide + run the fan-ON A/B probe** (root cause still untested).
      Capture-path probe WAVs exist (`eval/u1/C1b/probe_shared.wav`,
      `probe_exclusive.wav`, `probe_wdmks.wav`, 22.6 s each, run after §9
      was written) but their census results were never persisted anywhere.
      Blocker: **user decision** — fan-ON probe was awaiting approval when
      the 2026-11-10 session ended (`raw_probe.py` is ready; each probe
      capture ≈ 23 s + analysis).
- [ ] **Record 2 fan-ON takes** (C1 condition: 240 Hz fan ON, all else per
      `setup_note.md` checklist) if the A/B confirms the hypothesis.
      Time: ≈ 10 min per take — documented from 2026-11-10 mtime deltas
      (level test 21:47 → C1b_1 21:56 → C1b_2 22:06 → C1b_1r 22:30), so
      2 takes ≈ 20 min.
- [ ] **Segment the takes.** Scripts exist (`segment3.py` via
      `mask_markers.py`, `segment3b.py` envelope-affine); take-1 fallback
      already wandered once (99/100 matched, lag range −3881..+3848 ms,
      resid std 1876.7 ms, 6/100 content-verified —
      `eval/u1/C1b/segment_C1b_1.log`). Time: **estimate unavailable on
      disk** (the only C1b-cycle anchor, 22:09→22:32, bundles script
      writing + refit + retake + §9 write-up).
- [ ] **Restore the Python env + free disk.** RESULTS_U1.md §9 documents,
      at stop time (2026-11-10 ~22:50): `torch` and `soundfile` missing
      from the Python 3.12 that ran U1/U3 (numpy/scipy remained) and C:
      at 100% (4.2 GB free). Until restored, scoring and A8 cannot run.
      (Note: env was restored for the 2026-11-12 re-checks in §1–§2;
      re-verify disk space before recording.)
- [ ] **Score 200 C1b clips + detector metrics** (frozen AASIST-L) → the
      C1b-1 / C1b-2 columns. Time: estimate unavailable on disk.
- [ ] **Run A8 end-to-end + crypto check for C1b** (the 28/50 figure in
      RESULTS_U1.md §5 is C1 only).
      Time: estimate unavailable on disk.
- [ ] **Fill RESULTS_U1.md §9 (or successor) with the four deliverables:**
      (i) side-by-side Clean | C1 | C1b-1 | C1b-2 | C2; (ii) matched-units
      noise-floor / speech-band SNR for C1 vs C1b; (iii) take-to-take
      agreement; (iv) C1b A8 e2e count. Also persist the capture-path
      probe results (currently console-only).
- [ ] **Commit** — RESULTS_U1.md and all of eval/u1/ are untracked in git.

## 5. Anonymized artifact (packaging)

This section records the state of the anonymized review-artifact copy
(Sections 5/§5.1 added 2026-11-12 as part of the demo-asset follow-up that
made the Node test suite runnable from the artifact root alone).

- Shipped, in addition to the previously listed contents: a demo-only Ed25519
  issuer keypair (`demo_keys/`, generated 2026-11-12, see
  `demo_keys/DEMO_ONLY.md`), synthetic fixed-seed demo WAVs
  (`demo_audio/`, generator `demo_audio/make_demo_audio.py`), and the public
  AASIST-L checkpoint + official model code/config
  (`models/AASIST-L.pth`, `models/aasist/`), fetched from the official
  clovaai/aasist repo and sha-256-pinned in `outputs/v4/PINS.md`. No ASVspoof
  audio, no original issuer key material, no real recordings.
- Bootstrap plumbing: `scripts/demo_assets.js` routes every
  audio/issuer-key/weights path used by the `scripts/*.js` CLIs and the tests
  onto the shipped demo assets (env overrides documented in README §2a);
  `scripts/fetch_weights.py` fetches/verifies the checkpoint.
- Two small gaps found and restored in the artifact copy (plain source /
  compiled artifacts, no data): `audio_benchmark/detect_audio.py` (the
  single-file detector CLI that `scripts/issue_capture_record_v4.js` invokes)
  and `outputs/verification_key.json` (the v2 verification key used by
  `tests/verify_media.test.js` as its wrong-key fixture).
- Test-runner note: files that require `snarkjs` in-process need the same
  `after(() => process.exit(...))` hook `tests/verify_media.test.js` already
  documented (snarkjs worker threads keep the event loop alive — the runner
  would hang after a fully passing run). The hook was added to the other
  snarkjs-using test files verbatim; assertions unchanged.

### 5.1 Demo-asset test run (2026-11-12, follow-up)

What was added for this run:

1. **Demo issuer keys** — `demo_keys/issuer_private.pem` /
   `demo_keys/issuer_public.pem`, generated 2026-11-12 with Node
   `crypto.generateKeyPairSync('ed25519')` (PKCS#8 / SPKI PEM). Demo-only,
   never copied from anywhere (see `demo_keys/DEMO_ONLY.md`). The verifier
   pin in demo mode is the sha-256 of the shipped public key,
   `a4ced10b91eecb2869ed118fc425bd5c67e1ab38973557a2f99834b51ee8edba`,
   recorded in `outputs/v4/PINS.md` ("issuer pubkey pin (demo mode)").
2. **Demo audio** — `demo_audio/bon_00.wav` (2.0 s, byte-exact regeneration
   of the synthetic clip `outputs/v3/proof_v3.json` is bound to; sha
   `d77437d81d0608a3e459c2b9cd10fa969bb8ee4dc724bb7e101ec0521e7ab9fd`),
   `demo_audio/demo_la_e_1194478.wav` (5.0 s, seeds 1234; measures
   +5.498566 under the real AASIST-L checkpoint → BONAFIDE at the issuer
   threshold 1.7635419737), `demo_audio/demo_la_e_1000147.wav` (5.0 s, seed
   1234; measures −0.658498 → SPOOF at the same threshold). Generator:
   `demo_audio/make_demo_audio.py` (numpy + soundfile, fixed seeds; no
   recordings, no dataset audio); tuning search:
   `demo_audio/tune_demo_audio.py`.
3. **Weights** — `models/AASIST-L.pth` fetched from the OFFICIAL
   clovaai/aasist repo URL
   (`https://raw.githubusercontent.com/clovaai/aasist/main/models/weights/AASIST-L.pth`)
   via `scripts/fetch_weights.py`; sha-256
   `814331d088032bb4c3fa61cc014789eadeed464209dd094ab3a2dd6ffbdce27a`
   recorded in `outputs/v4/PINS.md` ("weights" entry). The file is
   byte-identical to the pre-existing local checkpoint (sha comparison at
   packaging time), so the documented offline fallback (`--from-local`)
   yields the same bytes. Official model code + config vendored to
   `models/aasist/` (LICENSE/NOTICE included).
4. **Per-file results** (all commands run from the artifact root as
   `NODE_PATH=<node_modules> node --test --test-timeout=60000
   tests/<file>`; summaries verbatim):

   | Test file | tests | pass | fail | skipped | duration (ms, runner-reported) |
   |---|---|---|---|---|---|
   | tests/provenance_v4_circuit.test.js | 6 | 6 | 0 | 0 | 2206.3417 |
   | tests/provenance_v4_policy_audit.test.js | 4 | 4 | 0 | 0 | 912.3783 |
   | tests/verify_media.test.js | 12 | 12 | 0 | 0 | 1457.9612 |
   | tests/issue_capture_record_v4.test.js | 8 | 8 | 0 | 0 | 22223.7912 |
   | tests/verify_media_v4.test.js | 8 | 8 | 0 | 0 | 10119.8156 |
   | tests/verify_fully_v4.test.js | 8 | 8 | 0 | 0 | 22300.0023 |
   | tests/demo_workflow_v4.test.js | 8 | 8 | 0 | 0 | 14285.6221 |
   | **total** | **54** | **54** | **0** | **0** | — |

   Every summary read `tests N / pass N / fail 0 / skipped 0` for its file;
   no test was skipped once the weights were fetched (the skip guards in
   `scripts/demo_assets.js` `assetsStatus()` never fired — status
   `{"ready":true,"missing":[]}`).

5. **Identifier re-scan** — full byte-level scan of every shipped file
   (255 files, including the new demo keys/docs, the generator scripts, the
   updated tests, and the binary WAVs read with a latin-1 byte-scan
   fallback), case-insensitive, for the identifier-pattern classes of
   the packaging checklist: the bare username substrings (2 variants: the
   username handle and its GitHub-handle variant), the home-directory path
   prefixes in every separator/casing style (drive-letter and slash forms of
   the machine's user-directory prefix), the cloud-sync folder name, the
   machine-name token (the `<MACHINE>` placeholder's plaintext), and the
   strict email regex
   (`[A-Za-z0-9._%+-]+` at-sign `[A-Za-z0-9.-]+` dot `tld-of-2-plus`). The
   literal pattern tokens themselves are deliberately NOT written into this
   file (quoting them would re-introduce the hits they are meant to catch);
   the exact token list is step 6 of the packaging instruction and was
   scanned with a script that mirrors it one-to-one. Result: **0 hits**
   after scrubbing the two regenerable `__pycache__` bytecode dirs that the
   detector runs had created on this machine (bytecode caches embed the
   absolute source path; re-created automatically by any Python run, so they
   must be cleared before packaging).
6. **Package** — the artifact copy is zipped (local file, nothing uploaded)
   as `artifact_anon.zip` next to the artifact folder on the Desktop, so the
   zip does not contain itself. Packaged size approximately 10 MB
   (10,012,658 bytes measured on the first packaging; the doc line itself,
   once packaged, shifts the exact byte count by a few compressed bytes on
   the re-packaged zip).
