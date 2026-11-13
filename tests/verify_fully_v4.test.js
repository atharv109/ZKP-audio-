'use strict';
// tests/verify_fully_v4.test.js -- Step-5 composed-verifier tests.
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
const WASM = path.join(ROOT, 'outputs', 'v4', 'provenance_v4_js', 'provenance_v4.wasm');
const ZKEY = path.join(ROOT, 'outputs', 'v4', 'circuit_v4.zkey');
const SCRIPT = path.join(ROOT, 'scripts', 'verify_fully_v4.js');
const GENUINE = DEMO.resolve('ASVspoof2019_LA_eval/flac/LA_E_1194478.flac');
const SPOOF = DEMO.resolve('ASVspoof2019_LA_eval/flac/LA_E_1000147.flac');
const WORK = path.join(os.tmpdir(), 'v4fix');
fs.mkdirSync(WORK, { recursive: true });
const DEFAULT_POLICY = {
  device_ids: [1024, 2048, 4096], timestamp_range: [1780278000, 1780867200],
  gps_lat_range: [407400, 408400], gps_long_range: [778000, 779200], sensor_min: 70 };
const POL_PATH = path.join(WORK, 'pol_def.json');
fs.writeFileSync(POL_PATH, JSON.stringify(DEFAULT_POLICY));

function ensure(kind) {  // kind: honest | flagged
  const rec = path.join(WORK, `rec_${kind}.json`);
  const hand = path.join(WORK, `handoff_${kind}.json`);
  if (!fs.existsSync(rec)) {
    const audio = kind === 'honest' ? GENUINE : SPOOF;
    const args = [path.join(ROOT, 'scripts', 'issue_capture_record_v4.js'), audio, rec,
      '--metadata', path.join(ROOT, 'inputs', 'demo_metadata_v4.json'),
      '--issuer-key', '<HOME>/zkp-demo-issuer-keys/issuer_private.pem',
      '--handoff', hand, '--weights',
      '<HOME>/external/aasist/models/weights/AASIST-L.pth', '--aasist-repo',
      '<HOME>/external/aasist', '--config',
      '<HOME>/external/aasist/config/AASIST-L.conf', '--expires-hours', '24'];
    if (kind !== 'honest') args.push('--allow-spoof-enrollment');
    const r = require('node:child_process').spawnSync(process.execPath, args,
      { encoding: 'utf8', cwd: ROOT });
    if (r.status !== 0 && !(kind !== 'honest' && r.status === 1))
      throw new Error(`bootstrap ${kind}: ` + (r.stderr || '').slice(-400));
  }
  const recObj = JSON.parse(fs.readFileSync(rec, 'utf8'));
  return { rec, hand, recObj };
}
let HONEST, FLAGGED, HANDM;
testA('setup bootstrap', () => {
  HONEST = ensure('honest'); FLAGGED = ensure('flagged');
  HANDM = JSON.parse(fs.readFileSync(HONEST.hand, 'utf8'));
});

function wi(meta, salt, nonce, limbsHi, limbsLo) {
  const LIMB = limbsHi || '340282366920938463463374607431768211455';
  return { device_id: String(meta.device_id), timestamp: String(meta.timestamp),
    sensor_score: String(meta.sensor_score), gps_lat: String(meta.gps_lat),
    gps_long: String(meta.gps_long), salt: salt,
    media_hash_hi: LIMB, media_hash_lo: limbsLo || LIMB, valid_claim: '1',
    session_nonce: String(nonce || 0),
    allowed_device_0: '1024', allowed_device_1: '2048', allowed_device_2: '4096',
    timestamp_min: '1780278000', timestamp_max: '1780867200',
    gps_lat_min: '407400', gps_lat_max: '408400',
    gps_long_min: '778000', gps_long_max: '779200', sensor_min: '70' };
}
const { sha256File, limbsFromDigest } = require(path.join(ROOT, 'scripts', 'hash_limbs.js'));

function runFV(argvExtra, audio, proof, pub, rec) {
  const r = require('node:child_process').spawnSync(process.execPath, [SCRIPT, audio, proof,
    pub, rec, '--policy-file', POL_PATH, ...(argvExtra || [])], { encoding: 'utf8', cwd: ROOT });
  return { code: r.status, out: (r.stdout || '') + (r.stderr || '') };
}

testA('(f1) genuine path ACCEPT', async () => {
  const sha = await sha256File(GENUINE);
  const limbs = limbsFromDigest(sha);
  const r = await snarkjs.groth16.fullProve(wi(HANDM.metadata, HANDM.salt, 0,
    limbs.media_hash_hi, limbs.media_hash_lo), WASM, ZKEY);
  const d = path.join(WORK, 'f1'); fs.mkdirSync(d, { recursive: true });
  const proof = path.join(d, 'proof.json'), pub = path.join(d, 'public.json');
  fs.writeFileSync(proof, JSON.stringify(r.proof));
  fs.writeFileSync(pub, JSON.stringify(r.publicSignals));
  const v = runFV([], GENUINE, proof, pub, HONEST.rec);
  assert.strictEqual(v.code, 0, v.out.slice(-500));
  assert.ok(v.out.includes('ATTEST'));
});

testA('(f2) A4-negative: fresh proof, DIFFERENT metadata + different salt, original record -> REJECT', async () => {
  const sha = await sha256File(GENUINE);
  const limbs = limbsFromDigest(sha);
  const meta2 = { device_id: 4096, timestamp: 1780867199, sensor_score: 99,
                  gps_lat: 408399, gps_long: 779199 };
  const r = await snarkjs.groth16.fullProve(wi(meta2, '999' + HANDM.salt, 0,
    limbs.media_hash_hi, limbs.media_hash_lo), WASM, ZKEY);
  const d = path.join(WORK, 'f2'); fs.mkdirSync(d, { recursive: true });
  const proof = path.join(d, 'proof.json'), pub = path.join(d, 'public.json');
  fs.writeFileSync(proof, JSON.stringify(r.proof));
  fs.writeFileSync(pub, JSON.stringify(r.publicSignals));
  const v = runFV([], GENUINE, proof, pub, HONEST.rec);
  assert.strictEqual(v.code, 1);
  assert.ok(v.out.includes('metadata_commitment mismatch'), v.out.slice(-300));
});

testA('(f3) expired record REJECT via --now', async () => {
  const recObj = JSON.parse(fs.readFileSync(HONEST.rec, 'utf8'));
  const afterExp = new Date(Date.parse(recObj.expires_at_utc) + 3600000).toISOString();
  const sha = await sha256File(GENUINE); const limbs = limbsFromDigest(sha);
  const r = await snarkjs.groth16.fullProve(wi(HANDM.metadata, HANDM.salt, 0,
    limbs.media_hash_hi, limbs.media_hash_lo), WASM, ZKEY);
  const d = path.join(WORK, 'f3'); fs.mkdirSync(d, { recursive: true });
  const proof = path.join(d, 'proof.json'), pub = path.join(d, 'public.json');
  fs.writeFileSync(proof, JSON.stringify(r.proof));
  fs.writeFileSync(pub, JSON.stringify(r.publicSignals));
  const v = runFV(['--now', afterExp], GENUINE, proof, pub, HONEST.rec);
  assert.strictEqual(v.code, 1); assert.ok(v.out.includes('EXPIRED'), v.out.slice(-300));
});

testA('(f4) flagged record: REJECT without override, ACCEPT with --allow-flagged', async () => {
  const sha = await sha256File(SPOOF); const limbs = limbsFromDigest(sha);
  const FLAGM = JSON.parse(fs.readFileSync(FLAGGED.hand, 'utf8'));
  const r = await snarkjs.groth16.fullProve(wi(FLAGM.metadata, FLAGM.salt, 0,
    limbs.media_hash_hi, limbs.media_hash_lo), WASM, ZKEY);
  const d = path.join(WORK, 'f4'); fs.mkdirSync(d, { recursive: true });
  const proof = path.join(d, 'proof.json'), pub = path.join(d, 'public.json');
  fs.writeFileSync(proof, JSON.stringify(r.proof));
  fs.writeFileSync(pub, JSON.stringify(r.publicSignals));
  const recObj = JSON.parse(fs.readFileSync(FLAGGED.rec, 'utf8'));
  const within = new Date(Date.parse(recObj.issued_at_utc) + 3600000).toISOString();
  const v1 = runFV(['--now', within], SPOOF, proof, pub, FLAGGED.rec);
  assert.strictEqual(v1.code, 1); assert.ok(v1.out.includes('allow-flagged'), v1.out.slice(-200));
  const v2 = runFV(['--now', within, '--allow-flagged'], SPOOF, proof, pub, FLAGGED.rec);
  assert.strictEqual(v2.code, 0, v2.out.slice(-400));
});

testA('(f5) nonce session: matching --expect-nonce ACCEPT, different REJECT', async () => {
  const sha = await sha256File(GENUINE); const limbs = limbsFromDigest(sha);
  const r = await snarkjs.groth16.fullProve(wi(HANDM.metadata, HANDM.salt, 42,
    limbs.media_hash_hi, limbs.media_hash_lo), WASM, ZKEY);
  const d = path.join(WORK, 'f5'); fs.mkdirSync(d, { recursive: true });
  const proof = path.join(d, 'proof.json'), pub = path.join(d, 'public.json');
  fs.writeFileSync(proof, JSON.stringify(r.proof));
  fs.writeFileSync(pub, JSON.stringify(r.publicSignals));
  const v1 = runFV(['--expect-nonce', '42'], GENUINE, proof, pub, HONEST.rec);
  assert.strictEqual(v1.code, 0, v1.out.slice(-300));
  const v2 = runFV(['--expect-nonce', '43'], GENUINE, proof, pub, HONEST.rec);
  assert.strictEqual(v2.code, 1); assert.ok(v2.out.includes('session_nonce'));
});

testA('(f6) SIGNED-FIELD COVERAGE: every record field mutated -> REJECT; unknown field -> REJECT', async () => {
  const sha = await sha256File(GENUINE); const limbs = limbsFromDigest(sha);
  const r = await snarkjs.groth16.fullProve(wi(HANDM.metadata, HANDM.salt, 0,
    limbs.media_hash_hi, limbs.media_hash_lo), WASM, ZKEY);
  const d = path.join(WORK, 'f6'); fs.mkdirSync(d, { recursive: true });
  const proof = path.join(d, 'proof.json'), pub = path.join(d, 'public.json');
  fs.writeFileSync(proof, JSON.stringify(r.proof));
  fs.writeFileSync(pub, JSON.stringify(r.publicSignals));
  const base = JSON.parse(fs.readFileSync(HONEST.rec, 'utf8'));
  // mutate every field; all canonical fields are signed -> canonical-digest
  // mismatch or Ed25519 invalid; the 3 verification fields have named checks.
  const muts = {
    record_version: 3,
    record_type: 'other_record_type',
    file_sha256: 'ff' + base.file_sha256.slice(2),
    vkey_sha256: 'ee' + base.vkey_sha256.slice(2),
    metadata_commitment: '1215646899841022300645841416276440562848330199606337074311526351504421592451',
    det_checkpoint_sha256: 'dd' + base.det_checkpoint_sha256.slice(2),
    det_threshold: '0.0',
    det_score_decimals6: '9.999999',
    det_decision: 'spoof',
    issued_at_utc: '2026-11-04T00:00:00.000Z',
    expires_at_utc: '2026-11-04T01:00:00.000Z',
    flagged: true,
    issuer_label: base.issuer_label + 'x',
    signature_algorithm: 'rs256',
    canonical_sha256: 'cd' + base.canonical_sha256.slice(2),
    signature: base.signature.slice(0, -2) + (base.signature.endsWith('A') ? 'B' : 'A') ,
  };
  let covered = 0;
  for (const [k, newV] of Object.entries(muts)) {
    const rec = JSON.parse(pathToFile(base));
    rec[k] = newV;
    const rp = path.join(WORK, 'f6_mut.json');
    fs.writeFileSync(rp, JSON.stringify(rec));
    const withinIso = new Date(Date.parse(base.issued_at_utc) + 1800000).toISOString();
    const v = runFV(['--now', withinIso], GENUINE, proof, pub, rp);
    if (v.code !== 1) assert.fail(`field ${k} mutation was NOT rejected`);
    covered += 1;
  }
  assert.strictEqual(covered, Object.keys(muts).length);  // fail test if any field unsigned
  console.log(`    every one of ${covered} record fields: mutation -> REJECT`);
  // unknown extra field -> REJECT (fail-closed; stated policy)
  const recX = JSON.parse(JSON.stringify(base));
  recX.attacker_note = 'injected';
  const rp2 = path.join(WORK, 'f6_extra.json');
  fs.writeFileSync(rp2, JSON.stringify(recX));
  const withinIso2 = new Date(Date.parse(base.issued_at_utc) + 1800000).toISOString();
  const vx = runFV(['--now', withinIso2], GENUINE, proof, pub, rp2);
  assert.strictEqual(vx.code, 1); assert.ok(vx.out.includes('unknown record field'), vx.out.slice(-200));
});

function pathToFile(obj) { return JSON.stringify(obj); }

testA('(f7) v3-closure regression: valid record+proof bound to file X, presented with file Y -> REJECT', async () => {
  const sha = await sha256File(GENUINE); const limbs = limbsFromDigest(sha);
  const r = await snarkjs.groth16.fullProve(wi(HANDM.metadata, HANDM.salt, 0,
    limbs.media_hash_hi, limbs.media_hash_lo), WASM, ZKEY);
  const d = path.join(WORK, 'f7'); fs.mkdirSync(d, { recursive: true });
  const proof = path.join(d, 'proof.json'), pub = path.join(d, 'public.json');
  fs.writeFileSync(proof, JSON.stringify(r.proof));
  fs.writeFileSync(pub, JSON.stringify(r.publicSignals));
  // same metadata/salt/record (all bound consistently), but the PRESENTED FILE is the spoof
  const v = runFV(['--allow-flagged'], SPOOF, proof, pub, HONEST.rec);
  assert.strictEqual(v.code, 1);
  // Part A' fires first on the limb mismatch (the limbs ARE the file hash);
  // the 2b record-identity check is the defense-in-depth layer behind it.
  assert.ok(v.out.includes('hash binding') || v.out.includes('record file_sha256')
    || v.out.includes('DIFFERENT file'), v.out.slice(-300));
});

// snarkjs worker threads keep the event loop alive after the tests finish
// (same known issue documented in tests/verify_media.test.js) -- the runner
// would otherwise hang. Force-exit with the runner's recorded exit code.
const { after } = require('node:test');
after(() => setImmediate(() => process.exit(process.exitCode ?? 0)));
