#!/usr/bin/env node
/**
 * verify_media.js — Independent verifier: audio file + existing v3 proof.
 * (Step 4 of the provenance CLI prototype.)
 *
 *   node scripts/verify_media.js <audio.{wav,flac}> <proof.json> <public.json>
 *       [--vkey <verification_key_v3.json>]   (default: the repo's Step-3 key)
 *       [--expect-vkey-sha256 <64-hex>]       (deliberate key-pin update)
 *
 * Trust boundary:
 *   The verification key is a TRUSTED VERIFIER CONFIGURATION from the repo
 *   (outputs/v3/verification_key_v3.json, SHA-256 pinned below). A key bundled
 *   next to a proof is never used or trusted. If --vkey / --expect-vkey-sha256
 *   are used (deliberate local experiments / key rotation), BOTH values must
 *   come from the trusted verifier side — the prover (and proof bundle) must
 *   never dictate the verification key or its expected hash. A configured key
 *   whose SHA-256 differs from the pin is rejected unless the operator passes
 *   a new --expect-vkey-sha256 explicitly (printed loudly as an override).
 *
 * Checks (fail-closed, each printed):
 *   1. audio file exists, .wav/.flac
 *   2. proof / public / vkey files parse as JSON
 *   3. configured vkey SHA-256 == pinned (or explicit override)
 *   4. public signals: length 4, decimal strings, v3 order
 *      [valid, media_hash_hi, media_hash_lo, valid_claim]; length cross-checked
 *      against the trusted vkey's nPublic
 *   5. valid == "1" AND valid_claim == "1"
 *   6. public limbs == SHA-256(audio) limbs, recomputed here (BigInt only,
 *      same convention as scripts/hash_limbs.js)
 *   7. snarkjs JavaScript API (LOCAL dependency — no global CLI): the actual
 *      boolean from snarkjs.groth16.verify(trustedVk, publicSignals, proof);
 *      false or any thrown exception ⇒ reject (fail-closed)
 *
 * Exit codes: 0 accepted · 1 rejected · 2 usage error.
 * Acceptance never says "authentic audio": success means the supplied
 * file's SHA-256 equals the limbs in a proof that verifies under the
 * trusted key with valid = valid_claim = "1".
 */

const fs = require("fs");
const path = require("path");
const snarkjs = require("snarkjs");               // pinned local devDependency
const { sha256File, limbsFromDigest } = require(path.join(__dirname, "hash_limbs.js"));

// ── Trusted verifier configuration (Step 3 key) ──────────────────────────────
const DEFAULT_VKEY = path.resolve(__dirname, "..", "outputs", "v3", "verification_key_v3.json");
const PINNED_VKEY_SHA256 = "cbae94c0fdbe0295ddf81e92f2e414c757babdd360064d65364c85a52f16e93c";
const EXPECTED_PUBLIC_LEN = 4;
const AUDIO_EXTS = new Set([".wav", ".flac"]);

const EXIT_ACCEPT = 0;
const EXIT_REJECT = 1;
const EXIT_USAGE = 2;

const pass = (msg) => ({ ok: true, msg });
const fail = (msg) => ({ ok: false, msg });

/**
 * Runs `snarkjs groth16 verify` and classifies the ACTUAL result line:
 *   true  ⇔ output contains "snarkJS: OK!"
 *   false ⇔ output contains "Invalid proof"
 *   null  → inconclusive (no recognizable result line) ⇒ caller rejects.
 * snarkjs CLI exit codes alone do not distinguish all outcomes reliably.
 */
/** Pure trust classifier for a snarkjs API verify outcome — fail-closed:
 *  accept ONLY the literal boolean `true`; false / exceptions / anything
 *  else reject. */
function classifySnarkResult(resultOrError) {
  if (resultOrError instanceof Error) {
    return { verified: false, detail: `snarkjs API exception: ${resultOrError.message}` };
  }
  if (resultOrError === true) return { verified: true, detail: "snarkjs.groth16.verify → true" };
  if (resultOrError === false) return { verified: false, detail: "snarkjs.groth16.verify → false (invalid proof)" };
  return { verified: false, detail: `snarkjs.groth16.verify returned ${String(resultOrError)} — refusing to accept` };
}

/** Verify against ALREADY-PARSED trusted artifacts (objects, not paths). */
async function groth16Verify(vkeyObj, pubArray, proofObj) {
  try {
    const ok = await snarkjs.groth16.verify(vkeyObj, pubArray, proofObj);
    return classifySnarkResult(ok);
  } catch (e) {
    return classifySnarkResult(e);
  }
}

function report(checks, accepted) {
  console.log("\n=== verify_media.js — independent verification ===");
  for (const c of checks) console.log(`${c.ok ? "[ OK ]" : "[FAIL]"} ${c.msg}`);
  console.log("─".repeat(64));
  if (accepted) {
    console.log('RESULT : ACCEPT — the supplied file\'s SHA-256 matches the hash limbs of a proof that');
    console.log('         verifies under the trusted v3 key with valid = "1" and valid_claim = "1".');
    console.log('         (This does NOT assert real capture provenance, speaker/origin identity, or truthful metadata.)');
    return EXIT_ACCEPT;
  }
  console.log("RESULT : REJECT");
  return EXIT_REJECT;
}

async function main() {
  const args = process.argv.slice(2);
  let vkeyArg = DEFAULT_VKEY;
  let expectSha = PINNED_VKEY_SHA256;
  const positional = [];
  for (let i = 0; i < args.length; i++) {
    if (args[i] === "--vkey") vkeyArg = path.resolve(args[++i]);
    else if (args[i] === "--expect-vkey-sha256") expectSha = args[++i];
    else positional.push(args[i]);
  }
  const [audioArg, proofArg, pubArg] = positional;
  if (!audioArg || !proofArg || !pubArg) {
    console.error("Usage: node scripts/verify_media.js <audio> <proof.json> <public.json> [--vkey PATH] [--expect-vkey-sha256 HEX]");
    return EXIT_USAGE;
  }

  const checks = [];

  // ── Check 1: audio file ────────────────────────────────────────────────────
  const audio = path.resolve(require(path.join(__dirname, "demo_assets.js")).resolve(audioArg));
  if (!fs.existsSync(audio)) {
    checks.push(fail(`audio file           : ${audio} — not found`));
    return report(checks, false);
  }
  checks.push(pass(`audio file           : ${audio}`));
  const ext = path.extname(audio).toLowerCase();
  if (!AUDIO_EXTS.has(ext)) {
    checks.push(fail(`audio format check   : unsupported extension '${ext}' (expected .wav/.flac)`));
    return report(checks, false);
  }
  checks.push(pass(`audio format check   : ${ext.slice(1).toUpperCase()} accepted`));

  // ── Check 2: proof / public-signals files parse as JSON ────────────────────
  let proof, pub;
  for (const [name, p] of [["proof file", proofArg], ["public-signals file", pubArg]]) {
    const abs = path.resolve(p);
    try {
      const obj = JSON.parse(fs.readFileSync(abs, "utf8"));
      if (name === "proof file") proof = obj;
      else pub = obj;
      checks.push(pass(`${name.padEnd(21)}: ${abs}`));
    } catch (e) {
      checks.push(fail(`${name.padEnd(21)}: ${abs} — missing or not valid JSON (${e.message.split("\n")[0]})`));
      return report(checks, false);
    }
  }
  if (!Array.isArray(pub)) {
    checks.push(fail("public-signal format  : public file is not a JSON array"));
    return report(checks, false);
  }

  // ── Check 3: trusted vkey configuration (never the proof bundle's key) ──────
  let vkey, vkeySha;
  try {
    vkeySha = await sha256File(vkeyArg);
    vkey = JSON.parse(fs.readFileSync(vkeyArg, "utf8"));
    checks.push(pass(`trusted vkey          : ${path.resolve(vkeyArg)}`));
  } catch (e) {
    checks.push(fail(`trusted vkey          : ${vkeyArg} — missing or not valid JSON (${e.message.split("\n")[0]})`));
    return report(checks, false);
  }
  if (vkeySha !== expectSha) {
    checks.push(fail("vkey integrity        : configured key SHA-256 does not match the pinned/expected one\n" +
      `                         configured key : ${vkeySha}\n` +
      `                         pinned/expected: ${expectSha}\n` +
      "                         (deliberate key change? pass --expect-vkey-sha256 <hex> explicitly)"));
    return report(checks, false);
  }
  checks.push(pass("vkey integrity        : SHA-256 matches the pinned v3 key"));
  if (expectSha !== PINNED_VKEY_SHA256) {
    console.log("*** WARNING: operator override — key pin is NOT the Step-3 v3 key ***");
  }
  if (vkey.nPublic !== pub.length) {
    checks.push(fail(`public-signal count   : public file has ${pub.length} signals; trusted vkey declares nPublic=${vkey.nPublic}`));
    return report(checks, false);
  }

  // ── Check 4: public-signal array shape, values, order ───────────────────────
  if (pub.length !== EXPECTED_PUBLIC_LEN) {
    checks.push(fail(`public-signal count   : ${pub.length}, expected ${EXPECTED_PUBLIC_LEN} ` +
      "[valid, media_hash_hi, media_hash_lo, valid_claim]"));
    return report(checks, false);
  }
  const [validPub, hiPub, loPub, claimPub] = pub.map(String);
  const slots = { "public[0] valid": validPub, "public[1] media_hash_hi": hiPub,
                  "public[2] media_hash_lo": loPub, "public[3] valid_claim": claimPub };
  for (const [name, v] of Object.entries(slots)) {
    if (!/^\d+$/.test(v)) {
      checks.push(fail(`public-signal format  : ${name} = ${JSON.stringify(v)} — expected a decimal string`));
      return report(checks, false);
    }
  }
  checks.push(pass("public-signal format  : 4 decimal strings in v3 order [valid, hi, lo, valid_claim]"));

  // ── Check 5: claim gates ────────────────────────────────────────────────────
  if (validPub !== "1" || claimPub !== "1") {
    checks.push(fail(`validity claim        : valid=${validPub}, valid_claim=${claimPub} — both must be "1"`));
    return report(checks, false);
  }
  checks.push(pass('validity claim        : valid = "1" and valid_claim = "1"'));

  // ── Check 6: recompute SHA-256 limbs from the supplied audio file ───────────
  let sha256, limbs;
  try {
    sha256 = await sha256File(audio);
    limbs = limbsFromDigest(sha256);
    checks.push(pass(`audio sha256          : ${sha256}`));
  } catch (e) {
    checks.push(fail(`audio sha256          : hashing failed (${e.message})`));
    return report(checks, false);
  }
  if (limbs.media_hash_hi !== hiPub || limbs.media_hash_lo !== loPub) {
    checks.push(fail("hash binding          : MISMATCH between file and proof\n" +
      `                         limbs from audio: hi=${limbs.media_hash_hi} lo=${limbs.media_hash_lo}\n` +
      `                         limbs in proof  : hi=${hiPub} lo=${loPub}`));
    return report(checks, false);
  }
  checks.push(pass("hash binding          : public limbs equal limbs recomputed from the supplied file"));

  // ── Check 7: snarkjs Groth16 actual boolean result with the trusted key ─────
  const r = await groth16Verify(vkey, pub, proof);
  if (r.verified !== true) {
    checks.push(fail(`groth16 verify        : ${r.detail}`));
    return report(checks, false);
  }
  checks.push(pass(`groth16 verify        : ${r.detail} (trusted vkey)`));

  return report(checks, true);
}

if (require.main === module) {
  main()
    .then((code) => process.exit(code))
    .catch((e) => { console.error(`[error] ${e.stack || e.message}`); process.exit(EXIT_REJECT);
    });
}

// Exported for the trust-boundary tests only (not an API).
module.exports = { groth16Verify, classifySnarkResult, PINNED_VKEY_SHA256, EXIT_ACCEPT, EXIT_REJECT, EXIT_USAGE };