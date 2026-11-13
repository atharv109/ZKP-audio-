/**
 * validate_row.js
 *
 * Checks whether a provenance metadata row satisfies every rule.
 * Each rule maps to one constraint in the Circom circuit — if a row
 * fails here it will also fail to produce a valid ZK proof.
 *
 * Column name mapping from the xlsx dataset
 * ──────────────────────────────────────────
 *  dataset column     → rule field
 *  timestamp_unix     → timestamp
 *  gps_lat_scaled     → gps_lat   (integer, e.g. 407900 = 40.7900°)
 *  gps_long_scaled    → gps_long  (negative integer; we compare abs value)
 *
 * Rules
 * ─────
 *  device_id   : must be exactly one of [1024, 2048, 4096]
 *  timestamp   : 1780278000 ≤ value ≤ 1780867200   (Jun 1–7 2026 window)
 *  gps_lat     : 407400 ≤ value ≤ 408400            (scaled × 10000)
 *  gps_long    : 778000 ≤ abs(value) ≤ 779200       (scaled × 10000)
 *  sensor_score: value ≥ 70
 */

const path = require("path");
const XLSX = require("xlsx");

// ── Rule constants ──────────────────────────────────────────────────────────

const RULES = {
  APPROVED_DEVICES: [1024, 2048, 4096],

  // Unix epoch window: Jun 1 2026 00:00:00 UTC → Jun 7 2026 23:59:59 UTC
  TIMESTAMP_MIN: 1780278000,
  TIMESTAMP_MAX: 1780867200,

  // Scaled lat/lon (degrees × 10000, centred on State College PA area)
  GPS_LAT_MIN: 407400,
  GPS_LAT_MAX: 408400,
  GPS_LON_MIN: 778000,   // compared against Math.abs(gps_long_scaled)
  GPS_LON_MAX: 779200,

  SENSOR_SCORE_MIN: 70,
};

// ── Core validation function ────────────────────────────────────────────────

/**
 * Validates a single row against all provenance rules.
 *
 * @param {object} row - Row from the dataset (xlsx column names).
 * @returns {{ device_id: bool, timestamp: bool, gps_lat: bool,
 *             gps_long: bool, sensor_score: bool, overall: bool }}
 */
function validateRow(row) {
  const device_id    = parseInt(row.device_id, 10);
  const timestamp    = parseInt(row.timestamp_unix ?? row.timestamp, 10);
  const gps_lat      = parseInt(row.gps_lat_scaled  ?? row.gps_lat,  10);
  const gps_long_abs = Math.abs(parseInt(row.gps_long_scaled ?? row.gps_long, 10));
  const sensor_score = parseInt(row.sensor_score, 10);

  const checks = {
    device_id:    RULES.APPROVED_DEVICES.includes(device_id),
    timestamp:    timestamp >= RULES.TIMESTAMP_MIN && timestamp <= RULES.TIMESTAMP_MAX,
    gps_lat:      gps_lat >= RULES.GPS_LAT_MIN && gps_lat <= RULES.GPS_LAT_MAX,
    gps_long:     gps_long_abs >= RULES.GPS_LON_MIN && gps_long_abs <= RULES.GPS_LON_MAX,
    sensor_score: sensor_score >= RULES.SENSOR_SCORE_MIN,
  };

  checks.overall = Object.values(checks).every(Boolean);
  return checks;
}

// ── Standalone runner ───────────────────────────────────────────────────────

if (require.main === module) {
  const datasetPath = path.resolve(
    __dirname,
    "../inputs/zkp_provenance_synthetic_dataset.xlsx"
  );

  console.log("\n=== ZKP Provenance — Row Validator ===\n");

  let workbook;
  try {
    workbook = XLSX.readFile(datasetPath);
  } catch {
    const csvPath = datasetPath.replace(".xlsx", ".csv");
    try {
      workbook = XLSX.readFile(csvPath);
    } catch {
      console.error("ERROR: Could not read dataset. Expected:\n ", datasetPath);
      process.exit(1);
    }
  }

  const sheet = workbook.Sheets[workbook.SheetNames[0]];
  const rows  = XLSX.utils.sheet_to_json(sheet);

  console.log(`Loaded ${rows.length} rows from dataset.\n`);

  let shownPass = false;
  let shownFail = false;

  for (let i = 0; i < rows.length; i++) {
    const result = validateRow(rows[i]);

    if (result.overall && !shownPass) {
      console.log(`Row ${i + 1} (PASS) — will produce valid ZK proof`);
      console.log("  Values :", {
        device_id:    rows[i].device_id,
        timestamp:    rows[i].timestamp_unix,
        gps_lat:      rows[i].gps_lat_scaled,
        gps_long:     rows[i].gps_long_scaled,
        sensor_score: rows[i].sensor_score,
        expected:     rows[i].expected_result,
      });
      console.log("  Checks :", result);
      console.log();
      shownPass = true;
    }

    if (!result.overall && !shownFail) {
      const failed = Object.entries(result)
        .filter(([k, v]) => k !== "overall" && !v)
        .map(([k]) => k);
      console.log(`Row ${i + 1} (FAIL) — failed: [${failed.join(", ")}]`);
      console.log("  Values :", {
        device_id:    rows[i].device_id,
        timestamp:    rows[i].timestamp_unix,
        gps_lat:      rows[i].gps_lat_scaled,
        gps_long:     rows[i].gps_long_scaled,
        sensor_score: rows[i].sensor_score,
        expected:     rows[i].expected_result,
        failure_reason: rows[i].failure_reason,
      });
      console.log("  Checks :", result);
      console.log();
      shownFail = true;
    }

    if (shownPass && shownFail) break;
  }

  const validCount = rows.filter((r) => validateRow(r).overall).length;
  console.log(`Summary: ${validCount} / ${rows.length} rows pass all rules.`);
  console.log("\nRules applied:");
  console.log(`  device_id    ∈ [${RULES.APPROVED_DEVICES.join(", ")}]`);
  console.log(`  timestamp    ∈ [${RULES.TIMESTAMP_MIN}, ${RULES.TIMESTAMP_MAX}]  (Jun 1–7 2026)`);
  console.log(`  gps_lat      ∈ [${RULES.GPS_LAT_MIN}, ${RULES.GPS_LAT_MAX}]`);
  console.log(`  abs(gps_long)∈ [${RULES.GPS_LON_MIN}, ${RULES.GPS_LON_MAX}]`);
  console.log(`  sensor_score ≥ ${RULES.SENSOR_SCORE_MIN}`);
  console.log();
}

module.exports = { validateRow, RULES };
