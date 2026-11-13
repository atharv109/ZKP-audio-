/**
 * prepare_input.js
 *
 * Reads the provenance dataset, selects the first row that passes all
 * validation rules, then writes inputs/input.json ready for snarkjs.
 *
 * Why strings in input.json?
 * ─────────────────────────
 * Circom/snarkjs works with 254-bit prime field elements.  JavaScript
 * numbers lose precision above 2^53, so snarkjs expects values as
 * decimal strings (e.g. "2048") rather than bare JS numbers.
 *
 * Column mapping (xlsx → circuit signal)
 * ──────────────────────────────────────
 *  timestamp_unix   → timestamp
 *  gps_lat_scaled   → gps_lat   (integer, e.g. 407900)
 *  gps_long_scaled  → gps_long  Math.abs() applied — raw data is negative
 *                                (western hemisphere); circuit requires a
 *                                non-negative field element for range checks
 *
 * Usage:
 *   node scripts/prepare_input.js
 *   npm run prepare-input
 */

const path = require("path");
const fs   = require("fs");
const XLSX = require("xlsx");
const { validateRow } = require("./validate_row");

// ── File paths ──────────────────────────────────────────────────────────────

const DATASET_XLSX = path.resolve(
  __dirname,
  "../inputs/zkp_provenance_synthetic_dataset.xlsx"
);
const DATASET_CSV = path.resolve(
  __dirname,
  "../inputs/zkp_provenance_synthetic_dataset.csv"
);
const OUTPUT_PATH = path.resolve(__dirname, "../inputs/input.json");

// ── Load dataset ────────────────────────────────────────────────────────────

function loadDataset() {
  for (const filePath of [DATASET_XLSX, DATASET_CSV]) {
    if (fs.existsSync(filePath)) {
      const workbook = XLSX.readFile(filePath);
      const sheet    = workbook.Sheets[workbook.SheetNames[0]];
      const rows     = XLSX.utils.sheet_to_json(sheet);
      console.log(`Loaded ${rows.length} rows from: ${path.basename(filePath)}`);
      return rows;
    }
  }
  throw new Error(
    `Dataset not found. Expected:\n  ${DATASET_XLSX}\n  ${DATASET_CSV}`
  );
}

// ── Select first valid row ──────────────────────────────────────────────────

function selectValidRow(rows) {
  for (let i = 0; i < rows.length; i++) {
    if (validateRow(rows[i]).overall) {
      return { row: rows[i], index: i };
    }
  }
  return null;
}

// ── Build input.json ────────────────────────────────────────────────────────

/**
 * Converts a dataset row into the snarkjs input format.
 *
 * All five circuit signals are included (device_id, timestamp, sensor_score,
 * gps_lat, gps_long).  Signal names must match exactly what is declared in
 * circuits/provenance.circom — snarkjs uses them as keys.
 *
 * gps_long: raw data is negative (western hemisphere, e.g. -778637).
 * Math.abs() converts it to the positive magnitude the circuit expects.
 */
function buildCircuitInput(row) {
  return {
    device_id:    String(parseInt(row.device_id, 10)),
    timestamp:    String(parseInt(row.timestamp_unix ?? row.timestamp, 10)),
    sensor_score: String(parseInt(row.sensor_score, 10)),
    gps_lat:      String(parseInt(row.gps_lat_scaled  ?? row.gps_lat, 10)),
    gps_long:     String(Math.abs(parseInt(row.gps_long_scaled ?? row.gps_long, 10))),
  };
}

// ── Main ────────────────────────────────────────────────────────────────────

function main() {
  console.log("\n=== ZKP Provenance — Input Preparation ===\n");

  let rows;
  try {
    rows = loadDataset();
  } catch (err) {
    console.error("ERROR:", err.message);
    process.exit(1);
  }

  const found = selectValidRow(rows);
  if (!found) {
    console.error("ERROR: No row in the dataset passes all validation rules.");
    process.exit(1);
  }

  const { row, index } = found;

  console.log(`\nSelected row ${index + 1} (first row passing all rules):`);
  console.log({
    media_file:      row.media_file,
    device_id:       row.device_id,
    timestamp:       row.timestamp_unix,
    gps_lat:         row.gps_lat_scaled,
    gps_long:        row.gps_long_scaled,
    sensor_score:    row.sensor_score,
    expected_result: row.expected_result,
  });

  const circuitInput = buildCircuitInput(row);

  console.log("\nCircuit input (private signals — will become the ZK witness):");
  console.log(circuitInput);

  fs.writeFileSync(OUTPUT_PATH, JSON.stringify(circuitInput, null, 2));
  console.log(`\nWrote: ${OUTPUT_PATH}`);

  console.log("\nNext steps (full ZKP pipeline):");
  console.log("  1. npm install circomlib");
  console.log("  2. circom circuits/provenance.circom --r1cs --wasm --sym -o outputs/");
  console.log("  3. snarkjs groth16 setup outputs/provenance.r1cs pot12_final.ptau outputs/circuit_final.zkey");
  console.log("  4. snarkjs zkey export verificationkey outputs/circuit_final.zkey outputs/verification_key.json");
  console.log("  5. snarkjs groth16 fullprove inputs/input.json outputs/provenance_js/provenance.wasm outputs/circuit_final.zkey outputs/proof.json outputs/public.json");
  console.log("  6. snarkjs groth16 verify outputs/verification_key.json outputs/public.json outputs/proof.json");
  console.log();
}

main();
