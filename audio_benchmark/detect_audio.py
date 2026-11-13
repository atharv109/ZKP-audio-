"""Single-file AASIST-L detection CLI (Step 2 of the provenance demo).

Reuses the exact model-loading and scoring path of run_inference.py /
models.py (importlib file-path load of the upstream AASIST repo, bonafide
logit score). One audio file in, one score out.

Default threshold 1.81681 is the EER operating point of the frozen 500-file
ASVspoof 2019 LA eval subset (results/aasist_eval_sample500_v3_metrics.json,
"eer_threshold" field). It is an EXPLORATORY threshold derived from that
subset — not a validated deployment threshold. --threshold overrides it
always; run_inference.py's 0.0 default is intentionally NOT used.

Checkpoint and upstream-repo paths resolve from CLI flags, then environment
variables (AASIST_WEIGHTS / AASIST_REPO / AASIST_CONFIG) — no machine
specific paths are hard-coded.

Exit codes: 0 ok · 2 usage error (missing file, unsupported format,
missing config paths) · 1 model-loading/scoring failure.

Usage (from audio_benchmark/):
    python detect_audio.py path/to/audio.wav \
        [--weights PATH] [--aasist-repo PATH] [--config PATH] [--threshold T]
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path

import models  # local module — same loading path as run_inference.py

# Exploratory default — verified verbatim from the saved clean-run metrics
# (results/aasist_eval_sample500_v3_metrics.json: "eer_threshold": 1.81681).
DEFAULT_THRESHOLD = 1.81681

AUDIO_EXTS = {".wav", ".flac"}

EXIT_OK, EXIT_MODEL, EXIT_USAGE = 0, 1, 2

THRESHOLD_NOTE = (
    "exploratory threshold = EER operating point of the 500-file clean "
    "subset; NOT a validated deployment threshold"
)


def sha256_file(path: str) -> str:
    """Streamed SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="detect_audio.py",
        description="Score one audio file with the frozen AASIST-L "
                    "checkpoint (higher score = more bonafide).")
    p.add_argument("audio", help="Path to a .wav or .flac file")
    p.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD,
                   help=f"Decision threshold on the bonafide score "
                        f"(default {DEFAULT_THRESHOLD}: {THRESHOLD_NOTE}).")
    p.add_argument("--weights", default=os.environ.get("AASIST_WEIGHTS"),
                   help="AASIST-L checkpoint path (or env AASIST_WEIGHTS)")
    p.add_argument("--aasist-repo", default=os.environ.get("AASIST_REPO"),
                   help="Path to the clovaai/aasist repo clone "
                        "(or env AASIST_REPO)")
    p.add_argument("--config", default=os.environ.get("AASIST_CONFIG"),
                   help="AASIST-L JSON config (or env AASIST_CONFIG)")
    p.add_argument("--device", default="cpu")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    audio = Path(args.audio)

    if not audio.is_file():
        print(f"[error] file not found: {audio}", file=sys.stderr)
        return EXIT_USAGE
    if audio.suffix.lower() not in AUDIO_EXTS:
        print(f"[error] unsupported format {audio.suffix!r} — "
              f"expected .wav or .flac ({audio})", file=sys.stderr)
        return EXIT_USAGE
    for label, value in (("--aasist-repo", args.aasist_repo),
                         ("--weights", args.weights),
                         ("--config", args.config)):
        if not value:
            print(f"[error] {label} not given and env var is unset; pass it "
                  "as a flag or set AASIST_REPO / AASIST_WEIGHTS / "
                  "AASIST_CONFIG", file=sys.stderr)
            return EXIT_USAGE

    try:
        model = models.build_model(
            "aasist",
            weights=args.weights,
            device=args.device,
            aasist_repo=args.aasist_repo,
            config_path=args.config,
        )
    except Exception as e:
        print(f"[error] model loading failed: {e!r}", file=sys.stderr)
        return EXIT_MODEL

    try:
        score = model.score(str(audio))
    except Exception as e:
        print(f"[error] scoring failed: {e!r}", file=sys.stderr)
        return EXIT_MODEL

    decision = "bonafide" if score >= args.threshold else "spoof"
    print(f"file              : {audio.resolve()}")
    print(f"checkpoint        : {Path(args.weights).resolve()}")
    print(f"checkpoint_sha256 : {sha256_file(args.weights)}")
    print(f"score_direction   : higher = more bonafide")
    print(f"threshold         : {args.threshold} ({'default' if args.threshold == DEFAULT_THRESHOLD else 'override'}; {THRESHOLD_NOTE})")
    print(f"score             : {score:.6f}")
    print(f"decision          : {decision}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
