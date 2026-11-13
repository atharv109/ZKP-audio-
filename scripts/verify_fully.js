#!/usr/bin/env node
/**
 * verify_fully.js — Step-8 COMPOSED independent verification.
 *
 *   node scripts/verify_fully.js <audio.{wav,flac}> <proof.json> <public.json> <record.json>
 *       [--trusted-pubkey P --expect-pubkey-sha256 <64-hex>]   (deliberate pin override)
 *
 * Requires BOTH artifacts for the SAME file:
 *   A. the existing valid v3 proof — checked by spawning scripts/verify_media.js
 *      as an INDEPENDENT process on its own pinned trusted vkey (its exit code
 *      0 is the only evidence of proof acceptance);
 *   B. a valid SIMULATED-issuer signed capture record (Ed25519) over the file's
 *      SHA-256 and the trusted v3 vkey digest — verified here from the record's
 *      canonical fields.
 *
 * Issuer-key trust boundary (fail-closed):
 *   The verifier loads the issuer PUBLIC key from its own trusted configuration
 *   — default %USERPROFILE%\zkp-demo-issuer-keys\issuer_public.pem, PINNED by
 *   SHA-256 below. It NEVER accepts a public key supplied alongside the record:
 *   the record carries no key material that verifies anything, and key paths
 *   given on the command line require an explicit `--expect-pubkey-sha256`
 *   printed as an override (same pattern as scripts/verify_media.js's vkey pin).
 *
 * Labels: acceptance means proof verification + file hash binding + valid
 * reference record. The issuer is SIMULATED; a local signature is not blockchain
 * anchoring, device attestation, or proof of truthful metadata/real capture.
 *
 * Exit codes: 0 both artifacts valid · 1 reject/failure · 2 usage error.
 */

const path = require("path");
const { spawnSync } = require("child_process");
const crypto = require("crypto");
const fs = require("fs");
const { sha256File } = require(path.join(__dirname, "hash_limbs.js"));
const { canonicalRecord } = require(path.join(__dirname, "issue_capture_record.js"));

const REPO = path.resolve(__dirname, "..");
const VERIFY_SCRIPT = path.join(REPO, "scripts", "verify_media.js");
const DEFAULT_TRUSTED_VKEY = path.join(REPO, "outputs", "v3", "verification_key_v3.json");

// Trusted issuer public key: resolved via demo_assets.js (this artifact pins
// its shipped demo public key; see outputs/v4/PINS.md and demo_keys/DEMO_ONLY.md).
const DEFAULT_TRUSTED_PUBKEY = require(path.join(__dirname, "demo_assets.js")).issuerPubPath();
const PINNED_PUBKEY_SHA256 = require(path.join(__dirname, "demo_assets.js")).issuerPubkeyPin();
const RECORD_TYPE = "simulated_capture_record";

const EXIT_OK = 0, EXIT_FAIL = 1, EXIT_USAGE = 2;

const LABEL =
  "Simulated issuer. A local signature shows how a trusted reference would close the "
  + "file-substitution gap between proof and file. NOT blockchain anchoring, NOT device "
  + "attestation, NOT proof that the metadata is truthful. Proof part: file-hash binding "
  + "only, never a claim of 'authentic audio'.";

function usage() {
  console.error("Usage: node scripts/verify_fully.js <audio.{wav,flac}> <proof.json> "
    + "<public.json> <record.json> [--trusted-pubkey P --expect-pubkey-sha256 <64-hex>]");
}

function parseArgs(argv) {
  const flags = {}, positional = [];
  const names = new Set(["--trusted-pubkey", "--expect-pubkey-sha256"]);
  for (let i = 0; i < argv.length; i++) {
    if (names.has(argv[i])) {
      if (i + 1 >= argv.length) return null;
      flags[argv[i]] = argv[++i];
    } else positional.push(argv[i]);
  }
  return { flags, positional };
}

function failAll(msg) {
  console.log(`────────────────────────────────────────────────────`);
  console.log(`RESULT : FULL-VERIFY REJECT — ${msg}`);
  console.log(`          ${LABEL}`);
  return EXIT_FAIL;
}

async function main() {
  const parsed = parseArgs(process.argv.slice(2));
  if (!parsed) { usage(); return EXIT_USAGE; }
  const [audioArg, proofArg, pubArg, recordArg] = parsed.positional;
  if (!audioArg || !proofArg || !pubArg || !recordArg) { usage(); return EXIT_USAGE; }
  const audio = path.resolve(require(path.join(__dirname, "demo_assets.js")).resolve(audioArg));
  const recordPath = path.resolve(recordArg);
  const checks = [];

  // ── Part A: existing proof verification — INDEPENDENT process (unchanged) ──
  console.log(`[full] part A: independent process on scripts/verify_media.js (own pinned vkey)...`);
  const ver = spawnSync(process.execPath, [VERIFY_SCRIPT, audio, proofArg, pubArg],
                        { encoding: "utf8" });
  if (ver.status !== 0) {
    console.log((ver.stdout || "") + (ver.stderr || ""));
    return failAll(`existing-proof verification rejected (verify_media.js exit ${ver.status})`);
  }
  checks.push("[ OK ] part A: scripts/verify_media.js ACCEPTED (exit 0, independent process)");

  // ── Part B: record — trusted issuer pubkey, PINNED; never from the record ──
  console.log(`[full] part B: signed capture record (Ed25519, SIMULATED issuer)...`);
  let record;
  try { record = JSON.parse(fs.readFileSync(recordPath, "utf8")); }
  catch (e) { return failAll(`record unreadable: ${e.message}`); }

  if (record.record_version !== 1) return failAll(`record_version: ${JSON.stringify(record.record_version)}, supported 1`);
  if (record.record_type !== RECORD_TYPE) return failAll(`record_type: ${JSON.stringify(record.record_type)}`);
  for (const k of ["file_sha256", "vkey_sha256", "issued_at_utc", "issuer_label"]) {
    if (typeof record[k] !== "string" || record[k].length === 0)
      return failAll(`record field ${k} missing or malformed`);
    checks.push(`[ OK ] record field ${k}`);
  }

  // public key: trusted configuration only
  const pubkeyPath = parsed.flags["--trusted-pubkey"]
    ? path.resolve(parsed.flags["--trusted-pubkey"]) : DEFAULT_TRUSTED_PUBKEY;
  if (parsed.flags["--trusted-pubkey"]) {
    if (!parsed.flags["--expect-pubkey-sha256"]) {
      return failAll("--trusted-pubkey given without --expect-pubkey-sha256 (refusing implicit trust change)");
    }
    console.log(`[full] [OVERRIDE] trusted-pubkey=${pubkeyPath} expect-sha256=${parsed.flags["--expect-pubkey-sha256"]}`);
  }
  let pubPem;
  try { pubPem = fs.readFileSync(pubkeyPath); }
  catch { return failAll(`trusted issuer public key not found at trusted path: ${pubkeyPath}`); }
  const pubSha = crypto.createHash("sha256").update(pubPem).digest("hex");
  const expectedSha = parsed.flags["--expect-pubkey-sha256"] || PINNED_PUBKEY_SHA256;
  if (pubSha !== expectedSha) {
    return failAll(`issuer public key pin mismatch: ${pubSha} != pinned ${expectedSha}`);
  }
  checks.push(`[ OK ] issuer pubkey pinned: ${pubSha} (trusted side: ${pubkeyPath})`);

  // canonical rebuild + Ed25519 verify
  const canonical = canonicalRecord(record);
  const canonicalSha = crypto.createHash("sha256").update(Buffer.from(canonical, "utf8")).digest("hex");
  if (record.canonical_sha256 !== canonicalSha) {
    return failAll(`record content altered (canonical digest mismatch: stored ${record.canonical_sha256}, rebuilt ${canonicalSha})`);
  }
  checks.push("[ OK ] record canonical form intact");
  let sigOk = false;
  try {
    if (record.signature_algorithm !== "ed25519") return failAll(`signature_algorithm: ${JSON.stringify(record.signature_algorithm)}`);
    const pubKeyObj = crypto.createPublicKey(pubPem);
    sigOk = crypto.verify(null, Buffer.from(canonical, "utf8"), pubKeyObj,
                          Buffer.from(record.signature, "base64"));
  } catch (e) { return failAll(`signature check errored: ${e.message}`); }
  if (!sigOk) return failAll("Ed25519 signature INVALID under the pinned issuer key (altered record or wrong signing key)");
  checks.push("[ OK ] record signature: Ed25519 VALID under pinned issuer key");

  // hash identity across all three artifacts and the file
  const audioSha = await sha256File(audio);
  if (record.file_sha256 !== audioSha)
    return failAll(`record file_sha256 ${record.file_sha256} != file ${audioSha} — record is for a DIFFERENT file (or file altered)`);
  checks.push(`[ OK ] file hash identity: record == file ${audioSha}`);
  const vkeySha = await sha256File(DEFAULT_TRUSTED_VKEY);
  if (record.vkey_sha256 !== vkeySha)
    return failAll(`record vkey_sha256 ${record.vkey_sha256} != trusted v3 vkey ${vkeySha} — record binds a different key generation`);
  checks.push("[ OK ] v3 verification-key digest: record == trusted vkey");

  console.log(checks.join("\n"));
  console.log(`────────────────────────────────────────────────────`);
  console.log(`RESULT : FULL-VERIFY ACCEPT — proof verified (independent process) AND record signature valid AND file hash consistent.`);
  console.log(`          ${LABEL}`);
  return EXIT_OK;
}

if (require.main === module) {
  main()
    .then((code) => process.exit(code))
    .catch((e) => { console.error(`[error] ${e.stack || e.message}`); process.exit(EXIT_FAIL); });
}

module.exports = { main, PINNED_PUBKEY_SHA256 };