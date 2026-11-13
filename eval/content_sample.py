#!/usr/bin/env python
"""eval/content_sample.py -- seed-43 content-attack manifest + seed-44 A1 substitutes.

- 50 bona fide + 50 spoof from the LA eval CM protocol (seed 43), DISJOINT from
  the seed-42 binding manifest (eval/sample_manifest.csv).
- 10 A1 substitute files (seed 44, all spoof), disjoint from BOTH manifests and
  from every enrolled hash (they are never enrolled).
Writes eval/sample_manifest_content.csv (file_id,label,attack_id,flac_path,s4_score)
and eval/content_meta.json.
"""
import csv
import json
import os
import random
import sys

SEED_CONTENT = 43
SEED_A1SUB = 44
N_BONA, N_SPOOF, N_A1SUB = 50, 50, 10

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROTOCOL = r"ASVspoof2019_LA_cm_protocols\ASVspoof2019.LA.cm.eval.trl.txt"
FLAC_DIR = r"ASVspoof2019_LA_eval\flac"
MERGED = os.path.join(REPO, "final_outputs", "minnah_comparison",
                      "dataset_acquisition", "merged_scores.csv")
OLD_MANIFEST = os.path.join(REPO, "eval", "sample_manifest.csv")
OUT = os.path.join(REPO, "eval", "sample_manifest_content.csv")
OUT_META = os.path.join(REPO, "eval", "content_meta.json")


def main() -> int:
    if os.path.exists(OUT):
        print(f"STOP: refusing to overwrite existing {OUT}", file=sys.stderr)
        return 1
    old_ids = set()
    with open(OLD_MANIFEST) as f:
        for r in csv.DictReader(f):
            old_ids.add(r["file_id"])

    protocol = {}
    with open(PROTOCOL) as f:
        for line in f:
            parts = line.split()
            if len(parts) == 5 and parts[4] in ("bonafide", "spoof"):
                protocol[parts[1]] = (parts[3], parts[4])
    scores = {}
    with open(MERGED, newline="") as f:
        for row in csv.DictReader(f):
            scores[os.path.splitext(os.path.basename(row["file"]))[0]] = float(row["score"])

    bona = sorted(k for k, (_, lab) in protocol.items() if lab == "bonafide" and k not in old_ids)
    by_attack = {}
    for k, (att, lab) in protocol.items():
        if lab == "spoof" and k not in old_ids:
            by_attack.setdefault(att, []).append(k)

    rng = random.Random(SEED_CONTENT)
    sel_bona = sorted(rng.sample(bona, N_BONA))
    attacks = sorted(by_attack)  # A07..A19
    # round-robin over attack ids so the 50 spoofs span A07-A19
    sel_spoof, used_att = [], {a: [] for a in attacks}
    for i in range(N_SPOOF):
        a = attacks[i % len(attacks)]
        pool = [k for k in sorted(by_attack[a]) if k not in used_att[a]]
        k = pool[rng.randrange(len(pool))]
        used_att[a].append(k)
        sel_spoof.append((a, k))

    rng2 = random.Random(SEED_A1SUB)
    used = old_ids | set(sel_bona) | {u for _, u in sel_spoof}
    spoof_pool = sorted(k for k, (_, lab) in protocol.items() if lab == "spoof" and k not in used)
    a1_subs = sorted(rng2.sample(spoof_pool, N_A1SUB))

    rows, missing = [], []
    for utt, att, lab in ([(u, "", "bonafide") for u in sel_bona]
                          + [(u, a, "spoof") for a, u in sel_spoof]
                          + [(u, "", "a1sub") for u in a1_subs]):
        flac = os.path.join(FLAC_DIR, utt + ".flac")
        if utt not in scores or not os.path.isfile(flac):
            missing.append(utt)
            continue
        rows.append({"file_id": utt, "label": lab, "attack_id": att,
                     "flac_path": flac, "s4_score": repr(scores[utt])})
    if missing:
        print(f"STOP: samples missing: {missing}", file=sys.stderr)
        return 1

    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    with open(OUT_META, "w") as f:
        json.dump({"seed_content": SEED_CONTENT, "seed_a1sub": SEED_A1SUB,
                   "disjoint_from": "eval/sample_manifest.csv (seed 42, 20 files)",
                   "n_bona": N_BONA, "n_spoof": N_SPOOF, "n_a1sub": N_A1SUB}, f, indent=2)
    print(f"wrote {OUT} ({len(rows)} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())