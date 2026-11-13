#!/usr/bin/env python
"""eval/u1/build_track.py -- A8 clip set + playback track construction.

Selects 50 spoof + 50 bona fide from the seed-44 sample (deterministic;
spoofs spread across attack IDs), builds ONE playback WAV:
  2 s 1 kHz start marker | for each clip: 1 s silence* | 200 ms 1 kHz sync
  beep | 500 ms silence | clip (16 kHz) | 500 ms silence | 2 s end marker.
*pre-clip gap = 1 s silence before each sync beep.
Track built at 16 kHz mono; playback export resampled to 48 kHz 16-bit WAV.
Manifest: eval/u1/track_manifest.json (clip order + exact sample offsets).
"""
import csv, json, os, sys
import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EVAL = os.path.join(REPO, "eval")
U1 = os.path.join(EVAL, "u1")
MAN = os.path.join(EVAL, "sample_manifest_u2.csv")
FS = 16000

def main():
    os.makedirs(U1, exist_ok=True)
    rows = list(csv.DictReader(open(MAN)))
    bona = [r for r in rows if r["label"] == "bonafide"][:50]
    spoof = [r for r in rows if r["label"] == "spoof"][:50]
    if len(bona) < 50 or len(spoof) < 50:
        print("STOP: need 50/50"); return 1
    # interleave 10 bona / 10 spoof per attack-decade so channel effects spread
    clips = []
    for i in range(50):
        clips.extend([("spoof", spoof[i]), ("bonafide", bona[i])])
    beep = np.sin(2 * np.pi * 1000 * np.arange(int(0.2 * FS)) / FS).astype(np.float64)
    marker = np.sin(2 * np.pi * 1000 * np.arange(2 * FS) / FS).astype(np.float64)
    silence_05 = np.zeros(int(0.5 * FS))
    silence_10 = np.zeros(FS)
    track = [marker, silence_05]
    manifest = {"format": "16 kHz mono WAV; 1 kHz markers; per clip: 1 s gap, "
                           "200 ms beep, 500 ms silence, clip, 500 ms silence",
                "fs": FS, "clips": []}
    pos = sum(len(x) for x in track)
    for idx, (kind, r) in enumerate(clips):
        y, fsx = sf.read(r["flac_path"], dtype="float64")
        assert fsx == FS and y.ndim == 1, (r["file_id"], fsx, y.ndim)
        track += [silence_10, beep, silence_05, y, silence_05]
        manifest["clips"].append({
            "order": idx, "kind": kind, "file_id": r["file_id"],
            "attack_id": r["attack_id"], "src": r["flac_path"],
            "track_pos_s": round(pos / FS, 6), "len_samples": len(y),
            "len_s": round(len(y) / FS, 6)})
        pos += FS + len(beep) + len(silence_05) * 2 + len(y)
    track += [silence_05, marker]
    wav_all = np.concatenate(track)
    sf.write(os.path.join(U1, "playback_16k.wav"), wav_all, FS, subtype="PCM_16")
    # 48 kHz export for playback devices
    y48 = resample_poly(wav_all, 3, 1)
    sf.write(os.path.join(U1, "playback_48k.wav"), y48, 48000, subtype="PCM_16")
    manifest["total_s"] = round(len(wav_all) / FS, 3)
    manifest["n_clips"] = len(clips)
    json.dump(manifest, open(os.path.join(U1, "track_manifest.json"), "w"), indent=2)
    print(f"track built: {manifest['total_s']} s, {len(clips)} clips "
          f"(16k + 48k WAVs in eval/u1/)")
    return 0

if __name__ == "__main__":
    sys.exit(main())
