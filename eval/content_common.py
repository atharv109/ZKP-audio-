#!/usr/bin/env python
"""eval/content_common.py -- shared helpers for the content-attack harness.

Fixes carried over from the binding harness:
- command stdout/stderr logs are read with encoding="utf-8" (the binding run's
  cp1252 decode caused mojibake -> empty/”unparseable” reason strings).
- RAM gate via GlobalMemoryStatusEx (dwLength=64 padded struct; MS-Store Python
  spawns python3.12.exe, so the sampler in _measure.ps1 covers both names).
"""
import csv
import ctypes
import ctypes.wintypes as wt
import hashlib
import json
import os
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVAL = os.path.join(REPO, "eval")

DEMO_WF = os.path.join(REPO, "scripts", "demo_workflow.js")
ISSUE = os.path.join(REPO, "scripts", "issue_capture_record.js")
VERIFY_FULLY = os.path.join(REPO, "scripts", "verify_fully.js")
ISSUER_KEY = r"<HOME>\zkp-demo-issuer-keys\issuer_private.pem"
WEIGHTS = r"<HOME>\external\aasist\models\weights\AASIST-L.pth"
AASIST_REPO = r"<HOME>\external\aasist"
CONFIG = r"<HOME>\external\aasist\config\AASIST-L.conf"
ENROLL_META = os.path.join(REPO, "inputs", "demo_private_metadata.json")
RUN_INFERENCE = os.path.join(REPO, "audio_benchmark", "run_inference.py")
THRESHOLD = 1.7635419737
THRESHOLD_DEFAULT = 1.81681

RAM_GATE_MB = int(os.environ.get("EVAL_RAM_GATE_MB", "2000"))


class Stop(Exception):
    pass


def ram_free_mb() -> int:
    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [("dwLength", wt.DWORD),
                    ("dwMemoryLoad", wt.DWORD),
                    ("ull", ctypes.c_uint64 * 8)]
    st = MEMORYSTATUSEX()
    st.dwLength = 64
    k32 = ctypes.windll.kernel32
    k32.GlobalMemoryStatusEx.restype = wt.BOOL
    k32.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(MEMORYSTATUSEX)]
    if not k32.GlobalMemoryStatusEx(ctypes.byref(st)):
        raise Stop("GlobalMemoryStatusEx failed")
    return int(st.ull[1] // (1024 * 1024))


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
    arglist = " ".join(q(a) for a in args[1:])
    ps_cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
              "-File", os.path.join(EVAL, "_measure.ps1"),
              "-Exe", args[0], "-ArgList", arglist, "-WorkDir", REPO,
              "-StdoutFile", stdout_path, "-StderrFile", stderr_path]
    try:
        r = subprocess.run(ps_cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        raise Stop(f"command timed out after {timeout}s: {args[0]} "
                   f"(historical -sync hang hazard; resumed runs retry)")
    js = [l.strip() for l in reversed((r.stdout or "").splitlines())
          if l.strip().startswith("{")]
    if not js:
        raise Stop(f"_measure.ps1: no JSON. tail: {(r.stdout or '')[-300:]} | {(r.stderr or '')[-300:]}")
    return json.loads(js[0])


def run_cmd(args: list, tag: str, need_exit=0, timeout: int = 900) -> dict:
    out_dir = os.path.join(REPO, "outputs", "v3", "eval_content", "logs")
    os.makedirs(out_dir, exist_ok=True)
    base = os.path.join(out_dir, tag + "." + str(int(time.time() * 1000)))
    m = measure(args, base + ".out", base + ".err", timeout)
    code = m["exit"]
    stdout, stderr = "", ""
    try:
        with open(base + ".out", encoding="utf-8", errors="replace") as f:   # FIX: utf-8
            stdout = f.read()
        with open(base + ".err", encoding="utf-8", errors="replace") as f:
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
            "stdout": stdout, "stderr": stderr, "out": stdout + stderr,
            "log_base": base}


def parse_fv(stdout: str, exit_code: int, tag: str) -> dict:
    """verify_fully stdout -> verdict + the EXACT reason (utf-8-clean)."""
    rline = [l for l in stdout.splitlines() if l.startswith("RESULT : FULL-VERIFY")]
    if not rline or exit_code not in (0, 1):
        raise Stop(f"{tag}: unparseable verify_fully output (exit {exit_code}):\n{stdout[-500:]}")
    reason = rline[-1].split("\u2014", 1)[1].strip() if "\u2014" in rline[-1] else ""
    if reason.startswith("existing-proof verification rejected"):
        raise Stop(f"{tag}: Part A rejected -- unexpected (proofs are always "
                   f"generated for the presented file):\n{stdout[-500:]}")
    return {"verdict": "ACCEPT" if exit_code == 0 else "REJECT",
            "reason": reason or ("FV ACCEPT" if exit_code == 0 else "FV REJECT")}


def s3(mode: str, sha: str, meta=None):
    args = [sys_executable(), os.path.join(EVAL, "s3_registry.py")]
    args += (["enroll", sha, json.dumps(meta or {})] if mode == "enroll" else ["lookup", sha])
    r = subprocess.run(args, capture_output=True, text=True, timeout=60)
    if mode == "enroll" and r.returncode != 0 \
            and "refusing duplicate" in (r.stderr or ""):
        return "ACCEPT", "already enrolled (resume: registry has this sha)"
    out = (r.stdout or "").strip()
    if not out or out.split()[0] not in ("ACCEPT", "REJECT", "ENROLLED"):
        raise Stop(f"s3_registry {mode} unparseable rc={r.returncode}: {out[:200]} | {r.stderr[:200]}")
    if mode == "enroll" and r.returncode != 0:
        if "refusing duplicate" in (r.stderr or "") or "refusing duplicate" in out:
            return "ACCEPT", "already enrolled (resume: registry has this sha)"
        raise Stop(f"s3_registry enroll failed: {out} | {r.stderr[:200]}")
    return ("ACCEPT" if out.startswith(("ACCEPT", "ENROLLED")) else "REJECT"), out


def sys_executable() -> str:
    return sys.executable


CSV_FIELDS = ["file_id", "label", "attack_id", "system", "command", "exit_code",
              "verdict", "reason", "runtime_ms", "peak_node_mb", "peak_python_mb"]


class ContentRows:
    """Append-only writer with resume dedupe on (system, file_id, attack_id)."""

    def __init__(self, path: str, dedupe: bool = True):
        self.path = path
        self.done = set()
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    self.done.add((r["system"], r["file_id"], r["attack_id"], r["label"]))
        elif dedupe:
            with open(path, "w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(CSV_FIELDS)
        else:
            raise Stop(f"expected existing {path} for strict append")

    def add(self, file_id="", label="", attack_id="", system="", command="",
            exit_code="", verdict="", reason="", runtime_ms="",
            peak_node_mb="", peak_python_mb=""):
        key = (system, file_id, attack_id, label)
        if key in self.done:
            return False
        self.done.add(key)
        with open(self.path, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow([file_id, label, attack_id, system, command,
                                    exit_code, verdict, reason, runtime_ms,
                                    peak_node_mb, peak_python_mb])
        print(f"  [row] {attack_id}/{system} {file_id} -> {verdict} "
              f"({runtime_ms or ''} ms)", flush=True)
        return True