#!/usr/bin/env python
"""eval/run_binding_eval.py -- binding-attack measurement driver (A1/A4/A5/A6/A7 x S1-S4).

Runs the UNCHANGED pipeline commands exactly as THREAT_MODEL.md describes.
All new code lives under eval/. Sequential; fresh dirs; never overwrites
existing artifacts; stops and reports on any unexpected error.
"""
import csv
import ctypes
import ctypes.wintypes
import hashlib
import json
import os
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVAL = os.path.join(REPO, "eval")
OUTROOT = os.path.join(REPO, "outputs", "v3", "eval_binding")
MANIFEST = os.path.join(EVAL, "sample_manifest.csv")
CSV_OUT = os.path.join(EVAL, "results_binding.csv")
COSTS = os.path.join(EVAL, "run_costs.json")
REG = os.path.join(EVAL, "s3_registry.json")

DEMO_WF = os.path.join(REPO, "scripts", "demo_workflow.js")
PROV_CLI = os.path.join(REPO, "scripts", "provenance_cli.js")
ISSUE = os.path.join(REPO, "scripts", "issue_capture_record.js")
VERIFY_FULLY = os.path.join(REPO, "scripts", "verify_fully.js")
ISSUER_KEY = r"<HOME>\zkp-demo-issuer-keys\issuer_private.pem"
WEIGHTS = r"<HOME>\external\aasist\models\weights\AASIST-L.pth"
AASIST_REPO = r"<HOME>\external\aasist"
CONFIG = r"<HOME>\external\aasist\config\AASIST-L.conf"
ENROLL_META = os.path.join(REPO, "inputs", "demo_private_metadata.json")
ENROLL_META_DOC = {"device_id": 1024, "timestamp": 1780298225, "sensor_score": 77,
                   "gps_lat": 408259, "gps_long_abs": 778637}
A4_META = {"device_id": 4096, "timestamp": 1780867199, "sensor_score": 99,
           "gps_lat": 408399, "gps_long_abs": 779199}
THRESH_PRI = 1.7635419737
THRESH_DEF = 1.81681
FORGED_SCORE = 7.5
FORGED_DECISION = "bonafide"


class Stop(Exception):
    pass


def ram_free_mb() -> int:
    # MEMORYSTATUSEX as the OS expects it: dwLength must be 64 (empirically
    # verified; a 56-byte struct gets ERROR_INVALID_PARAMETER), and after the
    # two DWORD fields there are 8 ULONGLONG slots: TotalPhys, AvailPhys, ...
    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.wintypes.DWORD),
                    ("dwMemoryLoad", ctypes.wintypes.DWORD),
                    ("ull", ctypes.c_uint64 * 8)]
    st = MEMORYSTATUSEX()
    st.dwLength = 64
    k32 = ctypes.windll.kernel32
    k32.GlobalMemoryStatusEx.restype = ctypes.wintypes.BOOL
    k32.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(MEMORYSTATUSEX)]
    if not k32.GlobalMemoryStatusEx(ctypes.byref(st)):
        raise Stop("GlobalMemoryStatusEx failed")
    return int(st.ull[1] // (1024 * 1024))  # ullAvailPhys


RAM_GATE_MB = int(os.environ.get("EVAL_RAM_GATE_MB", "2000"))  # protocol: 2000


def ram_gate(label: str) -> None:
    free = ram_free_mb()
    if free < RAM_GATE_MB:
        raise Stop(f"RAM gate: {free} MB free before {label}; >={RAM_GATE_MB} MB required")


def sha256_file(p: str) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def q(s: str) -> str:
    return '"' + s + '"' if (" " in s) else s


def measure(args, stdout_path: str, stderr_path: str, timeout: int = 900) -> dict:
    """Run [exe, a1, ...] via eval/_measure.ps1. Returns {exit, ms, peak_*}."""
    arglist = " ".join(q(a) for a in args[1:])
    ps_cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
              "-File", os.path.join(EVAL, "_measure.ps1"),
              "-Exe", args[0], "-ArgList", arglist, "-WorkDir", REPO,
              "-StdoutFile", stdout_path, "-StderrFile", stderr_path]
    r = subprocess.run(ps_cmd, capture_output=True, text=True, timeout=timeout)
    js = [l.strip() for l in reversed((r.stdout or "").splitlines())
          if l.strip().startswith("{")]
    if not js:
        raise Stop(f"_measure.ps1: no JSON. tail: {(r.stdout or '')[-300:]} | {(r.stderr or '')[-300:]}")
    return json.loads(js[0])


def run_cmd(args: list, tag: str, need_exit=0, timeout: int = 900) -> dict:
    logdir = os.path.join(OUTROOT, "logs")
    os.makedirs(logdir, exist_ok=True)
    base = os.path.join(logdir, tag + "." + str(int(time.time() * 1000)))
    m = measure(args, base + ".out", base + ".err", timeout)
    code = m["exit"]
    stdout, stderr = "", ""
    try:
        with open(base + ".out") as f:
            stdout = f.read()
        with open(base + ".err") as f:
            stderr = f.read()
    except OSError:
        pass
    if code < 0:
        raise Stop(f"could not start {args[0]} ({tag})")
    if need_exit is not None and code != need_exit:
        raise Stop(f"unexpected exit {code} (wanted {need_exit}) for {tag}\n"
                   f"stdout tail: {stdout[-400:]}\nstderr tail: {stderr[-400:]}")
    return {"exit": code, "ms": m["ms"],
            "peak_node_mb": m["peak_node_mb"], "peak_python_mb": m["peak_python_mb"],
            "stdout": stdout, "stderr": stderr, "log_base": base}


def parse_fv(stdout: str, exit_code: int, tag: str) -> dict:
    """verify_fully stdout -> {partA_ok, verdict, reason}.

    Part A/B separation (documented for S2): verify_fully buffers its checks
    and only flushes them ("[ OK ] part A" line) on ACCEPT -- on ANY reject,
    failAll() returns early and the checks are never printed. The outcomes
    are still separable from the RESULT reason string:
      Part A rejected  <=>  reason starts with "existing-proof verification rejected"
      any other reason <=>  Part A PASSED and this reason is Part B's verdict
    Our design always presents a proof valid for the presented file, so a
    Part A rejection is an unexpected state (STOP, not measured).
    """
    rline = [l for l in stdout.splitlines() if l.startswith("RESULT : FULL-VERIFY")]
    if not rline or exit_code not in (0, 1):
        raise Stop(f"{tag}: unparseable verify_fully output (exit {exit_code}):\n{stdout[-500:]}")
    reason = rline[-1].split("\u2014", 1)[1].strip() if "\u2014" in rline[-1] else ""
    if reason.startswith("existing-proof verification rejected"):
        raise Stop(f"{tag}: Part A rejected -- unexpected (design always presents "
                   f"a proof valid for the presented file):\n{stdout[-500:]}")
    return {"partA_ok": True,
            "verdict": "ACCEPT" if exit_code == 0 else "REJECT",
            "reason": reason or ("FV ACCEPT" if exit_code == 0 else "FV REJECT")}


class Rows:
    FIELDS = ["file_id", "label", "attack_id", "system", "command", "exit_code",
              "verdict", "reason", "runtime_ms", "peak_node_mb", "peak_python_mb"]

    def __init__(self):
        if os.path.exists(CSV_OUT):
            raise Stop(f"refusing to overwrite existing {CSV_OUT}")
        with open(CSV_OUT, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(self.FIELDS)

    def add(self, file_id="", label="", attack_id="", system="", command="",
            exit_code="", verdict="", reason="", ms="", pn="", pp=""):
        with open(CSV_OUT, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow([file_id, label, attack_id, system, command,
                                    exit_code, verdict, reason, ms, pn, pp])
        print(f"  [row] {attack_id}/{system} {file_id or '-'} -> {verdict} ({ms} ms)")


def s3(mode: str, sha: str, meta: dict | None = None):
    args = [sys.executable, os.path.join(EVAL, "s3_registry.py")]
    args += (["enroll", sha, json.dumps(meta or {})] if mode == "enroll"
             else ["lookup", sha])
    r = subprocess.run(args, capture_output=True, text=True, timeout=60)
    out = (r.stdout or "").strip()
    if not out or out.split()[0] not in ("ACCEPT", "REJECT", "ENROLLED"):
        raise Stop(f"s3_registry {mode} unparseable rc={r.returncode}: {out[:200]} | {r.stderr[:200]}")
    if mode == "enroll" and r.returncode != 0:
        raise Stop(f"s3_registry enroll failed: {out} | {r.stderr[:200]}")
    verdict = "ACCEPT" if out.startswith(("ACCEPT", "ENROLLED")) else "REJECT"
    return verdict, out


def verdict4(score: float) -> tuple:
    pri = "bonafide" if score >= THRESH_PRI else "spoof"
    dflt = "bonafide" if score >= THRESH_DEF else "spoof"
    return pri, dflt


def stage_times(run_dir: str) -> dict:
    p = os.path.join(run_dir, "demo_result.json")
    if not os.path.isfile(p):
        return {}
    with open(p) as f:
        m = json.load(f)
    return {s.get("stage"): s.get("ms") for s in m.get("stages", [])}


def main() -> int:
    t0 = time.perf_counter()
    print("=== binding-attack eval (A1/A4/A5/A6/A7 x S1-S4) ===")
    if (os.path.exists(OUTROOT) or os.path.exists(CSV_OUT)
            or os.path.exists(os.path.join(EVAL, "s3_registry.json")) or os.path.exists(COSTS)):
        raise Stop("fresh-state check failed: outputs already exist; refusing overwrite")
    os.makedirs(OUTROOT, exist_ok=True)

    with open(MANIFEST) as f:
        samples = list(csv.DictReader(f))
    bona = [s for s in samples if s["label"] == "bonafide"]
    spoof = [s for s in samples if s["label"] == "spoof"]
    if len(bona) != 10 or len(spoof) != 10:
        raise Stop(f"manifest must contain 10 bonafide + 10 spoof; got {len(bona)}/{len(spoof)}")
    score_of = {s["file_id"]: float(s["s4_score"]) for s in samples}

    rows = Rows()
    costs = {"started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
             "enrollment": [], "a4_proofs": []}
    enroll = {}   # fid -> {run_dir, proof, public, record, sha}

    def enroll_group(group, lab):
        d = os.path.join(OUTROOT, "enroll", lab)
        for s in group:
            fid = s["file_id"]
            run_dir = os.path.join(d, fid)
            if os.path.exists(run_dir):
                raise Stop(f"refusing existing run dir {run_dir}")
            ram_gate(f"enroll {fid}")
            r = run_cmd(["node", DEMO_WF, s["flac_path"], ENROLL_META, run_dir,
                         "--weights", WEIGHTS, "--aasist-repo", AASIST_REPO,
                         "--config", CONFIG], f"enroll-{lab}-{fid}", need_exit=0)
            for k, pth in (("proof", os.path.join(run_dir, "proof.json")),
                           ("public", os.path.join(run_dir, "public.json")),
                           ("record", os.path.join(run_dir, "record.json"))):
                if k == "record":
                    r2 = run_cmd(["node", ISSUE, s["flac_path"], pth,
                                  "--issuer-key", ISSUER_KEY], f"issue-{lab}-{fid}")
                enroll.setdefault(fid, {})[k] = pth
            enroll[fid]["run_dir"] = run_dir
            enroll[fid]["sha"] = sha256_file(s["flac_path"])
            costs["enrollment"].append({
                "file_id": fid, "label": lab, "attack_id": s.get("attack_id", ""),
                "ms_total": r["ms"], "stage_ms": stage_times(run_dir),
                "peak_node_mb": r["peak_node_mb"],
                "peak_python_mb": r["peak_python_mb"]})
            v, msg = s3("enroll", enroll[fid]["sha"], ENROLL_META_DOC)
            print(f"[enroll {lab}] {fid}: prove+verify ok ({r['ms']} ms), record issued, S3 {msg}")
        return d

    enroll_group(bona, "genuine")
    enroll_group(spoof, "spoof")

    def add_fv_rows(attack, fid, label, argv, r, extra=""):
        pv = parse_fv(r["stdout"], r["exit"], f"{attack}/{fid}")
        cmd = "node scripts/verify_fully.js " + " ".join(os.path.basename(a) for a in argv[1:])
        rows.add(file_id=fid, label=label, attack_id=attack, system="S1",
                 command=cmd, exit_code=r["exit"], verdict=pv["verdict"],
                 reason=pv["reason"] + extra, ms=r["ms"], pn=r["peak_node_mb"],
                 pp=r["peak_python_mb"])
        rows.add(file_id=fid, label=label, attack_id=attack, system="S2",
                 command=cmd + "  [Part B outcome of the same S1 run]",
                 exit_code=r["exit"], verdict=pv["verdict"],
                 reason="Part B: " + pv["reason"] + extra, ms=r["ms"],
                 pn=r["peak_node_mb"], pp=r["peak_python_mb"])
        return pv

    def add_s3_row(attack, fid, label, sha, verdict, msg):
        rows.add(file_id=fid, label=label, attack_id=attack, system="S3",
                 command=f"python eval/s3_registry.py lookup {sha[:16]}...",
                 exit_code="", verdict=verdict, reason=msg)

    def add_s4_row(attack, fid, label, score, note=""):
        pri, dflt = verdict4(score)
        rows.add(file_id=fid, label=label, attack_id=attack, system="S4",
                 command="read final_outputs/.../merged_scores.csv (frozen AASIST-L score)",
                 exit_code="", verdict=pri,
                 reason=f"score={score}: {pri}@{THRESH_PRI}, {dflt}@{THRESH_DEF}{note}")

    # ── A1: substitute Y (first sampled spoof, its own fresh proof) ────────
    Y = spoof[0]
    print(f"[A1] substitute = {Y['file_id']} ({Y['attack_id']})")
    for s in bona:
        fid = s["file_id"]
        e_r, e_y = enroll[fid], enroll[Y["file_id"]]
        argv = ["node", VERIFY_FULLY, Y["flac_path"], e_y["proof"],
                e_y["public"], e_r["record"]]
        r = run_cmd(argv, f"A1-{fid}", need_exit=None)
        add_fv_rows("A1", fid, "bonafide->substituted", argv, r,
                    extra=" [substituted file + its own fresh proof]")
        v, msg = s3("lookup", e_y["sha"])
        add_s3_row("A1", fid, s["label"], e_y["sha"], v, msg)
        add_s4_row("A1", fid, s["label"], score_of[Y["file_id"]],
                   " (score of SUBSTITUTE file Y)")

    # ── A4: new proof over the SAME file, fabricated rule-compliant meta ───
    for s in bona:
        fid = s["file_id"]
        run_dir = os.path.join(OUTROOT, "A4", fid)
        if os.path.exists(run_dir):
            raise Stop(f"refusing existing run dir {run_dir}")
        ram_gate(f"A4 prove {fid}")
        argv = ["node", PROV_CLI, s["flac_path"], run_dir,
                "--device-id", str(A4_META["device_id"]),
                "--timestamp", str(A4_META["timestamp"]),
                "--sensor-score", str(A4_META["sensor_score"]),
                "--gps-lat", str(A4_META["gps_lat"]),
                "--gps-long-abs", str(A4_META["gps_long_abs"]),
                "--weights", WEIGHTS, "--aasist-repo", AASIST_REPO, "--config", CONFIG]
        r = run_cmd(argv, f"A4-prove-{fid}", need_exit=0)
        costs["a4_proofs"].append({"file_id": fid, "ms_total": r["ms"],
                                   "stage_ms": stage_times(run_dir),
                                   "peak_node_mb": r["peak_node_mb"],
                                   "peak_python_mb": r["peak_python_mb"]})
        argv2 = ["node", VERIFY_FULLY, s["flac_path"],
                 os.path.join(run_dir, "proof.json"),
                 os.path.join(run_dir, "public.json"),
                 enroll[fid]["record"]]
        r2 = run_cmd(argv2, f"A4-verify-{fid}", need_exit=None)
        add_fv_rows("A4", fid, s["label"], argv2, r2, extra=" [NEW proof, fabricated same-file metadata]")
        v, msg = s3("lookup", enroll[fid]["sha"])
        add_s3_row("A4", fid, s["label"], enroll[fid]["sha"], v, msg)
        add_s4_row("A4", fid, s["label"], score_of[fid])

    # ── A6: replay same record+file, fresh context ──────────────────────────
    for s in bona:
        fid = s["file_id"]
        e = enroll[fid]
        argv = ["node", VERIFY_FULLY, s["flac_path"], e["proof"],
                e["public"], e["record"]]
        r = run_cmd(argv, f"A6-{fid}", need_exit=None)
        add_fv_rows("A6", fid, s["label"], argv, r,
                    extra=" [replay: same record+file; issued_at_utc never checked]")
        v, msg = s3("lookup", e["sha"])
        add_s3_row("A6", fid, s["label"], e["sha"], v, msg)
        add_s4_row("A6", fid, s["label"], score_of[fid])

    # ── A7: spoof enrollment -> full verification ──────────────────────────
    for s in spoof:
        fid = s["file_id"]
        e = enroll[fid]
        argv = ["node", VERIFY_FULLY, s["flac_path"], e["proof"],
                e["public"], e["record"]]
        r = run_cmd(argv, f"A7-{fid}", need_exit=None)
        add_fv_rows("A7", fid, s["label"] + f"({s['attack_id']})", argv, r,
                    extra=" [enrolled spoof]")
        v, msg = s3("lookup", e["sha"])
        add_s3_row("A7", fid, s["label"], e["sha"], v, msg)
        add_s4_row("A7", fid, s["label"], score_of[fid], f" attack={s['attack_id']}")

    # ── A5: tampered manifest (favorable forgery) + identical FV command ───
    for s in spoof:
        fid = s["file_id"]
        e = enroll[fid]
        tam_dir = os.path.join(OUTROOT, "A5", fid)
        if os.path.exists(tam_dir):
            raise Stop(f"refusing existing run dir {tam_dir}")
        os.makedirs(tam_dir)
        with open(os.path.join(e["run_dir"], "demo_result.json")) as f:
            man = json.load(f)
        true_score, true_dec = man["detector"]["score"], man["detector"]["decision"]
        man["detector"]["score"] = FORGED_SCORE
        man["detector"]["decision"] = FORGED_DECISION
        with open(os.path.join(tam_dir, "tampered_demo_result.json"), "w") as f:
            json.dump(man, f, indent=2)
        r = run_cmd(["node", VERIFY_FULLY, s["flac_path"], e["proof"],
                     e["public"], e["record"]], f"A5-{fid}", need_exit=None)
        # byte-compare against the untampered A7 output (same command, same paths)
        a7_out_path = None
        logs = sorted(d for d in os.listdir(os.path.join(OUTROOT, "logs"))
                      if d.startswith(f"A7-{fid}.") and d.endswith(".out"))
        if logs:
            a7_out_path = os.path.join(OUTROOT, "logs", logs[-1])
        with open(a7_out_path, "r") as f:
            a7_txt = f.read()
        identical = (a7_txt == r["stdout"])
        pv = parse_fv(r["stdout"], r["exit"], f"A5/{fid}")
        cmd = "node scripts/verify_fully.js <same argv as A7>  [tampered_demo_result.json present]"
        rows.add(file_id=fid, label=s["label"], attack_id="A5", system="S1",
                 command=cmd, exit_code=r["exit"], verdict=pv["verdict"],
                 reason=f"verifier output byte-{'IDENTICAL' if identical else 'DIFFERENT'} "
                        f"vs untampered A7 run; true detector score={true_score} ({true_dec}) "
                        f"forged to {FORGED_SCORE}/{FORGED_DECISION}",
                 ms=r["ms"], pn=r["peak_node_mb"], pp=r["peak_python_mb"])
        rows.add(file_id=fid, label=s["label"], attack_id="A5", system="S2",
                 command=cmd, exit_code=r["exit"], verdict=pv["verdict"],
                 reason="Part B: as S1 (record checks pass; manifest never read)",
                 ms=r["ms"], pn=r["peak_node_mb"], pp=r["peak_python_mb"])
        v, msg = s3("lookup", e["sha"])
        add_s3_row("A5", fid, s["label"], e["sha"], v, msg
                   + " (registry holds no detector data; tampering invisible)")
        add_s4_row("A5", fid, s["label"], FORGED_SCORE,
                   f" (FORGED; true score={true_score} -> spoof)")

    write_summary(rows, costs)
    print(f"DONE in {time.perf_counter() - t0:.1f}s (see {CSV_OUT})")
    return 0


def write_summary(rows, costs):
    with open(COSTS, "w") as f:
        json.dump(costs, f, indent=2)
        f.write("\n")
    # counts per (attack, system, verdict)
    counts = {}
    with open(CSV_OUT, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            k = (row["attack_id"], row["system"])
            counts.setdefault(k, {"ACCEPT": 0, "REJECT": 0})
            counts[k][row["verdict"]] = counts[k].get(row["verdict"], 0) + 1
    print("counts:")
    for (a, sy), c in sorted(counts.items()):
        print(f"  {a} x {sy}: {c['ACCEPT']} ACCEPT / {c['REJECT']} REJECT")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Stop as e:
        print(f"\nSTOPPED — unexpected error (per rules, not worked around):\n{e}",
              file=sys.stderr)
        sys.exit(2)