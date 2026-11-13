'use strict';
// tests/provenance_v4_circuit.test.js -- 5 circuit tests for outputs/v4.
// Fixture: frozen-v3-rule policy + demo metadata; salt 12345.
const { test } = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const snarkjs = require('snarkjs');

const ROOT = path.resolve(__dirname, '..');
const WASM = path.join(ROOT, 'outputs', 'v4', 'provenance_v4_js', 'provenance_v4.wasm');
const ZKEY = path.join(ROOT, 'outputs', 'v4', 'circuit_v4.zkey');
const R1CS = path.join(ROOT, 'outputs', 'v4', 'provenance_v4.r1cs');

// frozen v3 rule values as the DEFAULT policy
const POLICY = {
  allowed_device_0: '1024', allowed_device_1: '2048', allowed_device_2: '4096',
  timestamp_min: '1780278000', timestamp_max: '1780867200',
  gps_lat_min: '407400', gps_lat_max: '408400',
  gps_long_min: '778000', gps_long_max: '779200',
  sensor_min: '70',
};
const META = { device_id: '1024', timestamp: '1780298225', sensor_score: '77',
               gps_lat: '408259', gps_long: '778637' };
const SALT = '12345';
const SALTB = '12346';
const LIMB = '340282366920938463463374607431768211455'; // 2^128-1 (test value)

const ORDER = ['valid', 'C', 'media_hash_hi', 'media_hash_lo', 'valid_claim',
  'session_nonce', 'allowed_device_0', 'allowed_device_1', 'allowed_device_2',
  'timestamp_min', 'timestamp_max', 'gps_lat_min', 'gps_lat_max',
  'gps_long_min', 'gps_long_max', 'sensor_min'];

function witnessInput(o) {
  return { device_id: o.device_id ?? META.device_id,
           timestamp: o.timestamp ?? META.timestamp,
           sensor_score: o.sensor_score ?? META.sensor_score,
           gps_lat: o.gps_lat ?? META.gps_lat,
           gps_long: o.gps_long ?? META.gps_long,
           salt: o.salt ?? SALT,
           media_hash_hi: o.media_hash_hi ?? LIMB,
           media_hash_lo: o.media_hash_lo ?? LIMB,
           valid_claim: o.valid_claim ?? '1',
           session_nonce: o.session_nonce ?? '0',
           allowed_device_0: o.allowed_device_0 ?? POLICY.allowed_device_0,
           allowed_device_1: o.allowed_device_1 ?? POLICY.allowed_device_1,
           allowed_device_2: o.allowed_device_2 ?? POLICY.allowed_device_2,
           timestamp_min: o.timestamp_min ?? POLICY.timestamp_min,
           timestamp_max: o.timestamp_max ?? POLICY.timestamp_max,
           gps_lat_min: o.gps_lat_min ?? POLICY.gps_lat_min,
           gps_lat_max: o.gps_lat_max ?? POLICY.gps_lat_max,
           gps_long_min: o.gps_long_min ?? POLICY.gps_long_min,
           gps_long_max: o.gps_long_max ?? POLICY.gps_long_max,
           sensor_min: o.sensor_min ?? POLICY.sensor_min };
}

test('(pre) artifacts exist and r1cs constrained <= 4096', async () => {
  for (const p of [WASM, ZKEY, R1CS]) assert.ok(fs.existsSync(p), p);
  // parse via r1csfile (snarkjs's own r1cs parser; a hand-rolled flat-offset
  // read is wrong -- r1cs v1 files are section-framed)
  const r = await require('r1csfile').readR1cs(R1CS,
    { loadConstraints: false, loadMap: false });
  console.log(`    r1cs #Constraints: ${r.nConstraints}`);
  assert.strictEqual(r.nConstraints, 1426);
  assert.ok(r.nConstraints <= 4096, `constraint count ${r.nConstraints} > pot12 capacity 4096`);
});

test('(a) fullProve succeeds; 16 publics in documented order', async () => {
  const { proof, publicSignals } = await snarkjs.groth16.fullProve(
    witnessInput({}), WASM, ZKEY);
  assert.strictEqual(publicSignals.length, 16);
  // outputs first: valid, C; then publics in declaration order
  assert.strictEqual(publicSignals[0], '1');                    // valid
  assert.strictEqual(publicSignals[4], '1');                    // valid_claim
  assert.strictEqual(publicSignals[5], '0');                    // session_nonce
  assert.strictEqual(publicSignals[6], POLICY.allowed_device_0);
  assert.strictEqual(publicSignals[8], POLICY.allowed_device_2);
  assert.strictEqual(publicSignals[9], POLICY.timestamp_min);
  assert.strictEqual(publicSignals[10], POLICY.timestamp_max);
  assert.strictEqual(publicSignals[15], POLICY.sensor_min);
  assert.ok(proof.pi_a.length > 0);
});

test('(b) metadata violating the policy -> witness generation fails', async () => {
  await assert.rejects(
    () => snarkjs.groth16.fullProve(
      witnessInput({ sensor_score: '60' }), WASM, ZKEY),
    (err) => true);  // any error = the circuit refused the witness
});

test('(c) empty range policy (t_min > t_max) -> witness generation fails', async () => {
  await assert.rejects(
    () => snarkjs.groth16.fullProve(
      witnessInput({ timestamp_min: '1780867200', timestamp_max: '1780278000' }),
      WASM, ZKEY),
    (err) => true);
});

test('(d) salt sensitivity: different salt -> different C; same salt -> same C', async () => {
  const r1 = await snarkjs.groth16.fullProve(witnessInput({}), WASM, ZKEY);
  const r2 = await snarkjs.groth16.fullProve(witnessInput({ salt: SALTB }), WASM, ZKEY);
  const r3 = await snarkjs.groth16.fullProve(witnessInput({}), WASM, ZKEY);
  const C1 = r1.publicSignals[1], C2 = r2.publicSignals[1], C3 = r3.publicSignals[1];
  assert.notStrictEqual(C1, C2, 'different salt must change C');
  assert.strictEqual(C1, C3, 'same salt must reproduce C');
  console.log(`    C(salt=${SALT}) = ${C1}`);
  console.log(`    C(salt=${SALTB}) = ${C2}`);
});

test('(e) circuit C equals circomlibjs Poseidon off-circuit', async () => {
  const circomlibjs = require('circomlibjs');
  const poseidon = await circomlibjs.buildPoseidon();
  const { publicSignals } = await snarkjs.groth16.fullProve(
    witnessInput({}), WASM, ZKEY);
  const C_circuit = BigInt(publicSignals[1]);
  const inputs = ['1024', '1780298225', '77', '408259', '778637', '12345'].map(BigInt);
  const C_ref = poseidon(inputs);
  const C_ref_dec = poseidon.F.toString(C_ref, 10);
  assert.strictEqual(C_circuit.toString(), C_ref_dec,
    `circuit C ${C_circuit} != circomlibjs Poseidon ${C_ref_dec}`);
  console.log(`    off-circuit C = ${C_ref_dec}`);
});
'use strict';

// snarkjs worker threads keep the event loop alive after the tests finish
// (same known issue documented in tests/verify_media.test.js) -- the runner
// would otherwise hang. Force-exit with the runner's recorded exit code.
const { after } = require('node:test');
after(() => setImmediate(() => process.exit(process.exitCode ?? 0)));
