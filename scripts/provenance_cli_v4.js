#!/usr/bin/env node
/**
 * provenance_cli_v4.js -- the HOLDER (Step 6): prove under a verifier policy.
 *
 *   node scripts/provenance_cli_v4.js <audio.{wav,flac}> <fresh_outdir>
 *       --handoff <json-outside-...> --policy <policy.json> [--nonce N]
 *       [--holder-config <json>]
 *
 * The holder holds the PRIVATE handoff {metadata, salt} issued at enrollment.
 * It NEVER prints or writes metadata/salt; the only outputs are
 * <outdir>/proof.json and <outdir>/public.json.
 *
 * Refusals BEFORE any proving (fail-closed, no outdir, no proof):
 *   - invalid/empty handoff or policy; policy narrower than holder minimum
 *     ("refusing: policy narrower than holder minimum (<field>)")
 *   - policy allow-list a single distinct device, ONLY when the holder config
 *     sets refuse_single_device=true (default false; see FIX_DESIGN)
 *   - holder metadata does not satisfy the policy ("metadata does not satisfy
 *     policy: <rule-name>" — the rule name only, no values)
 * Any refusal: exit 1 and NO proof. So a REJECT never reveals more than a
 * refusal (policy-oracle-leakage mitigation, FIX_DESIGN rev 2).
 */
const fs = require("fs");
const path = require("path");
const snarkjs = require("snarkjs");
const { sha256File, limbsFromDigest } = require(path.join(__dirname, "hash_limbs.js"));
const { validatePolicyText, policyPublics } = require(path.join(__dirname, "verify_media_v4.js"));

const WASM = path.resolve(__dirname, "..", "outputs", "v4", "provenance_v4_js", "provenance_v4.wasm");
const ZKEY = path.resolve(__dirname, "..", "outputs", "v4", "circuit_v4.zkey");
const EXIT_OK = 0, EXIT_FAIL = 1, EXIT_USAGE = 2;
const META_KEYS = ["device_id", "timestamp", "sensor_score", "gps_lat", "gps_long"];

const DEFAULT_HOLDER_CONFIG = {
  min_timestamp_width: 3600,
  min_gps_lat_width: 100,
  min_gps_long_width: 100,
  grid_timestamp: 3600,      // timestamp_min and timestamp_max+1 must be multiples
  grid_gps: 100,             // gps_lat/gps_long bounds must be multiples
  refuse_single_device: false,
  enforce_query_budget: false, // optional per-verifier query budget (default off);
                               // when true, the holder tracks consecutive policy
                               // narrows in --budget-file (JSON counter) and refuses
                               // past budget_max (default 100); see FIX_DESIGN
  budget_max: 100,
  budget_file: null,
};

function parseArgs(argv) {
  const known = new Set(["--handoff", "--policy", "--nonce", "--holder-config"]);
  const flags = {}; const pos = [];
  for (let i = 0; i < argv.length; i++) {
    if (known.has(argv[i])) { if (i + 1 >= argv.length) return null; flags[argv[i]] = argv[++i]; }
    else pos.push(argv[i]);
  }
  return { flags, pos };
}

function refuse(msg) {
  console.error(msg);
  return EXIT_FAIL;
}

function metadataSatisfies(m, p) {
  // returns the FAILING RULE NAME only (never values) or null
  if (!p.device_ids.includes(m.device_id)) return "device_ids";
  if (m.timestamp < p.timestamp_range[0] || m.timestamp > p.timestamp_range[1])
    return "timestamp_range";
  if (m.sensor_score < p.sensor_min) return "sensor_min";
  if (m.gps_lat < p.gps_lat_range[0] || m.gps_lat > p.gps_lat_range[1]) return "gps_lat_range";
  if (m.gps_long < p.gps_long_range[0] || m.gps_long > p.gps_long_range[1]) return "gps_long_range";
  return null;
}

async function main() {
  const parsed = parseArgs(process.argv.slice(2));
  if (!parsed) { console.error("usage"); return EXIT_USAGE; }
  const { flags, pos } = parsed;
  const [audioArg, outDirArg] = pos;
  if (!audioArg || !outDirArg || !flags["--handoff"] || !flags["--policy"]) {
    console.error("Usage: node scripts/provenance_cli_v4.js <audio> <fresh_outdir> " +
      "--handoff <json> --policy <policy.json> [--nonce N] [--holder-config <json>]");
    return EXIT_USAGE;
  }
  const audio = path.resolve(require(path.join(__dirname, "demo_assets.js")).resolve(audioArg));
  const outDir = path.resolve(outDirArg);

  // ── pre-checks: everything fails closed BEFORE the outdir is created ─────
  if (!fs.existsSync(audio)) return refuse(`[holder] audio not found: ${audio}`);
  const ext = path.extname(audio).toLowerCase();
  if (![".wav", ".flac"].includes(ext)) return refuse(`[holder] unsupported format: ${ext}`);
  if (fs.existsSync(outDir)) return refuse(`[holder] refusing existing outdir: ${outDir}`);
  let hand;
  try { hand = JSON.parse(fs.readFileSync(path.resolve(flags["--handoff"]), "utf8")); }
  catch (e) { return refuse(`[holder] handoff unreadable: ${e.message}`); }
  for (const k of [...META_KEYS]) {
    if (hand.metadata === undefined || !Number.isInteger(hand.metadata[k]))
      return refuse(`[holder] handoff metadata malformed (missing/unint ${k})`);
  }
  if (typeof hand.salt !== "string" || !/^\d+$/.test(hand.salt))
    return refuse("[holder] handoff salt malformed");
  const pol = validatePolicyText(require("fs").readFileSync(path.resolve(flags["--policy"]), "utf8"));
  if (pol.error) return refuse(`[holder] ${pol.error}`);   // includes bit-width/range checks
  // holder-side width enforcement (configurable; FIX_DESIGN policy-oracle item)
  let cfg = DEFAULT_HOLDER_CONFIG;
  if (flags["--holder-config"]) {
    try { cfg = { ...DEFAULT_HOLDER_CONFIG, ...JSON.parse(fs.readFileSync(path.resolve(flags["--holder-config"]), "utf8")) }; }
    catch (e) { return refuse(`[holder] holder config unreadable: ${e.message}`); }
  }
  const p = pol.policy;
  const widths = { timestamp_range: p.timestamp_range[1] - p.timestamp_range[0],
                   gps_lat_range: p.gps_lat_range[1] - p.gps_lat_range[0],
                   gps_long_range: p.gps_long_range[1] - p.gps_long_range[0] };
  const minWid = { timestamp_range: cfg.min_timestamp_width,
                   gps_lat_range: cfg.min_gps_lat_width,
                   gps_long_range: cfg.min_gps_long_width };
  // optional per-verifier query budget (default off): each narrow/misaligned
  // refusal increments the counter in --budget-file; past budget_max the holder
  // refuses outright ("query budget exhausted") -- a rate-limit on oracle use.
  const budgetRefusal = (msg) => {
    if (cfg.enforce_query_budget && cfg.budget_file) {
      let n = 0;
      try { n = JSON.parse(fs.readFileSync(path.resolve(cfg.budget_file), "utf8")).count || 0; } catch {}
      n += 1;
      fs.writeFileSync(path.resolve(cfg.budget_file), JSON.stringify({ count: n }));
      if (n > cfg.budget_max)
        return refuse(msg + ` -- query budget exhausted (${n - 1}/${cfg.budget_max} queries refused)`);
    }
    return refuse(msg);
  };
  for (const k of ["timestamp_range", "gps_lat_range", "gps_long_range"]) {
    if (widths[k] < minWid[k])
      return budgetRefusal(`[holder] refusing: policy narrower than holder minimum (${k})`);
  }
  // grid alignment (Part A): width floors alone are insufficient -- a verifier
  // sliding the window by 1 s per query ([t, t+W] -> [t+1, t+W+1] ...) binary-
  // searches the hidden value; grid-aligned bounds make each ACCEPT identify
  // only a grid cell.
  const mod = (v, g) => ((BigInt(Math.trunc(v)) % BigInt(g)) + BigInt(g)) % BigInt(g);
  const alignChecks = [
    ["timestamp_min", p.timestamp_range[0], cfg.grid_timestamp],
    ["timestamp_max+1", Number(p.timestamp_range[1]) + 1, cfg.grid_timestamp],
    ["gps_lat_min", p.gps_lat_range[0], cfg.grid_gps],
    ["gps_lat_max", p.gps_lat_range[1], cfg.grid_gps],
    ["gps_long_min", p.gps_long_range[0], cfg.grid_gps],
    ["gps_long_max", p.gps_long_range[1], cfg.grid_gps],
  ];
  for (const [label, value, grid] of alignChecks) {
    if (mod(value, grid) !== 0n)
      return budgetRefusal(`[holder] refusing: policy bounds not grid-aligned (${label}=` +
        `${value}, grid ${grid})`);
  }
  const distinct = new Set(p.device_ids);
  if (cfg.refuse_single_device && distinct.size < 2)
    return refuse("[holder] refusing: policy allow-list has a single distinct device (holder config refuse_single_device)");
  const badRule = metadataSatisfies(hand.metadata, p);
  if (badRule) return refuse(`[holder] metadata does not satisfy policy: ${badRule}`);
  // ── all pre-checks passed: create outdir, build witness, prove ────────────
  fs.mkdirSync(outDir, { recursive: true });
  const nonce = flags["--nonce"] != null ? String(parseInt(flags["--nonce"], 10)) : "0";
  if (flags["--nonce"] != null && (nonce === "NaN" || (BigInt(nonce) < 0n) ||
      nonce !== String(flags["--nonce"]).trim()))
    return refuse("[holder] --nonce must be a non-negative integer");
  const pp = policyPublics(p);
  const input = {
    device_id: String(hand.metadata.device_id), timestamp: String(hand.metadata.timestamp),
    sensor_score: String(hand.metadata.sensor_score), gps_lat: String(hand.metadata.gps_lat),
    gps_long: String(hand.metadata.gps_long), salt: String(hand.salt),
    media_hash_hi: "0", media_hash_lo: "0",   // overwritten below
    valid_claim: "1", session_nonce: nonce,
    allowed_device_0: pp[0], allowed_device_1: pp[1], allowed_device_2: pp[2],
    timestamp_min: pp[3], timestamp_max: pp[4], gps_lat_min: pp[5], gps_lat_max: pp[6],
    gps_long_min: pp[7], gps_long_max: pp[8], sensor_min: pp[9],
  };
  const sha = await sha256File(audio);
  const limbs = limbsFromDigest(sha);
  input.media_hash_hi = limbs.media_hash_hi;
  input.media_hash_lo = limbs.media_hash_lo;
  let proof, pub;
  try {
    const r = await snarkjs.groth16.fullProve(input, WASM, ZKEY);
    proof = r.proof; pub = r.publicSignals;
  } catch (e) {
    try { fs.unlinkSync(outDir + "/proof.json"); } catch {}
    try { fs.rmdirSync(outDir); } catch {}   // refusal: no proof, no dir
    return refuse(`[holder] witness/proof generation failed: ${String(e.message).split("\n")[0]}`);
  }
  fs.writeFileSync(path.join(outDir, "proof.json"), JSON.stringify(proof));
  fs.writeFileSync(path.join(outDir, "public.json"), JSON.stringify(pub));
  console.log(`[holder] proved: audio sha256=${sha.slice(0, 16)}... policy+nonce ${nonce ? "nonce=" + nonce : "nonce=0"}`);
  console.log(`[holder] wrote ${path.join(outDir, "proof.json")} + public.json only`);
  return EXIT_OK;
}

if (require.main === module) {
  main().then((code) => process.exit(code), (e) => {
    console.error(`[error] ${e.message}`); process.exit(EXIT_FAIL);
  });
}
module.exports = { main, DEFAULT_HOLDER_CONFIG, metadataSatisfies };
