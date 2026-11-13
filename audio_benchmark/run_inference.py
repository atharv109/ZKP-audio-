"""Run an audio anti-spoofing model over audio files -> CSV.

Three input modes (highest priority first):

1. Single file (smoke test):
       python run_inference.py --backend aasist --weights checkpoints/aasist_l.pt \
           --aasist-repo /path/to/aasist --file path/to/audio.wav

2. labels.csv (real labelled dataset, e.g. ASVspoof-style):
       python run_inference.py --backend aasist --weights checkpoints/aasist_l.pt \
           --labels labels.csv --out results/aasist_results.csv
   labels.csv columns: file,label  (file paths relative to the CSV's directory,
   or absolute; label is 'bonafide' or 'spoof')

3. Folder layout (default):
       python run_inference.py --backend placeholder --data data --out results/aasist_results.csv
   Walks data/bonafide/ and data/spoof/ (label from the top folder name).

CSV columns: file, label, prediction, score, correct
  - label      : bonafide | spoof | unknown
  - prediction : bonafide | spoof   (threshold on score; default 0.0)
  - score      : higher = more bonafide
  - correct    : 1 if prediction == label, else 0 (empty for unknown labels)

This script does NOT depend on the ZKP circuit, proof artifacts, or any
blockchain files. It is fully self-contained within audio_benchmark/.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from typing import Iterable

import models  # local module


AUDIO_EXTS = {".wav", ".flac", ".mp3", ".ogg", ".m4a"}


def _iter_audio(root: str) -> Iterable[str]:
    for dirpath, _dirs, files in os.walk(root):
        for f in sorted(files):
            if os.path.splitext(f)[1].lower() in AUDIO_EXTS:
                yield os.path.join(dirpath, f)


def _label_from_path(path: str, data_root: str) -> str:
    rel = os.path.relpath(path, data_root).replace("\\", "/")
    top = rel.split("/")[0].lower()
    if top == "bonafide":
        return "bonafide"
    if top == "spoof":
        return "spoof"
    return "unknown"


def _read_labels_csv(labels_path: str) -> list[tuple[str, str]]:
    """Read a labels.csv (columns: file,label). Paths resolved vs the CSV dir."""
    base = os.path.dirname(os.path.abspath(labels_path))
    out: list[tuple[str, str]] = []
    with open(labels_path, newline="", encoding="utf-8") as fh:
        r = csv.DictReader(fh)
        if not r or "file" not in (r.fieldnames or []) or "label" not in (r.fieldnames or []):
            raise SystemExit(
                f"[run_inference] labels.csv needs 'file,label' columns; "
                f"got {r.fieldnames!r}"
            )
        for row in r:
            fpath = row["file"].strip()
            if not os.path.isabs(fpath):
                fpath = os.path.join(base, fpath)
            out.append((fpath, row["label"].strip().lower()))
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Audio anti-spoof inference -> CSV")
    p.add_argument("--backend", choices=["placeholder", "aasist", "ecapa", "rawnet2_nii"], default="placeholder")
    p.add_argument("--weights", default=None,
                   help="Checkpoint path (aasist/eecapa backends). Required for aasist/ecapa.")
    p.add_argument("--aasist-repo", default=None,
                   help="Path to a clone of clovaai/aasist (added to sys.path for the import)")
    p.add_argument("--ecapa-repo", default=None,
                   help="Path to a Python module/package defining the ECAPA-TDNN anti-spoofing "
                        "`Model` class matching the checkpoint (ecapa backend only).")
    p.add_argument("--config", default=None,
                   help="JSON model config. Optional for aasist (default AASIST-L); required for ecapa.")
    p.add_argument("--device", default="cpu")
    p.add_argument("--threshold", type=float, default=0.0,
                   help="Decision threshold on score (higher = bonafide). Default 0.0.")
    p.add_argument("--data", default="data", help="Dataset root with bonafide/ and spoof/ subdirs")
    p.add_argument("--labels", default=None,
                   help="labels.csv (columns: file,label) — real labelled dataset mode")
    p.add_argument("--file", default=None, help="Single audio file (smoke test; overrides --data/--labels)")
    p.add_argument("--label", default=None, help="Label for --file mode (bonafide|spoof|unknown)")
    p.add_argument("--out", default="results/aasist_results.csv", help="Output CSV path")
    args = p.parse_args(argv)

    model = models.build_model(
        args.backend,
        weights=args.weights,
        device=args.device,
        aasist_repo=args.aasist_repo,
        config_path=args.config,
        ecapa_repo=args.ecapa_repo,
    )
    print(f"[run_inference] backend={model.name} threshold={args.threshold}")

    # Build the file list with labels (priority: --file > --labels > --data).
    if args.file:
        files = [(args.file, args.label or "unknown")]
    elif args.labels:
        if not os.path.isfile(args.labels):
            print(f"[run_inference] labels.csv not found: {args.labels}", file=sys.stderr)
            return 2
        files = _read_labels_csv(args.labels)
        if not files:
            print(f"[run_inference] labels.csv had no rows: {args.labels}", file=sys.stderr)
            return 2
    else:
        data_root = args.data
        if not os.path.isdir(data_root):
            print(f"[run_inference] data root not found: {data_root}", file=sys.stderr)
            return 2
        files = [(f, _label_from_path(f, data_root)) for f in _iter_audio(data_root)]
        if not files:
            print(f"[run_inference] no audio under {data_root}/bonafide or {data_root}/spoof",
                  file=sys.stderr)
            return 2

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    n = 0
    with open(args.out, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["file", "label", "prediction", "score", "correct"])
        for path, label in files:
            if not os.path.isfile(path):
                print(f"  [skip] {path}: file not found", file=sys.stderr)
                continue
            try:
                score = model.score(path)
            except Exception as e:  # pragma: no cover - per-file robustness
                print(f"  [skip] {path}: {e!r}", file=sys.stderr)
                continue
            prediction = "bonafide" if score >= args.threshold else "spoof"
            correct = "" if label == "unknown" else ("1" if prediction == label else "0")
            w.writerow([path, label, prediction, f"{score:.6f}", correct])
            n += 1
            print(f"  {os.path.basename(path):30s} label={label:8s} "
                  f"pred={prediction:8s} score={score:+.4f} correct={correct}")

    print(f"[run_inference] wrote {n} rows -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())