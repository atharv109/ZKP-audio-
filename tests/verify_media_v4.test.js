'use strict';
// tests/verify_media_v4.test.js -- Step-4 verifier tests (real snarkjs API).
const { test } = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const snarkjs = require('snarkjs');

const ROOT = path.resolve(__dirname, '..');
const DEMO = require(path.join(ROOT, 'scripts', 'demo_assets.js'));
// demo-asset skip guard: tests SKIP (never hard-fail) when the demo
// bootstrap isn't ready (e.g. weights not fetched -- run scripts/fetch_weights).
const ASSETS_ALL = DEMO.assetsStatus();
const testA = ASSETS_ALL.ready ? test : (name, fn) =>
  test(name, (t) => t.skip(DEMO.SKIP_REASON + ' | missing: ' + ASSETS_ALL.missing.join('; ')));
const SCRIPT = path.join(ROOT, 'scripts', 'verify_media_v4.js');
const WASM = path.join(ROOT, 'outputs', 'v4', 'provenance_v4_js', 'provenance_v4.wasm');
const ZKEY = path.join(ROOT, 'outputs', 'v4', 'circuit_v4.zkey');
const VKEY_V4 = path.join(ROOT, 'outputs', 'v4', 'verification_key_v4.json');
const GENUINE = DEMO.resolve('ASVspoof2019_LA_eval/flac/LA_E_1194478.flac');
const OTHER = DEMO.resolve('ASVspoof2019_LA_eval/flac/LA_E_1000147.flac');
const WORK = path.join(os.tmpdir(), 'v4fix');
fs.mkdirSync(WORK, { recursive: true });
const HANDOFF = path.join(WORK, 'handoff_honest.json');
const DEF_POLICY = {
  device_ids: [1024, 2048, 4096], timestamp_range: [1780278000, 1780867200],
  gps_lat_range: [407400, 408400], gps_long_range: [778000, 779200], sensor_min: 70 };

function ensureHandoff() {
  if (fs.existsSync(HANDOFF)) return;
  const rec = path.join(WORK, 'rec_honest.json');
  const args = [path.join(ROOT, 'scripts', 'issue_capture_record_v4.js'), GENUINE, rec,
    '--metadata', path.join(ROOT, 'inputs', 'demo_metadata_v4.json'),
    '--issuer-key', '<HOME>/zkp-demo-issuer-keys/issuer_private.pem',
    '--handoff', HANDOFF, '--weights',
    '<HOME>/external/aasist/models/weights/AASIST-L.pth', '--aasist-repo',
    '<HOME>/external/aasist', '--config',
    '<HOME>/external/aasist/config/AASIST-L.conf', '--expires-hours', '24'];
  const r = require('node:child_process').spawnSync(process.execPath, args,
    { encoding: 'utf8', cwd: ROOT });
  if (r.status !== 0) throw new Error('bootstrap issuer failed: ' + (r.stderr || '').slice(-400));
}
let HAND; // {metadata, salt}

function policyFile(obj, name) {
  const p = path.join(WORK, name || ('pol_' + Math.random().toString(36).slice(2) + '.json'));
  fs.writeFileSync(p, JSON.stringify(obj || DEF_POLICY));
  return p;
}
function mutatePolicy(i) {
  const m = [
    { ...DEF_POLICY, device_ids: [2048, 2048, 4096] },
    { ...DEF_POLICY, device_ids: [1024, 2048, 1024] },
    { ...DEF_POLICY, device_ids: [1024, 2048, 2048] },
    { ...DEF_POLICY, timestamp_range: [1780278000, 1780290000] },
    { ...DEF_POLICY, timestamp_range: [1780300000, 1780867200] },
    { ...DEF_POLICY, gps_lat_range: [407400, 408000] },
    { ...DEF_POLICY, gps_lat_range: [408300, 408400] },
    { ...DEF_POLICY, gps_long_range: [778000, 778500] },
    { ...DEF_POLICY, gps_long_range: [778700, 779200] },
    { ...DEF_POLICY, sensor_min: 80 },
  ][i];
  return m;
}

function verifyV4(audio, proofPath, pubPath, extra) {
  const extraArgs = extra && extra.flagArgs ? extra.flagArgs : [];
  const r = require('node:child_process').spawnSync(process.execPath, [SCRIPT, audio,
    proofPath, pubPath, '--policy-file', policyFile(DEF_POLICY, 'pol_def.json'),
    ...extraArgs],
    { encoding: 'utf8', cwd: ROOT });
  const out = (r.stdout || '') + (r.stderr || '');
  try { fs.appendFileSync(path.join(WORK, 'debug_verify.log'),
    `
=== verifyV4 ${path.basename(audio)} code=${r.status}
` + out); } catch {}
  return { code: r.status, out };
}

function wi(over) {
  const LIMB = '340282366920938463463374607431768211455';
  return { device_id: String(over.device_id ?? HAND.metadata.device_id),
    timestamp: String(over.timestamp ?? HAND.metadata.timestamp),
    sensor_score: String(over.sensor_score ?? HAND.metadata.sensor_score),
    gps_lat: String(over.gps_lat ?? HAND.metadata.gps_lat),
    gps_long: String(over.gps_long ?? HAND.metadata.gps_long),
    salt: over.salt ?? HAND.salt,
    media_hash_hi: LIMBS_HI ?? LIMB, media_hash_lo: LIMBS_LO ?? LIMB, valid_claim: '1',
    session_nonce: String(over.nonce ?? 0),
    allowed_device_0: '1024', allowed_device_1: '2048', allowed_device_2: '4096',
    timestamp_min: '1780278000', timestamp_max: '1780867200',
    gps_lat_min: '407400', gps_lat_max: '408400',
    gps_long_min: '778000', gps_long_max: '779200', sensor_min: '70' };
}

async function makeProof(over, name) {
  const r = await snarkjs.groth16.fullProve(wi(over || {}), WASM, ZKEY);
  const dir = path.join(WORK, name || ('pr_' + Math.random().toString(36).slice(2)));
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(dir, 'proof.json'), JSON.stringify(r.proof));
  fs.writeFileSync(path.join(dir, 'public.json'), JSON.stringify(r.publicSignals));
  return { dir, publicSignals: r.publicSignals };
}

const { sha256File, limbsFromDigest } = require(path.join(ROOT, 'scripts', 'hash_limbs.js'));
let LIMBS_HI, LIMBS_LO;
testA('setup: bootstrap handoff + real limbs once', async () => {
  ensureHandoff();
  HAND = JSON.parse(fs.readFileSync(HANDOFF, 'utf8'));
  const limbs = limbsFromDigest(await sha256File(GENUINE));
  LIMBS_HI = limbs.media_hash_hi; LIMBS_LO = limbs.media_hash_lo;
});

testA('(m1) honest proof ACCEPT under its own policy', async () => {
  const pr = await makeProof({}, 'pr_honest');
  const r = verifyV4(GENUINE, path.join(pr.dir, 'proof.json'), path.join(pr.dir, 'public.json'));
  assert.strictEqual(r.code, 0, r.out.slice(-400));
});

testA('(m2) REJECT under a mismatched policy (each of the 10 bounds changed once)', async () => {
  const pr = await makeProof({}, 'pr_honest');  // publics = DEF_POLICY
  for (let i = 0; i < 10; i++) {
    const pol = mutatePolicy(i);
    const r = verifyV4(GENUINE, path.join(pr.dir, 'proof.json'),
      path.join(pr.dir, 'public.json'), { policy: pol, flagArgs: ['--policy-file', policyFile(pol)] });
    assert.strictEqual(r.code, 1, `mutation ${i} not rejected: ` + r.out.slice(-300));
    assert.ok(r.out.includes('policy equality'), `mutation ${i}: reason missing: ` + r.out.slice(-300));
  }
});

testA('(m3) policy loader rejects: negative bound, bound >= 2^n, min > max (exit 2)', () => {
  const vm = require(SCRIPT.replace(/\.js$/, '.js'));
  const bad1 = JSON.stringify({ ...DEF_POLICY, timestamp_range: [-1, 1780867200] });
  const bad2 = JSON.stringify({ ...DEF_POLICY, timestamp_range: [1780278000, 2147483653] });
  const bad3 = JSON.stringify({ ...DEF_POLICY, gps_lat_range: [408400, 407400] });
  for (const [bad, tag] of [[bad1, 'negative'], [bad2, 'over-width'], [bad3, 'min>max']]) {
    const res = vm.validatePolicyText(bad);
    assert.ok(res.error, `loader failed to reject (${tag})`);
    console.log(`    loader reject (${tag}): ${res.error.slice(0, 80)}`);
    // also via the real process -> exit 2
    const p = path.join(WORK, 'bad_policy.json'); fs.writeFileSync(p, bad);
    const r = require('node:child_process').spawnSync(process.execPath,
      [SCRIPT, GENUINE, path.join(WORK, 'pr_honest', 'proof.json'),
       path.join(WORK, 'pr_honest', 'public.json'), '--policy-file', p],
      { encoding: 'utf8', cwd: ROOT });
    assert.strictEqual(r.status, 2, `expected exit 2 for ${tag}`);
  }
});

testA('(m4) nonce: wrong expected nonce REJECT; nonzero nonce without expectation REJECT', async () => {
  const pr7 = await makeProof({ nonce: 7 }, 'pr_n7');
  const r1 = verifyV4(GENUINE, path.join(pr7.dir, 'proof.json'),
    path.join(pr7.dir, 'public.json'), { flagArgs: ['--expect-nonce', '8'] });
  assert.strictEqual(r1.code, 1); assert.ok(r1.out.includes('session_nonce'));
  const r2 = verifyV4(GENUINE, path.join(pr7.dir, 'proof.json'), path.join(pr7.dir, 'public.json'));
  assert.strictEqual(r2.code, 1); assert.ok(r2.out.includes('must be 0 or checked'));
});

testA('(m5) doctored proof REJECT', async () => {
  const pr = await makeProof({}, 'pr_honest');
  const doctored = JSON.parse(fs.readFileSync(path.join(pr.dir, 'proof.json'), 'utf8'));
  const a0 = doctored.pi_a[0];
  doctored.pi_a[0] = a0.slice(0, -1) + (a0[a0.length - 1] === '1' ? '2' : '1');
  const dPath = path.join(WORK, 'pr_doctored.json');
  fs.writeFileSync(dPath, JSON.stringify(doctored));
  const r = verifyV4(GENUINE, dPath, path.join(pr.dir, 'public.json'));
  assert.strictEqual(r.code, 1); assert.ok(r.out.includes('groth16 verify'));
});

testA('(m6) wrong-file REJECT (honest proof vs a different audio file)', async () => {
  const pr = await makeProof({}, 'pr_honest');
  const r = verifyV4(OTHER, path.join(pr.dir, 'proof.json'), path.join(pr.dir, 'public.json'));
  assert.strictEqual(r.code, 1); assert.ok(r.out.includes('hash binding'));
});

testA('(m7) vkey pin mismatch REJECT (v3 key offered against v4 pin)', async () => {
  const pr = await makeProof({}, 'pr_honest');
  const r = require('node:child_process').spawnSync(process.execPath, [SCRIPT, GENUINE,
    path.join(pr.dir, 'proof.json'), path.join(pr.dir, 'public.json'),
    '--policy-file', policyFile(DEF_POLICY, 'pol_def.json'),
    '--vkey', path.join(ROOT, 'outputs', 'v3', 'verification_key_v3.json')],
    { encoding: 'utf8', cwd: ROOT });
  assert.strictEqual(r.status, 1);
  assert.ok((r.stdout || '').includes('vkey integrity: configured'));
});

// snarkjs worker threads keep the event loop alive after the tests finish
// (same known issue documented in tests/verify_media.test.js) -- the runner
// would otherwise hang. Force-exit with the runner's recorded exit code.
const { after } = require('node:test');
after(() => setImmediate(() => process.exit(process.exitCode ?? 0)));
