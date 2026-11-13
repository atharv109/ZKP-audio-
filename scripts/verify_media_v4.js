#!/usr/bin/env node
/**
 * verify_media_v4.js -- independent proof verifier for the v4 circuit (Step 4).
 *
 *   node scripts/verify_media_v4.js <audio.{wav,flac}> <proof.json> <public.json>
 *       --policy-file <policy.json> [--expect-nonce N] [--now <iso>]
 *       [--vkey <verification_key_v4.json>] [--expect-vkey-sha256 <64-hex>]
 *
 * Trust boundary (as v3): the verification key comes from the REPOSITORY's
 * trusted configuration (outputs/v4/verification_key_v4.json, SHA-256 pinned
 * below). A vkey bundled with the proof bundle is never trusted; overrides
 * require BOTH --vkey and --expect-vkey-sha256 (printed loudly).
 *
 * Public shape (provenance_v4.circom, snarkjs emits outputs first):
 *   [0]=valid  [1]=C (metadata commitment)  [2]=media_hash_hi  [3]=media_hash_lo
 *   [4]=valid_claim  [5]=session_nonce  [6..8]=allowed_device_0..2
 *   [9]=timestamp_min [10]=timestamp_max [11]=gps_lat_min [12]=gps_lat_max
 *   [13]=gps_long_min [14]=gps_long_max [15]=sensor_min      -> 16 signals
 *
 * Policy loader (--policy-file, validator chose the policy):
 *   keys: device_ids[3], timestamp_range[2], gps_lat_range[2],
 *         gps_long_range[2], sensor_min
 *   every value: integer, >= 0, < 2^width for its comparator bit-width
 *   (timestamp 31, sensor_min 8, lat 19, lon 20 bits; device ids within 30
 *   bits); each range min <= max. Violations exit 2 (usage error, clear reason).
 *   Then all 10 policy PUBLIC signals must equal the policy exactly.
 *
 * Checks: files parse; vkey pin; count/shape; policy equality; nonce
 * (--expect-nonce N required match, else must be 0); valid == valid_claim == 1;
 * SHA-256 of the audio == limbs; snarkjs.groth16.verify literal true.
 *
 * Exit codes: 0 ACCEPT · 1 REJECT · 2 usage error. Acceptance NEVER asserts
 * authentic audio/capture/truth (same scope as v3).
 */
const fs = require("fs");
const path = require("path");
const snarkjs = require("snarkjs");
const { sha256File, limbsFromDigest } = require(path.join(__dirname, "hash_limbs.js"));

const DEFAULT_VKEY = path.resolve(__dirname, "..", "outputs", "v4", "verification_key_v4.json");
const PINNED_VKEY_SHA256 = "a89ef3c25a3c00fc4d35240b994d30b9c58b6d5068f8235e169e9ae319d8b023";
const EXPECTED_PUBLIC_LEN = 16;
const PUBLIC_NAMES = ["valid", "C", "media_hash_hi", "media_hash_lo", "valid_claim",
  "session_nonce", "allowed_device_0", "allowed_device_1", "allowed_device_2",
  "timestamp_min", "timestamp_max", "gps_lat_min", "gps_lat_max",
  "gps_long_min", "gps_long_max", "sensor_min"];
const WIDTHS = { timestamp: 31n, sensor_min: 8n, gps_lat: 19n, gps_long: 20n, device: 30n };
const AUDIO_EXTS = new Set([".wav", ".flac"]);
const EXIT_ACCEPT = 0, EXIT_REJECT = 1, EXIT_USAGE = 2;

const pass = (msg) => ({ ok: true, msg });
const fail = (msg) => ({ ok: false, msg });

function parseArgs(argv) {
  const known = new Set(["--policy-file", "--expect-nonce", "--vkey", "--expect-vkey-sha256"]);
  const flags = {}; const pos = [];
  for (let i = 0; i < argv.length; i++) {
    if (known.has(argv[i])) { if (i + 1 >= argv.length) return null; flags[argv[i]] = argv[++i]; }  // last occurrence wins
    else pos.push(argv[i]);
  }
  return { flags, pos };
}

// policy loader: structural + bit-width + range validation (fail-closed, exit 2)
function validatePolicyText(text) {
  let p;
  try { p = JSON.parse(text); } catch (e) { return { error: `policy file is not valid JSON: ${e.message}` }; }
  const errs = [];
  const ints = (k, arr, width) => {
    for (const v of arr) {
      if (typeof v === "number" && Number.isInteger(v) && v >= 0 && v < (1n << width)) continue;
      errs.push(`${k}: ${JSON.stringify(v)} must be an integer in [0, 2^${width})`);
    }
  };
  if (!Array.isArray(p.device_ids) || p.device_ids.length !== 3)
    errs.push("device_ids: expected exactly 3 slots");
  else ints("device_ids", p.device_ids, WIDTHS.device);
  for (const [k, width] of [["timestamp_range", WIDTHS.timestamp],
                            ["gps_lat_range", WIDTHS.gps_lat],
                            ["gps_long_range", WIDTHS.gps_long]]) {
    if (!Array.isArray(p[k]) || p[k].length !== 2) errs.push(`${k}: expected [min, max]`);
    else {
      ints(k, p[k], width);
      if (p[k].length === 2 && !(p[k][0] <= p[k][1]))
        errs.push(`${k}: min must be <= max (empty range policies are meaningless)`);
    }
  }
  if (typeof p.sensor_min === "number" && Number.isInteger(p.sensor_min)
      && p.sensor_min >= 0 && p.sensor_min < (1n << WIDTHS.sensor_min)) {}
  else errs.push(`sensor_min: expected integer in [0, 2^${WIDTHS.sensor_min})`);
  if (errs.length) return { error: "invalid policy: " + errs.join("; ") };
  return { policy: p };
}

function policyPublics(p) {
  const strs = (a) => a.map(String);
  return [...strs(p.device_ids), ...strs(p.timestamp_range),
          ...strs(p.gps_lat_range), ...strs(p.gps_long_range), String(p.sensor_min)];
}

function report(checks, accepted) {
  console.log("\n=== verify_media_v4.js -- independent verification ===");
  for (const c of checks) console.log(`${c.ok ? "[ OK ]" : "[FAIL]"} ${c.msg}`);
  console.log("-".repeat(64));
  if (accepted) {
    console.log('RESULT : ACCEPT -- the supplied file\'s SHA-256 matches the limbs of a v4 proof that');
    console.log('         verifies under the trusted v4 key with valid = valid_claim = "1", the proof\'s');
    console.log('         10 policy signals equal the verifier policy, and the nonce check passed.');
    console.log('         (This does NOT assert real capture, provenance, or "authentic audio".)');
    return EXIT_ACCEPT;
  }
  console.log("RESULT : REJECT");
  return EXIT_REJECT;
}

async function main() {
  const parsed = parseArgs(process.argv.slice(2));
  if (!parsed) { console.error("usage error"); return EXIT_USAGE; }
  const { flags, pos } = parsed;
  const [audioArg, proofArg, pubArg] = pos;
  if (!audioArg || !proofArg || !pubArg || !flags["--policy-file"]) {
    console.error("Usage: node scripts/verify_media_v4.js <audio> <proof.json> <public.json> " +
      "--policy-file <policy.json> [--expect-nonce N] [--vkey P --expect-vkey-sha256 H]");
    return EXIT_USAGE;
  }
  const checks = [];
  const audio = path.resolve(require(path.join(__dirname, "demo_assets.js")).resolve(audioArg));
  if (!fs.existsSync(audio)) {
    checks.push(fail(`audio file: ${audio} — not found`)); return report(checks, false);
  }
  checks.push(pass(`audio file: ${audio}`));
  const ext = path.extname(audio).toLowerCase();
  if (!AUDIO_EXTS.has(ext)) {
    checks.push(fail(`audio format: unsupported extension '${ext}' (.wav/.flac expected)`));
    return report(checks, false);
  }
  checks.push(pass(`audio format: ${ext.slice(1).toUpperCase()}`));
  let proof, pub;
  for (const [name, p] of [["proof", proofArg], ["public", pubArg]]) {
    const abs = path.resolve(p);
    try { const o = JSON.parse(fs.readFileSync(abs, "utf8"));
          if (name === "proof") proof = o; else pub = o;
          checks.push(pass(`${name}: ${abs}`)); }
    catch (e) { checks.push(fail(`${name}: ${abs} — missing/invalid JSON`)); return report(checks, false); }
  }
  if (!Array.isArray(pub)) {
    checks.push(fail("public: not a JSON array")); return report(checks, false);
  }
  // policy: validate THEN require equality with the proof's 10 policy signals
  const pol = validatePolicyText(fs.readFileSync(path.resolve(flags["--policy-file"]), "utf8"));
  if (pol.error) { console.error(`[policy] ${pol.error}`); return EXIT_USAGE; }
  checks.push(pass(`policy: validated (${path.resolve(flags["--policy-file"])})`));
  // vkey: trusted config only
  let vkey, vkeySha;
  const vkeyArg = flags["--vkey"] ? path.resolve(flags["--vkey"]) : DEFAULT_VKEY;
  const expectedSha = flags["--expect-vkey-sha256"] || PINNED_VKEY_SHA256;
  try { vkeySha = await sha256File(vkeyArg); vkey = JSON.parse(fs.readFileSync(vkeyArg, "utf8"));
        checks.push(pass(`trusted vkey: ${vkeyArg}`)); }
  catch (e) { checks.push(fail(`trusted vkey: ${vkeyArg} — missing/invalid`)); return report(checks, false); }
  if (vkeySha !== expectedSha) {
    checks.push(fail(`vkey integrity: configured ${vkeySha} != pinned ${expectedSha} ` +
      "(deliberate key change? pass --expect-vkey-sha256 explicitly)"));
    return report(checks, false);
  }
  checks.push(pass("vkey integrity: SHA-256 matches the pinned v4 key"));
  if (flags["--vkey"]) console.log("*** WARNING: operator key override in use ***");
  if (vkey.nPublic !== EXPECTED_PUBLIC_LEN || pub.length !== EXPECTED_PUBLIC_LEN) {
    checks.push(fail(`public count: pubs=${pub.length}, vkey nPublic=${vkey.nPublic}, expected ${EXPECTED_PUBLIC_LEN}`));
    return report(checks, false);
  }
  checks.push(pass(`public count: ${EXPECTED_PUBLIC_LEN}`));
  for (let i = 0; i < EXPECTED_PUBLIC_LEN; i++) {
    if (!/^\d+$/.test(String(pub[i]))) {
      checks.push(fail(`public ${i}: expected decimal string, got ${JSON.stringify(pub[i])}`));
      return report(checks, false);
    }
  }
  checks.push(pass("public format: 16 decimal strings"));
  // policy equality
  const polPubs = policyPublics(pol.policy);
  for (let i = 0; i < 10; i++) {
    if (pub[6 + i] !== polPubs[i]) {
      checks.push(fail(`policy equality: public[${PUBLIC_NAMES[6 + i]}] = ${pub[6 + i]}, ` +
        `policy = ${polPubs[i]} (proof computed under a different policy)`));
      return report(checks, false);
    }
  }
  checks.push(pass("policy equality: all 10 policy signals match the verifier policy"));
  // nonce
  const nonce = String(pub[5]);
  if (flags["--expect-nonce"] != null) {
    if (nonce !== String(flags["--expect-nonce"])) {
      checks.push(fail(`nonce: public session_nonce=${nonce}, expected ${flags["--expect-nonce"]} ` +
        "(stale or forged session binding)"));
      return report(checks, false);
    }
    checks.push(pass(`nonce: session_nonce matches --expect-nonce ${flags["--expect-nonce"]}`));
  } else if (nonce !== "0") {
    checks.push(fail(`nonce: session_nonce=${nonce} but no --expect-nonce given (must be 0 or checked)`));
    return report(checks, false);
  } else checks.push(pass("nonce: session_nonce = 0 (no session binding)"));
  // claim gates
  if (pub[0] !== "1" || pub[4] !== "1") {
    checks.push(fail(`claim gates: valid=${pub[0]}, valid_claim=${pub[4]} — both must be "1"`));
    return report(checks, false);
  }
  checks.push(pass('claim gates: valid = "1" and valid_claim = "1"'));
  // hash recompute
  let sha, limbs;
  try { sha = await sha256File(audio); limbs = limbsFromDigest(sha);
        checks.push(pass(`audio sha256: ${sha}`)); }
  catch (e) { checks.push(fail(`audio sha256: hashing failed (${e.message})`)); return report(checks, false); }
  if (limbs.media_hash_hi !== pub[2] || limbs.media_hash_lo !== pub[3]) {
    checks.push(fail("hash binding: MISMATCH between file and proof\n" +
      `       limbs from audio: hi=${limbs.media_hash_hi} lo=${limbs.media_hash_lo}\n` +
      `       limbs in proof  : hi=${pub[2]} lo=${pub[3]}`));
    return report(checks, false);
  }
  checks.push(pass("hash binding: limbs equal the recomputed file digest"));
  // real snarkjs verify: literal true only
  let ok = null, detail = "";
  try { ok = await snarkjs.groth16.verify(vkey, pub, proof); } catch (e) { detail = e.message; }
  if (ok !== true) {
    checks.push(fail(`groth16 verify: not literal true (${ok === false ? "invalid proof" : JSON.stringify(ok) + (detail ? " — " + detail : "")}) ` +
      "-- fail-closed"));
    return report(checks, false);
  }
  checks.push(pass("groth16 verify: true (trusted v4 vkey)"));
  return report(checks, true);
}

if (require.main === module) {
  main().then((code) => process.exit(code), (e) => {
    console.error(`[error] ${e.message}`); process.exit(EXIT_REJECT);
  });
}
module.exports = { main, validatePolicyText, policyPublics, PINNED_VKEY_SHA256 };
