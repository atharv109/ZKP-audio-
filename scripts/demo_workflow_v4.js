#!/usr/bin/env node
 /**
 * demo_workflow_v4.js -- end-to-end: enroll -> holder-prove -> verify_fully_v4.
 *
 *   node scripts/demo_workflow_v4.js <audio.{wav,flac}> <fresh_outdir>
 *       --metadata <json> --policy <json> [--nonce N] [--expires-hours 24]
 *       [--allow-spoof-enrollment] [--holder-config <json>] [--issuer-key P]
 *       [--handoff P (default: fresh temp file, outside the repo)]
 *       [--weights P] [--aasist-repo P] [--config P]
 *
 * Stages (each in its own process; fail-closed; report has NO secrets):
 *   1 enroll   : issue_capture_record_v4 (real detector; refuses spoof)
 *   2 hold     : provenance_cli_v4 (holder-side refusal paths; no proof on refusal)
 *   3 verify   : verify_fully_v4 (independent; pinned keys/policy)
 *
 * Fresh outdir MANDATORY (refuses existing). Stage timings + verdicts in
 * <outdir>/demo_workflow_report_v4.json (no metadata/salt ever serialized).
 */
const fs = require("fs");
const os = require("os");
const path = require("path");
const { spawnSync } = require("child_process");

const REPO = path.resolve(__dirname, "..");
const DEMO = require(path.join(__dirname, "demo_assets.js")); // demo-asset bootstrap
const ISSUER = path.join(REPO, "scripts", "issue_capture_record_v4.js");
const HOLDER = path.join(REPO, "scripts", "provenance_cli_v4.js");
const VERIFIER = path.join(REPO, "scripts", "verify_fully_v4.js");
const RECORD = "record.json", REPORT = "demo_workflow_report_v4.json";
const EXIT_OK = 0, EXIT_FAIL = 1, EXIT_USAGE = 2;

function parseArgs(argv) {
  const known = new Set(["--metadata", "--policy", "--nonce", "--expires-hours",
    "--allow-spoof-enrollment", "--holder-config", "--issuer-key", "--handoff",
    "--weights", "--aasist-repo", "--config"]);
  const flags = {}; const pos = [];
  for (let i = 0; i < argv.length; i++) {
    if (known.has(argv[i])) {
      if (argv[i] === "--allow-spoof-enrollment") { flags[argv[i]] = true; continue; }
      if (i + 1 >= argv.length) return null;
      flags[argv[i]] = argv[++i];
    } else pos.push(argv[i]);
  }
  return { flags, pos };
}

function stage(name, argv, keepOut) {
  const t = performance.now();
  const r = spawnSync(process.execPath, argv, { encoding: "utf8", cwd: REPO,
    stdio: ["ignore", "pipe", "pipe"] });
  const ms = Math.round(performance.now() - t);
  const out = (r.stdout || "") + (r.stderr || "");
  if (!keepOut) {} else {}
  return { name, argv, code: r.status, ms, out };
}

function main() {
  const parsed = parseArgs(process.argv.slice(2));
  if (!parsed) { console.error("usage"); return EXIT_USAGE; }
  const { flags, pos } = parsed;
  const [audioArg, outDirArg] = pos;
  if (!audioArg || !outDirArg || !flags["--metadata"] || !flags["--policy"]) {
    console.error("Usage: node scripts/demo_workflow_v4.js <audio> <fresh_outdir> " +
      "--metadata <json> --policy <json> [--nonce N] [--expires-hours H] " +
      "[--allow-spoof-enrollment] [--holder-config C] [--issuer-key P] [--handoff P] " +
      "[--weights P] [--aasist-repo P] [--config P]");
    return EXIT_USAGE;
  }
  const audio = path.resolve(DEMO.resolve(audioArg));
  const outDir = path.resolve(outDirArg);
  if (fs.existsSync(outDir)) {
    console.error(`[workflow4] refusing existing outdir: ${outDir}`);
    return EXIT_FAIL;
  }
  const stages = [];
  const report = { version: "demo_workflow_v4", audio, outDir, stages: [],
    verdict: null, attestation: null };
  // ── stage 1: enroll (record path inside outdir; handoff OUTSIDE repo) ────
  const recPath = path.join(outDir, RECORD);
  const handPath = flags["--handoff"] ? path.resolve(flags["--handoff"])
    : path.join(os.tmpdir(), `v4handoff_${process.pid}_${Date.now()}.json`);
  fs.mkdirSync(outDir, { recursive: true });
  const enrollArgv = [ISSUER, audio, recPath, "--metadata", flags["--metadata"],
    "--issuer-key", flags["--issuer-key"] ||
      DEMO.resolve("<HOME>/zkp-demo-issuer-keys/issuer_private.pem"),
    "--handoff", handPath, "--expires-hours", flags["--expires-hours"] || "24",
    "--weights", flags["--weights"],
    "--aasist-repo", flags["--aasist-repo"], "--config", flags["--config"]];
  if (flags["--allow-spoof-enrollment"]) enrollArgv.push("--allow-spoof-enrollment");
  const s1 = stage("enroll", enrollArgv, true);
  stages.push(s1);
  console.log(`[stage] enroll ${s1.code === 0 ? "OK" : "FAIL"} (${s1.ms} ms)`);
  if (s1.code !== 0) {
    console.error((s1.out || "").split("\n").slice(-3).join("\n"));
    const rep = { ...report, verdict: "REJECT_enroll", stderr_tail: (s1.out || "").slice(-500) };
    fs.writeFileSync(path.join(outDir, REPORT), JSON.stringify(rep, null, 2) + "\n");
    return EXIT_FAIL;
  }
  const recObj = JSON.parse(fs.readFileSync(recPath, "utf8"));
  report.attestation = { decision: recObj.det_decision, threshold: recObj.det_threshold,
    score: recObj.det_score_decimals6, flagged: recObj.flagged,
    checkpoint_sha256: recObj.det_checkpoint_sha256.slice(0, 16) + "..." };
  // ── stage 2: holder proves under the policy ───────────────────────────────
  const holderArgv = [HOLDER, audio, path.join(outDir, "proofs"), "--handoff", handPath,
    "--policy", flags["--policy"]];
  if (flags["--nonce"] != null) holderArgv.push("--nonce", flags["--nonce"]);
  if (flags["--holder-config"]) holderArgv.push("--holder-config", flags["--holder-config"]);
  const s2 = stage("hold", holderArgv, true);
  stages.push(s2);
  console.log(`[stage] hold ${s2.code === 0 ? "OK" : "FAIL"} (${s2.ms} ms)`);
  if (s2.code !== 0) {
    console.error((s2.out || "").split("\n").slice(-3).join("\n"));
    const rep = { ...report, verdict: "REJECT_holder", stderr_tail: (s2.out || "").slice(-500) };
    fs.writeFileSync(path.join(outDir, REPORT), JSON.stringify(rep, null, 2) + "\n");
    return EXIT_FAIL;
  }
  const proofPath = path.join(outDir, "proofs", "proof.json");
  const pubPath = path.join(outDir, "proofs", "public.json");
  // ── stage 3: independent composed verification ─────────────────────────────
  const verifyArgv = [VERIFIER, audio, proofPath, pubPath, recPath,
    "--policy-file", flags["--policy"]];
  if (flags["--nonce"] != null) verifyArgv.push("--expect-nonce", flags["--nonce"]);
  const s3 = stage("verify", verifyArgv, true);
  stages.push(s3);
  console.log(`[stage] verify ${s3.code === 0 ? "OK (independent process ACCEPTED)" : "FAIL"} (${s3.ms} ms)`);
  const ok = s3.code === 0;
  report.stages = stages.map(({ name, code, ms }) => ({ name, code, ms }));
  report.verdict = ok ? "FULL-VERIFY ACCEPT" : "FULL-VERIFY REJECT";
  fs.writeFileSync(path.join(outDir, REPORT), JSON.stringify(report, null, 2) + "\n"); 
  console.log("-".repeat(60));
  console.log(ok ? "RESULT : VERIFIED (v4) — proof + record + policy + freshness."
                 : "RESULT : REJECT (v4)");
  console.log(ok ? "        NOT a claim of authentic audio." : (s3.out || "").slice(-300));
  return ok ? EXIT_OK : EXIT_FAIL;
}

if (require.main === module) {
  process.exit(main());
}
module.exports = { parseArgs, main };
