pragma circom 2.0.0;

include "../node_modules/circomlib/circuits/comparators.circom";
include "../node_modules/circomlib/circuits/bitify.circom";

// ─────────────────────────────────────────────────────────────────────────────
// ProvenanceCheck  (v3 — v2 rules + PUBLIC file-hash limbs)
//
// New in v3: the SHA-256 of the media file is bound into the proof as a
// PUBLIC input. The digest (256 bits) is split into two 128-bit limbs:
//     media_hash_hi = first 16 digest bytes  (big-endian value)
//     media_hash_lo = last  16 digest bytes  (big-endian value)
// Scripts/hash_limbs.js computes these with BigInt only (never Number).
//
// Each limb is range-constrained to exactly 128 bits (Num2Bits), which both
// constrains the public inputs (compiler --inspect stays silent) and makes
// the limb pair decode to a UNIQUE 256-bit digest — no field-modulo aliasing.
//
// The metadata rules are UNCHANGED from v2 and stay PRIVATE:
//     device_id    ∈ {1024, 2048, 4096}
//     timestamp    ∈ [1780278000, 1780867200]
//     sensor_score ≥ 70
//     gps_lat      ∈ [407400, 408400]
//     gps_long     = |longitude| ∈ [778000, 779200]
//
// Scope note (accurate claim): the proof binds the hash supplied TO the
// prover — the same limbs the prover passed to snarkjs appear in public.json.
// Nothing in this circuit attests the file bytes, who captured the media, or
// that the private metadata is truthful; the verifier-side file-hash
// recompute (Step 4/5) closes the file↔hash gap.
//
// Claim enforcement: v2 only OUTPUT `valid`, so a prover with bad metadata
// could still honestly prove `valid = 0` (measured behaviour — see report).
// v3 adds public input `valid_claim`, constrained to equal the rule
// conjunction. With valid_claim = 1, witness generation FAILS unless every
// rule holds; the verifier additionally checks public[0] == "1".
// ─────────────────────────────────────────────────────────────────────────────

template ProvenanceCheck() {

    // ── Private inputs (ZK witness — never exposed) ──────────────────────────
    signal input device_id;
    signal input timestamp;
    signal input sensor_score;
    signal input gps_lat;
    signal input gps_long;   // absolute value of longitude

    // ── Public inputs (file SHA-256 as two 128-bit limbs) ────────────────────
    signal input media_hash_hi;
    signal input media_hash_lo;

    // ── Public claim: prover asserts all five rules hold ─────────────────────
    // Constrained to the computed conjunction below: proving the claim with
    // any rule-violating metadata makes witness generation fail outright.
    signal input valid_claim;

    // ── Public output ────────────────────────────────────────────────────────
    signal output valid;

    // ── Hash limb range constraints ──────────────────────────────────────────
    // Num2Bits(128) both proves each limb < 2^128 and constrains the inputs
    // (a limb equal to its p-modulo alias would violate the bit constraints).
    component hi_bits = Num2Bits(128);
    hi_bits.in <== media_hash_hi;

    component lo_bits = Num2Bits(128);
    lo_bits.in <== media_hash_lo;

    // ════════════════════════════════════════════════════════════════════════
    // CHECK 1 — Device ID ∈ {1024, 2048, 4096}
    // ════════════════════════════════════════════════════════════════════════

    component eq1024 = IsEqual();
    eq1024.in[0] <== device_id;
    eq1024.in[1] <== 1024;

    component eq2048 = IsEqual();
    eq2048.in[0] <== device_id;
    eq2048.in[1] <== 2048;

    component eq4096 = IsEqual();
    eq4096.in[0] <== device_id;
    eq4096.in[1] <== 4096;

    signal device_ok;
    device_ok <== eq1024.out + eq2048.out + eq4096.out;

    // ════════════════════════════════════════════════════════════════════════
    // CHECK 2 — Timestamp ∈ [1780278000, 1780867200] (n = 31)
    // ════════════════════════════════════════════════════════════════════════

    component ts_lo = GreaterEqThan(31);
    ts_lo.in[0] <== timestamp;
    ts_lo.in[1] <== 1780278000;

    component ts_hi = LessEqThan(31);
    ts_hi.in[0] <== timestamp;
    ts_hi.in[1] <== 1780867200;

    signal ts_ok;
    ts_ok <== ts_lo.out * ts_hi.out;

    // ════════════════════════════════════════════════════════════════════════
    // CHECK 3 — Sensor score ≥ 70 (n = 8)
    // ════════════════════════════════════════════════════════════════════════

    component score_ge = GreaterEqThan(8);
    score_ge.in[0] <== sensor_score;
    score_ge.in[1] <== 70;

    // ════════════════════════════════════════════════════════════════════════
    // CHECK 4 — GPS latitude ∈ [407400, 408400] (n = 19)
    // ════════════════════════════════════════════════════════════════════════

    component lat_lo = GreaterEqThan(19);
    lat_lo.in[0] <== gps_lat;
    lat_lo.in[1] <== 407400;

    component lat_hi = LessEqThan(19);
    lat_hi.in[0] <== gps_lat;
    lat_hi.in[1] <== 408400;

    signal lat_ok;
    lat_ok <== lat_lo.out * lat_hi.out;

    // ════════════════════════════════════════════════════════════════════════
    // CHECK 5 — GPS longitude (absolute) ∈ [778000, 779200] (n = 20)
    // ════════════════════════════════════════════════════════════════════════

    component lon_lo = GreaterEqThan(20);
    lon_lo.in[0] <== gps_long;
    lon_lo.in[1] <== 778000;

    component lon_hi = LessEqThan(20);
    lon_hi.in[0] <== gps_long;
    lon_hi.in[1] <== 779200;

    signal lon_ok;
    lon_ok <== lon_lo.out * lon_hi.out;

    // ════════════════════════════════════════════════════════════════════════
    // FINAL OUTPUT — AND of all five checks (degree-2 chain, as in v2)
    // ════════════════════════════════════════════════════════════════════════

    signal step1;
    step1 <== device_ok * ts_ok;

    signal step2;
    step2 <== step1 * score_ge.out;

    signal step3;
    step3 <== step2 * lat_ok;

    valid <== step3 * lon_ok;

    // The claim must match reality: valid_claim === valid. (valid is 0/1 by
    // construction — a product chain of IsEqual/comparator outputs — so this
    // one equality also pins valid_claim to {0, 1}.)
    valid_claim === valid;
}

// media_hash_hi / media_hash_lo / valid_claim are public; every rule input
// stays private. `valid` (output) is public automatically.
component main {public [media_hash_hi, media_hash_lo, valid_claim]} = ProvenanceCheck();