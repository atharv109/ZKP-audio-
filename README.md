# Anonymized review artifact — zero-knowledge provenance circuits (v3/v4) + synthetic-speech eval harness

This package is a scrubbed snapshot of a small research codebase built around
two provenance circuits in circom:

- **v1→v3→v4 circuit sources**: `circuits/provenance.circom`,
  `circuits/provenance_v3.circom`, `circuits/provenance_v4.circom`
  (v4 is the paper's circuit; v3 is its predecessor used for binding-policy
  comparisons; `provenance.circom` is the earlier v1 circuit kept for history).
- **Compiled artifacts**: `outputs/v3/` and `outputs/v4/` hold the compiled
  `.zkey`, `.r1cs`, `.sym`, `verification_key_*.json`, sample
  `proof_*.json`/`public_*.json` and snarkjs-generated witness dirs
  (`provenance_v*_js/`). `outputs/v4/PINS.md` records the pinned
  verifier/issuer parameters of v4; `outputs/v4/COSTS.md` records
  proving/verification cost measurements.
  The sha256 values recorded in `outputs/v4/PINS.md` were re-verified against
  the shipped v4 circuit source and compiled artifacts in this copy: all five
  match bit-for-bit.
- **Verifier/CLI scripts**: `scripts/verify_media_v4.js`,
  `scripts/verify_fully_v4.js`, `scripts/issue_capture_record_v4.js`,
  `scripts/demo_workflow_v4.js`, `scripts/provenance_cli_v4.js` (v4) and the
  corresponding `_v3`/non-suffixed scripts from earlier iterations, plus
  helpers (`prepare_input.js`, `validate_row.js`, `hash_media.js`,
  `hash_limbs.js`).
- **Tests**: `tests/*.test.js` (node:test suite; v4 tests plus earlier
  iterations `verify_media.test.js`, `demo_workflow_v4.test.js`, etc.).
- **Eval harness and results**: `eval/` (scoring, sampling, transform and
  metric scripts; score caches, result CSVs, sample manifests with seeds, the
  crash-snapshot files `*_crashed_20261103-*`, and `eval/final/` with the two
  final-computation scripts and their machine-readable outputs
  `eval/final/eer_json.json`, `eval/final/rates_json.json`).
- **Eval score source**: `final_outputs/minnah_comparison/dataset_acquisition/merged_scores.csv`
  (71,237 rows = full ASVspoof 2019 LA eval set, one score per utterance).
- **Official CM protocols**: `ASVspoof2019_LA_cm_protocols/`
  contains the public ASVspoof 2019 LA CM protocol text files (dev + eval
  target lists) referenced by the commands in the RESULTS documents. These
  are public text metadata; no ASVspoof audio is included in this artifact.
- **RESULTS documents**: `RESULTS_*.md` at the root are the append-only
  verification reports; `REPO_MAP.md`, `THREAT_MODEL.md`, `FIX_DESIGN.md`,
  `DEMO.md`, `REPO_README.md` (the original repo README) give additional
  context. `audio_benchmark/models.py` and `audio_benchmark/run_inference.py`
  are the two detector-side scripts cited by line number in the RESULTS docs.

## 1. Re-running the final eval numbers (Python 3.12, `python`)

Run from this artifact's root. Requires `numpy` and `scipy` (user
site-packages). No model weights, no audio, no network access.

(a) Dev-set EER (method A/B/C + AUC), reproduces `eval/final/eer_json.json`:

```
python eval/final/compute_eer.py --scores eval/dev_scores.json --labels eval/dev_labels.csv --json-out <TMPDIR>/eer.json
```

Expected: `n_bonafide=2548 n_spoof=22296`; method A discrete-point
EER 0.510753% @ −0.947072; method B linear-interp EER 0.510204% @
−0.944942612244898 (the paper's official dev EER/threshold); method C scipy
ROC 0.510204%; AUC 0.999641.

(b) Full-eval rates (pooled + per-attack), reproduces `eval/final/rates_json.json`:

```
python eval/final/compute_rates.py --scores final_outputs/minnah_comparison/dataset_acquisition/merged_scores.csv --protocol ASVspoof2019_LA_cm_protocols/ASVspoof2019.LA.cm.eval.trl.txt --threshold -0.944942612244898 --json-out <TMPDIR>/rates.json
```

Expected: `rows=71237 unique=71237 protocol=71237 (bona=7355 spoof=63882)
missing=0 extra=0 label_mismatches=0`, pooled spoof-accept 7,115/63,882
(11.14%), bona-fide-reject 7/7,355 (0.10%), and the per-attack A07–A19 table
in `RESULTS_FINAL.md` §1.

`<TMPDIR>` = any scratch directory; writing to `eval/final/*.json` also works
but would overwrite the shipped copies of the two result files.

**Path-scrub note for `merged_scores.csv`**: the `file` column of the
original CSV stored absolute Windows paths (home + repo prefix +
`Downloads/LA/LA/...`). In this artifact those prefixes were removed, so the
column holds `Downloads/LA/LA/ASVspoof2019_LA_eval/flac/<ID>.flac` relative
paths. The scripts key utterances by basename, so all counts, scores and
labels are byte-for-byte unaffected — only the path prefix differs. Because
of this the sha256 of this copy differs from the original-file sha quoted in
`RESULTS_FINAL.md` §1 (the quoted value is a provenance anchor for the
pre-scrub file inside the original repo).

## 2. Re-running the v3/v4 verifier and tests (Node)

The tests use `node:test`. With a local install of the pinned dependencies
(snarkjs 0.7.6 is the real runtime used by the scripts):

```
npm install "snarkjs@0.7.6" "circomlibjs@0.1.7" "circomlib@2.0.5" "xlsx@0.18.5"
NODE_PATH=<path to that node_modules> node --test tests/
```

Run per test file on slow machines (the suite spawns snarkjs/pipeline child
processes):

```
NODE_PATH=<path to node_modules> node --test --test-timeout=60000 tests/<file>.test.js
```

### 2a. Demo assets — the bootstrap the tests default to

The issuer/detector end-to-end flows need three resources that are NOT shipped
(upstream: ASVspoof 2019 LA eval FLAC audio, the original demo issuer
keypair, AASIST-L weights). This artifact replaces all three with shipped
DEMO equivalents and routes every path through one bootstrap module,
`scripts/demo_assets.js` (`resolve()` is called at the audio/issuer-key/
weights/config entry points of the `scripts/*.js` CLIs). `node --test` from
the artifact root therefore works with no extra setup:

| Resource | Shipped demo replacement | Env override |
|---|---|---|
| ASVspoof 2019 LA eval audio | `demo_audio/*.wav` — synthetic, fixed-seed, generated by `demo_audio/make_demo_audio.py`; `demo_audio/demo_assets.json` maps every nominal utterance path the tests use to a demo WAV (real files on disk always win over the mapping) | `ZKP_DEMO_AUDIO_DIR`-style indirection is via the manifest file |
| issuer keypair | `demo_keys/issuer_{private,public}.pem` — generated Ed25519 pair, demo-only (`demo_keys/DEMO_ONLY.md`); staged at runtime to a temp dir OUTSIDE the repo because the issuer still enforces its key-outside-repo guard | `ZKP_DEMO_KEYS_DIR` (dir with both PEMs), `ZKP_DEMO_ISSUER_PUB` |
| AASIST-L weights | `models/AASIST-L.pth` — fetch with `python scripts/fetch_weights.py` (official `clovaai/aasist` URL; sha-256 pinned in `outputs/v4/PINS.md`) | `ZKP_DEMO_WEIGHTS`, `ZKP_DEMO_AASIST_REPO`, `ZKP_DEMO_CONFIG`, `ZKP_DEMO_HOME` |

- `scripts/fetch_weights.py` downloads the checkpoint from the official
  clovaai/aasist repo (the pretrained models are hosted IN that repo —
  `config/AASIST-L.conf` points at `models/weights/AASIST-L.pth`), verifies
  the SHA-256 against the pin in `outputs/v4/PINS.md`, and vendors the
  official model code + config (`models/aasist/`) when missing. Offline
  fallback documented there: `--from-local <path>` copies a checkpoint you
  already have (still sha-verified against the same pin).
- The nominally-placeholder `<HOME>/...` strings that remain in the tests and
  scripts are resolved by `scripts/demo_assets.js` onto the demo locations
  (with the env overrides above; anything unmatched falls back to the home
  directory, restoring pre-scrub behaviour).
- **Skipping behaviour**: asset-dependent tests in
  `tests/issue_capture_record_v4.test.js`, `tests/verify_media_v4.test.js`,
  `tests/verify_fully_v4.test.js`, `tests/demo_workflow_v4.test.js` and
  `tests/verify_media.test.js` check `scripts/demo_assets.js` `assetsStatus()`
  first and SKIP with a message like `weights not fetched — run:
  python scripts/fetch_weights.py` when anything is missing or the weights
  sha mismatches the pin. They never hard-fail on a missing resource.
- The issuer pubkeys pin in `verify_fully.js` / `verify_fully_v4.js` resolves
  through `demo_assets.js`: in this artifact the pin is the SHA-256 of the
  shipped demo public key (see `outputs/v4/PINS.md`, "issuer pubkey pin").
- Expected result with `models/AASIST-L.pth` fetched and the other demo
  assets as shipped: **54/54 passing, 0 skipped** (per-file counts in
  `RESULTS_FINAL.md` §5.1).

The same `scripts/*.js` CLIs can be used directly, e.g.:

```
node scripts/verify_media_v4.js <audio> <proof.json> <public.json> --policy-file <policy.json>
```

(see the argument parser inside each script for the exact flags; the
committed sample run directories referenced by the RESULTS docs were not
shipped to keep the artifact focused on source + compiled circuits + eval).
Note that `audio_benchmark/data/bonafide/bon_00.wav` also maps onto
`demo_audio/bon_00.wav` — a byte-exact regeneration (pin inside
`demo_audio/make_demo_audio.py`) of the tiny synthetic clip the shipped
`outputs/v3/proof_v3.json` is bound to. `outputs/verification_key.json` (the
v2 verification key, used only as a WRONG-key fixture by
`tests/verify_media.test.js`) is shipped with the compiled outputs.

The same `scripts/*.js` CLIs can be used directly, e.g.:

```
node scripts/verify_media_v4.js --input <input.json> --proof <proof.json> --zkey outputs/v4/circuit_v4.zkey --vkey outputs/v4/verification_key_v4.json
```

(see the argument parser inside each script for the exact flags; the
committed sample run directories referenced by the RESULTS docs were not
shipped to keep the artifact focused on source + compiled circuits + eval).

## 3. Placeholders used by the anonymization scrub

Every identifying string was replaced as follows (case-insensitive):

| Placeholder | Replaces |
|---|---|
| `<HOME>` | the user's home directory prefix (drive letter, `Users` folder, username — every separator/case variation found, including Git-bash style) and standalone tilde home-path prefixes. **Runtime note:** in the demo-asset bootstrap (`scripts/demo_assets.js`) a leading `<HOME>/` is a RESOLVED placeholder mapping onto the shipped demo assets (issuer keys, model weights/config/repo); unmatched paths fall back to the home directory |
| `<USER>` | the bare username/handle and the GitHub handle |
| `<MACHINE>` | the machine/computer name (NetBIOS name) |
| `<EMAIL>` | email addresses |

Also removed entirely (replaced by the empty string, leaving the remaining
relative path intact):

- the user's cloud-synced-folder name, both as a segment inside absolute
  paths and in a few prose/log fragments (in the latter only the word was
  dropped, e.g. "historical -sync hang hazard" was originally "historical
  <cloud-sync>-sync");
- the original repo folder prefix (`<HOME>\Desktop\<repo>`), so absolute
  repo paths in logs/JSON results become repo-root-relative paths;
- `Downloads\LA\LA\` between the home prefix and the ASVspoof2019 protocol
  or LA data folders, so the protocol files match the shipped
  `ASVspoof2019_LA_cm_protocols/` directory (see the commands in §1 and
  `RESULTS_FINAL.md`).

## 4. Not included (and why)

- All real audio (*.wav/*.flac/*.mp3/*.opus of any real capture or dataset),
  node_modules, .git, and cached artifacts — per review-artifact rules. The
  WAVs under `demo_audio/` are the documented SYNTHETIC exception: fixed-seed
  generated signals, no recordings of any voice. The only model weights file
  shipped, `models/AASIST-L.pth`, is the public pretrained checkpoint from
  the official clovaai/aasist repo, re-fetched at packaging time via
  `scripts/fetch_weights.py` and sha-256-pinned in `outputs/v4/PINS.md`
  (officially published data, not identifying).
- Upstream demo issuer key material (the private key the original demo was
  signed with) — excluded by policy; this artifact ships its own demo-only
  keypair instead (`demo_keys/`, see `demo_keys/DEMO_ONLY.md`), and the
  verifier pin follows it in demo mode (recorded in `outputs/v4/PINS.md`,
  where the legacy upstream pin is also kept for reference).
- The per-run output directories of the eval (e.g. `outputs/v3/eval_binding/`)
  — only their summarized CSV/JSON results are shipped inside `eval/`.
- The circom compiler source tree (`circom/`), pot12 setup files and other
  benchmark tracks unrelated to the v3/v4 circuits and the LA eval harness
  (e.g. `video_benchmark/`); `audio_benchmark/` ships the two scripts cited
  by the RESULTS documents plus `detect_audio.py`, the single-file detector
  CLI the v4 issuer invokes (restored to the artifact copy 2026-11-12 — it
  is plain source, no data).
