'use strict';
// tests/issue_capture_record_v4.test.js -- Part B issuer tests (real detector runs).
const { test } = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const crypto = require('node:crypto');
const { spawnSync } = require('node:child_process');

const ROOT = path.resolve(__dirname, '..');
const DEMO = require(path.join(ROOT, 'scripts', 'demo_assets.js'));
// demo-asset skip guard: asset-dependent tests SKIP (with a clear message)
// instead of failing when the demo weights/keys/audio bootstrap isn't ready.
// T3 below stays on the raw `test` -- it asserts failure behaviour that does
// not need the assets.
const ASSETS = DEMO.assetsStatus();
const testA = ASSETS.ready ? test : (name, fn) =>
  test(name, (t) => t.skip(DEMO.SKIP_REASON + ' | missing: ' + ASSETS.missing.join('; ')));
const SCRIPT = path.join(ROOT, 'scripts', 'issue_capture_record_v4.js');
const ISSUER_KEY = DEMO.resolve('<HOME>/zkp-demo-issuer-keys/issuer_private.pem');
const ISSUER_PUB = DEMO.resolve('<HOME>/zkp-demo-issuer-keys/issuer_public.pem');
const GENUINE = 'ASVspoof2019_LA_eval/flac/LA_E_1194478.flac';
const SPOOF = 'ASVspoof2019_LA_eval/flac/LA_E_1000147.flac';
const WEIGHTS = '<HOME>/external/aasist/models/weights/AASIST-L.pth';
const AASIST_REPO = '<HOME>/external/aasist';
const CONFIG = '<HOME>/external/aasist/config/AASIST-L.conf';
const META_FILE = path.join(ROOT, 'inputs', 'demo_metadata_v4.json');
const WORK = fs.mkdtempSync(path.join(os.tmpdir(), 'iv4tests-'));
const PINNED = require(path.join(ROOT, 'scripts', 'verify_fully.js')).PINNED_PUBKEY_SHA256;

function runIssuer(extra, recordName) {
  const rec = path.join(WORK, recordName || ('rec_' + Math.random().toString(36).slice(2) + '.json'));
  const args = ['node', SCRIPT, GENUINE, rec, '--metadata', META_FILE,
    '--issuer-key', ISSUER_KEY, '--weights', WEIGHTS, '--aasist-repo', AASIST_REPO,
    '--config', CONFIG, ...extra];
  const r = spawnSync(process.execPath, args.slice(1), { encoding: 'utf8', cwd: ROOT });
  return { code: r.status, stdout: r.stdout || '', stderr: r.stderr || '', rec };
}


function issueOnce(argv, recPath) {
  const args = [SCRIPT, GENUINE, recPath, '--metadata', META_FILE,
    '--issuer-key', ISSUER_KEY, '--weights', WEIGHTS, '--aasist-repo', AASIST_REPO,
    '--config', CONFIG, ...argv];
  const r = spawnSync(process.execPath, args, { encoding: 'utf8', cwd: ROOT });
  return { code: r.status, stdout: r.stdout || '', stderr: r.stderr || '' };
}

testA('T1 canonical roundtrip: signature verifies under PINNED issuer pubkey', () => {
  const recPath = path.join(WORK, 'rec_t1.json');
  const h1 = issueOnce(['--handoff', path.join(WORK, 'hand_t1.json')], recPath);
  assert.strictEqual(h1.code, 0, 'issuer exit: ' + h1.code + ' | ' + h1.stderr.slice(-300));
  fs.writeFileSync(path.join(WORK, 't1_stdout.txt'), h1.stdout);
  const rec = JSON.parse(fs.readFileSync(recPath, 'utf8'));
  const canon = require(path.join(ROOT, 'scripts', 'issue_capture_record_v4.js'))
    .canonicalRecordV2(rec);
  assert.strictEqual(crypto.createHash('sha256').update(Buffer.from(canon, 'utf8'))
    .digest('hex'), rec.canonical_sha256);
  const ok = crypto.verify(null, Buffer.from(canon, 'utf8'),
    crypto.createPublicKey(fs.readFileSync(ISSUER_PUB)),
    Buffer.from(rec.signature, 'base64'));
  assert.strictEqual(ok, true);
  const pubSha = crypto.createHash('sha256').update(fs.readFileSync(ISSUER_PUB)).digest('hex');
  assert.strictEqual(pubSha, PINNED, 'issuer pubkey must be the pinned v3 key');
  assert.strictEqual(rec.record_version, 2);
  assert.strictEqual(rec.det_decision, 'bonafide');
  assert.strictEqual(rec.det_threshold, '1.7635419737');
  assert.ok(/^true|false$/.test(String(rec.flagged)));
});

testA('T2 refuses a known spoof FLAC (no record)', () => {
  const recPath = path.join(WORK, 'rec_t2.json');
  const args = [SCRIPT, SPOOF, recPath, '--metadata', META_FILE,
    '--issuer-key', ISSUER_KEY, '--weights', WEIGHTS, '--aasist-repo', AASIST_REPO,
    '--config', CONFIG, '--handoff', path.join(WORK, 'hand_t2.json')];
  const r = spawnSync(process.execPath, args, { encoding: 'utf8', cwd: ROOT });
  assert.strictEqual(r.status, 1);
  assert.ok(!fs.existsSync(recPath));
  assert.ok((r.stderr || '').includes('refusing'));
});

test('T3 refuses when the detector is missing/fails (no record)', () => {
  const recPath = path.join(WORK, 'rec_t3.json');
  const args = [SCRIPT, GENUINE, recPath, '--metadata', META_FILE,
    '--issuer-key', ISSUER_KEY, '--weights', 'C:/nonexistent/weights.pth',
    '--aasist-repo', AASIST_REPO, '--config', CONFIG,
    '--handoff', path.join(WORK, 'hand_t3.json')];
  const r = spawnSync(process.execPath, args, { encoding: 'utf8', cwd: ROOT });
  assert.strictEqual(r.status, 1);
  assert.ok(!fs.existsSync(recPath));
});

testA('T4 override --allow-spoof-enrollment emits flagged=true', () => {
  const recPath = path.join(WORK, 'rec_t4.json');
  const args = [SCRIPT, SPOOF, recPath, '--metadata', META_FILE,
    '--issuer-key', ISSUER_KEY, '--weights', WEIGHTS, '--aasist-repo', AASIST_REPO,
    '--config', CONFIG, '--handoff', path.join(WORK, 'hand_t4.json'),
    '--allow-spoof-enrollment'];
  const r = spawnSync(process.execPath, args, { encoding: 'utf8', cwd: ROOT });
  assert.strictEqual(r.status, 0, r.stderr.slice(-200));
  const rec = JSON.parse(fs.readFileSync(recPath, 'utf8'));
  assert.strictEqual(rec.flagged, true);
});

testA('T5 refuses to overwrite an existing record', () => {
  const recPath = path.join(WORK, 'rec_t5.json');
  const base = ['--metadata', META_FILE, '--issuer-key', ISSUER_KEY,
    '--weights', WEIGHTS, '--aasist-repo', AASIST_REPO, '--config', CONFIG,
    '--handoff', path.join(WORK, 'hand_t5.json')];
  assert.strictEqual(issueOnce(base, recPath).code, 0);
  const second = spawnSync(process.execPath,
    [SCRIPT, GENUINE, recPath, ...base], { encoding: 'utf8', cwd: ROOT });
  assert.strictEqual(second.status, 1);
  assert.ok((second.stderr || '').includes('refusing to overwrite'));
});

testA('T6 handoff must land OUTSIDE the repo; in-repo refused', () => {
  const recPath = path.join(WORK, 'rec_t6.json');
  const args = [SCRIPT, GENUINE, recPath, '--metadata', META_FILE,
    '--issuer-key', ISSUER_KEY, '--weights', WEIGHTS, '--aasist-repo', AASIST_REPO,
    '--config', CONFIG, '--handoff', path.join(ROOT, 'handoff_inrepo.json')];
  const r = spawnSync(process.execPath, args, { encoding: 'utf8', cwd: ROOT });
  assert.strictEqual(r.status, 2);
  assert.ok((r.stderr || '').includes('OUTSIDE the repository'));
  // and outside-repo handoffs are real files with the expected shape
  const hand = JSON.parse(fs.readFileSync(path.join(WORK, 'hand_t1.json'), 'utf8'));
  for (const k of ['metadata', 'salt', 'metadata_commitment']) assert.ok(k in hand);
  assert.ok(!path.resolve(path.join(WORK, 'hand_t1.json')).toLowerCase()
    .startsWith(ROOT.toLowerCase()));
});

testA('T7 records/stdout leak no metadata or salt (grep + structural)', () => {
  const rec = JSON.parse(fs.readFileSync(path.join(WORK, 'rec_t1.json'), 'utf8'));
  const hand = JSON.parse(fs.readFileSync(path.join(WORK, 'hand_t1.json'), 'utf8'));
  const recStr = JSON.stringify(rec);
  const t1 = require('node:test');
  // structural: no metadata field names in the record
  for (const k of ['device_id', 'timestamp', 'sensor_score', 'gps_lat', 'gps_long', 'salt'])
    assert.ok(!(k in rec), `record must not carry metadata key: ${k}`);
  // distinctive-value greps (record text + issuer stdout from T1's capture)
  const t1out = fs.readFileSync(path.join(WORK, 't1_stdout.txt'), 'utf8');
  for (const v of ['1780298225', '408259', '778637']) {
    assert.ok(!recStr.includes(v), `record leaks metadata value: ${v}`);
    assert.ok(!t1out.includes(v), `stdout leaks metadata value: ${v}`);
  }
  assert.ok(!recStr.includes(hand.salt), 'record leaks the salt');
  assert.ok(!t1out.includes(hand.salt), 'stdout leaks the salt');
  assert.ok(!recStr.includes('"metadata":'), 'record leaks a metadata object');
});

testA('T8 record C == fullProve C computed from the handoff', async () => {
  const rec = JSON.parse(fs.readFileSync(path.join(WORK, 'rec_t1.json'), 'utf8'));
  const hand = JSON.parse(fs.readFileSync(path.join(WORK, 'hand_t1.json'), 'utf8'));
  const snarkjs = require('snarkjs');
  const REF = require(path.join(ROOT, 'scripts', 'issue_capture_record_v4.js'))
    .REFERENCE_POLICY;
  const input = { ...hand.metadata, salt: hand.salt,
    media_hash_hi: '0', media_hash_lo: '0', valid_claim: '1', session_nonce: '0' };
  input.allowed_device_0 = String(REF.device_ids[0]);
  input.allowed_device_1 = String(REF.device_ids[1]);
  input.allowed_device_2 = String(REF.device_ids[2]);
  input.timestamp_min = String(REF.timestamp[0]);
  input.timestamp_max = String(REF.timestamp[1]);
  input.gps_lat_min = String(REF.gps_lat[0]);
  input.gps_lat_max = String(REF.gps_lat[1]);
  input.gps_long_min = String(REF.gps_long[0]);
  input.gps_long_max = String(REF.gps_long[1]);
  input.sensor_min = String(REF.sensor_min);
  const r = await snarkjs.groth16.fullProve(input,
    path.join(ROOT, 'outputs', 'v4', 'provenance_v4_js', 'provenance_v4.wasm'),
    path.join(ROOT, 'outputs', 'v4', 'circuit_v4.zkey'));
  assert.strictEqual(r.publicSignals[1], rec.metadata_commitment);
});

// snarkjs worker threads keep the event loop alive after the tests finish
// (same known issue documented in tests/verify_media.test.js) -- the runner
// would otherwise hang. Force-exit with the runner's recorded exit code.
const { after } = require('node:test');
after(() => setImmediate(() => process.exit(process.exitCode ?? 0)));
