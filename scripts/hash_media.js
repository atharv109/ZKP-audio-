/**
 * hash_media.js
 *
 * Computes the SHA-256 hash of a media file.
 *
 * Why hash the media file?
 * ────────────────────────
 * The hash acts as a unique fingerprint of the media content.
 * In a full ZKP provenance system the hash would be:
 *   1. Embedded in the ZKP proof as a public input (commitment)
 *   2. Anchored on-chain so anyone can verify the file has not been tampered with
 *   3. Linked to the private metadata (device, timestamp, GPS) without revealing it
 *
 * The current script just prints the hash — blockchain anchoring is a later step.
 *
 * Usage:
 *   node scripts/hash_media.js
 *   node scripts/hash_media.js path/to/custom_file.jpg
 *   npm run hash-media
 */

const fs = require("fs");
const path = require("path");
const crypto = require("crypto");

// ── File hashing ────────────────────────────────────────────────────────────

/**
 * Returns the SHA-256 hex digest of a file.
 * @param {string} filePath - Absolute or relative path to the file.
 * @returns {string} 64-character hex string
 */
function hashFile(filePath) {
  const buffer = fs.readFileSync(filePath);
  return crypto.createHash("sha256").update(buffer).digest("hex");
}

// ── Main ────────────────────────────────────────────────────────────────────

function main() {
  const defaultTarget = path.resolve(__dirname, "../media/sample_001.jpg");
  const targetPath = process.argv[2]
    ? path.resolve(process.argv[2])
    : defaultTarget;

  console.log("\n=== ZKP Provenance — Media File Hasher ===\n");

  if (!fs.existsSync(targetPath)) {
    console.error(`ERROR: File not found: ${targetPath}`);
    console.error(
      "Place a JPEG (or any media file) at media/sample_001.jpg and re-run."
    );
    process.exit(1);
  }

  const stats = fs.statSync(targetPath);
  const hash = hashFile(targetPath);

  console.log("File     :", targetPath);
  console.log("Size     :", stats.size, "bytes");
  console.log("SHA-256  :", hash);
  console.log();
  console.log("This hash is the public commitment to the media content.");
  console.log("In a full system it would be:");
  console.log("  • Passed as a public input to the ZKP circuit");
  console.log("  • Stored on-chain alongside the proof");
  console.log("  • Used by anyone to verify the file was not altered");
  console.log();
}

main();

module.exports = { hashFile };
