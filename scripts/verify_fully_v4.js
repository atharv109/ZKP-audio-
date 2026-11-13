#!/usr/bin/env node
/**
 * verify_fully_v4.js -- composed independent verification (Step 5, 9 ordered checks).
 *
 *   node scripts/verify_fully_v4.js <audio> <proof.json> <public.json> <record.json>
 *       --policy-file <policy.json>
 *       [--expect-nonce N] [--now <iso> (testing override for freshness)]
 *       [--trusted-pubkey P --expect-pubkey-sha256 H] (deliberate pin override)
 *       [--allow-flagged] (explicit override for flagged=true records)
 *
 * Order (FIX_DESIGN rev 2):
 *   1 Part A' : verify_media_v4.js spawned independently (own pinned v4 vkey)
 *   2 C equality: proof's public C == record.metadata_commitment
 *   3 record structure: version/type/required fields + EXACT key-set match
 *     (unknown extra fields -> REJECT: fail-closed, stated)
 *   4 pinned issuer pubkey (demo-mode pin via scripts/demo_assets.js; see
 *     outputs/v4/PINS.md — the shipped demo public key, not the upstream pin)
 *   5 canonical rebuild + Ed25519 verify
 *   6 freshness: issued_at_utc <= now <= expires_at_utc
 *   7 enrollment policy: flagged -> REJECT absent --allow-flagged
 *   8 session nonce: passed through to Part A' (--expect-nonce)
 *   9 final decision + printed signed detector attestation
 *
 * Exit 0 ACCEPT / 1 REJECT / 2 usage; distinct reason for every failure.
 * Labels as v3: SIMULATED issuer; never a claim of authentic audio.
 */
const { spawnSync } = require("child_process");
const crypto = require("crypto");
const fs = require("fs");
const path = require("path");
const { sha256File } = require(path.join(__dirname, "hash_limbs.js"));
const { canonicalRecordV2, RECORD_TYPE } = require(path.join(__dirname, "issue_capture_record_v4.js"));

const REPO = path.resolve(__dirname, "..");
const DEMO = require(path.join(__dirname, "demo_assets.js")); // demo-asset bootstrap
const VERIFY_SCRIPT = path.join(REPO, "scripts", "verify_media_v4.js");
const EXIT_OK = 0, EXIT_FAIL = 1, EXIT_USAGE = 2;
const DEFAULT_TRUSTED_PUBKEY = require(path.join(__dirname, "demo_assets.js")).issuerPubPath();
const PINNED_PUBKEY_SHA256 = require(path.join(__dirname, "demo_assets.js")).issuerPubkeyPin();
const REQUIRED_FIELDS = ["record_version", "record_type", "file_sha256", "vkey_sha256",
  "metadata_commitment", "det_checkpoint_sha256", "det_threshold", "det_score_decimals6",
  "det_decision", "issued_at_utc", "expires_at_utc", "flagged", "issuer_label",
  "signature_algorithm", "canonical_sha256", "signature"];
const LABEL = "Simulated issuer. Proof verified (independent process), record signed under the " +
  "pinned issuer key, committed metadata bound via C, detector attested at enrollment. NOT " +
  "blockchain anchoring, NOT device attestation, NOT proof of authentic audio or truthful content.";

function parseArgs(argv) {
  const known = new Set(["--policy-file", "--expect-nonce", "--now", "--trusted-pubkey", "--expect-pubkey-sha256", "--allow-flagged"]);
  const flags = {}; const pos = [];
  for (let i = 0; i < argv.length; i++) {
    if (known.has(argv[i])) {
      if (argv[i] === "--allow-flagged") { flags[argv[i]] = true; continue; }
      if (i + 1 >= argv.length) return null;
      flags[argv[i]] = argv[++i];
    } else pos.push(argv[i]);
  }
  return { flags, pos };
}

function failAll(msg) {
  console.log("-".repeat(52));
  console.log(`RESULT : FULL-VERIFY REJECT \u2014 ${msg}`);
  console.log(`          ${LABEL}`);
  return EXIT_FAIL;
}

async function main() {
  const parsed = parseArgs(process.argv.slice(2));
  if (!parsed) { console.error("usage"); return EXIT_USAGE; }
  const { flags, pos } = parsed;
  const [audioArg, proofArg, pubArg, recordArg] = pos;
  if (!audioArg || !proofArg || !pubArg || !recordArg || !flags["--policy-file"]) {
    console.error("Usage: node scripts/verify_fully_v4.js <audio> <proof.json> <public.json> " +
      "<record.json> --policy-file <policy.json> [--expect-nonce N] [--now <iso>] " +
      "[--trusted-pubkey P --expect-pubkey-sha256 H] [--allow-flagged]");
    return EXIT_USAGE;
  }
  const audio = path.resolve(DEMO.resolve(audioArg));
  const checks = [];

  // 1 -- Part A' : independent process (pinned v4 vkey; policy + nonce passed through)
  console.log(`[full4] 1: Part A' -- scripts/verify_media_v4.js (independent process) ...`);
  const child = spawnSync(process.execPath, [VERIFY_SCRIPT, audioArg, proofArg, pubArg,
      "--policy-file", flags["--policy-file"],
      ...(flags["--expect-nonce"] != null ? ["--expect-nonce", flags["--expect-nonce"]] : [])],
    { encoding: "utf8" });
  if (child.status !== 0) {
    console.log((child.stdout || "") + (child.stderr || ""));
    return failAll(`Part A' rejected (verify_media_v4.js exit ${child.status})`);
  }
  checks.push("[ OK ] 1 Part A': proof verifies + file bound + policy/nonce equal (independent process)");

  // 2 -- C equality
  const pub = JSON.parse(fs.readFileSync(path.resolve(pubArg), "utf8"));
  const C = String(pub[1]);
  let record;
  try { record = JSON.parse(fs.readFileSync(path.resolve(recordArg), "utf8")); }
  catch (e) { return failAll(`record unreadable: ${e.message}`); }
  if (record.metadata_commitment !== C) {
    return failAll(`metadata_commitment mismatch: record C ${record.metadata_commitment} != ` +
      `proof public C ${C} (record is for different enrolled metadata, or the proof was re-generated)`);
  }
  checks.push("[ OK ] 2 C equality: record.metadata_commitment == proof C");
  // 2b record<->file binding: the record's signed file_sha256 must name the
  //    presented file (matches v3's "record file_sha256 != file" rejection;
  //    without it a holder-side re-proof over DIFFERENT bytes of the same
  //    committed metadata would pass -- found in the A3 pre-check 2026-11-04)
  {
    const { sha256File: _s } = require(path.join(__dirname, "hash_limbs.js"));
    const fileSha = await _s(audio);
    if (record.file_sha256 !== fileSha)
      return failAll(`record file_sha256 ${record.file_sha256.slice(0, 16)}... != presented-file ` +
        `${fileSha.slice(0, 16)}... -- record is for a DIFFERENT file (v3-closure re-added)`);
    checks.push("[ OK ] 2b record<->file binding: record.file_sha256 == presented file");
  }

  // 3 -- record structure + EXACT key set (fail-closed: unknown fields rejected)
  if (record.record_version !== 2) return failAll(`record_version: ${JSON.stringify(record.record_version)}, supported 2`);
  if (record.record_type !== RECORD_TYPE) return failAll(`record_type: ${JSON.stringify(record.record_type)}`);
  const keys = Object.keys(record);
  const extra = keys.filter((k) => !REQUIRED_FIELDS.includes(k));
  const missing = REQUIRED_FIELDS.filter((k) => !(k in record));
  if (extra.length) return failAll(`unknown record field(s): ${extra.join(", ")} — refusing silently-ignored extras`);
  if (missing.length) return failAll(`record missing field(s): ${missing.join(", ")}`);
  for (const k of REQUIRED_FIELDS) if (typeof record[k] === "undefined")
    return failAll(`record field ${k} undefined`);
  checks.push("[ OK ] 3 record structure: v2 fields complete, no unknown fields");

  // 4 -- pinned issuer key
  const pubPath = flags["--trusted-pubkey"] ? path.resolve(flags["--trusted-pubkey"]) : DEFAULT_TRUSTED_PUBKEY;
  if (flags["--trusted-pubkey"] && !flags["--expect-pubkey-sha256"])
    return failAll("--trusted-pubkey given without --expect-pubkey-sha256 (refusing implicit trust change)");
  let pubPem;
  try { pubPem = fs.readFileSync(pubPath); }
  catch { return failAll(`trusted issuer public key not found: ${pubPath}`); }
  const pubSha = crypto.createHash("sha256").update(pubPem).digest("hex");
  if (pubSha !== (flags["--expect-pubkey-sha256"] || PINNED_PUBKEY_SHA256))
    return failAll(`issuer pubkey pin mismatch: ${pubSha} != pinned ${flags["--expect-pubkey-sha256"] || PINNED_PUBKEY_SHA256}`);
  checks.push(`[ OK ] 4 issuer pubkey pinned: ${pubSha}`);

  // 5 -- canonical rebuild + Ed25519
  const canonical = canonicalRecordV2(record);
  const canonSha = crypto.createHash("sha256").update(Buffer.from(canonical, "utf8")).digest("hex");
  if (record.canonical_sha256 !== canonSha)
    return failAll(`record content altered (canonical digest mismatch: stored ${record.canonical_sha256}, rebuilt ${canonSha})`);
  if (record.signature_algorithm !== "ed25519")
    return failAll(`signature_algorithm: ${JSON.stringify(record.signature_algorithm)}`);
  let sigOk = false;
  try { sigOk = crypto.verify(null, Buffer.from(canonical, "utf8"),
        crypto.createPublicKey(pubPem), Buffer.from(record.signature, "base64")); }
  catch (e) { return failAll(`signature check errored: ${e.message}`); }
  if (!sigOk) return failAll("Ed25519 signature INVALID under the pinned issuer key (altered field or wrong signing key)");
  checks.push("[ OK ] 5 canonical form intact + Ed25519 VALID under pinned issuer key");

  // 6 -- freshness (deterministic --now override for tests)
  const nowIso = flags["--now"] || new Date().toISOString();
  const now = Date.parse(nowIso);
  if (Number.isNaN(now)) { console.error(`[usage] --now is not ISO: ${nowIso}`); return EXIT_USAGE; }
  const issued = Date.parse(record.issued_at_utc);
  const expires = Date.parse(record.expires_at_utc);
  if (Number.isNaN(issued) || Number.isNaN(expires))
    return failAll("record timestamps unparseable (issued_at_utc/expires_at_utc must be ISO)");
  if (now < issued) return failAll(`freshness: now ${nowIso} is BEFORE issued_at_utc ${record.issued_at_utc}`);
  if (now > expires) return failAll(`freshness: record EXPIRED (expires_at_utc ${record.expires_at_utc} < now ${nowIso})`);
  checks.push(`[ OK ] 6 freshness: issued_at <= now <= expires_at (now=${nowIso})`);

  // 7 -- flagged policy (fail-closed)
  if (record.flagged === true && !flags["--allow-flagged"])
    return failAll("record flagged=true at enrollment (spoof detected by the issuer) — " +
      "rejected without --allow-flagged");
  checks.push(`[ OK ] 7 enrollment policy: flagged=${JSON.stringify(record.flagged)}, decision=${record.det_decision}`);

  // 8 -- session nonce already enforced inside Part A' (passed through);
  // record carries no nonce field, so nothing further here.
  checks.push(flags["--expect-nonce"] != null
    ? `[ OK ] 8 session nonce: --expect-nonce ${flags["--expect-nonce"]} enforced in Part A'`
    : "[ OK ] 8 session nonce: none expected (Part A' verified public nonce = 0)");

  // 9 -- final decision with the signed detector attestation printed
  console.log(checks.join("\n"));
  console.log("-".repeat(52));
  console.log("RESULT : FULL-VERIFY ACCEPT -- proof verified (independent process), record signature valid, " +
    "committed metadata bound, file hash consistent, freshness + policy honored.");
  console.log(`ATTEST (issuer-signed at enrollment): decision=${record.det_decision} ` +
    `threshold=${record.det_threshold} score=${record.det_score_decimals6} ` +
    `checkpoint=${record.det_checkpoint_sha256.slice(0, 16)}... flagged=${record.flagged}`);
  console.log(`          ${LABEL}`);
  return EXIT_OK;
}

if (require.main === module) {
  main().then((code) => process.exit(code),
    (e) => { console.error(`[error] ${e.message}`); process.exit(EXIT_FAIL); });
}
module.exports = { main, PINNED_PUBKEY_SHA256, REQUIRED_FIELDS };
