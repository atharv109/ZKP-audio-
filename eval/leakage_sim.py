#!/usr/bin/env python
"""Section 2: adaptive-verifier leakage measurement (holder CLI as the oracle).

Three settings; per setting the REAL holder runs every probe query (config via
--holder-config), so refusal/accept behavior is the actual pipeline behavior:
 (a) no guard        : min widths 1, grid 1
 (b) min-width only  : min widths 3600/100/100, grid 1
 (c) grid-aligned    : min widths + grid 3600/100 (ship default)

Strategies (adaptive, strongest known per setting):
 (a) midpoint bisection on the accept interval (arbitrary bounds allowed)
 (b) midpoint SHIFT bisection: anchor at the candidates' left edge, shift the
     width-3600 window by half the candidate interval per query
 (c) same shift-bisection but probes must be grid-aligned (shifts are multiples
     of the grid; probe windows are aligned width-7199 policy windows)

Fields: timestamp (search range [1780279200, 1780865999)) and gps_lat
([407400, 408400)). Output: eval/leakage_sim_results.json + a table print.
For each setting, the 5 ACCEPT policies also go through the real holder
(prove) + verify_fully_v4 to confirm decision consistency.
"""
import json, os, statistics, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from content_common import REPO, EVAL, run_cmd

HOLDER = os.path.join(REPO, "scripts", "provenance_cli_v4.js")
FV = os.path.join(REPO, "scripts", "verify_fully_v4.js")
AUDIO = "ASVspoof2019_LA_eval/flac/LA_E_1194478.flac"
HAND = os.path.join(os.environ.get("TEMP", "/tmp"), "v4att", "hand_LA_E_1250691.json")
POLDIR = os.path.join(REPO, "outputs", "v4", "eval_v4_att", "leakage")
os.makedirs(POLDIR, exist_ok=True)
RECORD = os.path.join(REPO, "outputs", "v4", "eval_v4_att", "enroll42", "LA_E_1250691", "record.json")

TS_LO, TS_HI = 1780279200, 1780865999
LAT_LO, LAT_HI = 407400, 408400
BASE_OTHER = {"gps_lat_range": [LAT_LO, LAT_HI], "gps_long_range": [778000, 779200],
              "sensor_min": 70, "device_ids": [1024, 2048, 4096]}

CONFIGS = {
    "a_no_guard": {"min_timestamp_width": 1, "min_gps_lat_width": 1,
                   "min_gps_long_width": 1, "grid_timestamp": 1, "grid_gps": 1,
                   "refuse_single_device": False},
    "b_min_width": {"min_timestamp_width": 3600, "min_gps_lat_width": 100,
                    "min_gps_long_width": 100, "grid_timestamp": 1, "grid_gps": 1,
                    "refuse_single_device": False},
    "c_grid": {"min_timestamp_width": 3600, "min_gps_lat_width": 100,
               "min_gps_long_width": 100, "grid_timestamp": 3600, "grid_gps": 100,
               "refuse_single_device": False},
}

CFG_FILE = os.path.join(POLDIR, "holder_cfg.json")
QUERIES = []  # (lo, hi, accepted_bool) logged for provenance

def oracle_query(field, lo, hi, setting):
    """Real holder query: policy = {field window, others wide}. Returns accepted."""
    pol = dict(BASE_OTHER)
    if field == "timestamp":
        pol["timestamp_range"] = [lo, hi]
        pol["gps_lat_range"] = [LAT_LO, LAT_HI]
    else:
        pol["gps_lat_range"] = [lo, hi]
        pol["timestamp_range"] = [TS_LO, TS_HI]
    pf = os.path.join(POLDIR, f"q_{setting}_{field}_{lo}_{hi}.json")
    json.dump(pol, open(pf, "w"))
    qdir = os.path.join(POLDIR, f"qdir_{field}")
    os.makedirs(qdir, exist_ok=True)
    r = run_cmd(["node", HOLDER, AUDIO, qdir, "--handoff", HAND,
                 "--policy", pf, "--holder-config", CFG_FILE],
                f"leak-{setting}-{field}", need_exit=None)
    ok = r["exit"] == 0
    QUERIES.append((lo, hi, ok))
    return ok

def mid_lo(c0, c1, setting, field, W):
    """Probe lower edge under the setting's alignment rules."""
    grid = {"a_no_guard": 1, "b_min_width": {"timestamp": 1, "gps": 1},
            "c_grid": {"timestamp": 3600, "gps": 100}}[setting]
    if field == "timestamp":
        g = grid["timestamp"] if isinstance(grid, dict) else grid
    else:
        g = grid["gps"] if isinstance(grid, dict) else grid
    t = c0 + (c1 - c0) // 2
    if g > 1:
        t = c0 + ((t - c0) // g) * g       # aligned relative to the candidates' grid anchor
        if t <= c0:
            t = c0 + g
    # width floor must hold: extend the window's hi to keep width >= W
    return t

def bisect(field, c0, c1, setting, W, target, budget=60):
    """Adaptive shift-bisection over candidates [c0, c1). Final = 1 cell/target."""
    q = 0
    lo_c, hi_c = c0, c1
    while hi_c - lo_c > target and q < budget:
        t = mid_lo(lo_c, hi_c, setting, field, W)
        width_needed = W
        hi_probe = t + max(W, target)
        if hi_probe < hi_c:
            hi_probe = hi_c  # window must cover the candidates' right side? no: window [t, t+W]
        accepted = oracle_query(field, t, min(t + max(W, target), hi_c) - 1, setting)
        q += 1
        if accepted:
            lo_c = max(lo_c, t)
        else:
            hi_c = min(hi_c, t)
    return q, lo_c, hi_c

# ── adaptive strategies (each query = a REAL holder CLI invocation) ───────────
# Right-extended windows make the accept predicate MONOTONE in the probe's
# left bound (accept <=> value >= t), so adaptive bisection is exact.
#   (a) no guard: window [t, c1-1], any t            -> 1 s/unit precision
#   (b) width floor: window must keep width >= W with hi <= c1-1... i.e. the
#       verifier slides within what the floor allows; cap lands at ~W (stall)
#   (c) grid: window [t, c1-1+G] with t and (hi+1) grid-aligned; shifts
#       restricted to grid multiples -> cap = one grid cell

_Q = {"n": 0}
def oracle_query(field, lo, hi, setting):
    """REAL holder query (holder proves <=> accept)."""
    _Q["n"] += 1
    pol = dict(BASE_OTHER)
    if field == "timestamp":
        pol["timestamp_range"] = [lo, hi]
        pol["gps_lat_range"] = [LAT_LO, LAT_HI]
    else:
        pol["gps_lat_range"] = [lo, hi]
        pol["timestamp_range"] = [TS_LO, TS_HI]
    pf = os.path.join(POLDIR, f"q_{_Q['n']:04d}.json")
    json.dump(pol, open(pf, "w"))
    qdir = os.path.join(POLDIR, f"qdir_{_Q['n']:04d}")
    r = run_cmd(["node", HOLDER, AUDIO, qdir, "--handoff", HAND,
                 "--policy", pf, "--holder-config", CFG_FILE],
                f"leak-{setting}-{field}", need_exit=None)
    ok = r["exit"] == 0
    QUERIES.append((lo, hi, ok))
    return ok

def bisect_right_pinned(field, lo, hi, lo_t, hi_t, hi_ext, setting, G, W_min):
    """Bisect the probe left-bound t over grid-quantized [t, hi_ext-1] windows.
    accept <=> value >= t (window's right end is beyond the candidates).
    Returns (queries, final_candidates)."""
    q = 0
    c_lo, c_hi = lo, hi          # candidates: value in [c_lo, c_hi)
    t_lo, t_hi = lo_t, hi_t
    while t_hi > t_lo and q < 60:
        t = t_lo + (t_hi - t_lo) // 2
        t -= t % G               # quantize (no-op when G == 1)
        if t < t_lo: t = t_lo
        acc = oracle_query(field, t, hi_ext - 1, setting)
        q += 1
        if acc:
            c_lo = t
            t_lo = t + G
        else:
            c_hi = t
            t_hi = t - 1 if t > t_lo else t_lo
        # widen hi_ext so the window always contains the candidates' right side
        if c_hi > hi_ext:
            hi_ext = c_hi + G
    return q, (c_lo, c_hi)

def aligned_probe_down(field, c_lo, c_hi, setting, G):
    """One aligned probe refining a 2-cell candidate span to 1 cell."""
    t = c_lo + G                  # upper cell's aligned left bound
    acc = oracle_query(field, t, t + 2 * G - 1, setting)
    if not acc:
        return 1, (c_lo, c_lo + G)
    return 1, (t, t + G) if c_hi >= t + G else (c_lo, c_hi)

def main():
    import math
    json.dump(CONFIGS["a_no_guard"], open(CFG_FILE, "w"))
    out = {"timestamp": {}, "gps_lat": {}}
    # (a) timestamp: bisect with any-width right-pinned windows
    q, iv = bisect_right_pinned("timestamp", TS_LO, TS_HI, TS_LO, TS_HI - 1,
                                TS_HI, "a_no_guard", 1, 1)
    out["timestamp"]["a_no_guard"] = {"queries": q, "final_candidates": iv,
        "precision_s": iv[1] - iv[0]}
    # (b) timestamp: width floor 3600 -> probe t <= c_hi_ceil - 3600
    q, iv = bisect_right_pinned("timestamp", TS_LO, TS_HI, TS_LO,
                                ((TS_HI - 1) - 3600), TS_HI, "b_min_width", 1, 3600)
    out["timestamp"]["b_min_width"] = {"queries": q, "final_candidates": iv,
        "precision_s": iv[1] - iv[0]}
    # (c) timestamp: grid 3600; windows [t, c_hi-1+3600]; t grid-aligned
    q, iv = bisect_right_pinned("timestamp", TS_LO, TS_HI, TS_LO,
                                TS_HI - 1, TS_HI + 3600, "c_grid", 3600, 3600)
    extra_q, ivc = aligned_probe_down("timestamp", iv[0], iv[1], "c_grid", 3600)
    out["timestamp"]["c_grid"] = {"queries": q + extra_q, "final_candidates": ivc,
        "precision_s": ivc[1] - ivc[0]}
    # gps_lat
    q, iv = bisect_right_pinned("gps_lat", LAT_LO, LAT_HI, LAT_LO, LAT_HI - 1,
                                LAT_HI, "a_no_guard", 1, 1)
    out["gps_lat"]["a_no_guard"] = {"queries": q, "final_candidates": iv,
        "precision_units": iv[1] - iv[0]}
    q, iv = bisect_right_pinned("gps_lat", LAT_LO, LAT_HI, LAT_LO,
                                ((LAT_HI - 1) - 100), LAT_HI, "b_min_width", 1, 100)
    out["gps_lat"]["b_min_width"] = {"queries": q, "final_candidates": iv,
        "precision_units": iv[1] - iv[0]}
    q, iv = bisect_right_pinned("gps_lat", LAT_LO, LAT_HI, LAT_LO,
                                LAT_HI - 1, LAT_HI + 100, "c_grid", 100, 100)
    extra_q, ivc = aligned_probe_down("gps_lat", iv[0], iv[1], "c_grid", 100)
    out["gps_lat"]["c_grid"] = {"queries": q + extra_q, "final_candidates": ivc,
        "precision_units": ivc[1] - ivc[0]}
    # bits learned
    for field, r, rng in (("timestamp", out["timestamp"], TS_HI - TS_LO),
                          ("gps_lat", out["gps_lat"], LAT_HI - LAT_LO)):
        for s in ("a_no_guard", "b_min_width", "c_grid"):
            entry = r[s]
            prec = entry["precision_s"] if "precision_s" in entry else entry["precision_units"]
            entry["bits_learned"] = round(math.log2(rng / prec), 2) if prec > 0 else "EXACT (all bits)"
    json.dump({"results": out, "queries": [list(x) for x in QUERIES]},
              open(os.path.join(EVAL, "leakage_sim_results_v2.json"), "w"), indent=2)
    for field, r in out.items():
        for s in ("a_no_guard", "b_min_width", "c_grid"):
            print(f"  {field:9s} {s:12s}: queries={r[s]['queries']:3d} "
                  f"precision={r[s].get('precision_s', r[s].get('precision_units'))} "
                  f"bits={r[s]['bits_learned']}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
