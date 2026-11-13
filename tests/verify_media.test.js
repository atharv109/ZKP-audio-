/** Trust-boundary tests for scripts/verify_media.js (Step 4). Run: node --test tests/verify_media.test.js
 *
 * NOTE: requiring scripts/verify_media.js loads snarkjs, whose worker threads
 * keep the event loop alive after tests finish — the node --test runner would
 * hang waiting for it. The after() hook below force-exits with the runner's
 * recorded exit code (tests keep reporting normally).
 */
const test = require("node:test");
const assert = require("node:assert");
const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const REPO = path.resolve(__dirname, "..");
const VM = path.join(REPO, "scripts", "verify_media.js");

const DEMO = require(path.join(REPO, "scripts", "demo_assets.js"));
// v3 binding assets are relocated onto shipped demo assets (scripts/demo_assets.js);
// tests SKIP with a clear message instead of failing if they are not ready.
const AUDIO = DEMO.resolve(path.join(REPO, "audio_benchmark", "data", "bonafide", "bon_00.wav"));
const V3_READY = ["outputs/v3/proof_v3.json", "outputs/v3/public_v3.json", "outputs/v3/verification_key_v3.json", "outputs/verification_key.json", "scripts/verify_media.js"].every((rel) => fs.existsSync(path.join(REPO, rel))) && fs.existsSync(AUDIO);
const testA = V3_READY ? test : (name, fn) =>
  test(name, (t) => t.skip("v3 demo assets not ready (proof/vkey/audio binding missing) | see README, 'Demo assets'"));

const PROOF = path.join(REPO, "outputs", "v3", "proof_v3.json");
const PUB = path.join(REPO, "outputs", "v3", "public_v3.json");
const VKEY_V3 = path.join(REPO, "outputs", "v3", "verification_key_v3.json");
const VKEY_V2 = path.join(REPO, "outputs", "verification_key.json"); // NOT the v3 key

function run(...args) {
  return spawnSync(process.execPath, [VM, ...args], { encoding: "utf8" });
}
function scratch() { return fs.mkdtempSync(path.join(os.tmpdir(), "vm-test-")); }
function jsonCopy(src, mut, dir, name) {
  const dst = path.join(dir, name);
  const obj = JSON.parse(fs.readFileSync(src, "utf8"));
  mut(obj);
  fs.writeFileSync(dst, JSON.stringify(obj));
  return dst;
}

// ── snarkjs result classifier (the "actual boolean result" guarantee) ────────
const { groth16Verify, classifySnarkResult, PINNED_VKEY_SHA256 } = require(VM);

testA("classifier: literal boolean true is the ONLY accepting result", () => {
  assert.strictEqual(classifySnarkResult(true).verified, true);
  assert.strictEqual(classifySnarkResult(false).verified, false);
  assert.strictEqual(classifySnarkResult("true").verified, false);   // not `true === true`
  assert.strictEqual(classifySnarkResult(1).verified, false);
  assert.strictEqual(classifySnarkResult(new Error("boot failure")).verified, false);
});

testA("groth16Verify: honest artifacts → verified true (REAL snarkjs API call)", async () => {
  const fs = require("node:fs");
  const vk = JSON.parse(fs.readFileSync(VKEY_V3, "utf8"));
  const pub = JSON.parse(fs.readFileSync(PUB, "utf8"));
  const proof = JSON.parse(fs.readFileSync(PROOF, "utf8"));
  const r = await groth16Verify(vk, pub, proof);
  assert.strictEqual(r.verified, true);
});

testA("groth16Verify: tampered public limb → verified false (REAL snarkjs API call)", async () => {
  const fs = require("node:fs");
  const vk = JSON.parse(fs.readFileSync(VKEY_V3, "utf8"));
  const pub = JSON.parse(fs.readFileSync(PUB, "utf8"));
  const proof = JSON.parse(fs.readFileSync(PROOF, "utf8"));
  const r = await groth16Verify(vk, [pub[0], (BigInt(pub[1]) + 1n).toString(), pub[2], pub[3]], proof);
  assert.strictEqual(r.verified, false);
});

testA("groth16Verify: malformed vkey object → exception caught, verified false", async () => {
  const r = await groth16Verify({ nPublic: 4 }, ["1", "2", "3", "1"], { fake: true });
  assert.strictEqual(r.verified, false);
  assert.match(r.detail, /exception|invalid|error|refusing/i);
});

// ── pinned key identity ──────────────────────────────────────────────────────
testA("pin in code equals the Step-3 vkey on disk", async () => {
  const { sha256File } = require(path.join(REPO, "scripts", "hash_limbs.js"));
  const sha = await sha256File(VKEY_V3);
  assert.strictEqual(sha, PINNED_VKEY_SHA256);
});

testA("configured key NOT matching pin is rejected (v2 key offered)", () => {
  const r = run(AUDIO, PROOF, PUB, "--vkey", VKEY_V2);
  assert.strictEqual(r.status, 1);
  assert.match(r.stdout, /does not match the pinned\/expected/);
});

// ── CLI trust-boundary rejections ────────────────────────────────────────────
testA("valid=0 public signal rejected before snarkjs", () => {
  const d = scratch();
  const pub = jsonCopy(PUB, (o) => { o[0] = "0"; }, d, "p.json");
  const r = run(AUDIO, PROOF, pub);
  assert.strictEqual(r.status, 1);
  assert.match(r.stdout, /validity claim/);
  fs.rmSync(d, { recursive: true, force: true });
});

testA("tampered audio copy: limb mismatch rejects", () => {
  const d = scratch();
  const aud = path.join(d, "t.wav");
  const b = fs.readFileSync(AUDIO); b[100] ^= 0xff; fs.writeFileSync(aud, b);
  const r = run(aud, PROOF, PUB);
  assert.strictEqual(r.status, 1);
  assert.match(r.stdout, /hash binding.*MISMATCH/s);
  fs.rmSync(d, { recursive: true, force: true });
});

testA("extra public signal (length 5) rejected", () => {
  const d = scratch();
  const pub = jsonCopy(PUB, (o) => o.push("1"), d, "p.json");
  const r = run(AUDIO, PROOF, pub);
  assert.strictEqual(r.status, 1);
  fs.rmSync(d, { recursive: true, force: true });
});

testA("malformed public file rejected with clear error", () => {
  const d = scratch();
  const p = path.join(d, "bad.json");
  fs.writeFileSync(p, "{ broken: ");
  const r = run(AUDIO, PROOF, p);
  assert.strictEqual(r.status, 1);
  assert.match(r.stdout, /missing or not valid JSON/);
  fs.rmSync(d, { recursive: true, force: true });
});

testA("missing audio file rejected", () => {
  const r = run(path.join(os.tmpdir(), "definitely_missing_audio.wav"), PROOF, PUB);
  assert.strictEqual(r.status, 1);
  assert.match(r.stdout, /not found/);
});

// ── the integration point: honest accept ─────────────────────────────────────
testA("honest v3 proof + original audio accepted (exit 0, scoped wording)", () => {
  const r = run(AUDIO, PROOF, PUB);
  assert.strictEqual(r.status, 0);
  assert.match(r.stdout, /RESULT : ACCEPT/);
  assert.match(r.stdout, /snarkjs\.groth16\.verify → true/);
  assert.doesNotMatch(r.stdout, /authentic audio/i);
});

// snarkjs worker threads keep the event loop alive — force-exit the runner
// after tests complete, preserving the failure exit code if any test failed.
const { after } = require("node:test");
after(() => {
  setImmediate(() => process.exit(process.exitCode ?? 0));
});