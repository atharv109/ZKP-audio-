pragma circom 2.0.0;

include "../node_modules/circomlib/circuits/comparators.circom";

// ─────────────────────────────────────────────────────────────────────────────
// ProvenanceCheck  (v2 — full 5-signal proof)
//
// Proves that private media metadata satisfies all authenticity rules
// WITHOUT revealing the raw values to the verifier.
//
// Private inputs (ZK witness — never exposed to the verifier):
//   device_id    : integer ID of the capturing device
//   timestamp    : Unix epoch seconds of capture
//   sensor_score : quality score reported by the device (0–100)
//   gps_lat      : latitude  scaled to integer (e.g. 40.7900°  → 407900)
//   gps_long     : |longitude| scaled to integer (e.g. 77.8637° → 778637)
//                  IMPORTANT: pass the ABSOLUTE VALUE from JS.
//                  Raw data is negative (western hemisphere); Circom field
//                  elements are non-negative, so Math.abs() is applied before
//                  passing the value in, and the circuit checks the magnitude.
//
// Public output:
//   valid        : 1 if every check passes, 0 otherwise
//
// Rules encoded as constraints:
//   device_id    ∈ {1024, 2048, 4096}
//   timestamp    ∈ [1780278000, 1780867200]   (Jun 1–7 2026 window)
//   sensor_score ≥ 70
//   gps_lat      ∈ [407400, 408400]            (19-bit range; 2^19 = 524288)
//   gps_long     ∈ [778000, 779200]            (20-bit range; 2^20 = 1048576)
// ─────────────────────────────────────────────────────────────────────────────
template ProvenanceCheck() {

    // ── Private inputs ───────────────────────────────────────────────────────
    signal input device_id;
    signal input timestamp;
    signal input sensor_score;
    signal input gps_lat;
    signal input gps_long;   // absolute value of longitude (see note above)

    // ── Public output ────────────────────────────────────────────────────────
    signal output valid;


    // ════════════════════════════════════════════════════════════════════════
    // CHECK 1 — Device ID
    //
    // IsEqual() returns 1 when both inputs match, 0 otherwise.
    // The three approved IDs are distinct, so at most one IsEqual fires,
    // keeping device_ok in {0, 1}.
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
    // CHECK 2 — Timestamp range
    //
    // 1780278000 <= timestamp <= 1780867200
    // Both bounds < 2^31 = 2147483648  →  n = 31
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
    // CHECK 3 — Sensor score
    //
    // sensor_score >= 70
    // Values 0–100 fit in 8 bits (2^8 = 256)  →  n = 8
    // ════════════════════════════════════════════════════════════════════════

    component score_ge = GreaterEqThan(8);
    score_ge.in[0] <== sensor_score;
    score_ge.in[1] <== 70;


    // ════════════════════════════════════════════════════════════════════════
    // CHECK 4 — GPS Latitude
    //
    // 407400 <= gps_lat <= 408400
    // 408400 < 2^19 = 524288  →  n = 19
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
    // CHECK 5 — GPS Longitude (absolute value)
    //
    // 778000 <= gps_long <= 779200
    // 779200 < 2^20 = 1048576  →  n = 20
    //
    // The prover passes Math.abs(gps_long_scaled) from JavaScript.
    // The circuit proves the magnitude is within the allowed bounding box
    // without the verifier learning the exact coordinate.
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
    // FINAL OUTPUT
    //
    // R1CS constraints are degree-2 (A * B = C), so AND-ing five signals
    // requires a chain of intermediate products — one multiplication per step.
    //
    //   step1 = device_ok  AND ts_ok
    //   step2 = step1      AND score_ok
    //   step3 = step2      AND lat_ok
    //   valid = step3      AND lon_ok
    //
    // valid = 1 only when all five checks return 1 simultaneously.
    // ════════════════════════════════════════════════════════════════════════

    signal step1;
    step1 <== device_ok * ts_ok;

    signal step2;
    step2 <== step1 * score_ge.out;

    signal step3;
    step3 <== step2 * lat_ok;

    valid <== step3 * lon_ok;
}

// All inputs to main are private (the ZK witness).
// The only public value is the output signal `valid`.
component main = ProvenanceCheck();
