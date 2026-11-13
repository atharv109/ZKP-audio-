# THREAT MODEL — zkp-media-provenance (audio pipeline)

Companion to `REPO_MAP.md`. Purpose: for the paper, characterize where the
pipeline (AASIST-L detector + SHA-256 + Groth16 metadata proof + Ed25519
signed record) **fails end to end** — what each artifact actually binds, what
a verifier is entitled to conclude, and an attack matrix with *hypothesized*
verdicts to be tested later. **No code was written or changed for this
document.** Every verdict below is a **HYPOTHESIS** unless marked MEASURED
(the A1-family repro of 2026-11-03).

---

## 1. Verifier's goal — one sentence

On `FULL-VERIFY ACCEPT`, the verifier concludes **only**: *"these exact file
bytes hash to the digest in a Groth16 proof whose private metadata satisfied
the five circuit rules, verified under the pinned trusted vkey, and a record
signing this same digest and this vkey generation carries a valid Ed25519
signature under the pinned issuer key."*

It must **NOT** conclude any of:

- "the speech is human / the audio is authentic" — the circuit contains no
  detector output and no acoustic content claim;
- "the metadata is true" — `device_id`, `timestamp`, `gps_*`, `sensor_score`
  are *supplied by whoever runs the CLI*; the circuit proves only rule
  compliance (`provenance_v3.circom:39-160`);
- "a trusted capture device produced this" — the issuer is SIMULATED and
  signs file hashes, not devices (`issue_capture_record.js:37-38` label);
- "the recorded detector score is genuine" — `demo_result.json` has no
  integrity mechanism and no verifier reads it.

This scoping is stated in the code itself: `verify_fully.js:49-53` (LABEL),
`verify_media.js:92-94` (acceptance wording), `provenance_cli.js:246-251`
(verdict text), `demo_result.json` `verdict`/`disclaimer` fields.

---

## 2. What each artifact binds (from the code; file:line citations)

| Artifact | Fields covered | Binding mechanism | What is NOT bound |
|---|---|---|---|
| **`capture_record.json`** (Ed25519 record) | `record_version`, `record_type`, `file_sha256`, `vkey_sha256`, `issued_at_utc`, `issuer_label` — signed as one canonical `\n`-joined string (`issue_capture_record.js:40-50`, fields built at `:72-79`, signed at `:88`). Verifier rebuilds the canonical string, checks its digest equals `canonical_sha256` (`verify_fully.js:132-135`), then Ed25519-verifies under the **pinned** issuer pubkey (`:43-44, :140-144`). Verifier additionally re-checks `file_sha256` == the audio on disk (`:149-151`) and `vkey_sha256` == the trusted vkey digest (`:153-155`). | Ed25519 signature over field values; file/vkey identity re-checks | **No proof identity** (record never names any proof), **no metadata values** (none of the 5 circuit inputs appear), **no session/scope nonce**, `issued_at_utc` informational only (no freshness check anywhere), **no acoustic content**, **no detector output** |
| **`proof.json` / `public.json`** (Groth16) | Public signals `[valid, media_hash_hi, media_hash_lo, valid_claim]` (`provenance_cli.js:201-220` builds witness; `provenance_v3.circom:39-56, :159-164`). In-circuit: both 128-bit limbs range-constrained (`Num2Bits(128)`, circom:63-67), five metadata rules (`circom:69-139`), and `valid_claim === valid` (`circom:159`). Verifier side: trusted vkey pin (`verify_media.js:47, :162-169`), claim gate `valid == valid_claim == 1` (`:196-200`), **hash recompute** from the actual audio bytes (`:202-218`), real `snarkjs.groth16.verify` boolean (`:220-226`). | Circuit constraints (rules + claim) + verifier-side SHA-256 recompute + Groth16 verification | **Private metadata VALUES are unproven** — any rule-satisfying values prove equally; **the file bytes are not attested in-circuit** (only prover-supplied limbs; byte binding is closed outside the circuit, `circom:26-30` comment); **detector score/decision/checkpoint** (`provenance_cli.js:174` note: "Recorded only. The AASIST score/verdict is NOT inside the ZK proof"); **who produced the proof** |
| **Detector output** (AASIST-L) | `score`, `decision`, `threshold`, `checkpoint_sha256` parsed from the detector process and stored in `demo_result.json` (`provenance_cli.js:158-176`) and echoed in `demo_workflow_report.json` (`demo_workflow.js:190-209`) | **Nothing.** No signature, no circuit tie, no verifier input. `verify_fully.js` reads only audio/proof/public/record (`verify_fully.js:80-83`); nothing consumes `demo_result.json` for a decision. The pipeline's only detector interaction is the process exit code and output parseability (`provenance_cli.js:153-167`) — the *decision* is never consulted (empirically: the 2026-11-03 repro accepted a file scored `spoof`, `decision=spoof`, exit 0) | Score integrity, decision enforcement, model-identity enforcement, content semantics |
| **`demo_result.json`** (manifest of the above) | Stage timings, artifact paths, detector snapshot, hashes | **Plain JSON file write** (`provenance_cli.js:110-114`); tamperable at will | Everything — no integrity, no signing |

**Binding topology (the one-line summary for the paper):** the record binds
*file bytes → vkey generation*; the proof binds *file bytes (via limbs) →
rule-compliant (unspecified) metadata*; nothing anywhere binds *metadata →
reality*, *(anything) → acoustic content*, *(anything) → the detector*, or
*the two artifacts → each other*.

---

## 3. Trust assumptions & attacker capabilities

**Trusted components (assumed honest for the model):**

- **Issuer:** SIMULATED — one local Ed25519 key at `<HOME>\zkp-demo-issuer-keys\`,
  public key pinned in verifier code (`verify_fully.js:44`). Assumption: only
  the trusted operator signs records. The instant this fails, A7 collapses
  the pipeline (see matrix).
- **Capture device:** *assumed but never attested.* No device key exists
  anywhere in the pipeline; "device_id ∈ {1024,2048,4096}" is a rule about
  an integer the operator types, not an attestation.
- **Prover code/keys:** frozen v3 wasm/zkey/vkey with SHA-256 pins (`verify_media.js:47`,
  verified 2026-11-03: vkey `cbae94c0…`, zkey `4d6821f5…`, checkpoint `814331d0…`).
  Groth16 keys are **zero-contribution `groth16 setup` output** (prototype
  convention) — no formal ceremony guarantee, but the setup-trapdoor threat
  (coordinator forges proofs) is out of scope here since the same local actor
  ran setup.
- **Verifier:** trusts its own pinned constants (vkey SHA-256 `verify_media.js:47`,
  issuer pubkey SHA-256 `verify_fully.js:44`); never accepts keys bundled
  with a proof/record (`verify_media.js:14-19`, `verify_fully.js:16-25`).

**Attacker capabilities (what they control):**

- The file bytes presented for verification; which proof/record bundle to
  present alongside; their own metadata values (they can run
  `provenance_cli.js` to generate arbitrary rule-compliant proofs for any
  file); re-encodings/splices/re-recordings of any audio; arbitrary edits to
  any *artifact they produce* (proofs, records under their own keys, manifests).
- They **cannot**: forge an Ed25519 signature under the pinned issuer key
  (standard assumption); produce a Groth16 proof that verifies under the
  pinned vkey while violating a circuit constraint; alter `verify_media.js`/
  `verify_fully.js` pins without that being a verifier-side compromise (out
  of scope — trust-config rotation requires an explicit override flag by
  design); force the issuer to sign (unless they control the operator — A7's
  assumption break — or present under their own key, which the pin rejects;
  MEASURED: Step-8 test case 5, REJECT exit 1).

---

## 4. Attack matrix

Layer abbreviations: **det** = detector layer, **hash** = SHA-256 binding,
**proof** = Groth16 proof, **sig** = Ed25519 record, **FV** = `verify_fully.js`
end to end (S1). All cells are HYPOTHESES except where marked MEASURED.
"REJECT✓" = intended defense works; "ACCEPT✗/⚠️" = suspected wrong-accept.

| id | Attack | Layer targeted | det | hash | proof | sig | FV (S1) | Generation method | Existing assets? |
|---|---|---|---|---|---|---|---|---|---|
| **A1** | Substitute file; check against original signed record/proof | hash+sig | — | REJECT✓ | REJECT✓ (limbs mismatch) | REJECT✓ (`file_sha256` != audio) | **REJECT✓ — MEASURED** (repro 2026-11-03: exit 1, "record is for a DIFFERENT file") | Any second FLAC + its own fresh proof, presented against the original record (already done with `LA_E_1000147.flac`; or byte-flip copy `media/step7_tampered_copy.flac` vs `outputs/v3/repro_sign/*`) | ✅ `media/step7_tampered_copy.flac`, `outputs/v3/repro_sign/` |
| **A2** | Benign re-encode of signed genuine file (MP3 32/64 kbps, Opus, resample 16→8→16 kHz, reverb, noise) | hash (content transform), det (secondary) | partial⚠️ — EER degrades: batch-1 clean 2.00% → noise10dB 13.60%, 8kHz 2.40%, errors mostly **false rejects** at thr 1.81681; mp3/reverb results in `results/robustness_scores2_*.csv` | REJECT✓ vs original record (hash changes) | n/a — fresh proof trivially works (same gap as A4/A7) | REJECT✓ vs original record | REJECT✓ vs original record — but rejects the *transformation*, not fakeness; **ACCEPT⚠️ on fresh-enrollment path** | Reuse `audio_benchmark/robustness_set*/` variants (noise 20/10 dB, 8kHz, mp3 32/64 kbps, reverb RT60 0.3/0.7 s) + generate the missing Opus & 16→8→16 kHz resample conditions with ffmpeg | ✅ `audio_benchmark/robustness_set/`, `robustness_set2/`; ⚠️ Opus/resample need generation |
| **A3** | Splice: insert ASVspoof LA spoof segment into signed genuine file | hash + det | uncertain⚠️ — detector trained on whole-utterance LA spoofs; the genuine segment may dominate the bonafide logit | REJECT✓ vs original record (splice's hash differs) | proof over splice trivially valid on fresh enrollment | REJECT✓ vs original record; ACCEPT⚠️ if the splice is re-enrolled | REJECT✓ vs original record; **ACCEPT⚠️ on enrollment path** | Concatenate genuine (e.g. `LA_E_9997285.flac`) with a spoof segment from any labeled `LA_E_*` spoof FLAC via ffmpeg/soundfile splice tooling at experiment time | ✅ `ASVspoof2019_LA_eval\flac\` (genuine + spoof files both available) |
| **A4** | **Metadata substitution** — new valid proof over the SAME genuine signed file with different fabricated rule-compliant metadata, presented with the original genuine record | proof (semantic emptiness) | — | — | ACCEPT (necessarily — circuit proves rule compliance only, `circom:69-160`) | ACCEPT (record checks `file_sha256` == audio — same genuine file — and `vkey_sha256`; the record never references any proof) | **ACCEPT — ⚠️ FLAGGED WRONG-ACCEPT.** Nothing binds metadata to the record, the proof, or reality; `verify_fully.js:132-155` checks only file/vkey identity | `node scripts/provenance_cli.js <same genuine flac> <new_outdir> --device-id 4096 --timestamp 1780867199 --sensor-score 99 --gps-lat 408399 --gps-long-abs 779199` (all inside rule ranges, all different from enrolled), then `verify_fully.js` with the original record | ✅ repo scripts + genuine FLAC from the A1 run |
| **A5** | Detector-output tampering — edit recorded `score`/`decision` in `demo_result.json` | detector-record integrity | — | — | — | — | **ACCEPT (unaffected) — ⚠️ FLAGGED:** no verifier reads `demo_result.json` (`verify_fully.js:80-83` reads only the 4 artifacts); the tampering is invisible to every layer | Edit a copy of `outputs/v3/repro_sign/run_honest2/demo_result.json`: set `detector.decision`="bonafide", `score`=6.9; show the FULL-VERIFY verdict unchanged | ✅ `outputs/v3/repro_sign/run_honest2/demo_result.json` |
| **A6** | Record replay — valid record for file X presented with file X in a different context (different session, later time, different claim) | sig (context binding) | — | — | — | ACCEPT✗ by design (record checks all pass — hash identity holds) | **ACCEPT (documented, not preventable):** record binds `file_sha256`, `vkey_sha256`, informational `issued_at_utc`, label. **No nonce, no session id, no link to any proof anywhere** (`issue_capture_record.js:72-79`) | Trivially: re-run `verify_fully.js` later, or copy `outputs/v3/repro_sign/capture_record.json` + the file into a fresh dir and verify | ✅ `outputs/v3/repro_sign/capture_record.json` |
| **A7** | Spoof enrollment — issuer signs a record over a spoofed file | trust (issuer + no enrollment gate) | detected IF consulted (full-eval EER 0.99%/AUC 0.9992 — but nothing consults it) | — | ACCEPT (fabricated metadata proves fine) | ACCEPT⚠️ (issuer mis-trusts) | **ACCEPT — ⚠️ FLAGGED WRONG-ACCEPT.** Structural no-enrollment-gate: `provenance_cli.js:153-167` checks detector exit code/parseability only; `demo_workflow.js:184-188` states "a 'bonafide' detector decision is NOT a prerequisite or gate"; MEASURED corroboration: the repro accepted a `spoof`-decision file (exit 0) | Pick a labeled spoof (e.g. `LA_E_1000147.flac` — already proven to self-accept in the repro), issue a record over it with the issuer key, run `verify_fully.js` | ✅ eval FLACs + issuer keys at `<HOME>\zkp-demo-issuer-keys\` |
| **A8** | Provenance laundering — spoof played through speaker, re-recorded, then enrolled (**physical; MEASURED U1 2026-11-09: C1 (laptop speaker→mic, own-device near-field) e2e acceptance 28/50 at the dev threshold (28/28 signed proved FULL-VERIFY ACCEPT); crypto vs original record 100/100 REJECT; C2 (phone voice memo ~1 m) FAR 1/50 with FRR 34/50 — detector collapses to chance on laundered audio in both channels**) | det (only hope) + trust | low⚠️ — AASIST-L is an LA-spoof *content* detector with no replay/channel model, and laundered audio is out-of-distribution in both directions (unreliable either way) | REJECT✓ vs original record (new recording's hash differs) | ACCEPT⚠️ on fresh enrollment | ACCEPT⚠️ (issuer trust, as A7) | REJECT vs original record; **ACCEPT⚠️ on enrollment** (structural gap as A7) | Design only: playback an `LA_E_*` spoof over a speaker, capture at ≥1 m, enroll via `provenance_cli.js` + issuer | ❌ requires physical capture — not generable from repo assets |

**Flagged rows (pipeline suspected of wrongly ACCEPTing):** A4 (worst case —
the *headline* gap: any valid proof over the same bytes replaces the enrolled
metadata and FULL-VERIFY still accepts), A5 (detector record has zero
integrity), A6 (no context binding — by design), A7 (no enrollment gate +
simulated issuer), and A2/A3/A8 on their **enrollment** paths (a changed
hash is rejected *against the original record* — the intended defense — but
freshly enrolled proof+record accepts the transformed content).

---

## 5. Systems under test & attack × system verdicts

- **S1 — full pipeline** (`verify_fully.js`): proof (independent
  `verify_media.js` process) + Ed25519 record + hash identity.
- **S2 — hash + Ed25519 record only**: the record signature/canonical/hash/vkey
  checks of `verify_fully.js` Part B; Groth16 skipped (evaluated by running
  S1 and ignoring Part A).
- **S3 — Minnah-style local hash registry** (simulated, no chain): verifier
  holds a table of enrolled `file_sha256 → {metadata, issued_at}`; ACCEPT iff
  the presented file's SHA-256 matches an enrolled entry.
- **S4 — AASIST-L detector only**: score vs a threshold; no cryptographic
  binding at all.

| Attack | S1 (full, FV) | S2 (hash+record) | S3 (hash registry) | S4 (detector) |
|---|---|---|---|---|
| A1 substitution | REJECT✓ (MEASURED) | REJECT✓ (hash identity) | REJECT✓ (hash not enrolled) | no gate — binds nothing; would score the presented file independently (scores MEASURED: 6.733125 for `LA_E_9997285`, −1.303891 for `LA_E_1000147`) |
| A2 re-encode | REJECT✓ vs original record; ACCEPT⚠️ if re-enrolled | REJECT✓ / ACCEPT⚠️ | REJECT✓ / ACCEPT⚠️ | partial⚠️ per condition (robustness EERs above) |
| A3 splice | REJECT✓ vs record; ACCEPT⚠️ re-enrolled | same | same | uncertain⚠️ |
| A4 metadata substitution | **ACCEPT ⚠️ flagged** | ACCEPT ⚠️ (never sees metadata) | ACCEPT (registry holds only the hash — it matches) | no gate (n/a) |
| A5 detector-record tampering | **ACCEPT ⚠️ flagged** (manifest unread by verifier) | ACCEPT ⚠️ | ACCEPT ⚠️ (no detector in the registry either) | n/a |
| A6 record replay | ACCEPT (context-free by design) | ACCEPT | ACCEPT ✓ (a hash registry *does* bind "file was enrolled once" — its only structural advantage) | n/a |
| A7 spoof enrollment | **ACCEPT ⚠️ flagged** | ACCEPT ⚠️ (signature valid if attacker has issuer trust) | ACCEPT ⚠️ (attacker controls enrollment) | **the only system that catches it: spoof scores at 0.99% full-eval EER — but S4 is not consulted by S1/S2/S3** |
| A8 laundering (design only) | REJECT vs record; ACCEPT⚠️ re-enrolled | same | same | low⚠️ (no replay model) |

**Paper takeaway (hypothesis to be confirmed):** the cryptographic layers
fail *upward* — hash/proof/signature defend substitution (A1) perfectly, but
defend *content* (A2/A3/A8) only against the *original* record, and defend
*meaning* (A4), *detector integrity* (A5), *context* (A6), and *enrollment*
(A7) not at all. S4, the only layer with content semantics (full-eval EER
0.9909%, AUC 0.99920), is wired as decoration.

---

## 6. Constraints for the later experiments

**Detector batching (RAM):** the 2026-11-03 repro hit `[error] scoring
failed: MemoryError()` at ~1.84 GB free of 15.68 GB (first attempt); the
identical retry succeeded minutes later — this 16 GB machine cannot
guarantee torch headroom. Safe protocol: **batches of ≤ 32 files per fresh
Python process, sequential**, with ≥ 2 GB physical RAM free before starting
a batch and a full process restart between batches (the full-eval driver
proved chunked fresh processes stable at 2.6–4.1 GB RAM); drop to 8 or 1 on
any MemoryError. Single-file detection is 13–25 s (MEASURED), so an attack
set of a few hundred files is hours, not days.

**Reported threshold:** report the **full-eval EER operating point
`threshold = 1.7635419737`** (`threshold_at_eer` in
`final_outputs/minnah_comparison/full_eval_metrics_v1.json`, MEASURED stable
across reproductions) as the primary detector threshold, with the **1.81681
500-file-subset point** reported alongside only as the code's built-in
default. Rationale: attacks A2/A3/A7 are drawn *from the full eval
distribution* the 1.76354 point was computed on; 1.81681 comes from a
500-file subset and is explicitly labeled exploratory in the code
(`detect_audio.py:6-11, :37`). No code change is needed: both
`detect_audio.py` and `provenance_cli.js` accept `--threshold`, and — per §2
— the threshold affects only *detector-layer* (S4) verdicts, since the
pipeline never gates on the decision.

**Scope discipline for experiments:** test rows A1–A7 by *running the
unchanged pipeline commands* (as done for A1); A8 stays design-only. All
verdict cells above are hypotheses until each is measured with its own
command + output + exit code in the evaluation report.