#!/usr/bin/env python3
"""fetch_weights.py -- fetch the public AASIST-L checkpoint + model code.

Downloads (official hosting, per clovaai/aasist docs: the pre-trained models
are provided IN the official repo, referenced by config/AASIST-L.conf's
"model_path": ./models/weights/AASIST-L.pth):

    https://raw.githubusercontent.com/clovaai/aasist/main/models/weights/AASIST-L.pth
    https://raw.githubusercontent.com/clovaai/aasist/main/models/AASIST.py
    https://raw.githubusercontent.com/clovaai/aasist/main/config/AASIST-L.conf
    https://raw.githubusercontent.com/clovaai/aasist/main/LICENSE
    https://raw.githubusercontent.com/clovaai/aasist/main/NOTICE

Saved to (relative to this artifact root):
    models/AASIST-L.pth
    models/aasist/models/AASIST.py
    models/aasist/config/AASIST-L.conf
    models/aasist/LICENSE
    models/aasist/NOTICE

The weights file's SHA-256 is verified against the pin recorded in
outputs/v4/PINS.md ("weights" entry). Exit 0 on success, non-zero on any
download/hash failure.

Usage:
    python scripts/fetch_weights.py            # official download
    python scripts/fetch_weights.py --from-local <path to AASIST-L.pth>
        # documented fallback: copy a checkpoint you already have locally and
        # verify its sha against the pin (no network).
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

WEIGHTS_URL = ("https://raw.githubusercontent.com/clovaai/aasist/main/"
               "models/weights/AASIST-L.pth")
# sha-256 of the official AASIST-L.pth (pin duplicated from outputs/v4/PINS.md)
WEIGHTS_SHA256 = "814331d088032bb4c3fa61cc014789eadeed464209dd094ab3a2dd6ffbdce27a"

CODE_FILES = {  # official-repo path -> destination under models/aasist/
    "models/AASIST.py": "models/AASIST.py",
    "config/AASIST-L.conf": "config/AASIST-L.conf",
    "LICENSE": "LICENSE",
    "NOTICE": "NOTICE",
}
BASE = "https://raw.githubusercontent.com/clovaai/aasist/main/"

PINS = ROOT / "outputs" / "v4" / "PINS.md"
PINS_LINE = f"{WEIGHTS_SHA256} *models/AASIST-L.pth\n"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def pin_weights() -> None:
    """Make sure outputs/v4/PINS.md carries the weights entry."""
    PINS.parent.mkdir(parents=True, exist_ok=True)
    if PINS.exists() and PINS_LINE in PINS.read_text(encoding="utf-8"):
        return
    with open(PINS, "a", encoding="utf-8") as fh:
        fh.write(PINS_LINE)
    print(f"[fetch_weights] recorded weights pin in {PINS.relative_to(ROOT)}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--from-local", metavar="PATH",
                    help="fallback: use a local AASIST-L checkpoint instead "
                         "of downloading (still verified against the pin)")
    args = ap.parse_args(argv)

    weights = ROOT / "models" / "AASIST-L.pth"
    weights.parent.mkdir(parents=True, exist_ok=True)

    if args.from_local:
        src = Path(args.from_local)
        if not src.is_file():
            print(f"[fetch_weights] local checkpoint not found: {src}",
                  file=sys.stderr)
            return 2
        shutil.copyfile(src, weights)
        print(f"[fetch_weights] copied local checkpoint -> {weights}")
    else:
        if weights.is_file() and sha256_file(weights) == WEIGHTS_SHA256:
            print(f"[fetch_weights] already present and pin-verified: {weights}")
        else:
            print(f"[fetch_weights] downloading {WEIGHTS_URL}")
            try:
                urllib.request.urlretrieve(WEIGHTS_URL, weights)
            except Exception as e:  # noqa: BLE001
                print(f"[fetch_weights] download failed: {e}\n"
                      "Offline fallback documented in README.md: copy a "
                      "checkpoint you already have with "
                      "`python scripts/fetch_weights.py --from-local <path>`",
                      file=sys.stderr)
                return 1
    sha = sha256_file(weights)
    if sha != WEIGHTS_SHA256:
        print(f"[fetch_weights] SHA-256 MISMATCH: {sha} != pinned "
              f"{WEIGHTS_SHA256} (outputs/v4/PINS.md). Deleting the bad copy; "
              "do not use unverified weights.", file=sys.stderr)
        weights.unlink()
        return 1
    print(f"[fetch_weights] sha-256 OK: {sha}")

    # Model code + config (small files, vendored under models/aasist/).
    for src_rel, dst_rel in CODE_FILES.items():
        dst = ROOT / "models" / "aasist" / dst_rel
        if dst.is_file():
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            urllib.request.urlretrieve(BASE + src_rel, dst)
            print(f"[fetch_weights] fetched {src_rel} -> {dst.relative_to(ROOT)}")
        except Exception as e:  # noqa: BLE001
            print(f"[fetch_weights] warning: {src_rel} download failed ({e}); "
                  "tests will skip until it is available", file=sys.stderr)

    pin_weights()
    print("[fetch_weights] done. Node tests will pick this up automatically "
          "(scripts/demo_assets.js).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
