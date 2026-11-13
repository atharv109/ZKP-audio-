#!/usr/bin/env node
/**
 * provenance_cli.js — combined CLI: detect → hash → prove → verify (Step 5).
 *
 *   node scripts/provenance_cli.js <audio.{wav,flac}> <fresh_output_dir>
 *       --device-id N --timestamp N --sensor-score N --gps-lat N --gps-long-abs N
 *       [--weights P] [--aasist-repo P] [--config P] [--threshold T]
 *       [--python EXE]
 *
 * Pipeline (each stage fails closed; timings + artifact paths recorded in
 * <outdir>/demo_result.json):
 *   1. audio checks (.wav/.flac, exists; original never modified)
 *   2. detector — spawns audio_benchmark/detect_audio.py as its OWN process
 *      with explicit argument arrays (no shell). Its raw output is preserved
 *      to <outdir>/detector_output.txt and parsed (threshold / score /
 *      decision / checkpoint sha). Missing/malformed/failed output aborts
 *      BEFORE proof generation. The detector verdict is RECORDED, not
 *      enforced: the hash limbs go into the circuit, the AASIST score does
 *      not (see DEMO.md).
 *   3. hash — SHA-256 over the exact supplied audio bytes → two 128-bit
 *      decimal limbs (BigInt only; scripts/hash_limbs.js convention).
 *   4. prove — builds the v3 witness input (the five private metadata values,
 *      the two public hash limbs, valid_claim = "1") and calls the LOCAL
 *      snarkjs API (snarkjs.groth16.fullProve) over the FROZEN v3 artifacts
 *      (outputs/v3/*). No key regeneration, no circuit edits, no global CLI.
 *   5. verify — spawns scripts/verify_media.js as an INDEPENDENT process on
 *      (supplied audio, generated proof, generated public signals). Its trust
 *      configuration is its own pinned repo vkey — never the generated
 *      bundle. Acceptance requires that process's exit code 0.
 *
 * Exit codes: 0 only after independent verification succeeds; otherwise
 * nonzero (2 usage, 1 stage failure). Success means: proof verification
 * succeeded AND the supplied file binds to the proof's hash limbs.
 * (Never a claim of "authentic audio".)
 */

const { spawnSync } = require("child_process");
const fs = require("fs");
const path = require("path");
const snarkjs = require("snarkjs");
const { sha256File, limbsFromDigest } = require(path.join(__dirname, "hash_limbs.js"));

const REPO = path.resolve(__dirname, "..");
const DETECTOR = path.join(REPO, "audio_benchmark", "detect_audio.py");
const WASM = path.join(REPO, "outputs", "v3", "provenance_v3_js", "provenance_v3.wasm");
const ZKEY = path.join(REPO, "outputs", "v3", "circuit_v3.zkey");
const VERIFY_SCRIPT = path.join(REPO, "scripts", "verify_media.js");

const AUDIO_EXTS = new Set([".wav", ".flac"]);
const EXIT_OK = 0, EXIT_FAIL = 1, EXIT_USAGE = 2;
const NUM_KEYS = ["device_id", "timestamp", "sensor_score", "gps_lat", "gps_long"];
const OPT_KEYS = ["weights", "aasist_repo", "config", "threshold", "python"];

// Explicit flag-name table (gps_long uses --gps-long-abs: circuit input is
// the ABSOLUTE value).
const FLAGS = {
  device_id: "--device-id", timestamp: "--timestamp", sensor_score: "--sensor-score",
  gps_lat: "--gps-lat", gps_long: "--gps-long-abs",
  weights: "--weights", aasist_repo: "--aasist-repo", config: "--config",
  threshold: "--threshold", python: "--python",
};

const USAGE = `Usage: node scripts/provenance_cli.js <audio.wav|*.flac> <fresh_output_dir> \
--device-id N --timestamp N --sensor-score N --gps-lat N --gps-long-abs N \
[--weights P] [--aasist-repo P] [--config P] [--threshold T] [--python EXE]`;

function parseArgs(argv) {
  const flags = {};
  const positional = [];
  const known = [...NUM_KEYS, ...OPT_KEYS];
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    const key = known.find((k) => FLAGS[k] === a);
    if (key != null) {
      if (i + 1 >= argv.length) return null; // dangling flag
      flags[key] = argv[++i];
    } else positional.push(a);
  }
  return { flags, positional };
}

async function main() {
  const t0 = performance.now();
  const stages = [];
  const mark = (name, status, detail, since) => {
    stages.push({ stage: name, status, ms: Math.round(performance.now() - since),
                  detail });
    console.log(`[stage] ${name.padEnd(8)} ${status.toUpperCase()}  (${Math.round(performance.now() - since)} ms)`);
    console.log("           " + (typeof detail === "string" ? detail : JSON.stringify(detail ?? "")));
  };
  const parsed = parseArgs(process.argv.slice(2));
  if (!parsed) { console.error(USAGE); return EXIT_USAGE; }
  const { flags, positional } = parsed;
  const [audioArg, outDirArg] = positional;
  if (!audioArg || !outDirArg || NUM_KEYS.some((k) => flags[k] == null)) {
    console.error(USAGE);
    console.error("[error] all five --device-id/--timestamp/--sensor-score/--gps-lat/--gps-long-abs are required");
    return EXIT_USAGE;
  }

  const audio = path.resolve(audioArg);
  const outDir = path.resolve(outDirArg);
  const result = {
    command: "node scripts/provenance_cli.js " + process.argv.slice(2).join(" "),
    audio: null, detector: null, stages, artifacts: {}, config: null,
    verdict: null,
    disclaimer: "Proof verification + file hash binding only — no claim of "
      + "authentic audio, capture truth, or detector enforcement.",
  };
  const writeManifest = (finalCode) => {
    try { fs.writeFileSync(path.join(outDir, "demo_result.json"),
        JSON.stringify(result, null, 2) + "\n"); return true; }
    catch { return false; }
  };
  const failNow = (stageName, msg, since) => {
    mark(stageName, "fail", msg, since);
    writeManifest(EXIT_FAIL);
    console.error(`[error] ${stageName}: ${msg}`);
    console.log(`RESULT : FAIL — ${msg}`);
    process.exit(EXIT_FAIL); // explicit: snarkjs keeps the event loop alive
  };

  // ── Stage 1: audio + fresh output directory ────────────────────────────────
  let s = performance.now();
  if (!fs.existsSync(audio)) {
    mark("audio", "fail", `file not found: ${audio}`, s);
    return EXIT_FAIL;
  }
  const ext = path.extname(audio).toLowerCase();
  if (!AUDIO_EXTS.has(ext)) {
    mark("audio", "fail", `unsupported format '${ext}' (expected .wav/.flac)`, s);
    return EXIT_FAIL;
  }
  if (fs.existsSync(outDir)) {
    mark("audio", "fail", `output directory already exists (refusing to overwrite): ${outDir}`, s);
    return EXIT_FAIL;
  }
  fs.mkdirSync(outDir, { recursive: true });
  mark("audio", "ok", `audio=${audio} outdir=${outDir}`, s);

  // ── Stage 2: detector (independent python process) ──────────────────────────
  s = performance.now();
  const detectorArgs = [DETECTOR, audio];
  for (const [flag, key] of [["--weights", "weights"], ["--aasist-repo", "aasist_repo"],
                             ["--config", "config"], ["--threshold", "threshold"]]) {
    if (flags[key] != null) detectorArgs.push(flag, flags[key]);
  }
  const det = spawnSync(flags.python || "python", detectorArgs,
                        { encoding: "utf8", cwd: REPO,
                          env: process.env }); // AASIST_* falls through to detect_audio.py
  const detectorTxt = (det.stdout || "") + (det.stderr || "");
  let detState = { exit: det.status, raw: detectorTxt };
  if (det.status !== 0) {
    fs.writeFileSync(path.join(outDir, "detector_output.txt"), detectorTxt);
    result.detector = detState;
    failNow("detect", `detector exited with code ${det.status}; see detector_output.txt`, s);
  }
  const parseLine = (re) => { const m = detectorTxt.match(re); return m ? m[1] : null; };
  const detScore = parseLine(/^score\s+:\s+([-+0-9.eE]+)$/m);
  const detDecision = parseLine(/^decision\s+:\s+(bonafide|spoof)$/m);
  const detThreshold = parseLine(/^threshold\s+:\s+([-+0-9.eE]+)/m);
  const detCkpt = parseLine(/^checkpoint_sha256\s+:\s+([0-9a-fA-F]{64})$/m);
  if (detScore == null || detDecision == null || detThreshold == null || detCkpt == null) {
    fs.writeFileSync(path.join(outDir, "detector_output.txt"), detectorTxt);
    result.detector = detState;
    failNow("detect", "detector output present but unparseable (malformed); see detector_output.txt", s);
  }
  fs.writeFileSync(path.join(outDir, "detector_output.txt"), detectorTxt);
  result.detector = {
    exit: det.status,
    score: Number(detScore), decision: detDecision, threshold: Number(detThreshold),
    checkpoint_sha256: detCkpt,
    raw_output_file: path.join(outDir, "detector_output.txt"),
    note: "Recorded only. The AASIST score/verdict is NOT inside the ZK proof.",
  };
  mark("detect", "ok", `score=${detScore} decision=${detDecision} threshold=${detThreshold}`, s);

  // ── Stage 3: hash limbs from exact audio bytes ──────────────────────────────
  s = performance.now();
  const sha256 = await sha256File(audio);
  const limbs = limbsFromDigest(sha256);
  // guard the convention from the start: limbs must be < 2^128 decimal digits
  for (const [k, v] of Object.entries(limbs)) {
    if (!/^\d+$/.test(v) || BigInt(v) >= (1n << 128n)) {
      result.config = { audio_sha256: sha256 };
      failNow("hash", `limb ${k} out of 128-bit range — internal convention error`, s);
    }
  }
  result.audio = {
    path: audio, format: ext.slice(1).toUpperCase(), bytes: fs.statSync(audio).size,
    sha256, media_hash_hi: limbs.media_hash_hi, media_hash_lo: limbs.media_hash_lo,
  };
  mark("hash", "ok", `sha256=${sha256} hi=${limbs.media_hash_hi} lo=${limbs.media_hash_lo}`, s);

  // ── Stage 4: prove with the FROZEN v3 artifacts via the local snarkjs API ───
  s = performance.now();
  if (!fs.existsSync(WASM) || !fs.existsSync(ZKEY)) {
    result.config = { wasm: WASM, zkey: ZKEY };
    failNow("prove", "frozen v3 wasm/zkey not found — repo artifacts missing", s);
  }
  const witness = {
    device_id: String(flags.device_id), timestamp: String(flags.timestamp),
    sensor_score: String(flags.sensor_score), gps_lat: String(flags.gps_lat),
    gps_long: String(flags.gps_long),
    media_hash_hi: limbs.media_hash_hi, media_hash_lo: limbs.media_hash_lo,
    valid_claim: "1",
  };
  const inPath = path.join(outDir, "input.json");
  fs.writeFileSync(inPath, JSON.stringify(witness, null, 2) + "\n");
  let res;
  try {
    res = await snarkjs.groth16.fullProve(witness, WASM, ZKEY);
  } catch (e) {
    result.artifacts.input = inPath;
    failNow("prove", `witness/proof generation failed: ${e.message?.split("\n")[0] || e}`, s);
  }
  const proofPath = path.join(outDir, "proof.json");
  const publicPath = path.join(outDir, "public.json");
  fs.writeFileSync(proofPath, JSON.stringify(res.proof, null, 2) + "\n");
  fs.writeFileSync(publicPath, JSON.stringify(res.publicSignals, null, 2) + "\n");
  result.artifacts = { input: inPath, proof: proofPath, public: publicPath,
    detector_output: path.join(outDir, "detector_output.txt"),
    manifest: path.join(outDir, "demo_result.json") };
  mark("prove", "ok", `proof=${proofPath} public=${publicPath}`, s);

  // ── Stage 5: INDEPENDENT verification (separate node process) ───────────────
  s = performance.now();
  const ver = spawnSync(process.execPath, [VERIFY_SCRIPT, audio, proofPath, publicPath],
                        { encoding: "utf8" });
  fs.writeFileSync(path.join(outDir, "verify_output.txt"),
                   (ver.stdout || "") + (ver.stderr || ""));
  if (ver.status !== 0) {
    result.artifacts.verify_output = path.join(outDir, "verify_output.txt");
    failNow("verify", `independent verifier rejected (exit=${ver.status}); see verify_output.txt`, s);
  }
  result.artifacts.verify_output = path.join(outDir, "verify_output.txt");
  mark("verify", "ok", "scripts/verify_media.js ACCEPTED (its own pinned vkey, independent of this bundle)", s);

  result.config = {
    circuit: "circuits/provenance_v3.circom (frozen; unchanged in Step 5)",
    proving_key: { path: ZKEY, note: "frozen Step-3 zkey — NOT regenerated here" },
    wasm: WASM,
    verifier_vkey_pin: "pinned inside scripts/verify_media.js (trusted configuration)",
    snarkjs: "local devDependency (see package.json devDependencies)",
  };
  result.verdict =
    "VERIFIED — proof verification succeeded under scripts/verify_media.js's trusted v3 key, "
    + "and the supplied audio file's SHA-256 equals the proof's hash limbs. This is proof "
    + "verification and file binding only; it is not a claim of authentic audio, capture "
    + "provenance, or truthful metadata, and the detector verdict (recorded above) is not "
    + "enforced by the ZK circuit.";
  writeManifest(EXIT_OK);
  console.log("─".repeat(64));
  console.log(`RESULT : VERIFIED (demo) — proof + file binding. ${Math.round(performance.now() - t0)} ms total.`);
  console.log("         NOT a claim of authentic audio.");
  return EXIT_OK;
}

if (require.main === module) {
  main()
    .then((code) => process.exit(code))
    .catch((e) => { console.error(`[error] ${e.stack || e.message}`); process.exit(EXIT_FAIL); });
}

module.exports = { main, parseArgs };