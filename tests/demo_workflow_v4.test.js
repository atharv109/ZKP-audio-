'use strict';
// tests/demo_workflow_v4.test.js -- Step-6 end-to-end tests.
const { test } = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const ROOT = path.resolve(__dirname, '..');
const DEMO = require(path.join(ROOT, 'scripts', 'demo_assets.js'));
// demo-asset skip guard: tests SKIP (never hard-fail) when the demo
// bootstrap isn't ready (e.g. weights not fetched -- run scripts/fetch_weights).
const ASSETS_ALL = DEMO.assetsStatus();
const testA = ASSETS_ALL.ready ? test : (name, fn) =>
  test(name, (t) => t.skip(DEMO.SKIP_REASON + ' | missing: ' + ASSETS_ALL.missing.join('; ')));
const WF = path.join(ROOT, 'scripts', 'demo_workflow_v4.js');
const HOLDER = path.join(ROOT, 'scripts', 'provenance_cli_v4.js');
const GENUINE = 'ASVspoof2019_LA_eval/flac/LA_E_1194478.flac';
const SPOOF = 'ASVspoof2019_LA_eval/flac/LA_E_1000147.flac';
const META = path.join(ROOT, 'inputs', 'demo_metadata_v4.json');
const WORKBASE = path.join(os.tmpdir(), 'v4e2e-' + Math.random().toString(36).slice(2, 8));
fs.mkdirSync(WORKBASE, { recursive: true });

// grid-aligned (timestamp bounds are multiples of 3600 with t_max+1 aligned;
// lat/long are multiples of 100). The frozen v3 window (remainders 2400/1200)
// is NOT aligned -- the holder would refuse it.
const WIDE_POLICY = {
  device_ids: [1024, 2048, 4096], timestamp_range: [1780279200, 1780865999],
  gps_lat_range: [407400, 408400], gps_long_range: [778000, 779200], sensor_min: 70 };
const polPath = (name, obj) => {
  const p = path.join(WORKBASE, name + '.json'); fs.writeFileSync(p, JSON.stringify(obj)); return p;
};
const WIDE = polPath('wide', WIDE_POLICY);
const NARROW_TS = polPath('narrow_ts', { ...WIDE_POLICY, timestamp_range: [1780279200, 1780281000] });
const NARROW_LAT = polPath('narrow_lat', { ...WIDE_POLICY, gps_lat_range: [408250, 408260] });
const EXCL_LAT = polPath('excl_lat', { ...WIDE_POLICY, gps_lat_range: [409000, 409500] });

function runWF(audio, outDirName, extra) {
  const outDir = path.join(WORKBASE, outDirName);
  const args = [WF, audio, outDir, '--metadata', META, '--policy', (extra && extra.pol) || WIDE,
    '--weights', '<HOME>/external/aasist/models/weights/AASIST-L.pth',
    '--aasist-repo', '<HOME>/external/aasist',
    '--config', '<HOME>/external/aasist/config/AASIST-L.conf',
    ...(extra && extra.flagArgs ? extra.flagArgs : [])];
  const r = spawnSync(process.execPath, args, { encoding: 'utf8', cwd: ROOT });
  const out = (r.stdout || '') + (r.stderr || '');
  try { fs.appendFileSync(path.join(WORKBASE, 'wf_debug.log'),
    `\n=== ${outDirName} code=${r.status}\n` + out); } catch {}
  return { code: r.status, out, outDir };
}

testA('(w1) end-to-end honest ACCEPT under a wide policy', async () => {
  const r = runWF(GENUINE, 'w1', { flagArgs: ['--handoff', path.join(WORKBASE, 'w1_handoff.json')] });
  assert.strictEqual(r.code, 0, r.out.slice(-500));
  assert.ok(fs.existsSync(path.join(r.outDir, 'record.json')));
  assert.ok(fs.existsSync(path.join(r.outDir, 'proofs', 'proof.json')));
  assert.ok(fs.existsSync(path.join(r.outDir, 'demo_workflow_report_v4.json')));
  const rep = JSON.parse(fs.readFileSync(path.join(r.outDir, 'demo_workflow_report_v4.json'), 'utf8'));
  assert.strictEqual(rep.verdict, 'FULL-VERIFY ACCEPT');
});

testA('(w2) nonce session end-to-end: ACCEPT with matching nonce', () => {
  const r = runWF(GENUINE, 'w2', { flagArgs: ['--nonce', '7'] });
  assert.strictEqual(r.code, 0, r.out.slice(-500));
});

testA('(w3) holder refuses too-narrow timestamp AND lat ranges; no proof created', () => {
  // w1's handoff (explicit path, outside the repo) is reused here
  const handPath = path.join(WORKBASE, 'w1_handoff.json');
  assert.ok(fs.existsSync(handPath), 'w1 handoff missing - w1 must run first');
  for (const [pol, field] of [[NARROW_TS, 'timestamp_range'], [NARROW_LAT, 'gps_lat_range']]) {
    const r1 = spawnSync(process.execPath, [HOLDER, GENUINE,
      path.join(WORKBASE, 'w3_out_' + field),
      '--handoff', handPath, '--policy', pol], { encoding: 'utf8', cwd: ROOT });
    assert.strictEqual(r1.status, 1, field + ': expected refusal');
    assert.ok((r1.stderr || '').includes(`policy narrower than holder minimum (${field})`),
      field + ': ' + (r1.stderr || '').slice(-220));
    assert.ok(!fs.existsSync(path.join(WORKBASE, 'w3_out_' + field, 'proof.json')));
    assert.ok(!fs.existsSync(path.join(WORKBASE, 'w3_out_' + field)));
  }
});

testA('(w4) holder refuses when metadata does not satisfy the policy; no proof', () => {
  const handPath = path.join(WORKBASE, 'w1_handoff.json');
  const r = spawnSync(process.execPath, [HOLDER, GENUINE,
    path.join(WORKBASE, 'w4_out'),
    '--handoff', handPath, '--policy', EXCL_LAT], { encoding: 'utf8', cwd: ROOT });
  assert.strictEqual(r.status, 1);
  assert.ok((r.stderr || '').includes('metadata does not satisfy policy'),
    (r.stderr || '').slice(-220));
  // no values leaked in the refusal
  assert.ok(!(r.stderr || '').includes('408259'));
  assert.ok(!fs.existsSync(path.join(WORKBASE, 'w4_out')));
});

testA('(w5) spoof file: issuer refuses, pipeline exits 1, no record or proof', () => {
  const r = runWF(SPOOF, 'w5', {});
  assert.strictEqual(r.code, 1);
  assert.ok(!fs.existsSync(path.join(r.outDir, 'record.json')));
  assert.ok(!fs.existsSync(path.join(r.outDir, 'proofs', 'proof.json')));
  assert.ok((r.out || '').includes('enrollment decision = spoof'));
});

testA('(w6) existing outdir refused', () => {
  const r = runWF(GENUINE, 'w1', {});
  assert.strictEqual(r.code, 1);
  assert.ok(r.out.includes('refusing existing outdir'));
});

testA('(w7) leak audit: outdir files + all stage stdout/stderr contain no metadata/salt', () => {
  const rep = JSON.parse(fs.readFileSync(path.join(WORKBASE, 'w2', 'demo_workflow_report_v4.json'), 'utf8'));
  assert.strictEqual(rep.verdict, 'FULL-VERIFY ACCEPT');
  const hand = JSON.parse(fs.readFileSync(path.join(WORKBASE, 'w1_handoff.json'), 'utf8'));
  // distinctive long values: plain substring grep (no chance collisions)
  const longValues = [String(hand.metadata.timestamp), String(hand.metadata.gps_lat),
                      String(hand.metadata.gps_long), hand.salt];
  // short values (1024 / 77): checked structurally -- no metadata KEY may exist
  const shortKeys = ['device_id', 'sensor_score', 'timestamp', 'gps_lat', 'gps_long', 'salt'];
  let filesChecked = 0;
  const walk = (d) => {
    for (const f of fs.readdirSync(d, { withFileTypes: true })) {
      const p = path.join(d, f.name);
      if (f.isDirectory()) walk(p);
      else {
        filesChecked += 1;
        const txt = fs.readFileSync(p, 'utf8');
        for (const v of longValues) assert.ok(!txt.includes(v), `LEAK: ${v.slice(0,12)} in ${p}`);
        let obj = null; try { obj = JSON.parse(txt); } catch {}
        if (obj && typeof obj === 'object' && !Array.isArray(obj))
          for (const k of shortKeys) assert.ok(!(k in obj), `metadata key '${k}' in ${p}`);
      }
    }
  };
  walk(path.join(WORKBASE, 'w1')); walk(path.join(WORKBASE, 'w2'));
  // stage outputs (issuer/holder/verifier stdout+stderr from every run so far)
  const debug = fs.readFileSync(path.join(WORKBASE, 'wf_debug.log'), 'utf8');
  if (debug.length) {
    for (const v of longValues) assert.ok(!debug.includes(v), `LEAK in stage output: ${v.slice(0,12)}`);
    for (const k of shortKeys) assert.ok(!debug.includes('"' + k + '":'), `metadata key '${k}' in stage output`);
  }
  assert.ok(filesChecked >= 6, `only ${filesChecked} files audited`);
});

testA('(w8) Part A: sliding-window (1 s shift, adequate width) refuses on GRID; aligned wide policy is accepted', () => {
  const handPath = path.join(WORKBASE, 'w1_handoff.json');
  // a) width passes (7199 >= 3600) but bounds shifted by 1 -> grid refusal
  const slide = polPath('slide', { ...WIDE_POLICY,
    timestamp_range: [1780279200 + 1, 1780279200 + 7200] });
  const r1 = spawnSync(process.execPath, [HOLDER, GENUINE,
    path.join(WORKBASE, 'w8_s'), '--handoff', handPath, '--policy', slide],
    { encoding: 'utf8', cwd: ROOT });
  assert.strictEqual(r1.status, 1);
  assert.ok((r1.stderr || '').includes('not grid-aligned (timestamp_min=1780279201'),
    (r1.stderr || '').slice(-200));
  assert.ok(!fs.existsSync(path.join(WORKBASE, 'w8_s', 'proof.json')));
  // b) aligned wide policy: holder proceeds past the guard (proves + verifies)
  const r2 = spawnSync(process.execPath, [HOLDER, GENUINE,
    path.join(WORKBASE, 'w8_a'), '--handoff', handPath, '--policy', WIDE],
    { encoding: 'utf8', cwd: ROOT });
  assert.strictEqual(r2.status, 0);
  assert.ok(fs.existsSync(path.join(WORKBASE, 'w8_a', 'proof.json')));
});
