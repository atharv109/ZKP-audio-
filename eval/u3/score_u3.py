#!/usr/bin/env python
"""eval/u3/score_u3.py -- U3 detector scoring harness.
Modes: dev | eval | a2 | a3 | u1c1 | u1c2, detector D1/D2/D3.
D3 uses a stratified dev subset (see items_devsub).
Batch <=32, RAM-gated, resumable caches keyed by absolute path."""
import csv, json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from content_common import ram_gate, run_cmd

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EVAL = os.path.join(REPO, "eval")
U3 = os.path.join(EVAL, "u3")
CACHE_DIR = os.path.join(os.environ.get("TEMP", "/tmp"), "u3work")
os.makedirs(CACHE_DIR, exist_ok=True)
RUN_INFERENCE = os.path.join(REPO, "audio_benchmark", "run_inference.py")
BATCH = 32
AASIST_REPO = r"<HOME>\external\aasist"
LA_DIR = r"<HOME>\Downloads\LA\LA"
U2ROOT = os.path.join(REPO, "outputs", "v3", "eval_content", "u2")
CONDS = ["mp3_64k", "mp3_32k", "opus_32k", "resample_8k_rt",
         "noise_20db", "noise_10db", "reverb_rt60_0.3s"]
FRACS = ["0.1", "0.25", "0.5"]
POSITIONS = ["start", "middle", "end"]
EVAL_SPOOF_PER_ATTACK = 500
SEED = 44
DETS = {
    "D1": (r"<HOME>\external\aasist\models\weights\AASIST-L.pth",
           r"<HOME>\external\aasist\config\AASIST-L.conf"),
    "D2": (r"<HOME>\external\aasist\models\weights\AASIST.pth",
           os.path.join(U3, "aasist_full_modelcfg.json")),
    # D3 = NII RawNet2 (Zenodo 8337778); config is None (weights file self-describing)
    "D3": (r"<HOME>\external\nii_asvspoof\rawnet2\01"
           r"\__pretrained\trained_network.pt", None),
}
BACKENDS = {"D1": "aasist", "D2": "aasist", "D3": "rawnet2_nii"}


def man_u2():
    out = []
    with open(os.path.join(EVAL, "sample_manifest_u2.csv")) as f:
        for r in csv.DictReader(f):
            out.append((r["file_id"], r["flac_path"], r["label"], r["attack_id"]))
    return out


def items_dev():
    path = os.path.join(LA_DIR, "ASVspoof2019_LA_dev", "flac")
    proto = os.path.join(LA_DIR, "ASVspoof2019_LA_cm_protocols",
                         "ASVspoof2019.LA.cm.dev.trl.txt")
    out = []
    with open(proto) as f:
        for line in f:
            p = line.strip().split()
            if len(p) >= 5:
                item = (os.path.join(path, p[1] + ".flac"), p[4].lower())
                if os.path.isfile(item[0]):
                    out.append(item)
    return out


def items_eval():
    path = os.path.join(LA_DIR, "ASVspoof2019_LA_eval", "flac")
    proto = os.path.join(LA_DIR, "ASVspoof2019_LA_cm_protocols",
                         "ASVspoof2019.LA.cm.eval.trl.txt")
    bona, spoofs = [], []
    with open(proto) as f:
        for line in f:
            p = line.strip().split()
            if len(p) < 5:
                continue
            fp = os.path.join(path, p[1] + ".flac")
            if p[4] == "bonafide":
                bona.append((fp, "bonafide"))
            else:
                spoofs.append((fp, "spoof", p[3]))
    import random
    rng = random.Random(SEED)
    by = {}
    for s in spoofs:
        by.setdefault(s[2], []).append(s)
    sub = []
    for a in sorted(by):
        picks = by[a][:]
        rng.shuffle(picks)
        sub += [(f, l) for f, l, _ in picks[:EVAL_SPOOF_PER_ATTACK]]
    return bona + sub


def items_devsub(per_attack=300):
    """D3-only stratified dev subset: ALL bona fide + fixed-seed (SEED) spoof
    subset spread evenly over the DISTINCT dev attacks. Note: dev protocols
    contain A07-A19 (A01-A06 are train-only), so the spread is over those."""
    path = os.path.join(LA_DIR, "ASVspoof2019_LA_dev", "flac")
    proto = os.path.join(LA_DIR, "ASVspoof2019_LA_cm_protocols",
                         "ASVspoof2019.LA.cm.dev.trl.txt")
    bona, by = [], {}
    with open(proto) as f:
        for line in f:
            p = line.strip().split()
            if len(p) < 5:
                continue
            fp = os.path.join(path, p[1] + ".flac")
            if not os.path.isfile(fp):
                continue
            if p[4] == "bonafide":
                bona.append((fp, "bonafide"))
            else:
                by.setdefault(p[3], []).append((fp, "spoof"))
    import random
    rng = random.Random(SEED)
    sub = []
    for a in sorted(by):
        picks = by[a][:]
        rng.shuffle(picks)
        sub += picks[:per_attack]
    return bona + sub


def items_a2():
    out = []
    for fid, flac, _lab, _atk in man_u2():
        for c in CONDS:
            p = os.path.join(U2ROOT, "a2", c, fid, "transform.flac")
            if os.path.isfile(p):
                out.append((p, "spoof"))
    return out


def items_a3():
    out = []
    for fid, flac, lab, _atk in man_u2():
        for fr in FRACS:
            for pos in POSITIONS:
                p = os.path.join(U2ROOT, "a3", fr, pos, fid, "splice.flac")
                if os.path.isfile(p):
                    out.append((p, lab))
    return out


def items_clean():
    return [(flac, lab) for _fid, flac, lab, _atk in man_u2()]


def items_u1(segdir):
    man = json.load(open(os.path.join(EVAL, "u1", "track_manifest.json")))
    out = []
    for c in man["clips"]:
        p = os.path.join(EVAL, "u1", segdir,
                         f"{c['order']:03d}_{c['kind']}_{c['file_id']}.wav")
        if os.path.isfile(p):
            out.append((p, c["kind"]))
    return out


def main():
    mode = sys.argv[1]
    det = sys.argv[2] if len(sys.argv) > 2 else "D2"
    weights, cfg = DETS[det]
    cachep = os.path.join(CACHE_DIR, f"u3_scores_{det}_{mode}.json")
    if mode == "dev":
        items = items_devsub() if det == "D3" else items_dev()
    elif mode == "eval":
        items = items_eval()
    elif mode == "a2":
        items = items_a2()
    elif mode == "a3":
        items = items_a3()
    elif mode == "clean":
        items = items_clean()
    elif mode == "u1c1":
        items = items_u1("C1_segments")
    elif mode == "u1c2":
        items = items_u1("C2_segments")
    else:
        print("unknown mode", mode)
        return 2
    cache = json.load(open(cachep)) if os.path.exists(cachep) else {}
    todo = [(f, l) for (f, l) in items if f not in cache and os.path.isfile(f)]
    print(f"[{det}/{mode}] items={len(items)} todo={len(todo)} "
          f"cached={len(cache)}", flush=True)
    import time
    for b, chunk in enumerate([todo[i:i + BATCH]
                               for i in range(0, len(todo), BATCH)]):
        retries = int(os.environ.get("U3_GATE_RETRIES", "240"))
        for attempt in range(retries):
            try:
                ram_gate(f"u3 {det}/{mode} batch {b}")
                break
            except Exception as e:
                if attempt == retries - 1:
                    raise
                print(f"  [gate retry {attempt}] {e}", flush=True)
                time.sleep(30)
        lp = os.path.join(EVAL, f"_u3_batch_{det}_{mode}_{b}.csv")
        with open(lp, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["file", "label"])
            for x in chunk:
                w.writerow([x[0], x[1]])
        outp = os.path.join(EVAL, f"_u3_batch_{det}_{mode}_{b}_out.csv")
        cmd = [sys.executable, RUN_INFERENCE, "--backend", BACKENDS[det],
               "--weights", weights]
        if BACKENDS[det] == "aasist":
            cmd += ["--aasist-repo", AASIST_REPO, "--config", cfg]
        cmd += ["--labels", lp, "--out", outp, "--threshold", "0.0"]
        r = run_cmd(cmd, f"u3-{det}-{mode}-b{b}",
                    need_exit=0, timeout=900)
        with open(outp) as f:
            for row in csv.DictReader(f):
                cache[row["file"]] = float(row["score"])
        json.dump(cache, open(cachep, "w"), indent=0, sort_keys=True)
        os.remove(lp)
        os.remove(outp)
        if b % 40 == 0:
            print(f"  batch {b}: {len(cache)} ({r['ms']} ms "
                  f"py_peak {r['peak_python_mb']}MB)", flush=True)
    print(f"DONE [{det}/{mode}] {len(cache)}/{len(items)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
