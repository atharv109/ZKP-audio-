#!/usr/bin/env node
/**
 * hash_limbs.js — SHA-256 of a file's exact bytes → decimal limb strings
 * for Circom input JSON (Step 3 of the provenance CLI prototype).
 *
 * The 256-bit digest is split into two 128-bit unsigned integers:
 *   media_hash_hi = first 16 digest bytes (big-endian)
 *   media_hash_lo = last  16 digest bytes (big-endian)
 * Only BigInt is used for limb arithmetic — limbs never pass through a
 * JavaScript Number (which would silently lose bits beyond 2^53).
 *
 * Usage:
 *   node scripts/hash_limbs.js <file>            → prints digest + limbs
 *   node scripts/hash_limbs.js <file> --json out → writes {file, sha256,
 *       media_hash_hi, media_hash_lo} to out for merging into input JSON
 */

const crypto = require("crypto");
const fs = require("fs");
const path = require("path");

function sha256File(filePath) {
  return new Promise((resolve, reject) => {
    const hash = crypto.createHash("sha256");
    const stream = fs.createReadStream(filePath); // exact file bytes
    stream.on("data", (chunk) => hash.update(chunk));
    stream.on("error", reject);
    stream.on("end", () => resolve(hash.digest("hex")));
  });
}

function limbsFromDigest(digestHex) {
  const hi = BigInt("0x" + digestHex.slice(0, 32)); // first 16 bytes
  const lo = BigInt("0x" + digestHex.slice(32));    // last 16 bytes
  // decimal strings via BigInt.toString — never through Number
  return { media_hash_hi: hi.toString(10), media_hash_lo: lo.toString(10) };
}

async function main() {
  const args = process.argv.slice(2);
  const jsonOutIdx = args.indexOf("--json");
  const writeJson = jsonOutIdx !== -1;
  const target = args[0];
  if (!target || (writeJson && !args[jsonOutIdx + 1])) {
    console.error("Usage: node scripts/hash_limbs.js <file> [--json <out>]");
    return 2;
  }
  const filePath = path.resolve(target);
  if (!fs.existsSync(filePath)) {
    console.error(`[error] file not found: ${filePath}`);
    return 2;
  }

  const sha256 = await sha256File(filePath);
  const limbs = limbsFromDigest(sha256);
  if (writeJson) {
    fs.writeFileSync(args[jsonOutIdx + 1], JSON.stringify({
      file: filePath, sha256, ...limbs,
    }, null, 2) + "\n");
    console.log(`wrote ${args[jsonOutIdx + 1]}`);
  } else {
    console.log(JSON.stringify({ file: filePath, sha256, ...limbs }, null, 2));
  }
  return 0;
}

if (require.main === module) {
  main().then((code) => process.exit(code), (err) => {
    console.error(`[error] ${err.message}`);
    process.exit(1);
  });
}

module.exports = { sha256File, limbsFromDigest };