#!/usr/bin/env node
/**
 * issue_capture_record_v4.js -- v4 ISSUER (simulated trusted issuer), Part B.
 *
 *   node scripts/issue_capture_record_v4.js <audio.{wav,flac}> <record.json>
 *       --metadata <json> --handoff <json-path-OUTSIDE-repo>
 *       --issuer-key <pem-path-OUTSIDE-repo>
 *       [--expires-hours 24] [--allow-spoof-enrollment]
 *       [--weights P] [--aasist-repo P] [--config P]
 *       (env fallbacks: AASIST_WEIGHTS / AASIST_REPO / AASIST_CONFIG; threshold
 *        env DET_THRESHOLD -- protocol default 1.7635419737, recorded in the
 *        record's det_threshold field)
 *
 * Steps (per FIX_DESIGN.md rev 2):
 *   1. validate audio, paths (key + handoff OUTSIDE the repo), metadata
 *      well-formedness (five int keys, enrollment reference policy, bit widths)
 *   2. run AASIST-L itself (fresh detection; threshold 1.7635419737 explicit)
 *   3. refuse det_decision = spoof (exit 1, no record) unless
 *      --allow-spoof-enrollment -> flagged=true record
 *   4. generate a cryptographically random salt (32 bytes, reduced mod p)
 *   5. compute C = Poseidon(m1..m5, salt) via WITNESS CALCULATION on the v4
 *      circuit (must equal the circuit's C; cross-checked against circoblibjs)
 *   6. sign the v2 record (record_version 2) Ed25519 under the pinned issuer key
 *   7. write the PRIVATE handoff (metadata + salt) outside the repo; NEVER
 *      print metadata or salt values
 *
 * Same trust/hygiene rules as v3: key must live outside the repo, refuse to
 * overwrite an existing record, issuer pubkey pin resolved via demo_assets.js
 * (this artifact pins its shipped demo public key; see outputs/v4/PINS.md).
 * The issuer is a SIMULATED trusted issuer (same labels as v3).
 */
const crypto = require("crypto");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { spawnSync } = require("child_process");

const REPO = path.resolve(__dirname, "..");
const DEMO = require(path.join(__dirname, "demo_assets.js")); // demo-asset bootstrap
const DEFAULT_VKEY = path.join(REPO, "outputs", "v4", "verification_key_v4.json");
const WASM = path.join(REPO, "outputs", "v4", "provenance_v4_js", "provenance_v4.wasm");
const DETECTOR = path.join(REPO, "audio_benchmark", "detect_audio.py");
const DET_THRESHOLD = process.env.DET_THRESHOLD || "1.7635419737";
const RECORD_TYPE = "simulated_capture_record";
const ISSUER_LABEL = "simulated trusted issuer - prototype reference signature; not "
  + "blockchain anchoring, not device attestation, not proof of truthful metadata";
const BN254_P = 21888242871839275222246405745257275088548364400416034343698204186575808495617n;

// enrollment reference policy = the frozen v3 rule bounds (FIX_DESIGN trust story)
const REFERENCE_POLICY = {
  device_ids: [1024, 2048, 4096],
  timestamp: [1780278000, 1780867200],
  sensor_min: 70,
  gps_lat: [407400, 408400],
  gps_long: [778000, 779200],
};
// comparator bit-widths inherited from v3 (FIX_DESIGN 1b limitation)
const BIT_WIDTHS = { timestamp: 31, sensor_score: 8, gps_lat: 19, gps_long: 20 };

const META_KEYS = ["device_id", "timestamp", "sensor_score", "gps_lat", "gps_long"];
const CANON_FIELDS = ["record_version", "record_type", "file_sha256", "vkey_sha256",
  "metadata_commitment", "det_checkpoint_sha256", "det_threshold",
  "det_score_decimals6", "det_decision",
  "issued_at_utc", "expires_at_utc", "flagged", "issuer_label"];

function canonicalRecordV2(rec) {
  return CANON_FIELDS.map((k) => {
    if (k === "flagged") return rec.flagged ? "true" : "false";
    return String(rec[k]);
  }).join("\n") + "\n";
}

function sha256File(p) {
  return crypto.createHash("sha256").update(fs.readFileSync(p)).digest("hex");
}

function parseArgs(argv) {
  const flags = {}; const pos = [];
  for (let i = 0; i < argv.length; i++) {
    if (["--metadata", "--handoff", "--issuer-key", "--expires-hours",
         "--allow-spoof-enrollment", "--weights", "--aasist-repo", "--config"]
        .includes(argv[i])) {
      if (argv[i] === "--allow-spoof-enrollment") { flags[argv[i]] = true; continue; }
      flags[argv[i]] = argv[++i];
    } else pos.push(argv[i]);
  }
  return { flags, pos };
}

function outsideRepo(p) {
  const abs = path.resolve(p);
  return !abs.toLowerCase().startsWith(REPO.toLowerCase() + path.sep)
      && abs.toLowerCase() !== REPO.toLowerCase();
}

function validateMetadata(m) {
  const errs = [];
  for (const k of META_KEYS)
    if (!Number.isInteger(m[k])) errs.push(`${k}: expected integer`);
  if (errs.length) return errs;
  if (!REFERENCE_POLICY.device_ids.includes(m.device_id))
    errs.push(`device_id ${m.device_id} not in enrollment reference set ` +
              REFERENCE_POLICY.device_ids.join(","));
  const [t0, t1] = REFERENCE_POLICY.timestamp;
  if (m.timestamp < t0 || m.timestamp > t1)
    errs.push(`timestamp ${m.timestamp} outside enrollment reference [${t0},${t1}]`);
  if (m.timestamp >= 2 ** BIT_WIDTHS.timestamp) errs.push("timestamp exceeds 31-bit comparator");
  if (m.sensor_score < REFERENCE_POLICY.sensor_min)
    errs.push(`sensor_score ${m.sensor_score} below enrollment minimum ${REFERENCE_POLICY.sensor_min}`);
  if (m.sensor_score >= 2 ** BIT_WIDTHS.sensor_score)
    errs.push("sensor_score exceeds 8-bit comparator");
  if (m.gps_lat < REFERENCE_POLICY.gps_lat[0] || m.gps_lat > REFERENCE_POLICY.gps_lat[1])
    errs.push(`gps_lat ${m.gps_lat} outside enrollment reference ` +
              `[${REFERENCE_POLICY.gps_lat[0]},${REFERENCE_POLICY.gps_lat[1]}]`);
  if (m.gps_lat >= 2 ** BIT_WIDTHS.gps_lat) errs.push("gps_lat exceeds 19-bit comparator");
  if (m.gps_long < REFERENCE_POLICY.gps_long[0] || m.gps_long > REFERENCE_POLICY.gps_long[1])
    errs.push(`gps_long ${m.gps_long} outside enrollment reference ` +
              `[${REFERENCE_POLICY.gps_long[0]},${REFERENCE_POLICY.gps_long[1]}]`);
  if (m.gps_long >= 2 ** BIT_WIDTHS.gps_long) errs.push("gps_long exceeds 20-bit comparator");
  return errs;
}

function runDetector(flags, audio) {
  const args = [DETECTOR, audio, "--threshold", DET_THRESHOLD];
  for (const [flag, envKey] of [["--weights", "weights"], ["--aasist-repo", "aasist_repo"],
                                ["--config", "config"]]) {
    const v = DEMO.resolve(flags[flag] || process.env[envKey.toUpperCase()]);
    if (!v) { console.error(`[issuer] missing model asset: pass ${flag}`); return null; }
    args.push(flag, v);
  }
  const det = spawnSync("python", args, { encoding: "utf8", cwd: REPO });
  const txt = (det.stdout || "") + (det.stderr || "");
  if (det.status !== 0) {
    console.error(`[issuer] detector failed (exit ${det.status}): ` +
                  txt.split("\n").slice(-2).join(" | "));
    return null;
  }
  const m = (re) => { const x = txt.match(re); return x ? x[1] : null; };
  const score = m(/^score\s+:\s+([-+0-9.eE]+)$/m);
  const decision = m(/^decision\s+:\s+(bonafide|spoof)$/m);
  const ckpt = m(/^checkpoint_sha256\s+:\s+([0-9a-f]{64})$/m);
  if (score == null || decision == null || ckpt == null) {
    console.error("[issuer] detector output unparseable");
    return null;
  }
  return { score, decision, checkpoint_sha256: ckpt, raw: txt };
}

async function computeC(metadata, saltStr) {
  // C via WITNESS CALCULATION on the v4 circuit; defaults are the enrollment
  // REFERENCE_POLICY publics (record-independent; per-verifier policies are
  // chosen later by the holder's verifier)
  const wtns = path.join(os.tmpdir(), `iv4witness_${process.pid}.wtns`);
  const input = {
    ...Object.fromEntries(META_KEYS.map((k) => [k, String(metadata[k])])),
    salt: saltStr,
    media_hash_hi: "0",     // placeholder limbs: C does not depend on them
    media_hash_lo: "0",
    valid_claim: "1",
    session_nonce: "0",
  };
  const [d0, d1, d2] = REFERENCE_POLICY.device_ids;
  input.allowed_device_0 = String(d0); input.allowed_device_1 = String(d1);
  input.allowed_device_2 = String(d2);
  input.timestamp_min = String(REFERENCE_POLICY.timestamp[0]);
  input.timestamp_max = String(REFERENCE_POLICY.timestamp[1]);
  input.gps_lat_min = String(REFERENCE_POLICY.gps_lat[0]);
  input.gps_lat_max = String(REFERENCE_POLICY.gps_lat[1]);
  input.gps_long_min = String(REFERENCE_POLICY.gps_long[0]);
  input.gps_long_max = String(REFERENCE_POLICY.gps_long[1]);
  input.sensor_min = String(REFERENCE_POLICY.sensor_min);
  const snarkjs = require("snarkjs");
  try {
    await snarkjs.wtns.calculate(input, WASM, wtns);
    // wtns.exportJson returns the raw witness array (w[i] = wire i value)
    const wjson = await snarkjs.wtns.exportJson(wtns);
    // resolve main.C's wire index from provenance_v4.sym:
    // format "<wire>:<type>,<idx>,<componentId>,main.C" (name is the last field)
    let cIdx;
    const symText = fs.readFileSync(
      path.join(REPO, "outputs", "v4", "provenance_v4.sym"), "utf8");
    // sym format: "wireIdx,name,idType,componentId,componentName" (name last)
    for (const line of symText.split("\n")) {
      const fields = line.trim().split(",");
      if (fields[fields.length - 1] === "main.C") { cIdx = parseInt(fields[0], 10); break; }
    }
    if (cIdx == null) throw new Error("main.C not found in provenance_v4.sym");
    const C = BigInt(wjson[cIdx]);
    try { fs.unlinkSync(wtns); } catch {}
    return C;
  } catch (e) {
    try { fs.unlinkSync(wtns); } catch {}
    throw e;
  }
}

async function main() {
  const { flags, pos } = parseArgs(process.argv.slice(2));
  // demo-asset bootstrap: nominal/excluded-resource paths map onto shipped
  // demo assets (see scripts/demo_assets.js); real files pass through.
  const [audioArg, recordArg] = [DEMO.resolve(pos[0]), pos[1]];
  if (!audioArg || !recordArg || !flags["--metadata"] || !flags["--handoff"] || !flags["--issuer-key"]) {
    console.error("Usage: node scripts/issue_capture_record_v4.js <audio> <record.json> "
      + "--metadata <json> --handoff <json-outside-repo> --issuer-key <pem-outside-repo> "
      + "[--expires-hours 24] [--allow-spoof-enrollment] [--weights P] [--aasist-repo P] [--config P]");
    return 2;
  }
  if (!fs.existsSync(audioArg)) { console.error(`[issuer] audio not found: ${audioArg}`); return 2; }
  if (!fs.existsSync(DEFAULT_VKEY)) { console.error(`[issuer] v4 vkey missing: ${DEFAULT_VKEY}`); return 1; }
  if (!fs.existsSync(WASM)) { console.error(`[issuer] v4 wasm missing: ${WASM}`); return 1; }
  const keyPath = path.resolve(DEMO.resolve(flags["--issuer-key"]));
  const handPath = path.resolve(flags["--handoff"]);
  if (!outsideRepo(keyPath)) {
    console.error(`[issuer] refusing: issuer key must live OUTSIDE the repository: ${keyPath}`); return 2;
  }
  if (!outsideRepo(handPath)) {
    console.error(`[issuer] refusing: handoff must be written OUTSIDE the repository: ${handPath}`); return 2;
  }
  if (fs.existsSync(path.resolve(recordArg))) {
    console.error(`[issuer] refusing to overwrite existing record: ${recordArg}`); return 1;
  }
  let metadata;
  try {
    metadata = JSON.parse(fs.readFileSync(flags["--metadata"], "utf8"));
  } catch (e) { console.error(`[issuer] metadata unreadable: ${e.message}`); return 1; }
  const errs = validateMetadata(metadata);
  if (errs.length) {
    console.error(`[issuer] metadata invalid (enrollment reference policy / bit widths):`);
    for (const e of errs) console.error(`  - ${e}`);
    return 1;
  }
  const det = runDetector(flags, path.resolve(audioArg));
  if (!det) return 1;
  let flagged = false;
  if (det.decision === "spoof") {
    if (!flags["--allow-spoof-enrollment"]) {
      console.error(`[issuer] refusing: enrollment decision = spoof (score ${det.score} `
        + `at threshold ${DET_THRESHOLD}). No record written. `
        + `(Use --allow-spoof-enrollment to issue a flagged=true record.)`);
      return 1;
    }
    console.error("[issuer] OVERRIDE: --allow-spoof-enrollment -> issuing flagged=true record");
    flagged = true;
  }
  const saltRaw = crypto.randomBytes(32);
  const saltBig = BigInt("0x" + saltRaw.toString("hex")) % BN254_P;
  const saltStr = saltBig.toString(10);
  let C;
  try { C = await computeC(metadata, saltStr); }
  catch (e) { console.error(`[issuer] witness calculation failed: ${e.message}`); return 1; }
  const now = new Date();
  const expiresHours = parseFloat(flags["--expires-hours"] ?? "24");
  if (!Number.isFinite(expiresHours) || expiresHours <= 0) {
    console.error("[issuer] --expires-hours must be a positive number"); return 2;
  }
  const fields = {
    record_version: 2,
    record_type: RECORD_TYPE,
    file_sha256: sha256File(path.resolve(audioArg)),
    vkey_sha256: sha256File(DEFAULT_VKEY),
    metadata_commitment: C.toString(10),
    det_checkpoint_sha256: det.checkpoint_sha256,
    det_threshold: DET_THRESHOLD,
    det_score_decimals6: Number(det.score).toFixed(6),
    det_decision: det.decision,
    issued_at_utc: now.toISOString(),
    expires_at_utc: new Date(now.getTime() + expiresHours * 3600000).toISOString(),
    flagged,
    issuer_label: ISSUER_LABEL,
  };
  let keyObj;
  try { keyObj = crypto.createPrivateKey(fs.readFileSync(keyPath)); }
  catch (e) { console.error(`[issuer] issuer key unreadable: ${e.message}`); return 1; }
  const canonical = canonicalRecordV2(fields);
  const signature = crypto.sign(null, Buffer.from(canonical, "utf8"), keyObj);
  const record = { ...fields,
    signature_algorithm: "ed25519",
    canonical_sha256: crypto.createHash("sha256").update(Buffer.from(canonical, "utf8")).digest("hex"),
    signature: signature.toString("base64") };
  fs.mkdirSync(path.dirname(path.resolve(recordArg)), { recursive: true });
  fs.writeFileSync(path.resolve(recordArg), JSON.stringify(record, null, 2) + "\n");
  const handoff = {
    metadata: { device_id: metadata.device_id, timestamp: metadata.timestamp,
                sensor_score: metadata.sensor_score, gps_lat: metadata.gps_lat,
                gps_long: metadata.gps_long },
    salt: saltStr,
    metadata_commitment: C.toString(10),
    issued_at_utc: fields.issued_at_utc,
  };
  fs.mkdirSync(path.dirname(handPath), { recursive: true });
  fs.writeFileSync(handPath, JSON.stringify(handoff, null, 2) + "\n");
  console.log(`[issuer] v4 SIMULATED issuer -- issued ${RECORD_TYPE} v1(record_version 2)`);
  console.log(`[issuer]   file             : ${path.resolve(audioArg)}`);
  console.log(`[issuer]   file_sha256      : ${fields.file_sha256}`);
  console.log(`[issuer]   vkey_sha256 (v4) : ${fields.vkey_sha256}`);
  console.log(`[issuer]   metadata_commitment C          : ${C.toString(10)}`);
  console.log(`[issuer]   det : decision=${det.decision} threshold=${DET_THRESHOLD} score=${fields.det_score_decimals6}`);
  console.log(`[issuer]   checkpoint_sha256: ${fields.checkpoint_sha256 ?? det.checkpoint_sha256}`);
  console.log(`[issuer]   flagged          : ${flagged}`);
  console.log(`[issuer]   expires_at_utc   : ${fields.expires_at_utc}`);
  console.log(`[issuer]   handoff (private, outside repo): ${handPath}`);
  console.log(`[issuer] record written: ${path.resolve(recordArg)}`);
  return 0;
}

if (require.main === module) {
  main().then((code) => process.exit(code))
    .catch((e) => { console.error(`[error] ${e.stack || e.message}`); process.exit(1); });
}

module.exports = { canonicalRecordV2, RECORD_TYPE, REFERENCE_POLICY, computeC, BIT_WIDTHS };
