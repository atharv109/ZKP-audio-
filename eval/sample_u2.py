#!/usr/bin/env python
"""eval/sample_u2.py -- seed-44 large sample: 200 bona fide + 200 spoof
(attack-round-robin over all 13 IDs), DISJOINT from seeds 42/43 manifests."""
import csv, json, os, random, sys

SEED = 44
N = 200
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROTO = r"ASVspoof2019_LA_cm_protocols\ASVspoof2019.LA.cm.eval.trl.txt"
FLAC = r"ASVspoof2019_LA_eval\flac"
MERGED = os.path.join(REPO, "final_outputs", "minnah_comparison",
                      "dataset_acquisition", "merged_scores.csv")
OLD = [os.path.join(REPO, "eval", "sample_manifest.csv"),
       os.path.join(REPO, "eval", "sample_manifest_content.csv")]
OUT = os.path.join(REPO, "eval", "sample_manifest_u2.csv")

def main():
    if os.path.exists(OUT):
        print(f"STOP: {OUT} exists"); return 1
    used = set()
    for p in OLD:
        with open(p) as f:
            for r in csv.DictReader(f):
                used.add(r["file_id"])
    proto = {}
    with open(PROTO) as f:
        for line in f:
            parts = line.split()
            if len(parts) == 5 and parts[4] in ("bonafide", "spoof"):
                proto[parts[1]] = (parts[3], parts[4])
    scores = {}
    with open(MERGED, newline="") as f:
        for r in csv.DictReader(f):
            scores[os.path.splitext(os.path.basename(r["file"]))[0]] = float(r["score"])
    bona = sorted(k for k, (_, lab) in proto.items() if lab == "bonafide" and k not in used)
    by_att = {}
    for k, (att, lab) in proto.items():
        if lab == "spoof" and k not in used:
            by_att.setdefault(att, []).append(k)
    rng = random.Random(SEED)
    sel_b = sorted(rng.sample(bona, N))
    attacks = sorted(by_att)
    sel_s, per = [], {a: 0 for a in attacks}
    i = 0
    while len(sel_s) < N:
        a = attacks[i % len(attacks)]
        pool = [k for k in sorted(by_att[a]) if per[a] < len(by_att[a])]
        k = sorted(by_att[a])[per[a]] if False else None
        avail = sorted(by_att[a])
        k = avail[per[a] % len(avail)]
        # ensure uniqueness across attack rounds: only advance per[a] when reused
        if k in {u for _, u in sel_s}:
            per[a] += 1
            continue
        sel_s.append((a, k)); per[a] += 1
        i += 1
    rows = []
    for utt, att, lab in ([(u, "", "bonafide") for u in sel_b]
                          + [(u, a, "spoof") for a, u in sel_s]):
        flac = os.path.join(FLAC, utt + ".flac")
        if utt not in scores or not os.path.isfile(flac):
            print(f"STOP: missing {utt}"); return 1
        rows.append({"file_id": utt, "label": lab, "attack_id": att,
                     "flac_path": flac, "s4_score": repr(scores[utt])})
    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    print(f"wrote {OUT}: {len(rows)} rows; attacks spanned={len({r['attack_id'] for r in rows if r['label']=='spoof'})}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
