#!/usr/bin/env python
"""eval/u1/C1b/raw_probe.py -- 20 s capture-path A/B for the C1b tone-suppression failure.

Plays the first SECONDS of playback_48k.wav (start marker + first clips/beeps) on the
default speakers while recording the mic through a chosen host-API path:
  shared    WASAPI shared mode (goes through the Windows audio engine / APOs) -- baseline
  exclusive WASAPI exclusive mode (bypasses the engine's effect APOs)
  wdmks     WDM kernel streaming (bypasses the Windows audio engine entirely)
Then reports the same 1 kHz burst census used in RESULTS_U1.md section 9, against the
reference over the same span.

usage: py -3.12 -E -P eval/u1/C1b/raw_probe.py {shared|exclusive|wdmks} [seconds]
"""
import os
import sys
import time

import numpy as np
import sounddevice as sd
from scipy.io import wavfile
from scipy.signal import butter, sosfiltfilt

HERE = os.path.dirname(os.path.abspath(__file__))
TRACK = os.path.join(HERE, "..", "playback_48k.wav")
FS = 48000
PRE, TAIL = 1.0, 1.5


def find_mic(api_prefix):
    for i, d in enumerate(sd.query_devices()):
        api = sd.query_hostapis(d["hostapi"])["name"]
        if api.startswith(api_prefix) and "Microphone Array" in d["name"] \
                and d["max_input_channels"] > 0:
            return i, d
    raise SystemExit(f"no mic for {api_prefix}")


def census(x, sr):
    b = sosfiltfilt(butter(4, [900, 1100], "bandpass", fs=sr, output="sos"), x)
    h = int(sr * 0.05)
    env = np.sqrt(np.convolve(b ** 2, np.ones(h) / h, "same"))[::h]
    on = env > 0.15 * env.max()
    runs, s = [], None
    for i, v in enumerate(np.append(on, False)):
        if v and s is None:
            s = i
        if not v and s is not None:
            runs.append((s * 0.05, (i - s) * 0.05))
            s = None
    return runs


def db(v):
    return 20 * np.log10(v + 1e-12)


def main():
    mode = sys.argv[1]
    secs = float(sys.argv[2]) if len(sys.argv) > 2 else 20.0
    sr, ref = wavfile.read(TRACK)
    assert sr == FS
    ref = ref.astype(np.float32) / 32768.0
    ref = ref[: int(secs * FS)]

    api = {"shared": "Windows WASAPI", "exclusive": "Windows WASAPI",
           "wdmks": "Windows WDM-KS"}[mode]
    in_id, in_dev = find_mic(api)
    ch = in_dev["max_input_channels"]
    extra = sd.WasapiSettings(exclusive=True) if mode == "exclusive" else None
    print(f"mode={mode} input #{in_id} '{in_dev['name']}' ch={ch} api={api}")

    chunks = []

    def cb(indata, frames, t, status):
        if status:
            print("status:", status, file=sys.stderr)
        chunks.append(indata.copy())

    with sd.InputStream(device=in_id, samplerate=FS, channels=ch, dtype="int16",
                        callback=cb, extra_settings=extra):
        time.sleep(PRE)
        sd.play(ref, FS, blocking=True)  # default speakers, same path for every mode
        time.sleep(TAIL)

    cap = np.concatenate(chunks).astype(np.float32) / 32768.0
    out = os.path.join(HERE, "raw", f"probe_{mode}.wav")
    wavfile.write(out, FS, (cap * 32767).astype(np.int16))
    mono = cap.mean(axis=1) if cap.ndim > 1 else cap

    floor = np.sqrt(np.mean(mono[int(0.1 * FS): int(0.9 * FS)] ** 2))  # pre-roll, room only
    r_ref, r_cap = census(ref, FS), census(mono, FS)
    beeps = lambda r: sum(0.1 <= d <= 0.4 for _, d in r)
    longs = lambda r: [round(t, 2) for t, d in r if d >= 1.5]
    print(f"saved {out}  dur={len(mono)/FS:.1f}s ch={cap.shape[1] if cap.ndim > 1 else 1}")
    print(f"peak={db(np.abs(mono).max()):.1f} dBFS  rms={db(np.sqrt(np.mean(mono**2))):.1f} dBFS"
          f"  noise floor(pre-roll)={db(floor):.1f} dBFS")
    print(f"reference: beep-like={beeps(r_ref)} markers@{longs(r_ref)}")
    print(f"capture:   beep-like={beeps(r_cap)} markers@{longs(r_cap)}  bursts={len(r_cap)}")


if __name__ == "__main__":
    main()
