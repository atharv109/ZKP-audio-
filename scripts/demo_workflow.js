#!/usr/bin/env node
/**
 * demo_workflow.js — Step-7 single-file demo workflow (JSON front end).
 *
 *   node scripts/demo_workflow.js <audio.{wav,flac}> <metadata.json> <fresh_output_dir>
 *       [--weights P] [--aasist-repo P] [--config P] [--threshold T] [--python EXE]
 *
 * Takes a user-supplied audio file and a PRIVATE METADATA JSON (five integer
 * keys: device_id, timestamp, sensor_score, gps_lat, gps_long_abs), pre-
 * validates them for CLEAR ERRORS against the frozen circuits/provenance_v3.circom
 * rules, then drives the existing tested pipeline scripts/provenance_cli.js
 * (AASIST-L score → SHA-256 limbs → Groth16 proof via frozen v3 zkey/wasm →
 * scripts/verify_media.js in its own process). Every stage below the wrapper
 * is upstream code, unchanged.
 *
 * Claims (kept separate, restated in every report):
 *   - the detector produces a SPOOF SCORE at an EXPLORATORY threshold
 *     (EER point of the frozen 500-file subset; not a deployed threshold);
 *   - the proof establishes that the SUPPLIED FILE HASH is bound to metadata
 *     satisfying the circuit rules;
 *   - NEITHER proves real capture, truthful metadata, or "authentic audio";
 *   - a "bonafide" detector decision is NOT a prerequisite — the detector
 *     score is recorded, never enforced, never claimed inside the proof.
 *
 * Exit codes: 0 ACCEPT (proof verified + file bound) · 1 REJECT/failure ·
 * 2 usage error. Each run writes a FRESH output directory (existing dirs are
 * refused); the frozen Step-3 proof/keys in outputs/v3 are never written.
 */

const { spawnSync } = require("child_process");
const fs = require("fs");
const path = require("path");

const REPO = path.resolve(__dirname, "..");
const INNER = path.join(REPO, "scripts", "provenance_cli.js");

const META_KEYS = ["device_id", "timestamp", "sensor_score", "gps_lat", "gps_long_abs"];

// Mirror of the frozen v3 circuit rules (circuits/provenance_v3.circom:
// device_id ∈ {1024,2048,4096}; timestamp ∈ [1780278000,1780867200];
// sensor_score ≥ 70; gps_lat ∈ [407400,408400]; gps_long(abs) ∈ [778000,779200]).
// The circuit itself remains the only enforcement point; this pre-check
// exists so the run stops with a naming error before any proving work.
const RANGE_RULES = {
  timestamp: [1780278000, 1780867200],
  gps_lat: [407400, 408400],
  gps_long_abs: [778000, 779200],
};
const DEVICE_IDS = [1024, 2048, 4096];
const SENSOR_MIN = 70;

const OPT_KEYS = [["--weights", "weights"], ["--aasist-repo", "aasist_repo"],
                  ["--config", "config"], ["--threshold", "threshold"], ["--python", "python"]];

const EXIT_OK = 0, EXIT_FAIL = 1, EXIT_USAGE = 2;
const THRESHOLD_LABEL = "EXPLORATORY — EER operating point of the frozen 500-file LA eval "
  + "subset (or explicit override); NOT a validated deployment threshold";
const CLAIMS_NOTE = "The proof establishes ONLY that the supplied file hash is bound to "
  + "metadata satisfying the circuit rules. The detector score is recorded, not attested. "
  + "Neither result proves real capture, truthful metadata, or authentic audio.";

function usage() {
  console.error("Usage: node scripts/demo_workflow.js <audio.wav|*.flac> <metadata.json> "
    + "<fresh_output_dir> [--weights P] [--aasist-repo P] [--config P] [--threshold T] [--python EXE]");
}

function parseArgs(argv) {
  const flags = {}, positional = [];
  const flagNames = new Set(OPT_KEYS.map(([f]) => f));
  for (let i = 0; i < argv.length; i++) {
    if (flagNames.has(argv[i])) {
      if (i + 1 >= argv.length) return null;
      flags[argv[i]] = argv[++i];
    } else positional.push(argv[i]);
  }
  return { flags, positional };
}

function readMetadata(p) {
  if (!fs.existsSync(p)) {
    console.error(`[workflow] metadata file not found: ${p}`);
    return null;
  }
  let obj;
  try {
    obj = JSON.parse(fs.readFileSync(p, "utf8"));
  } catch (e) {
    console.error(`[workflow] metadata file is not valid JSON: ${p} (${e.message})`);
    return null;
  }
  if (obj === null || typeof obj !== "object" || Array.isArray(obj)) {
    console.error(`[workflow] metadata must be a JSON object: ${p}`);
    return null;
  }
  const missing = META_KEYS.filter((k) => !(k in obj));
  const unknown = Object.keys(obj).filter((k) => !META_KEYS.includes(k));
  if (missing.length) console.error(`[workflow] metadata missing keys: ${missing.join(", ")}`);
  if (unknown.length) console.error(`[workflow] metadata has unknown keys: ${unknown.join(", ")}`);
  if (missing.length || unknown.length) return null;
  for (const k of META_KEYS) {
    const v = obj[k];
    if (!Number.isFinite(v) || !Number.isInteger(v)) {
      console.error(`[workflow] metadata value '${k}' must be a finite integer, got: ${JSON.stringify(v)}`);
      return null;
    }
  }
  if (!DEVICE_IDS.includes(obj.device_id)) {
    console.error(`[workflow] metadata fails v3 circuit rule for device_id: got ${obj.device_id} `
      + `(rule: one of ${DEVICE_IDS.join(", ")})`);
    return null;
  }
  if (obj.sensor_score < SENSOR_MIN) {
    console.error(`[workflow] metadata fails v3 circuit rule for sensor_score: got ${obj.sensor_score} `
      + `(rule: ≥ ${SENSOR_MIN})`);
    return null;
  }
  for (const [k, [lo, hi]] of Object.entries(RANGE_RULES)) {
    if (obj[k] < lo || obj[k] > hi) {
      console.error(`[workflow] metadata fails v3 circuit rule for ${k}: got ${obj[k]} (rule: [${lo}, ${hi}])`);
      return null;
    }
  }
  return obj;
}

function main() {
  const parsed = parseArgs(process.argv.slice(2));
  if (!parsed) { usage(); return EXIT_USAGE; }
  const [audioArg, metaArg, outDirArg] = parsed.positional;
  if (!audioArg || !metaArg || !outDirArg) { usage(); return EXIT_USAGE; }

  const audio = path.resolve(audioArg);
  const metaPath = path.resolve(metaArg);
  const outDir = path.resolve(outDirArg);
  const innerArgs = [INNER, audio, outDir];

  // Model-asset pre-checks (only for explicitly passed paths) — clear errors
  // before any detector process starts; missing weights ⇒ no run, no proof.
  const modelChecks = [
    ["--weights", parsed.flags["--weights"], "model weights", "no proof is generated"],
    ["--config", parsed.flags["--config"], "model config", "no proof is generated"],
    ["--aasist-repo", parsed.flags["--aasist-repo"], "AASIST repo", "no proof is generated"],
  ];
  for (const [flag, value, label, consequence] of modelChecks) {
    if (value != null && !fs.existsSync(path.resolve(value))) {
      console.error(`[workflow] ${label} not found: ${path.resolve(value)} — ${consequence}`);
      return EXIT_FAIL;
    }
  }

  const meta = readMetadata(metaPath);
  if (!meta) return EXIT_FAIL; // run directory intentionally never created for metadata errors

  if (fs.existsSync(audio)) {
    innerArgs.push("--device-id", String(meta.device_id), "--timestamp", String(meta.timestamp),
                   "--sensor-score", String(meta.sensor_score), "--gps-lat", String(meta.gps_lat),
                   "--gps-long-abs", String(meta.gps_long_abs));
  } else {
    console.error(`[workflow] audio file not found: ${audio}`); // no run dir on this either
    return EXIT_FAIL;
  }
  for (const [flag, key] of OPT_KEYS) {
    if (parsed.flags[flag] != null) innerArgs.push(flag, parsed.flags[flag]);
  }

  console.log(`[workflow] audio=${audio}`);
  console.log(`[workflow] metadata=${metaPath} (private inputs; only circuit-rule compliance is checked)`);
  console.log("[workflow] driving scripts/provenance_cli.js (fresh run directory, frozen v3 artifacts)...");

  const inner = spawnSync(process.execPath, innerArgs, { encoding: "utf8",
        stdio: ["ignore", "inherit", "inherit"] });
  const accepted = inner.status === 0;

  const report = {
    version: "demo_workflow_step7_v1",
    command: "node scripts/demo_workflow.js " + process.argv.slice(2).join(" "),
    accepted,
    exit_code: inner.status,
    audio_path: audio,
    metadata_path: metaPath,
    run_dir: outDir,
    detector_threshold_label: THRESHOLD_LABEL,
    claims: {
      detector: "spoof score at an exploratory threshold — recorded, never enforced or attested",
      proof: "supplied file hash bound to metadata satisfying the circuit rules",
      not_shown: ["real capture", "truthful metadata", "authentic audio"],
      detector_gate: "a 'bonafide' detector decision is NOT a prerequisite or gate for proof generation",
    },
  };
  if (fs.existsSync(outDir) && fs.existsSync(path.join(outDir, "demo_result.json"))) {
    try {
      const manifest = JSON.parse(fs.readFileSync(path.join(outDir, "demo_result.json"), "utf8"));
      report.pipeline_exit_code = manifest.exit_code ?? null;
      report.detector = manifest.detector?.score != null ? {
        score: manifest.detector.score,
        decision: manifest.detector.decision,
        threshold: manifest.detector.threshold,
        checkpoint_sha256: manifest.detector.checkpoint_sha256,
        in_proof: false,
        threshold_label: THRESHOLD_LABEL,
        note: "recorded only — never claimed or enforced by the circuit",
      } : manifest.detector ?? null;
      report.stages = manifest.stages ?? null;
      report.artifacts = manifest.artifacts ?? null;
      if (!accepted) {
        const failed = (report.stages ?? []).find((s) => s.status === "fail");
        report.fail_stage = failed ? failed.stage : null;
        report.fail_detail = failed ? failed.detail : null;
      }
    } catch { /* manifest unreadable — report still written with what is known */ }
  } else {
    report.pipeline_exit_code = inner.status;
    report.fail_stage = "pre-run (no run directory created)";
    report.fail_detail = "the existing pipeline aborted before creating the output directory";
  }
  // The run dir exists only after pipeline start; the report lives INSIDE it,
  // so it never touches a frozen artifact. Pre-run failures (above) stay
  // console-only by design.
  if (fs.existsSync(outDir)) {
    const reportPath = path.join(outDir, "demo_workflow_report.json");
    report.artifacts = { ...(report.artifacts ?? {}), workflow_report: reportPath };
    fs.writeFileSync(reportPath, JSON.stringify(report, null, 2) + "\n");
  }

  console.log("─".repeat(64));
  if (accepted) {
    const d = report.detector ?? {};
    console.log(`[workflow] ACCEPT — proof verified by independent process, file hash bound.`);
    if (d.score != null) {
      console.log(`[workflow] detector (RECORDED ONLY): score=${d.score} decision=${d.decision} `
        + `@ ${THRESHOLD_LABEL}`);
    }
    console.log("[workflow] this is NOT a claim of authentic audio, capture truth, or truthful metadata.");
  } else {
    console.log(`[workflow] REJECT — exit ${inner.status}` +
      (report.fail_stage ? ` (stage: ${report.fail_stage}${report.fail_detail ? `: ${report.fail_detail}` : ""})` : ""));
  }
  console.log(`[workflow] report: ${fs.existsSync(outDir) ? path.join(outDir, "demo_workflow_report.json") : "(none — pre-run failure)"}`);
  return accepted ? EXIT_OK : EXIT_FAIL;
}

module.exports = { parseArgs, readMetadata, THRESHOLD_LABEL, CLAIMS_NOTE };

if (require.main === module) {
  process.exit(main());
}