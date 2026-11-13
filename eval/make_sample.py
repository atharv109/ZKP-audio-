#!/usr/bin/env python
"""eval/make_sample.py -- fixed-seed sample manifest for the binding-attack eval.

Selects 10 bonafide + 10 spoof files from the ASVspoof 2019 LA eval *protocol*
(ASVspoof2019.LA.cm.eval.trl.txt), matching them against the frozen
merged_scores.csv (for S4 scores) and the FLAC directory on disk. Spoof
selection spans distinct attack IDs across A07-A19.

Writes eval/sample_manifest.csv with the seed, file IDs, labels, attack IDs,
and S4 scores. Reads only dataset/protocol files; writes one CSV + one meta JSON.
"""
import csv
import json
import os
import random
import sys

SEED = 42
N_BONA = 10
N_SPOOF = 10

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROTOCOL = r"ASVspoof2019_LA_cm_protocols\ASVspoof2019.LA.cm.eval.trl.txt"
FLAC_DIR = r"ASVspoof2019_LA_eval\flac"
MERGED = os.path.join(REPO, "final_outputs", "minnah_comparison",
                      "dataset_acquisition", "merged_scores.csv")
OUT = os.path.join(REPO, "eval", "sample_manifest.csv")
OUT_META = os.path.join(REPO, "eval", "sample_manifest_meta.json")


def main() -> int:
    protocol = {}  # utt_id -> (attack_id, label)
    # eval CM protocol format (5 fields): <speaker_id> <utt_id> "-" <attack_id> <label>
    with open(PROTOCOL) as f:
        for line in f:
            parts = line.split()
            if len(parts) != 5:
                continue
            utt, attack, label = parts[1], parts[3], parts[4]
            if label not in ("bonafide", "spoof"):
                continue
            protocol[utt] = (attack, label)

    scores = {}
    with open(MERGED, newline="") as f:
        for row in csv.DictReader(f):
            key = os.path.splitext(os.path.basename(row["file"]))[0]
            scores[key] = float(row["score"])

    bona = sorted(k for k, (_, lab) in protocol.items() if lab == "bonafide")
    by_attack = {}
    for k, (att, lab) in protocol.items():
        if lab == "spoof":
            by_attack.setdefault(att, []).append(k)

    rng = random.Random(SEED)
    sel_bona = sorted(rng.sample(bona, N_BONA))
    attacks = sorted(by_attack)  # A07..A19
    print(f"attacks available: {attacks}", file=sys.stderr)
    # one per attack id (deterministic random pick per attack), then shuffle
    # to N_SPOOF so every selected spoof has a distinct attack id
    picked = []
    for att in attacks:
        pool = sorted(by_attack[att])
        picked.append((att, pool[rng.randrange(len(pool))]))
    sel_spoof = [picked[i] for i in rng.sample(range(len(picked)), N_SPOOF)]

    rows, missing = [], []
    for utt, att, lab in ([(u, "", "bonafide") for u in sel_bona]
                          + [(u, a, "spoof") for a, u in sel_spoof]):
        flac = os.path.join(FLAC_DIR, utt + ".flac")
        if utt not in scores or not os.path.isfile(flac):
            missing.append(utt)
            continue
        rows.append({
            "file_id": utt, "label": lab, "attack_id": att,
            "flac_path": flac, "s4_score": repr(scores[utt]),
        })
    if missing:
        print(f"STOP: samples missing from scores or disk: {missing}", file=sys.stderr)
        return 1
    if os.path.exists(OUT):
        print(f"STOP: refusing to overwrite existing {OUT}", file=sys.stderr)
        return 1
    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    with open(OUT_META, "w") as f:
        json.dump({
            "seed": SEED, "protocol": PROTOCOL, "n_bona": N_BONA, "n_spoof": N_SPOOF,
            "sampling": "random.Random(42): bona = sorted sample of 10 bonafide ids; "
                        "spoof = one deterministic-random pick per attack id A07..A19, "
                        "shuffled, first 10 (distinct attack ids)",
        }, f, indent=2)
    print(f"wrote {OUT} ({len(rows)} rows, seed {SEED})")
    return 0


if __name__ == "__main__":
    sys.exit(main())