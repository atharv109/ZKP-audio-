'use strict';
// tests/provenance_v4_policy_audit.test.js -- Part A range-constraint soundness audit.
//
// Finding (from reading circomlib/circuits/comparators.circom verbatim):
//   - IsZero:  out = 1 - in*inv  with witness  inv <-- 1/in  and  in*out === 0
//   - IsEqual: IsZero(in[1]-in[0])
//   - LessThan(n): Num2Bits(n+1)( in[0] + 2^n - in[1] ), out = 1 - bit[n]
//   All comparators constrain the DIFFERENCE to [(-2^n), 2^n) -- exact over the
//   field, because p >> 2^(n+1) forbids mod-p aliasing into the decodable
//   window. No operand needs its own Num2Bits; ANY operand outside the
//   difference window makes witness generation FAIL (fail-closed).
// The tests below try the exploits and assert that NO proof can be produced.
const { test } = require('node:test');
const assert = require('node:assert');
const path = require('node:path');
const snarkjs = require('snarkjs');

const ROOT = path.resolve(__dirname, '..');
const WASM = path.join(ROOT, 'outputs', 'v4', 'provenance_v4_js', 'provenance_v4.wasm');
const ZKEY = path.join(ROOT, 'outputs', 'v4', 'circuit_v4.zkey');
const P_DEC = '21888242871839275222246405745257275088548364400416034343698204186575808495617';
const PM1 = String(BigInt(P_DEC) - 1n);          // p-1

const POLICY = {
  allowed_device_0: '1024', allowed_device_1: '2048', allowed_device_2: '4096',
  timestamp_min: '1780278000', timestamp_max: '1780867200',
  gps_lat_min: '407400', gps_lat_max: '408400',
  gps_long_min: '778000', gps_long_max: '779200', sensor_min: '70' };
const META = { device_id: '1024', timestamp: '1780298225', sensor_score: '77',
               gps_lat: '408259', gps_long: '778637' };
const LIMB = '340282366920938463463374607431768211455';

function wi(o) {
  return { device_id: o.device_id ?? META.device_id, timestamp: o.timestamp ?? META.timestamp,
           sensor_score: o.sensor_score ?? META.sensor_score,
           gps_lat: o.gps_lat ?? META.gps_lat, gps_long: o.gps_long ?? META.gps_long,
           salt: o.salt ?? '12345', media_hash_hi: o.media_hash_hi ?? LIMB,
           media_hash_lo: o.media_hash_lo ?? LIMB, valid_claim: o.valid_claim ?? '1',
           session_nonce: o.session_nonce ?? '0',
           ...Object.fromEntries(Object.entries(POLICY).map(
             ([k, v]) => [k, o[k] ?? v])) };
}

test('T1 p-1 in each private metadata field -> witness fails', async () => {
  for (const f of ['device_id', 'timestamp', 'sensor_score', 'gps_lat', 'gps_long']) {
    await assert.rejects(() => snarkjs.groth16.fullProve(wi({ [f]: PM1 }), WASM, ZKEY),
);
  }
});

test('T2 timestamp >= 2^31 (2^n + k exploit) -> witness fails', async () => {
  for (const bad of ['2147483648', '2147483648' + '000', String(BigInt(P_DEC) - 2n)]) {
    await assert.rejects(() => snarkjs.groth16.fullProve(wi({ timestamp: bad }), WASM, ZKEY));
  }
});

test('T3 policy bound >= 2^n (attacker-chosen t_max = 2^40) -> witness fails', async () => {
  await assert.rejects(() => snarkjs.groth16.fullProve(
    wi({ timestamp_max: String(2n ** 40n) }), WASM, ZKEY));
});

test('T4 attacker policy (bound 2^100, metadata = bound) -> crypto-verifies, ' +
     'but policy publics differ from the verifier -> not exploitable', async () => {
  const B = String(2n ** 100n);
  const r = await snarkjs.groth16.fullProve(
    wi({ timestamp: B, timestamp_min: B, timestamp_max: B }), WASM, ZKEY);
  const vkey = JSON.parse(require('fs').readFileSync(
    path.join(ROOT, 'outputs', 'v4', 'verification_key_v4.json'), 'utf8'));
  const ok = await snarkjs.groth16.verify(vkey, r.publicSignals, r.proof);
  assert.strictEqual(ok, true);
  // the verifier's own policy would reject this: attacker's public
  // timestamp_min/timestamp_max (2^100) differ from the verifier's policy
  const VERIFIER_POLICY = { allowed_device_0: '1024', allowed_device_1: '2048',
    allowed_device_2: '4096', timestamp_min: '1780278000', timestamp_max: '1780867200',
    gps_lat_min: '407400', gps_lat_max: '408400', gps_long_min: '778000',
    gps_long_max: '779200', sensor_min: '70' };
  const attacker = r.publicSignals;
  for (const [i, k] of [[6, 'allowed_device_0'], [9, 'timestamp_min'],
                        [10, 'timestamp_max'], [15, 'sensor_min']]) {
    if (attacker[i] !== VERIFIER_POLICY[k]) {
      console.log(`    T4: attacker public[${i}] (${k}) = ${attacker[i]} -> ` +
                  `policy MISMATCH (verifier rejects this proof)`);
      return;
    }
  }
  assert.fail('expected policy mismatch, none found');
});

// snarkjs worker threads keep the event loop alive after the tests finish
// (same known issue documented in tests/verify_media.test.js) -- the runner
// would otherwise hang. Force-exit with the runner's recorded exit code.
const { after } = require('node:test');
after(() => setImmediate(() => process.exit(process.exitCode ?? 0)));
