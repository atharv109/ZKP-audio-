# v4 COSTS — measured 2026-11-04 (Windows 11, CPU-only, 16 GB box)

Constraint count: **1,426** (r1csfile + snarkjs r1cs info agree; r1cs v1 files are
section-framed, so flat-offset parsing reads garbage). Poseidon(6) = 968 = 1,426 − 458 (v3).
pot12 (4,096 capacity) reused, phase-2-only setup.

| measurement | mean | median | range | n |
|---|---|---|---|---|
| fullProve (v4) | 278.1 ms | 206.0 ms | 188–588 | 5 (first run cold) |
| bare groth16.verify | 12.7 ms | 13 | 11–14 | 5 |
| verify_media_v4.js | 352.6 ms | 350.5 ms | 337.8–374.0 | 10 |
| verify_fully_v4.js | 447.1 ms | 457.1 ms | 391.1–495.6 | 10 |
| holder prove (provenance_cli_v4, warm) | ~476 ms | ~475 ms | — | 5 |
| issuer v4 enrollment (real AASIST-L detector + wtns + sign) | 16,704 ms (cold 65 s outlier in the mean) | **3,719 ms warm** | — | 5 |
| end-to-end workflow (demo_workflow_v4) | 17,568 ms | **4,558 ms warm** | — | 5 |

e2e per stage (5 honest runs, report JSONs): enroll = detector-dominated
(warm median 3.7 s); holder prove ≈ 0.48 s; verify_fully_v4 ≈ 0.39 s.