#!/usr/bin/env python
"""eval/u3/remap_d1.py -- build u3_scores_D1_<mode>.json from the EXISTING
AASIST-L caches (no re-scoring): dev_scores.json (utt-id keyed), the LA eval
chunk scores (Downloads/_la_work/chunks/*/scores.csv), u2_scores.json (a2+a3),
u1_scores.json / u1_scores_c2.json. D1 gets the same eval-subset rule as D2
(all bona fide + 500/attack seeded 44) applied to the cached full-eval scores."""
import csv, json, os, sys, random
U3 = os.path.dirname(os.path.abspath(__file__))
EVAL = os.path.dirname(U3)
U2ROOT = os.path.join(EVAL, "..", "outputs", "v3", "eval_content", "u2")
U2ROOT = os.path.abspath(U2ROOT)
LA_DIR = r"<HOME>\Downloads\LA\LA"
SEED = 44
CONDS = ["mp3_64k", "mp3_32k", "opus_32k", "resample_8k_rt",
         "noise_20db", "noise_10db", "reverb_rt60_0.3s"]
FRACS = ["0.1", "0.25", "0.5"]
POSITIONS = ["start", "middle", "end"]


def d1_dev():
    dev = json.load(open(os.path.join(EVAL, "dev_scores.json")))
    proto = os.path.join(LA_DIR, "ASVspoof2019_LA_cm_protocols",
                         "ASVspoof2019.LA.cm.dev.trl.txt")
    out = {}
    for line in open(proto):
        p = line.strip().split()
        if len(p) >= 5:
            f = os.path.join(LA_DIR, "ASVspoof2019_LA_dev", "flac", p[1] + ".flac")
            if p[1] in dev:
                out[f] = float(dev[p[1]])
    return out


def d1_eval():
    full = {}
    ch = os.path.join(r"<HOME>\Downloads", "_la_work", "chunks")
    for d in sorted(os.listdir(ch)):
        p = os.path.join(ch, d, "scores.csv")
        if not os.path.isfile(p):
            continue
        with open(p) as f:
            for r in csv.DictReader(f):
                full[r["file"]] = float(r["score"])
    proto = os.path.join(LA_DIR, "ASVspoof2019_LA_cm_protocols",
                         "ASVspoof2019.LA.cm.eval.trl.txt")
    bona, spoofs = [], []
    for line in open(proto):
        q = line.strip().split()
        if len(q) < 5:
            continue
        f = os.path.join(LA_DIR, "ASVspoof2019_LA_eval", "flac", q[1] + ".flac")
        if f not in full:
            continue
        if q[4] == "bonafide":
            bona.append((f, "bonafide"))
        else:
            spoofs.append((f, q[4], q[3]))
    rng = random.Random(SEED)
    by = {}
    for f, l, a in spoofs:
        by.setdefault(a, []).append((f, l))
    sub = []
    for a in sorted(by):
        picks = by[a][:]
        rng.shuffle(picks)
        sub += picks[:500]
    return dict((f, full[f]) for f, l in bona + sub)


def d1_u2():
    u = json.load(open(os.path.join(EVAL, "u2_scores.json")))
    a2 = {k: v for k, v in u.items() if (os.sep + "u2" + os.sep + "a2" + os.sep) in k}
    a3 = {k: v for k, v in u.items() if (os.sep + "u2" + os.sep + "a3" + os.sep) in k}
    return a2, a3


def d1_u1():
    m = json.load(open(os.path.join(EVAL, "u1", "track_manifest.json")))
    seg = {}
    for sd, cc in (("C1_segments", "u1_scores.json"), ("C2_segments", "u1_scores_c2.json")):
        u = json.load(open(os.path.join(EVAL, "u1", cc)))
        for c in m["clips"]:
            p = os.path.join(EVAL, "u1", sd,
                             f"{c['order']:03d}_{c['kind']}_{c['file_id']}.wav")
            if p in u:
                seg.setdefault(sd, {})[p] = u[p]
    return seg.get("C1_segments", {}), seg.get("C2_segments", {})


def main():
    json.dump(d1_dev(), open(os.path.join(U3, "u3_scores_D1_dev.json"), "w"), indent=0, sort_keys=True)
    json.dump(d1_eval(), open(os.path.join(U3, "u3_scores_D1_eval.json"), "w"), indent=0, sort_keys=True)
    a2, a3 = d1_u2()
    json.dump(a2, open(os.path.join(U3, "u3_scores_D1_a2.json"), "w"), indent=0, sort_keys=True)
    json.dump(a3, open(os.path.join(U3, "u3_scores_D1_a3.json"), "w"), indent=0, sort_keys=True)
    c1, c2 = d1_u1()
    json.dump(c1, open(os.path.join(U3, "u3_scores_D1_u1c1.json"), "w"), indent=0, sort_keys=True)
    json.dump(c2, open(os.path.join(U3, "u3_scores_D1_u1c2.json"), "w"), indent=0, sort_keys=True)
    print("D1 remap:", {m: len(json.load(open(os.path.join(U3, f"u3_scores_D1_{m}.json"))))
                        for m in ("dev", "eval", "a2", "a3", "u1c1", "u1c2")})
    return 0


if __name__ == "__main__":
    sys.exit(main())
