'use strict';
/**
 * demo_assets.js -- demo-asset bootstrap for the ANONYMIZED artifact copy.
 *
 * The upstream project expected three local resources that are deliberately
 * NOT shipped with this artifact (real ASVspoof 2019 LA eval audio, the
 * original issuer keypair, and locally stored model weights). This module
 * relocates every one of those resources onto shipped DEMO equivalents so
 * `node --test` works from the artifact root:
 *
 *   issuer keys  : demo_keys/issuer_{private,public}.pem (generated demo-only
 *                  keypair; staged to a path OUTSIDE the repo at run time
 *                  because scripts/issue_capture_record_v4.js still enforces
 *                  "key must live outside the repository")
 *   demo audio   : demo_audio/*.wav, mapped by demo_audio/demo_assets.json
 *                  from whatever nominal utterance paths the tests use
 *   weights      : models/AASIST-L.pth (fetch with scripts/fetch_weights.py;
 *                  sha-256 pinned in outputs/v4/PINS.md)
 *   model code   : models/aasist/ (official clovaai/aasist model file + config)
 *
 * Resolution rules (all scripts route path-like flags through resolve()):
 *   - "<HOME>/..." placeholder paths are mapped onto the demo locations, with
 *     env overrides ZKP_DEMO_KEYS_DIR / ZKP_DEMO_WEIGHTS / ZKP_DEMO_CONFIG /
 *     ZKP_DEMO_AASIST_REPO / ZKP_DEMO_HOME; anything unmatched falls back to
 *     os.homeDir() (the pre-anonymization behaviour).
 *   - audio paths that do not exist on disk are looked up in
 *     demo_audio/demo_assets.json (key = "/"-normalized path, relative to the
 *     artifact root when it lives inside the artifact). Existing real files
 *     always win -- real data present on disk is never shadowed.
 *
 * The issuer public keys pin in verify_fully.js / verify_fully_v4.js resolves
 * through issuerPubkeyPin(): in this demo copy the pin is the SHA-256 of the
 * SHIPPED demo public key (recorded in outputs/v4/PINS.md), not the upstream
 * pin, because the original keypair is intentionally not distributed. The
 * legacy upstream pin is kept in LEGACY_PUBKEY_PIN for reference.
 */
const crypto = require("crypto");
const fs = require("fs");
const os = require("os");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");
// Upstream pin (the original demo issuer public key). Kept only as a
// fallback/reference; this artifact pins its OWN demo public key instead.
const LEGACY_PUBKEY_PIN =
  "38fefd713279b33499c6450afb88d79881f48398351b82dfb09387e508ddf645";
// SHA-256 of models/AASIST-L.pth as downloaded from the official clovaai/aasist
// repo (see outputs/v4/PINS.md "weights" entry).
const WEIGHTS_SHA256 =
  "814331d088032bb4c3fa61cc014789eadeed464209dd094ab3a2dd6ffbdce27a";

const HOME_PREFIX = "<HOME>/";
const KEYS_DIRNAME = "zkp-demo-issuer-keys";
const MANIFEST = path.join(ROOT, "demo_audio", "demo_assets.json");

let memoPin = null;
let memoStageDir = null;

function sha256File(p) {
  return crypto.createHash("sha256").update(fs.readFileSync(p)).digest("hex");
}

function normalizeKey(p) {
  let s = String(p).replace(/\\/g, "/");
  if (path.isAbsolute(String(p))) {
    const rel = path.relative(ROOT, String(p)).replace(/\\/g, "/");
    if (!rel.startsWith("..") && !path.isAbsolute(rel)) return rel;
    return s;
  }
  return s.replace(/\/+$/, "");
}

function resolveHome(s) {
  const rest = s.slice(HOME_PREFIX.length);
  if (process.env.ZKP_DEMO_HOME) return path.join(process.env.ZKP_DEMO_HOME, rest);
  // Issuer keypair -> shipped demo keys, staged outside the repo on first use.
  if (rest.startsWith(KEYS_DIRNAME + "/")) {
    const dir = envKeysDir() || stageDemoKeys();
    return path.join(dir, rest.slice(KEYS_DIRNAME.length + 1));
  }
  if (rest === "external/aasist/models/weights/AASIST-L.pth") {
    const local = path.join(ROOT, "models", "AASIST-L.pth");
    if (process.env.ZKP_DEMO_WEIGHTS) return process.env.ZKP_DEMO_WEIGHTS;
    if (fs.existsSync(local)) return local;
    const legacy = path.join(os.homedir(), rest);
    return fs.existsSync(legacy) ? legacy : local; // clear error if neither
  }
  if (rest === "external/aasist/config/AASIST-L.conf") {
    if (process.env.ZKP_DEMO_CONFIG) return process.env.ZKP_DEMO_CONFIG;
    const local = path.join(ROOT, "models", "aasist", "config", "AASIST-L.conf");
    if (fs.existsSync(local)) return local;
    return path.join(os.homedir(), rest);
  }
  if (rest === "external/aasist" || rest.startsWith("external/aasist/")) {
    if (process.env.ZKP_DEMO_AASIST_REPO) {
      return process.env.ZKP_DEMO_AASIST_REPO +
        (rest === "external/aasist" ? "" : rest.slice("external/aasist".length));
    }
    const local = path.join(ROOT, "models", "aasist");
    if (fs.existsSync(path.join(local, "models", "AASIST.py"))) {
      return path.join(local, rest === "external/aasist" ? "" : rest.slice("external/aasist".length));
    }
    return path.join(os.homedir(), rest);
  }
  // Anything else: restore the pre-anonymization meaning of <HOME>.
  return path.join(os.homedir(), rest);
}

function demoKeysDirInRepo() {
  return path.join(ROOT, "demo_keys");
}

function stageDemoKeys() {
  if (memoStageDir) return memoStageDir;
  const dir = path.join(os.tmpdir(), KEYS_DIRNAME);
  fs.mkdirSync(dir, { recursive: true });
  for (const f of ["issuer_private.pem", "issuer_public.pem"]) {
    const src = path.join(demoKeysDirInRepo(), f);
    const dst = path.join(dir, f);
    if (!fs.existsSync(dst) || sha256File(dst) !== sha256File(src)) {
      fs.copyFileSync(src, dst);
    }
  }
  memoStageDir = dir;
  return dir;
}

function envKeysDir() {
  const d = process.env.ZKP_DEMO_KEYS_DIR;
  if (!d) return null;
  return fs.existsSync(path.join(d, "issuer_private.pem")) &&
         fs.existsSync(path.join(d, "issuer_public.pem")) ? d : null;
}

function manifestLookup(normalized) {
  let m;
  try { m = JSON.parse(fs.readFileSync(MANIFEST, "utf8")); } catch { return null; }
  if (m && Object.prototype.hasOwnProperty.call(m, normalized)) {
    const target = path.join(ROOT, m[normalized]);
    return fs.existsSync(target) ? target : null;
  }
  return null;
}

/**
 * Resolve a possibly-placeholder, possibly-nominal path.
 * Idempotent: already-real files pass through untouched.
 */
function resolve(p) {
  if (p == null) return p;
  const s = String(p);
  if (s.startsWith(HOME_PREFIX)) return resolveHome(s);
  if (fs.existsSync(s)) return s;
  const target = manifestLookup(normalizeKey(s));
  return target || s;
}

function issuerPubPath() {
  if (process.env.ZKP_DEMO_ISSUER_PUB) return process.env.ZKP_DEMO_ISSUER_PUB;
  const local = path.join(demoKeysDirInRepo(), "issuer_public.pem");
  if (fs.existsSync(local)) return local;
  const legacy = path.join(os.homedir(), KEYS_DIRNAME, "issuer_public.pem");
  return fs.existsSync(legacy) ? legacy : local;
}

/**
 * The issuer public keys pin. Demo mode: SHA-256 of the shipped demo public
 * key (recorded in outputs/v4/PINS.md). Legacy upstream pin only if the demo
 * key file is absent (artifact tampered with) -- never silently trusts a
 * different key.
 */
function issuerPubkeyPin() {
  if (memoPin) return memoPin;
  const p = issuerPubPath();
  memoPin = fs.existsSync(p) ? sha256File(p) : LEGACY_PUBKEY_PIN;
  return memoPin;
}

function weightsPath() {
  if (process.env.ZKP_DEMO_WEIGHTS) return process.env.ZKP_DEMO_WEIGHTS;
  return path.join(ROOT, "models", "AASIST-L.pth");
}

function aasistRepoPath() {
  if (process.env.ZKP_DEMO_AASIST_REPO) return process.env.ZKP_DEMO_AASIST_REPO;
  return path.join(ROOT, "models", "aasist");
}

function configPath() {
  if (process.env.ZKP_DEMO_CONFIG) return process.env.ZKP_DEMO_CONFIG;
  return path.join(ROOT, "models", "aasist", "config", "AASIST-L.conf");
}

/**
 * Readiness report for the skip guards in tests/. "ready" means every demo
 * resource the detector/issuer/e2e flows need is present AND the weights
 * match the PINS.md sha-256. Missing pieces are listed with concrete fixes.
 */
function assetsStatus() {
  const missing = [];
  const weights = weightsPath();
  if (!fs.existsSync(weights)) {
    missing.push("weights not fetched -- run: python scripts/fetch_weights.py");
  } else if (sha256File(weights) !== WEIGHTS_SHA256) {
    missing.push("weights sha-256 mismatch vs outputs/v4/PINS.md (" +
      sha256File(weights).slice(0, 16) + "...) -- re-run: python scripts/fetch_weights.py");
  }
  if (!fs.existsSync(path.join(aasistRepoPath(), "models", "AASIST.py")))
    missing.push("AASIST model code missing (models/aasist/models/AASIST.py) -- run: python scripts/fetch_weights.py");
  if (!fs.existsSync(configPath()))
    missing.push("AASIST-L config missing (models/aasist/config/AASIST-L.conf) -- run: python scripts/fetch_weights.py");
  if (!fs.existsSync(path.join(demoKeysDirInRepo(), "issuer_private.pem")) ||
      !fs.existsSync(path.join(demoKeysDirInRepo(), "issuer_public.pem")))
    missing.push("demo issuer keys missing (demo_keys/) -- regenerate per demo_keys/DEMO_ONLY.md");
  for (const [nominal] of audioManifestPairs()) {
    if (!manifestLookup(nominal))
      missing.push("demo audio mapping incomplete for " + nominal + " (demo_audio/demo_assets.json)");
  }
  if (!fs.existsSync(path.join(ROOT, "audio_benchmark", "detect_audio.py")))
    missing.push("audio_benchmark/detect_audio.py missing");
  return { ready: missing.length === 0, missing };
}

function audioManifestPairs() {
  let m = {};
  try { m = JSON.parse(fs.readFileSync(MANIFEST, "utf8")); } catch { /* keep {} */ }
  return Object.entries(m).filter(([k]) => !k.startsWith("_"));
}

const SKIP_REASON =
  "demo assets not ready -- weights not fetched? run: python scripts/fetch_weights.py " +
  "(see README, 'Demo assets')";

module.exports = {
  ROOT, resolve, issuerPubPath, issuerPubkeyPin, LEGACY_PUBKEY_PIN,
  weightsPath, aasistRepoPath, configPath, assetsStatus, SKIP_REASON,
  WEIGHTS_SHA256, stageDemoKeys, sha256File,
};
