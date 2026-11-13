#!/usr/bin/env node
/**
 * issue_capture_record.js — Step-8 ISSUER (SIMULATED trusted issuer).
 *
 *   node scripts/issue_capture_record.js <audio.{wav,flac}> <record.json>
 *       --issuer-key <pem-path-outside-repo>   (or env CAPTURE_ISSUER_KEY)
 *
 * Signs a VERSIONED record containing the file's SHA-256 and the digest of
 * the repo's trusted v3 verification key, using Node's standard Ed25519
 * (node:crypto). There is no existing signing/anchoring mechanism in this
 * repo to reuse (hash_media.js only prints a hash; README names anchoring a
 * future milestone), so this is the prototype's minimal reference signature.
 *
 * Labeling (part of the record): the issuer is a SIMULATED trusted issuer —
 * a local, operator-run signature. This demonstrates how a trusted reference
 * would close the file-substitution gap between proof and file; it is NOT
 * blockchain anchoring, NOT device attestation, and NOT evidence that the
 * provenance metadata is truthful.
 *
 * Key hygiene: the private key must live OUTSIDE this repository; the script
 * refuses an in-repo key path and never prints or copies key material.
 *
 * Record format (canonical fields, signed in this exact order):
 *   record_version, record_type, file_sha256, vkey_sha256,
 *   issued_at_utc, issuer_label   → one UTF-8 string, fields separated by \n.
 */

const crypto = require("crypto");
const fs = require("fs");
const path = require("path");
const { sha256File } = require(path.join(__dirname, "hash_limbs.js"));

const REPO = path.resolve(__dirname, "..");
const DEFAULT_VKEY = path.join(REPO, "outputs", "v3", "verification_key_v3.json");
const RECORD_VERSION = 1;
const RECORD_TYPE = "simulated_capture_record";
const ISSUER_LABEL = "simulated trusted issuer — prototype reference signature; not "
  + "blockchain anchoring, not device attestation, not proof of truthful metadata";

function canonicalRecord(rec) {
  return [
    String(rec.record_version),
    rec.record_type,
    rec.file_sha256,
    rec.vkey_sha256,
    rec.issued_at_utc,
    rec.issuer_label,
    "",
  ].join("\n");
}

async function main() {
  const [audioArg, recordArg, ...rest] = process.argv.slice(2);
  const keyFlagIdx = rest.indexOf("--issuer-key");
  const keyPath = keyFlagIdx >= 0 && rest[keyFlagIdx + 1]
    ? path.resolve(rest[keyFlagIdx + 1])
    : (process.env.CAPTURE_ISSUER_KEY ? path.resolve(process.env.CAPTURE_ISSUER_KEY) : null);
  if (!audioArg || !recordArg || !keyPath) {
    console.error("Usage: node scripts/issue_capture_record.js <audio.{wav,flac}> <record.json> "
      + "--issuer-key <pem-path-outside-repo>");
    return 2;
  }
  if (!fs.existsSync(audioArg)) { console.error(`[issuer] file not found: ${audioArg}`); return 2; }
  if (!fs.existsSync(DEFAULT_VKEY)) {
    console.error(`[issuer] trusted v3 vkey not found: ${DEFAULT_VKEY}`); return 1;
  }
  if (keyPath.startsWith(REPO)) {
    console.error(`[issuer] refusing: private key must live OUTSIDE the repository: ${keyPath}`);
    return 2; // guard against accidental in-repo keys; key material is never printed
  }

  const fields = {
    record_version: RECORD_VERSION,
    record_type: RECORD_TYPE,
    file_sha256: await sha256File(path.resolve(audioArg)),
    vkey_sha256: await sha256File(DEFAULT_VKEY),
    issued_at_utc: new Date().toISOString(),
    issuer_label: ISSUER_LABEL,
  };
  let keyObj;
  try {
    keyObj = crypto.createPrivateKey(fs.readFileSync(keyPath));
  } catch (e) {
    console.error(`[issuer] issuer key unreadable (path outside repo required): ${e.message}`);
    return 1;
  }
  const canonical = canonicalRecord(fields);
  const signature = crypto.sign(null, Buffer.from(canonical, "utf8"), keyObj);

  const record = {
    ...fields,
    signature_algorithm: "ed25519",
    canonical_sha256: crypto.createHash("sha256").update(Buffer.from(canonical, "utf8")).digest("hex"),
    signature: signature.toString("base64"),
  };
  if (fs.existsSync(path.resolve(recordArg))) {
    console.error(`[issuer] refusing to overwrite existing record: ${recordArg}`);
    return 1;
  }
  fs.mkdirSync(path.dirname(path.resolve(recordArg)), { recursive: true });
  fs.writeFileSync(path.resolve(recordArg), JSON.stringify(record, null, 2) + "\n");
  console.log(`[issuer] SIMULATED issuer — issued ${RECORD_TYPE} v${RECORD_VERSION}`);
  console.log(`[issuer]   file     : ${path.resolve(audioArg)}`);
  console.log(`[issuer]   file_sha256 : ${fields.file_sha256}`);
  console.log(`[issuer]   vkey_sha256 : ${fields.vkey_sha256}`);
  console.log(`[issuer]   issuer_label: local reference signature only (see record)`);
  console.log(`[issuer] record written: ${path.resolve(recordArg)}`);
  return 0;
}

module.exports = { canonicalRecord, RECORD_TYPE };

if (require.main === module) {
  main()
    .then((code) => process.exit(code))
    .catch((e) => { console.error(`[error] ${e.stack || e.message}`); process.exit(1); });
}